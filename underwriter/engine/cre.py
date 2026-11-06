"""Commercial real estate analysis — reproduces the CRE Investment Summary tables (Ballpoint sample).

Method (from the Ballpoint sample, "Company Prepared; adjusted by Underwriter"):
  1. Start from the borrower's projections. Line items are display-rounded; stated totals carry full precision,
     so totals are anchored to the stated figures (when they agree with the line sum within rounding) and every
     underwriter adjustment is applied as a delta.
  2. Underwriter adjustments (each becomes a numbered note under the table):
       - real estate taxes replaced by the appraiser's estimate when higher, grown at the expense growth rate
       - one-time lease-up costs (leasing & marketing) only in year 1
       - rent growth capped / expense growth floored at guideline rates
       - blended stabilized vacancy floored at the guideline commercial vacancy
       - replacement reserves added unless capital reserves already cover the guideline $/SF
  3. Debt service: base case = take-out loan (if given) else the Invest Detroit loan; partial years by months.
  4. Sensitivity: the vacancy on the largest rent line that drives DSCR to 1.00x on the Invest Detroit loan.
  5. Sources & uses, cost/SF, LTC, contingencies, rent roll, LOIs, collateral/LTV.
"""
from __future__ import annotations

from typing import Optional

from ..guidelines import load_guidelines
from ..schema import CRE_TOTAL_KEYS, REVENUE_KEYS, VACANCY_KEYS, Deal
from .common import Flag, annual_debt_service, fmt_money, fmt_pct, fmt_x, max_loan_for_payment, safe_div
from .small_business import collateral_analysis

EXPENSE_ORDER = ["management_fee", "leasing_marketing", "insurance", "trash", "cleaning", "maintenance", "turns", "cable",
                 "re_taxes", "tax_abatement", "water", "gas_electric", "utilities", "payroll", "capital_reserves",
                 "accounting", "asset_management", "replacement_reserves", "other_expense"]
COMMERCIAL_GROSS = {"gross_retail_rent", "gross_office_rent", "other_gross_rent"}
GROSS_FOR_VAC = {"retail_vacancy": "gross_retail_rent", "office_vacancy": "gross_office_rent",
                 "residential_vacancy": "gross_residential_rent", "other_vacancy": "other_gross_rent"}


def _assumptions(deal: Deal) -> dict:
    return load_guidelines()["cre_underwriting_assumptions"]


def _loan_ds(L, months: int) -> float:
    if L is None:
        return 0.0
    ann = L.annual_payment_override if L.annual_payment_override is not None else annual_debt_service(L.amount, L.rate, L.amort_months, L.day_count)
    return ann * months / 12


