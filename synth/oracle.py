"""Independent expected values ("second underwriter").

Written from the definitions in docs/sample-findings.md and the Credit Guidelines, without importing the engine.
Inputs: the scenario spec, the presented (document) figures and the underwriter inputs in the deal.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
G = yaml.safe_load((ROOT / "config" / "credit_guidelines.yaml").read_text())
A = G["cre_underwriting_assumptions"]


def payment(p, rate, months):
    r = rate / 12
    if months <= 0:
        return p * r
    return p * r / (1 - (1 + r) ** -months)


def annual(L):
    if L is None:
        return 0.0
    if L.get("annual_payment_override"):
        return L["annual_payment_override"]
    return payment(L["amount"], L["rate"], L["amort_months"]) * 12


def div(a, b):
    return None if a is None or not b else a / b


# ----------------------------------------------------------------------------- small business
SOI = json.loads((ROOT / "config" / "irs_soi_benchmarks.json").read_text())


def industry_growth(code):
    best, bl = None, 0
    for ind in SOI["industries"]:
        for p in ind["naics_prefixes"]:
            if code.startswith(p) and len(p) > bl:
                best, bl = ind, len(p)
    g = list((best or {}).get("receipts_growth", {}).values())
    return sum(g) / len(g) if g else None


def growth_limit(code):
    avg = industry_growth(code)
    return 0.25 if avg is None else min(0.25, max(avg + 0.10, 0.0))


def expected_sb(spec, deal, pres):
    t = deal["terms"]
    periods = pres["periods"]
    inc = {}
    for p in periods:
        I = pres["is"][p["id"]]
        m = p["months"]
        ebitda = I["net_income"] + I["interest"] + I["tax"] + I["depreciation"]
        ds = annual(t["proposed_loan"]) * m / 12
        for dl in t["debt_service_lines"]:
            ds += dl["amounts"].get(p["id"], 0.0) if dl.get("amounts") else dl["default_amount"] * m / 12
        inc[p["id"]] = {"revenue": I["revenue"], "gross_profit": I["gross_profit"], "net_income": I["net_income"],
                        "ebitda": ebitda, "debt_service": ds, "cfads": ebitda - ds, "dscr": div(ebitda, ds),
                        "dscr_ex_nonrecurring": div(ebitda - I["nonrecurring"], ds), "months": m, "kind": p["kind"]}
    hist = [p["id"] for p in periods if p["kind"] != "projection"]
    annual_ids = [p for p in hist if inc[p]["months"] == 12]
    ratios = {}
    for pid in hist:
        B = pres["bs"].get(pid)
        if not B:
            continue
        I = pres["is"][pid]
        # Invest Detroit's own (subordinated) note is presented as quasi-equity; its current portion leaves CPLTD too
        id_names = [d["creditor"] for d in spec["fin"].get("debts", []) if d.get("is_id")]
        id_bal = sum(B["debt_balances"].get(nm, 0) for nm in id_names)
        id_cur = sum(B["debt_current"].get(nm, 0) for nm in id_names)
        cl = B["ap"] + B["accrued"] + B["loc"] + B["cpltd"] - id_cur        # GAAP / ID 2018 exhibit: CPLTD is current
        ltobl = B["ltd"] - (id_bal - id_cur)
        nw = B["equity"] + id_bal
        tl = cl + ltobl
        pos = nw if nw > 0 else None
        e = inc[pid]["ebitda"]
        ratios[pid] = {"current_ratio": div(B["tca"], cl), "quick_ratio": div(B["cash"] + B["ar"] + B["related_receivable"], cl),
                       "working_capital": B["tca"] - cl, "debt_to_worth": div(tl, pos), "liabilities_to_assets": div(tl, B["ta"]),
                       "lt_debt_to_net_fixed_assets": div(ltobl, B["nfa"]), "interest_coverage": div(e, I["interest"]),
                       "return_on_assets": div(I["net_income"], B["ta"]), "return_on_equity": div(I["net_income"], pos),
                       "gross_margin": div(I["gross_profit"], I["revenue"]), "net_margin": div(I["net_income"], I["revenue"]),
                       "ar_days": div(B["ar"] * 360, I["revenue"]), "inventory_days": div(B["inventory"] * 360, I["revenue"]),
                       "ap_days": div(B["ap"] * 360, I["cogs"]), "sales_to_assets": div(I["revenue"], B["ta"]),
                       "sales_to_net_worth": div(I["revenue"], pos), "cash_to_sales": div(B["cash"], I["revenue"]),
                       "net_worth": nw, "ebitda_less_distributions": e - I["distributions"]}
    be = {}
    for pid in annual_ids:
        i = inc[pid]
        gm = div(i["gross_profit"], i["revenue"])
        if gm and gm > 0:
            s = i["revenue"] - i["cfads"] / gm
            be[pid] = {"revenue": s, "cushion_pct": 1 - s / i["revenue"]}
    growth = [div(inc[b]["revenue"] - inc[a]["revenue"], inc[a]["revenue"]) for a, b in zip(annual_ids, annual_ids[1:])]
    # projection aggregate: interim + projection periods that end the same fiscal year
    agg = None
    interim = [p for p in periods if p["kind"] == "interim"]
    if interim:
        y = interim[-1]["end_date"][:4]
        parts = [interim[-1]["id"]] + [p["id"] for p in periods if p["kind"] == "projection" and p["end_date"][:4] == y]
        if sum(inc[x]["months"] for x in parts) == 12:
            ebitda = sum(inc[x]["ebitda"] for x in parts)
            ds = sum(inc[x]["debt_service"] for x in parts)
            rev = sum(inc[x]["revenue"] for x in parts)
            agg = {"revenue": rev, "ebitda": ebitda, "debt_service": ds, "dscr": div(ebitda, ds),
                   "growth_vs_prior": div(rev - inc[annual_ids[-1]]["revenue"], inc[annual_ids[-1]]["revenue"])}
    proj_growth = []
    prev = annual_ids[-1] if annual_ids else None
    for p in periods:
        if p["kind"] == "projection" and p["months"] == 12 and prev:
            proj_growth.append((p["id"], div(inc[p["id"]]["revenue"] - inc[prev]["revenue"], inc[prev]["revenue"])))
            prev = p["id"]
    coll = t.get("collateral") or []
    gross = sum(c["gross_value"] for c in coll)
    prior = sum(c.get("prior_liens", 0) for c in coll)
    ltv = div(t["proposed_loan"]["amount"] + prior, gross) if gross else None   # CLTV when senior liens exist
    exc = exceptions(spec, deal, {"dscr_last": inc[annual_ids[-1]]["dscr"] if annual_ids else None,
                                  "dscr_proj": agg["dscr"] if agg else None, "ltv": ltv, "revenue": inc[annual_ids[-1]]["revenue"] if annual_ids else None})
    ic_y, ic_m = int(t["ic_date"][:4]), int(t["ic_date"][5:7])
    start_up = (ic_y - spec["year_established"] - 1) * 12 + ic_m < 24 or len(annual_ids) < 2
    return {"income": inc, "hist": hist, "annual": annual_ids, "ratios": ratios, "break_even": be, "growth": growth,
            "aggregate": agg, "projection_growth": proj_growth, "ltv": ltv, "exceptions": exc, "startup": start_up,
            "line_of_business": "C&I" if ((inc[annual_ids[-1]]["revenue"] if annual_ids else 0) >= 5e6 or spec["naics"][:2] in ("31", "32", "33")) else "Small Business"}


# ----------------------------------------------------------------------------- CRE
GMAP = {"retail_vacancy": "gross_retail_rent", "office_vacancy": "gross_office_rent",
        "residential_vacancy": "gross_residential_rent", "other_vacancy": "other_gross_rent"}
COMMERCIAL = {"gross_retail_rent", "gross_office_rent", "other_gross_rent"}


def cagr(v):
    n = len(v)
    if n < 2 or not v[0] or v[0] <= 0 or v[-1] <= 0:
        return None
    return (v[-1] / v[0]) ** (1 / (n - 1)) - 1


def expected_cre(spec, deal, pres):
    t, c = deal["terms"], deal["cre"]
    yrs = pres["years"]
    n = len(yrs)
    L = {k: list(v) for k, v in pres["lines"].items()}
    notes = []
    # rent growth cap: regrow gross lines at 2% and keep the borrower's vacancy percentage
    # Invest Detroit caps rent AND reimbursement (CAM) growth at the guideline rate (Ballpoint memo grows CAM at 2%)
    for g in [k for k in L if k.startswith("gross_") or k in ("other_gross_rent", "cam_reimbursement")]:
        gr = cagr(L[g])
        if gr is not None and gr > A["rent_growth_max"] + 0.0005:
            vac = next((v for v, gg in GMAP.items() if gg == g and v in L), None)
            pct = [div(-L[vac][i], L[g][i]) or 0 for i in range(n)] if vac else None
            L[g] = [L[g][0] * (1 + A["rent_growth_max"]) ** i for i in range(n)]
            if vac:
                L[vac] = [-L[g][i] * pct[i] for i in range(n)]
            if "cam_reimbursement" in L:
                pass
            notes.append("rent_growth_cap")
    est = c["appraisal"].get("re_tax_estimate")
    if est and est > L.get("re_taxes", [0])[0] + 1:
        L["re_taxes"] = [est * 1.03 ** i for i in range(n)]
        notes.append("re_tax")
    if "leasing_marketing" in L and any(L["leasing_marketing"][1:]):
        L["leasing_marketing"] = [L["leasing_marketing"][0]] + [0.0] * (n - 1)
        notes.append("one_time")
    rev_keys = [k for k in L if k.startswith("gross_") or k.endswith("_vacancy") or k in ("cam_reimbursement", "general_vacancy", "other_gross_rent", "other_income")]
    exp_keys = [k for k in L if k not in rev_keys]
    for k in exp_keys:
        if k in ("re_taxes", "leasing_marketing", "tax_abatement", "replacement_reserves"):
            continue
        gr = cagr(L[k])
        if gr is not None and gr < A["expense_growth_min"] - 0.0005:
            L[k] = [L[k][0] * (1 + A["expense_growth_min"]) ** i for i in range(n)]
            notes.append("expense_floor")
    sf = c["property"]["gross_sf"]
    need = A["replacement_reserve_per_sf"] * sf
    have = L.get("replacement_reserves", [0])[0] + L.get("capital_reserves", [0])[0]
    if have < need - 1:
        add = need - have
        L["replacement_reserves"] = [L.get("replacement_reserves", [0] * n)[i] + add * 1.03 ** i for i in range(n)]
        if "replacement_reserves" not in exp_keys:
            exp_keys.append("replacement_reserves")
        notes.append("replacement_reserves")
    # commercial vacancy floor in stabilized years (no lease-up vacancy)
    gv = L.get("general_vacancy", [0] * n)
    for i in range(n):
        if gv[i]:
            continue
        com_gross = sum(L[g][i] for g in L if g in COMMERCIAL)
        com_vac = -sum(L[v][i] for v, g in GMAP.items() if g in COMMERCIAL and v in L)
        if com_gross and com_vac / com_gross < A["commercial_vacancy_min"] - 0.0005:
            L.setdefault("general_vacancy", [0.0] * n)
            L["general_vacancy"][i] -= (A["commercial_vacancy_min"] * com_gross - com_vac)
            if "general_vacancy" not in rev_keys:
                rev_keys.append("general_vacancy")
            if "vacancy_floor" not in notes:
                notes.append("vacancy_floor")
    rev = [sum(L[k][i] for k in rev_keys) for i in range(n)]
    exp = [sum(L[k][i] for k in exp_keys) for i in range(n)]
    noi = [rev[i] - exp[i] for i in range(n)]
    months = [int(t["debt_service_months"].get(str(y), 12)) for y in yrs]
    base_loan = t.get("takeout_loan") or t["proposed_loan"]
    ds_base = [annual(base_loan) * m / 12 for m in months]
    ds_prop = [annual(t["proposed_loan"]) * m / 12 for m in months]
    stab = next((i for i in range(n) if months[i] == 12 and not pres["lines"].get("general_vacancy", [0] * n)[i]), None)
    # sensitivity: vacancy on the largest gross line
    gross_lines = [g for g in L if g.startswith("gross_") or g == "other_gross_rent"]
    big = max(gross_lines, key=lambda g: L[g][stab if stab is not None else 0])
    vac = next(v for v, g in GMAP.items() if g == big)
    base_loss = [-L.get(vac, [0] * n)[i] for i in range(n)]
    sens_pct = [div(noi[i] + base_loss[i] - ds_prop[i], L[big][i]) if ds_prop[i] else None for i in range(n)]
    # sources & uses
    amt = {}
    for b in c["budget"]:
        amt[b["category"]] = amt.get(b["category"], 0) + b["amount"]
    total = sum(amt.values())
    soft_base = sum(amt.get(k, 0) for k in ("professional", "lender_carry", "developer_fee", "other_soft", "reserves"))
    eq = sum(s["amount"] for s in c["sources"] if s["kind"] == "equity")
    su = {"total_uses": total, "ltc": div(t["proposed_loan"]["amount"], total), "equity_pct": div(eq, total),
          "hard_pct": div(amt.get("hard_contingency", 0), amt.get("hard", 0)), "soft_pct": div(amt.get("soft_contingency", 0), soft_base) if soft_base else None,
          "cost_psf": div(total, c["property"]["rentable_sf"])}
    value = c["appraisal"]["as_stabilized_value"]
    ltv = div(t["proposed_loan"]["amount"], value)
    dscr_prop_stab = div(noi[stab], ds_prop[stab]) if stab is not None else None
    exc = exceptions(spec, deal, {"dscr_stab": dscr_prop_stab, "ltv": ltv, "su": su})
    risk = {"project_financial": 1 if ltv < 0.55 else 2 if ltv < 0.75 else 3 if ltv < 0.85 else 4 if ltv <= 1 else 5,
            "debt_service": None if dscr_prop_stab is None else 1 if dscr_prop_stab > 1.45 else 2 if dscr_prop_stab >= 1.30 else 3 if dscr_prop_stab >= 1.20 else 4 if dscr_prop_stab >= 1.15 else 5}
    return {"years": yrs, "revenue": rev, "expenses": exp, "noi": noi, "ds_base": ds_base, "ds_prop": ds_prop,
            "dscr_base": [div(noi[i], ds_base[i]) for i in range(n)], "dscr_prop": [div(noi[i], ds_prop[i]) for i in range(n)],
            "stab": stab, "sens_line": vac, "sens_pct": sens_pct, "su": su, "ltv": ltv, "exceptions": exc, "adjustments": notes,
            "risk": risk, "lines": L}


# ----------------------------------------------------------------------------- guideline exceptions
def exceptions(spec, deal, m):
    t = deal["terms"]
    P = G["products"][t["product"]]
    allp = G["all_products"]
    L = t["proposed_loan"]
    out = set()
    if P.get("max_amount") and L["amount"] > P["max_amount"]:
        out.add("Loan amount")
    if P.get("min_amount") and L["amount"] < P["min_amount"]:
        out.add("Loan amount (minimum)")
    if L.get("term_months") and P.get("max_term_months") and L["term_months"] > P["max_term_months"]:
        out.add("Term")
    if P.get("max_amortization_months") and L["amort_months"] > P["max_amortization_months"]:
        out.add("Amortization")
    lo, hi = allp["interest_rate"]["real_estate_secured" if t["real_estate_secured"] else "non_real_estate_secured"]
    if not lo - 1e-9 <= L["rate"] <= hi + 1e-9:
        out.add("Interest rate")
    if P.get("origination_fee") and t.get("fee_pct") is not None and L["amount"] >= 100_000 and t["fee_pct"] + 1e-9 < P["origination_fee"]:
        out.add("Origination / extension fee")
    md = P.get("min_dscr")
    if md:
        d = m.get("dscr_last") if t["deal_type"] == "small_business" else m.get("dscr_stab")
        if d is not None and d < md:
            out.add("Min DSCR" if t["deal_type"] == "small_business" else "Min DSCR @ stabilization")
    if P.get("max_ltv") and m.get("ltv") is not None and m["ltv"] > P["max_ltv"]:
        out.add("Max LTV")
    su = m.get("su")
    if su:
        if P.get("max_ltc") and su["ltc"] > P["max_ltc"]:
            out.add("Max LTC")
        if su["equity_pct"] is not None and su["equity_pct"] < allp["min_equity_total"]:
            out.add("Min equity")
        rt = deal["cre"]["property"]["rehab_type"]
        if rt == "acquisition" or not su["hard_pct"] and not deal_hard(deal):
            return _people(deal, out, allp)
        req = G["contingencies"]["new_construction" if rt == "new_construction" else "rehab_construction"]
        lab = "new construction" if rt == "new_construction" else "rehab"
        if su["hard_pct"] is not None and su["hard_pct"] + 1e-9 < req["hard"]:
            out.add(f"Hard cost contingency for {lab}")
        if su["soft_pct"] is not None and su["soft_pct"] + 1e-9 < req["soft"]:
            out.add(f"Soft cost contingency for {lab}")
    return _people(deal, out, allp)


def deal_hard(deal):
    return sum(b["amount"] for b in deal["cre"]["budget"] if b["category"] == "hard")


def _people(deal, out, allp):
    for o in deal["profile"]["people"]:
        if (o.get("ownership_pct") or 0) >= allp["guarantee_ownership_threshold"]:
            if o.get("guarantor") is False:
                out.add("Guarantee for owners > 20%")
            if o.get("background_check") is False:
                out.add("Background check")
    return out


def counted(exc: set) -> int:
    not_counted = {"Loan amount (minimum)", "Interest rate", "Origination / extension fee", "Guarantee for owners > 20%", "Background check"}
    return len([e for e in exc if e not in not_counted])


def expected(spec, deal, pres):
    return expected_sb(spec, deal, pres) if spec["kind"] == "small_business" else expected_cre(spec, deal, pres)