def analyze_cre(deal: Deal) -> dict:
    flags: list[Flag] = []
    A = _assumptions(deal)
    cre = deal.cre
    P = cre.projections
    years = P.years
    n = len(years)
    if n == 0:
        flags.append(Flag("critical", "missing", "No operating projections found; cannot compute NOI or DSCR."))
        return {"flags": flags, "years": []}
    # ---- borrower lines (sum duplicates) ----
    lines: dict[str, list[float]] = {}
    labels: dict[str, str] = {}
    for ln in P.lines:
        vals = [(v or 0.0) for v in (ln.values + [None] * n)[:n]]
        if ln.key in lines:
            lines[ln.key] = [a + b for a, b in zip(lines[ln.key], vals)]
        else:
            lines[ln.key] = vals
            labels[ln.key] = ln.label
    rev_keys = [k for k in lines if k in REVENUE_KEYS or k in VACANCY_KEYS]
    exp_keys = [k for k in lines if k not in REVENUE_KEYS and k not in VACANCY_KEYS and k not in CRE_TOTAL_KEYS]
    rev_sum = [sum(lines[k][t] for k in rev_keys) for t in range(n)]
    exp_sum = [sum(lines[k][t] for k in exp_keys) for t in range(n)]
    tol_r, tol_e = 0.5 * len(rev_keys) + 1, 0.5 * len(exp_keys) + 1

    def anchored(key, computed, tol, name):
        out = []
        for t in range(n):
            st = lines.get(key, [None] * n)[t] if key in lines else None
            if st and abs(st - computed[t]) <= tol:
                out.append(st)
            else:
                if st and abs(st - computed[t]) > tol:
                    flags.append(Flag("warning", "consistency",
                                      f"{years[t]}: borrower's stated {name} {fmt_money(st)} differs from the sum of its lines {fmt_money(computed[t])}; using the line sum.",
                                      P.doc))
                out.append(computed[t])
        return out

    b_rev = anchored("total_revenue", rev_sum, tol_r, "total revenue")
    b_exp = anchored("total_expenses", exp_sum, tol_e, "total expenses")
    b_noi_calc = [r - e for r, e in zip(b_rev, b_exp)]
    b_noi = anchored("noi", b_noi_calc, 2, "NOI")

    # ---- underwriter adjustments ----
    id_lines = {k: list(v) for k, v in lines.items()}
    notes: list[dict] = []
    adjustments = []
    g_exp, g_rent = A["expense_growth_min"], A["rent_growth_max"]

    def growth(vals):
        return [safe_div(vals[t] - vals[t - 1], vals[t - 1]) for t in range(1, n) if vals[t - 1]]

    def cagr(vals):
        """Compound growth first->last; robust to display rounding of individual years."""
        if n < 2 or not vals[0] or vals[-1] is None or vals[0] <= 0 or vals[-1] <= 0:
            return None
        return (vals[-1] / vals[0]) ** (1 / (n - 1)) - 1

    # rent growth check
    for k in [k for k in lines if k in REVENUE_KEYS and k != "other_income"]:
        gr = cagr(lines[k])
        if gr is not None and gr > g_rent + 0.0005:
            new = [lines[k][0] * (1 + g_rent) ** t for t in range(n)]
            adjustments.append((k, new, f"{labels[k]} grown at Invest Detroit's maximum of {fmt_pct(g_rent, 0)} per year (borrower used {fmt_pct(gr)})."))
            vk = next((v for v, g in GROSS_FOR_VAC.items() if g == k and v in lines), None)
            if vk:
                pct = [safe_div(-lines[vk][t], lines[k][t]) or 0.0 for t in range(n)]
                adjustments.append((vk, [-new[t] * pct[t] for t in range(n)], None))
    # RE taxes
    est = deal.terms.re_tax_year1_override or cre.appraisal.re_tax_estimate
    if est and "re_taxes" in lines and est > lines["re_taxes"][0] + 1:
        new = [est * (1 + g_exp) ** t for t in range(n)]
        adjustments.append(("re_taxes", new, None))
        notes.append({"line": "re_taxes", "text": deal.terms.qualitative.get("re_tax_note") or
                      f"Based on appraiser's estimate ({fmt_money(est)}). Borrower projected {fmt_money(lines['re_taxes'][0])} of real estate taxes."})
    # one-time costs
    for k in deal.terms.one_time_expense_keys:
        if k in lines and any(lines[k][1:]):
            new = [lines[k][0]] + [0.0] * (n - 1)
            adjustments.append((k, new, None))
            notes.append({"line": k, "text": deal.terms.qualitative.get("lease_up_note") or
                          f"{labels[k]} is a one-time lease-up cost; excluded after the first year."})
    # expense growth floor
    for k in exp_keys:
        if k in ("re_taxes", "tax_abatement", "replacement_reserves") or k in deal.terms.one_time_expense_keys:
            continue
        gr = cagr(lines[k])
        if gr is not None and gr < g_exp - 0.0005 and lines[k][0] > 0:
            new = [lines[k][0] * (1 + g_exp) ** t for t in range(n)]
            adjustments.append((k, new, f"{labels[k]} grown at {fmt_pct(g_exp, 0)} (borrower used {fmt_pct(gr)} per year)"))
    # replacement reserves
    sf = cre.property.gross_sf or cre.property.rentable_sf
    rr_needed = (A["replacement_reserve_per_sf"] * sf) if sf else None
    have_rr = sum(lines.get("replacement_reserves", [0])[:1])
    cap_res = lines.get("capital_reserves", [0] * n)[0]
    if rr_needed and have_rr < rr_needed - 1:
        if cap_res + have_rr >= rr_needed - 1:
            notes.append({"line": "replacement_reserves",
                          "text": f"No replacement reserve was added since the borrower already includes capital reserves "
                                  f"({fmt_money(cap_res)}, ${cap_res / sf:,.2f}/SF) that exceed Invest Detroit's guideline of "
                                  f"${A['replacement_reserve_per_sf']:.2f}/SF ({fmt_money(rr_needed)})."})
        else:
            short = rr_needed - cap_res - have_rr
            base_rr = lines.get("replacement_reserves", [0.0] * n)
            new = [base_rr[t] + short * (1 + g_exp) ** t for t in range(n)]
            adjustments.append(("replacement_reserves", new, f"Replacement reserves increased by {fmt_money(short)} to Invest Detroit's guideline of "
                                f"${A['replacement_reserve_per_sf']:.2f}/SF ({fmt_money(rr_needed)} on {sf:,.0f} SF, net of capital reserves)."))
            labels.setdefault("replacement_reserves", "Replacement Reserves")
            lines.setdefault("replacement_reserves", [0.0] * n)
    # apply adjustments as deltas
    rev_delta = [0.0] * n
    exp_delta = [0.0] * n
    for k, new, note in adjustments:
        old = id_lines.get(k, [0.0] * n)
        for t in range(n):
            d = new[t] - old[t]
            if k in REVENUE_KEYS or k in VACANCY_KEYS:
                rev_delta[t] += d
            else:
                exp_delta[t] += d
        id_lines[k] = new
        if note:
            notes.append({"line": k, "text": note})
    # vacancy floor on stabilized years (years without a general vacancy line)
    gross_keys = [k for k in id_lines if k in GROSS_FOR_VAC.values()]
    vac_keys = [k for k in id_lines if k in GROSS_FOR_VAC]
    blended = []
    for t in range(n):
        gross = sum(id_lines[k][t] for k in gross_keys)
        vac = -sum(id_lines[k][t] for k in vac_keys) - id_lines.get("general_vacancy", [0] * n)[t]
        blended.append(safe_div(vac, gross))
    # Invest Detroit's vacancy guideline is for COMMERCIAL space; residential lines are not floored (flagged instead)
    vmin = A["commercial_vacancy_min"]
    lease_up = list(lines.get("general_vacancy", [0.0] * n))      # borrower's lease-up vacancy marks non-stabilized years
    stab_years = [t for t in range(n) if not lease_up[t]]
    com_gross_keys = [k for k in gross_keys if k in COMMERCIAL_GROSS]
    com_vac_keys = [v for v in vac_keys if GROSS_FOR_VAC[v] in COMMERCIAL_GROSS]
    floor_added = [0.0] * n
    for t in stab_years:
        cg = sum(id_lines[k][t] for k in com_gross_keys)
        cv = -sum(id_lines[k][t] for k in com_vac_keys)
        if cg and cv / cg < vmin - 0.0005:
            add = vmin * cg - cv
            id_lines.setdefault("general_vacancy", [0.0] * n)
            id_lines["general_vacancy"][t] -= add
            rev_delta[t] -= add
            floor_added[t] = add
    if any(floor_added):
        labels.setdefault("general_vacancy", "Less: Additional Vacancy (underwriter)")
        notes.append({"line": "general_vacancy", "text": f"Commercial vacancy increased to Invest Detroit's {vmin * 100:.0f}% commercial vacancy guideline "
                      f"(additional {fmt_money(max(floor_added))} in a stabilized year)."})
    res_keys = [k for k in gross_keys if k == "gross_residential_rent"]
    if res_keys:
        flags.append(Flag("info", "assumption", "Residential vacancy is the borrower's assumption; the Credit Guidelines state a vacancy "
                                                "standard for commercial space only. Confirm the residential vacancy assumption with Invest Detroit."))
    for t in range(n):
        gross = sum(id_lines[k][t] for k in gross_keys)
        vac = -sum(id_lines[k][t] for k in vac_keys) - id_lines.get("general_vacancy", [0] * n)[t]
        blended[t] = safe_div(vac, gross)
    if any(blended[t] is not None and blended[t] < vmin for t in stab_years):
        pass
    id_rev = [b_rev[t] + rev_delta[t] for t in range(n)]
    id_exp = [b_exp[t] + exp_delta[t] for t in range(n)]
    id_noi = [b_noi[t] + rev_delta[t] - exp_delta[t] for t in range(n)]

    # ---- debt service ----
    months = [int(deal.terms.debt_service_months.get(str(y), 12)) for y in years]
    prop, take = deal.terms.proposed_loan, deal.terms.takeout_loan
    base_loan = take or prop
    ds_base = [_loan_ds(base_loan, m) for m in months]
    ds_prop = [_loan_ds(prop, m) for m in months]
    dscr_base = [safe_div(id_noi[t], ds_base[t]) for t in range(n)]
    dscr_prop = [safe_div(id_noi[t], ds_prop[t]) for t in range(n)]
    stab = next((t for t in range(n) if months[t] == 12 and not lease_up[t]), None)

    sizing = None
    if take and stab is not None:
        target = deal.terms.options.target_dscr_takeout or A["takeout_sizing_dscr"]
        max_loan = max_loan_for_payment(id_noi[stab] / target, take.rate, take.amort_months)
        sizing = {"year": years[stab], "target_dscr": target, "noi": id_noi[stab], "max_loan": max_loan,
                  "chosen": take.amount, "dscr_at_chosen": dscr_base[stab]}

    # ---- sensitivity: vacancy that drives DSCR to 1.00x on the Invest Detroit loan ----
    sens_key = deal.terms.sensitivity_line
    if not sens_key:
        biggest = max(gross_keys, key=lambda k: id_lines[k][stab if stab is not None else 0]) if gross_keys else None
        sens_key = next((v for v, g in GROSS_FOR_VAC.items() if g == biggest), None)
    sens = None
    if sens_key:
        gross_line = GROSS_FOR_VAC[sens_key]
        base_loss = [-id_lines.get(sens_key, [0.0] * n)[t] for t in range(n)]
        loss, pct, rev_s, noi_s = [], [], [], []
        for t in range(n):
            if ds_prop[t] > 0:
                L_new = id_noi[t] + base_loss[t] - ds_prop[t]
            else:
                L_new = base_loss[t]
            loss.append(L_new)
            pct.append(safe_div(L_new, id_lines[gross_line][t]))
            rev_s.append(id_rev[t] + base_loss[t] - L_new)
            noi_s.append(id_noi[t] + base_loss[t] - L_new)
        stab_pcts = [pct[t] for t in range(n) if months[t] == 12 and ds_prop[t] > 0 and pct[t] is not None]
        sens = {"line": sens_key, "gross_line": gross_line, "loss": loss, "pct": pct, "revenue": rev_s, "noi": noi_s,
                "debt_service": ds_prop, "cfads": [noi_s[t] - ds_prop[t] for t in range(n)],
                "dscr": [safe_div(noi_s[t], ds_prop[t]) for t in range(n)],
                "min_stabilized_pct": min(stab_pcts) if stab_pcts else None,
                "max_stabilized_pct": max(stab_pcts) if stab_pcts else None}
    # break-even occupancy on stabilized year (all-in debt service on base case)
    be_occ = None
    if stab is not None:
        gpr = sum(id_lines[k][stab] for k in gross_keys) + id_lines.get("cam_reimbursement", [0] * n)[stab]
        be_occ = safe_div(id_exp[stab] + ds_base[stab], gpr)

    rent_roll = _rent_roll(deal, A, flags)
    su = _sources_uses(deal, flags)
    coll = collateral_analysis(deal)
    takeout_metrics = None
    if take:
        takeout_metrics = {"ltc": safe_div(take.amount, su["total_uses"]), "ltv": safe_div(take.amount, coll["gross_value"])}

    # vacancy & growth facts for notes
    vac_facts = {}
    for vk in vac_keys:
        gk = GROSS_FOR_VAC[vk]
        t = stab if stab is not None else min(1, n - 1)
        vac_facts[vk] = safe_div(-id_lines[vk][t], id_lines[gk][t])
    yr1_general = safe_div(-id_lines.get("general_vacancy", [0] * n)[0], sum(id_lines[k][0] for k in gross_keys))
    rent_growth = {k: growth(lines[k]) for k in gross_keys}
    exp_growth = {k: growth(lines[k]) for k in exp_keys if lines[k][0]}
    rent_cagr = {k: cagr(lines[k]) for k in gross_keys}
    exp_cagr = {k: cagr(lines[k]) for k in exp_keys if lines[k][0] and k not in deal.terms.one_time_expense_keys and k != "re_taxes"}
    _cre_flags(deal, A, flags, blended, stab, years, dscr_prop, cre)

    return {"years": years, "labels": labels, "borrower": {"lines": lines, "revenue": b_rev, "expenses": b_exp, "noi": b_noi},
            "id": {"lines": id_lines, "revenue": id_rev, "expenses": id_exp, "noi": id_noi},
            "rev_keys": rev_keys, "exp_keys": exp_keys, "notes": notes, "months": months,
            "ds_base": ds_base, "ds_proposed": ds_prop, "dscr_base": dscr_base, "dscr_proposed": dscr_prop,
            "cfads_base": [id_noi[t] - ds_base[t] for t in range(n)], "base_loan": base_loan.model_dump() if base_loan else None,
            "stabilized_index": stab, "sizing": sizing, "sensitivity": sens, "break_even_occupancy": be_occ,
            "blended_vacancy": blended, "vacancy_by_line": vac_facts, "year1_general_vacancy": yr1_general,
            "rent_growth": rent_growth, "expense_growth": exp_growth, "rent_cagr": rent_cagr, "expense_cagr": exp_cagr,
            "rent_roll": rent_roll, "sources_uses": su, "collateral": coll, "takeout": takeout_metrics, "flags": flags}


def _rent_roll(deal: Deal, A: dict, flags: list[Flag]) -> dict:
    cre = deal.cre
    loss_rate = A["commercial_vacancy_min"]
    rows = []
    for u in cre.rent_roll:
        rent = u.annual_rent or 0.0
        rows.append({"unit": u.unit, "use": u.use, "sf": u.sf, "rent_psf": safe_div(rent, u.sf), "rent": rent,
                     "loss": -rent * loss_rate, "net": rent * (1 - loss_rate), "status": u.status, "tenant": u.tenant})
    by_use = {}
    for r in rows:
        b = by_use.setdefault(r["use"], {"sf": 0.0, "rent": 0.0, "units": 0})
        b["sf"] += r["sf"] or 0
        b["rent"] += r["rent"]
        b["units"] += 1
    for b in by_use.values():
        b["avg_psf"] = safe_div(b["rent"], b["sf"])
        rents = [r["rent"] / 12 for r in rows]
    for use, b in by_use.items():
        monthly = [r["rent"] / 12 for r in rows if r["use"] == use]
        b["monthly_min"], b["monthly_max"] = (min(monthly), max(monthly)) if monthly else (None, None)
    total = {"sf": sum(r["sf"] or 0 for r in rows), "rent": sum(r["rent"] for r in rows),
             "loss": sum(r["loss"] for r in rows), "net": sum(r["net"] for r in rows)}
    ap = cre.appraisal
    market = {"office": ap.market_rent_office_psf, "retail": ap.market_rent_retail_psf}
    comparisons = []
    for use, mkt in market.items():
        if mkt and use in by_use:
            comparisons.append({"use": use, "avg_psf": by_use[use]["avg_psf"], "market_psf": mkt,
                                "premium": safe_div(by_use[use]["avg_psf"] - mkt, mkt)})
    lois = []
    for l in cre.lois:
        unit = next((r for r in rows if l.unit and r["unit"].lower().startswith(l.unit.lower())), None) or \
               next((r for r in rows if l.tenant.lower() in r["unit"].lower()), None)
        psf = safe_div((l.monthly_rent or 0) * 12, l.sf)
        lois.append({**l.model_dump(), "annual_rent": (l.monthly_rent or 0) * 12, "rent_psf": psf,
                     "rent_roll_rent": unit["rent"] if unit else None,
                     "market_psf": market.get("retail") if (l.use or "").lower().find("office") < 0 else market.get("office")})
        if unit and l.monthly_rent and abs(unit["rent"] - l.monthly_rent * 12) > 1:
            flags.append(Flag("warning", "consistency",
                              f"{l.tenant} LOI rent {fmt_money(l.monthly_rent * 12)}/yr differs from the rent roll ({fmt_money(unit['rent'])}/yr).", unit["unit"]))
    proj_gross = None
    P = cre.projections
    for k, use in (("gross_retail_rent", "retail"), ("gross_office_rent", "office")):
        line = next((ln for ln in P.lines if ln.key == k), None)
        if line and use in by_use and line.values and line.values[0] is not None and abs(line.values[0] - by_use[use]["rent"]) > 1:
            flags.append(Flag("warning", "consistency",
                              f"Year-1 projected {use} rent {fmt_money(line.values[0])} differs from the rent roll total {fmt_money(by_use[use]['rent'])}.", P.doc))
    return {"rows": rows, "by_use": by_use, "total": total, "loss_rate": loss_rate, "market": comparisons, "lois": lois}


def _sources_uses(deal: Deal, flags: list[Flag]) -> dict:
    cre = deal.cre
    cats = [("acquisition", "Acquisition"), ("hard", "Hard Costs"), ("hard_contingency", "Hard Cost Contingency"),
            ("professional", "Professional Fees"), ("lender_carry", "Lender Costs & Carrying Costs"),
            ("developer_fee", "Developer Fee"), ("reserves", "Reserves"), ("other_soft", "Other Soft Costs"),
            ("soft_contingency", "Soft Cost Contingency")]
    amt = {c: sum(b.amount for b in cre.budget if b.category == c) for c, _ in cats}
    total_uses = sum(amt.values())
    total_sources = sum(s.amount for s in cre.sources)
    if cre.sources and abs(total_sources - total_uses) > 1:
        flags.append(Flag("critical", "consistency",
                          f"Sources ({fmt_money(total_sources)}) do not equal uses ({fmt_money(total_uses)}); gap {fmt_money(total_sources - total_uses)}.", "sources & uses"))
    soft_base = amt["professional"] + amt["lender_carry"] + amt["developer_fee"] + amt["other_soft"] + amt["reserves"]
    hard_pct = safe_div(amt["hard_contingency"], amt["hard"])
    soft_pct = safe_div(amt["soft_contingency"], soft_base)
    labeled = {}
    import re
    for b in cre.budget:
        m = re.search(r"\((\d+(?:\.\d+)?)%\)", b.label)
        if m and b.category in ("hard_contingency", "soft_contingency"):
            labeled[b.category] = float(m.group(1)) / 100
    rsf = cre.property.rentable_sf or sum(u.sf or 0 for u in cre.rent_roll) or None
    gsf = cre.property.gross_sf
    id_amt = sum(s.amount for s in cre.sources if s.kind == "invest_detroit")
    equity = sum(s.amount for s in cre.sources if s.kind == "equity")
    uses = [{"key": c, "label": lab, "amount": amt[c], "pct": safe_div(amt[c], total_uses)} for c, lab in cats if amt[c]]
    sources = [{"label": s.label, "amount": s.amount, "kind": s.kind, "pct": safe_div(s.amount, total_sources)} for s in cre.sources]
    return {"uses": uses, "sources": sources, "total_uses": total_uses, "total_sources": total_sources,
            "hard_cost_psf": safe_div(amt["hard"], rsf), "total_cost_psf": safe_div(total_uses, rsf),
            "hard_cost_psf_gross": safe_div(amt["hard"], gsf), "total_cost_psf_gross": safe_div(total_uses, gsf),
            "rentable_sf": rsf, "gross_sf": gsf,
            "hard_contingency_pct": hard_pct, "soft_contingency_pct": soft_pct, "labeled_contingency": labeled,
            "hard_base": amt["hard"], "soft_base": soft_base,
            "id_loan": id_amt, "equity": equity, "equity_pct": safe_div(equity, total_uses), "ltc": safe_div(id_amt, total_uses),
            "budget": [b.model_dump() for b in cre.budget]}


def _cre_flags(deal, A, flags, blended, stab, years, dscr_prop, cre):
    vmin = A["commercial_vacancy_min"]
    if cre.appraisal.vacancy_estimate is not None and stab is not None and blended[stab] is not None:
        if blended[stab] < cre.appraisal.vacancy_estimate:
            flags.append(Flag("warning", "assumption", f"Stabilized vacancy {fmt_pct(blended[stab])} is below the appraiser's {fmt_pct(cre.appraisal.vacancy_estimate)}."))
    if stab is not None and dscr_prop[stab] is not None:
        mind = load_guidelines()["products"].get(deal.terms.product, {}).get("min_dscr")
        if mind and dscr_prop[stab] < mind:
            flags.append(Flag("warning", "policy", f"Stabilized DSCR on the Invest Detroit loan {fmt_x(dscr_prop[stab])} is below the {fmt_x(mind)} minimum."))
    if A.get("verified") is False:
        flags.append(Flag("info", "assumption",
                          f"CRE underwriting assumptions (rent growth {fmt_pct(A['rent_growth_max'], 0)}, expense growth {fmt_pct(A['expense_growth_min'], 0)}, "
                          f"commercial vacancy {fmt_pct(vmin, 0)}, reserves ${A['replacement_reserve_per_sf']:.2f}/SF) come from prior guideline wording and are not in the 4/2026 Credit Guidelines; confirm."))
