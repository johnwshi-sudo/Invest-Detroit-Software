"""Small Business / C&I analysis — reproduces the tables in Invest Detroit's Investment Summary.

Formulas (reverse-engineered from the Kirk's Automotive sample and checked to the dollar):
  Gross profit       = Sales - COGS
  Operating profit   = Gross profit - Total (operating) expenses
  Net income         = as stated (computed value is foot-checked)
  EBITDA             = Net income + Interest + Income taxes + Depreciation + Amortization
  Debt service       = proposed Invest Detroit loan P&I + other lines (LOC interest, notes P&I), pro-rated by months
  DSCR               = EBITDA / Total debt service ; Cash flow after debt service = EBITDA - Total debt service
  Break-even         = sales at which DSCR = 1.00x holding gross margin %, operating expenses, other income/expense fixed
  Ratios (Exhibit E) = 360-day year; inventory days on sales (template default); interim periods not annualized
"""
from __future__ import annotations

from typing import Optional

from ..schema import Deal
from .common import Flag, annual_debt_service, fmt_money, fmt_pct, fmt_x, safe_div
from .spread import Spread, build_spread, debt_balance

IS_FIELDS = ["revenue", "cogs", "operating_expenses", "other_income", "nonrecurring_income", "interest_expense",
             "other_expense", "income_taxes", "depreciation", "amortization", "net_income", "officer_compensation"]


def _income(s: Spread, pid: str, deal: Deal, flags: list[Flag]) -> dict:
    p = s.period(pid)
    g = lambda k: s.get(pid, k, 0.0) or 0.0
    rev = g("revenue")
    cogs = g("cogs") if s.has(pid, "cogs") else 0.0   # never derive COGS from a stated gross profit (would hide a misread)
    gp = rev - cogs
    if s.has(pid, "operating_expenses"):
        opex = g("operating_expenses")
    elif s.has(pid, "operating_income"):
        opex = gp - g("operating_income")
    else:
        opex = 0.0
        flags.append(Flag("warning", "missing", f"{p.label}: operating expenses not found.", pid))
    op = gp - opex
    if s.has(pid, "operating_income") and abs(op - g("operating_income")) > 2:
        flags.append(Flag("warning", "consistency",
                          f"{p.label}: operating income computed {fmt_money(op)} vs stated {fmt_money(g('operating_income'))}.", pid))
    nonrec = g("nonrecurring_income")
    other_inc = g("other_income") + nonrec
    interest = g("interest_expense")
    other_exp = interest + g("other_expense")
    taxes = g("income_taxes")
    ni_calc = op + other_inc - other_exp - taxes
    if s.has(pid, "net_income"):
        ni = g("net_income")
        if abs(ni - ni_calc) > 2:
            flags.append(Flag("warning", "consistency",
                              f"{p.label}: net income computed {fmt_money(ni_calc)} vs stated {fmt_money(ni)}; using stated.", pid))
    else:
        ni = ni_calc
    interest_addback = interest + g("interest_included_above")
    dep, amort = g("depreciation"), g("amortization")
    if not s.has(pid, "depreciation") and p.kind != "projection":
        flags.append(Flag("info", "missing", f"{p.label}: depreciation not found; EBITDA excludes it.", pid))
    ebitda = ni + interest_addback + taxes + dep + amort
    ebitda_ex = ebitda - nonrec
    if not deal.terms.options.include_nonrecurring_in_ebitda:
        ebitda, ebitda_ex = ebitda_ex, ebitda_ex
    return {"cogs_pct": safe_div(cogs, rev), "gross_margin": safe_div(gp, rev), "net_margin": safe_div(ni, rev),
            "ebitda_margin": safe_div(ebitda, rev),
            "revenue": rev, "cogs": cogs, "gross_profit": gp, "operating_expenses": opex, "operating_profit": op,
            "other_income": other_inc, "nonrecurring_income": nonrec, "other_expenses": other_exp,
            "interest": interest_addback, "income_taxes": taxes, "net_income": ni, "depreciation": dep,
            "amortization": amort, "ebitda": ebitda, "ebitda_ex_nonrecurring": ebitda_ex,
            "officer_compensation": s.get(pid, "officer_compensation", None), "distributions": g("distributions"),
            "months": p.months}


def proposed_annual_payment(deal: Deal) -> Optional[float]:
    L = deal.terms.proposed_loan
    if L is None:
        return None
    if L.annual_payment_override is not None:
        return L.annual_payment_override
    return annual_debt_service(L.amount, L.rate, L.amort_months, L.day_count)


def proposed_label(deal: Deal) -> str:
    L = deal.terms.proposed_loan
    if L is None:
        return "Proposed loan"
    amt = f"${L.amount / 1000:,.0f}K"
    am = f"{L.amort_months} Mos. Amort" if L.amort_months else "Interest Only"
    return f"{L.label} {amt} @ {L.rate * 100:.2f}%; {am}"


def debt_service(deal: Deal, pid: str, months: int, flags: list[Flag]) -> dict:
    lines = []
    ann = proposed_annual_payment(deal)
    if ann is not None:
        lines.append({"label": proposed_label(deal), "amount": ann * months / 12, "basis": "proposed"})
        L = deal.terms.proposed_loan
        if L.annual_payment_override is not None:
            calc = annual_debt_service(L.amount, L.rate, L.amort_months, L.day_count)
            if abs(calc - L.annual_payment_override) / max(calc, 1) > 0.001:
                msg = (f"Stated annual payment {fmt_money(L.annual_payment_override)} differs from computed "
                       f"{fmt_money(calc)} ({L.day_count}) for {proposed_label(deal)}; using stated.")
                if not any(f.message == msg for f in flags):
                    flags.append(Flag("info", "consistency", msg, "terms.proposed_loan"))
    for dl in deal.terms.debt_service_lines:
        if pid in dl.amounts:
            amt = dl.amounts[pid]
        elif dl.default_amount is not None:
            amt = dl.default_amount * months / 12
        else:
            flags.append(Flag("warning", "missing", f"No debt service amount for '{dl.label}' in {pid}.", pid))
            continue
        lines.append({"label": dl.label, "amount": amt, "basis": dl.basis})
    return {"lines": lines, "total": sum(l["amount"] for l in lines)}


# ------------------------------------------------------------------ balance sheet (Invest Detroit presentation)
def _balance_sheet(deal: Deal, s: Spread, pids: list[str], flags: list[Flag]) -> dict:
    opt = deal.terms.options
    out = {}
    id_debts = [d for d in s.debts if d.is_invest_detroit]
    sub_debts = [d for d in s.debts if d.subordinated and not d.is_invest_detroit]
    for pid in pids:
        g = lambda k: s.get(pid, k, 0.0) or 0.0
        ca = {k: g(k) for k in ["cash", "accounts_receivable", "inventory", "other_receivables", "prepaid_expenses", "other_current_assets"]}
        tca = sum(ca.values())
        fa_items = s.items(pid, "fixed_assets_gross")
        net_fa = g("fixed_assets_gross") + g("accumulated_depreciation") if s.has(pid, "fixed_assets_gross") else g("net_fixed_assets")
        if s.has(pid, "accumulated_depreciation") and g("accumulated_depreciation") > 0:
            net_fa = g("fixed_assets_gross") - g("accumulated_depreciation")
        oa = {k: g(k) for k in ["deposits", "other_assets", "intangible_assets"]}
        ta = tca + net_fa + sum(oa.values())
        if s.has(pid, "total_assets") and abs(ta - g("total_assets")) > 2:
            flags.append(Flag("warning", "consistency", f"{pid}: total assets computed {fmt_money(ta)} vs stated {fmt_money(g('total_assets'))}.", pid))
        cpltd, ltd = g("current_portion_ltd"), g("long_term_debt")
        cl_items = {"accounts_payable": g("accounts_payable"), "accrued_expenses": g("accrued_expenses"),
                    "line_of_credit": g("line_of_credit"), "other_current_liabilities": g("other_current_liabilities")}
        term_total = ltd + (0 if opt.cpltd_in_current else cpltd)
        if opt.cpltd_in_current:
            cl_items["current_portion_ltd"] = cpltd
        # allocate term debt by creditor
        id_bal = _period_balance(id_debts, pid, s, flags)
        sub_bal = _period_balance(sub_debts, pid, s, flags, assume_unchanged=True)
        id_bal = id_bal or 0.0
        sub_bal = sub_bal or 0.0
        # when CPLTD is shown as current, part of each note sits in CPLTD: split it out by the note's payment terms
        id_cur = _current_portion(id_debts, pid, flags) if (opt.cpltd_in_current and id_bal and cpltd) else 0.0
        sub_cur = _current_portion(sub_debts, pid, flags) if (opt.cpltd_in_current and sub_bal and cpltd) else 0.0
        id_cur, sub_cur = min(id_cur, cpltd), min(sub_cur, max(cpltd - id_cur, 0.0))
        other_term = term_total - (id_bal - id_cur) - (sub_bal - sub_cur) + g("other_liabilities")
        equity_stated = g("total_equity") if s.has(pid, "total_equity") else ta - sum(cl_items.values()) - term_total - g("other_liabilities")
        if opt.treat_id_note_as_equity and id_bal:
            if id_cur:
                cl_items["current_portion_ltd"] = cl_items.get("current_portion_ltd", 0.0) - id_cur
            tcl = sum(cl_items.values())
            lt_obligations = other_term + (sub_bal - sub_cur)
            nw = equity_stated + id_bal
            total_liab = tcl + lt_obligations
        else:
            tcl = sum(cl_items.values())
            lt_obligations = other_term + (sub_bal - sub_cur) + (id_bal - id_cur)
            nw = equity_stated
            total_liab = tcl + lt_obligations
        if abs(total_liab + nw - ta) > 5:
            flags.append(Flag("warning", "consistency",
                              f"{pid}: liabilities + net worth ({fmt_money(total_liab + nw)}) do not equal total assets ({fmt_money(ta)}).", pid))
        out[pid] = {
            "current_assets": ca, "total_current_assets": tca,
            "fixed_asset_items": fa_items, "accumulated_depreciation": -abs(g("accumulated_depreciation")),
            "net_fixed_assets": net_fa, "other_assets": oa, "total_other_assets": sum(oa.values()), "total_assets": ta,
            "current_liabilities": cl_items, "total_current_liabilities": tcl,
            "id_note": id_bal, "subordinated_notes": sub_bal, "other_term_debt": other_term,
            "lt_obligations": lt_obligations, "total_liabilities": total_liab,
            "equity_stated": equity_stated, "net_worth": nw,
            "equity_items": {k: g(k) for k in ["common_stock", "paid_in_capital", "retained_earnings", "current_year_income", "other_equity"] if s.has(pid, k)},
            "intangibles": g("intangible_assets"),
        }
    return out


def _current_portion(debts, pid, flags) -> float:
    """Principal due in the 12 months after `pid`, from each note's balance, rate and monthly payment."""
    total = 0.0
    for d in debts:
        bal = debt_balance(d, pid)
        if not bal:
            continue
        if d.monthly_payment is None or d.interest_rate is None:
            msg = f"Current portion of {d.creditor} cannot be split from CPLTD (payment terms not extracted); net worth may include it twice."
            if not any(f.message == msg for f in flags):
                flags.append(Flag("warning", "missing", msg, d.creditor))
            continue
        b, r = bal, d.interest_rate / 12
        for _ in range(12):
            if b <= 0:
                break
            p = min(d.monthly_payment - b * r, b)
            b -= max(p, 0.0)
        total += bal - b
    return total


def _period_balance(debts, pid, s: Spread, flags, assume_unchanged=False) -> Optional[float]:
    """Balance of a group of debts at pid; rolls back from the next period using cash-flow principal changes."""
    total = 0.0
    found = False
    pids = [p.id for p in s.periods]
    for d in debts:
        bal = debt_balance(d, pid)
        if bal is None:
            later = [b for b in d.balances if b.period_id in pids and pids.index(b.period_id) > pids.index(pid)]
            if later:
                nxt = min(later, key=lambda b: pids.index(b.period_id))
                if pids.index(nxt.period_id) == pids.index(pid) + 1 and d.cash_flow_change is not None:
                    bal = nxt.value - d.cash_flow_change
                    msg = (f"{d.creditor} balance at {pid} derived as {fmt_money(bal)} from the {nxt.period_id} balance "
                           f"{fmt_money(nxt.value)} less the cash-flow principal change {fmt_money(d.cash_flow_change)}.")
                    if not any(f.message == msg for f in flags):
                        flags.append(Flag("info", "derived", msg, d.doc or d.creditor))
                elif assume_unchanged:
                    bal = nxt.value
                    msg = f"{d.creditor} balance at {pid} assumed unchanged at {fmt_money(bal)} (no repayment shown)."
                    if not any(f.message == msg for f in flags):
                        flags.append(Flag("info", "derived", msg, d.doc or d.creditor))
        if bal is not None:
            total += bal
            found = True
    return total if found else None


def _ratios(deal: Deal, bs: dict, inc: dict) -> dict:
    out = {}
    for pid, b in bs.items():
        i = inc.get(pid)
        if i is None:
            continue
        sales, cogs, ni = i["revenue"], i["cogs"], i["net_income"]
        ca = b["current_assets"]
        tcl = b["total_current_liabilities"]
        nw = b["net_worth"]
        inv_base = sales if deal.terms.options.ratio_inventory_days_basis == "sales" else cogs
        pos_nw = nw if nw > 0 else None          # worth-based ratios are not meaningful with zero/negative net worth
        out[pid] = {
            "working_capital": b["total_current_assets"] - tcl,
            "quick_ratio": safe_div(ca["cash"] + ca["accounts_receivable"] + ca["other_receivables"], tcl),
            "current_ratio": safe_div(b["total_current_assets"], tcl),
            "sales_to_working_capital": safe_div(sales, b["total_current_assets"] - tcl),
            "net_worth": nw,
            "tangible_net_worth": nw - b["intangibles"],
            "debt_to_worth": safe_div(b["total_liabilities"], pos_nw),
            "debt_to_tangible_worth": safe_div(b["total_liabilities"], (nw - b["intangibles"]) if nw - b["intangibles"] > 0 else None),
            "lt_debt_to_net_fixed_assets": safe_div(b["lt_obligations"], b["net_fixed_assets"]),
            "liabilities_to_assets": safe_div(b["total_liabilities"], b["total_assets"]),
            "interest_coverage": safe_div(i["ebitda"], i["interest"]),
            "ebitda": i["ebitda"],
            "ebitda_less_distributions": i["ebitda"] - (i.get("distributions") or 0.0),
            "ebida": i["ebitda"] - i["income_taxes"],
            "dscr": i.get("dscr"),
            "return_on_assets": safe_div(ni, b["total_assets"]),
            "return_on_equity": safe_div(ni, pos_nw),
            "gross_margin": safe_div(i["gross_profit"], sales),
            "ebit": ni + i["interest"],
            "net_margin": safe_div(ni, sales),
            "ar_days": safe_div(ca["accounts_receivable"] * 360, sales),
            "ar_turnover": safe_div(sales, ca["accounts_receivable"]),
            "inventory_days": safe_div(ca["inventory"] * 360, inv_base),
            "inventory_turnover": safe_div(inv_base, ca["inventory"]),
            "ap_days": safe_div(b["current_liabilities"]["accounts_payable"] * 360, cogs),
            "sales_to_assets": safe_div(sales, b["total_assets"]),
            "sales_to_net_worth": safe_div(sales, pos_nw),
            "cash_to_sales": safe_div(ca["cash"], sales),
        }
    return out


def _tnw(deal: Deal, s: Spread, bs: dict) -> dict:
    excl = deal.terms.options.exclude_from_tnw
    out = {}
    sub_debts = [d for d in s.debts if d.subordinated and not d.is_invest_detroit]
    for pid, b in bs.items():
        sub_rows = []
        for d in sub_debts:
            bal = debt_balance(d, pid)
            if bal is None:  # assume unchanged (zero-interest subordinated shareholder notes)
                bal = next((x.value for x in d.balances), None)
            sub_rows.append((d.creditor, bal or 0.0))
        excluded = []
        for k in excl:
            v = (b["current_assets"].get(k) if k in b["current_assets"] else b["other_assets"].get(k, 0.0)) or 0.0
            excluded.append((k, -v))
        se = b["equity_stated"]
        total = se + b["id_note"] + sum(v for _, v in sub_rows) + sum(v for _, v in excluded)
        out[pid] = {"shareholders_equity": se, "id_note": b["id_note"], "subordinated": sub_rows,
                    "excluded": excluded, "computed_tnw": total}
    return out


def _break_even(inc: dict, ds: dict, pids: list[str]) -> dict:
    out = {}
    for pid in pids:
        i = inc[pid]
        if i["months"] != 12 or not i["revenue"]:
            continue
        gm = i["gross_profit"] / i["revenue"]
        cfads = i["ebitda"] - ds[pid]["total"]
        if gm <= 0:
            continue
        be_sales = i["revenue"] - cfads / gm
        be_gp = be_sales * gm
        delta = i["gross_profit"] - be_gp
        op = be_gp - i["operating_expenses"]
        ni = i["net_income"] - delta
        ebitda = i["ebitda"] - delta
        out[pid] = {"pct_of_sales": be_sales / i["revenue"], "revenue": be_sales, "cogs": be_sales - be_gp,
                    "gross_profit": be_gp, "operating_expenses": i["operating_expenses"], "operating_profit": op,
                    "other_income": i["other_income"], "other_expenses": i["other_expenses"], "net_income": ni,
                    "interest": i["interest"], "income_taxes": i["income_taxes"], "depreciation": i["depreciation"],
                    "amortization": i["amortization"], "ebitda": ebitda, "debt_service": ds[pid],
                    "cfads": ebitda - ds[pid]["total"], "dscr": safe_div(ebitda, ds[pid]["total"]),
                    "cushion_pct": 1 - be_sales / i["revenue"]}
    return out


def analyze_small_business(deal: Deal) -> dict:
    s = build_spread(deal)
    flags = list(s.flags)
    all_ids = [p.id for p in s.periods]
    hist = deal.terms.analysis_period_ids or [p.id for p in s.periods if p.kind in ("actual", "interim")]
    proj = [p.id for p in s.periods if p.kind == "projection"]
    inc, ds = {}, {}
    for pid in hist + proj:
        if pid not in all_ids:
            flags.append(Flag("warning", "missing", f"Period {pid} requested but not in extracted statements.", pid))
            continue
        inc[pid] = _income(s, pid, deal, flags)
        ds[pid] = debt_service(deal, pid, inc[pid]["months"], flags)
        i = inc[pid]
        i["debt_service"] = ds[pid]["total"]
        i["cfads"] = i["ebitda"] - ds[pid]["total"]
        i["dscr"] = safe_div(i["ebitda"], ds[pid]["total"])
        i["dscr_ex_nonrecurring"] = safe_div(i["ebitda_ex_nonrecurring"], ds[pid]["total"])
    hist = [p for p in hist if p in inc]
    proj = [p for p in proj if p in inc]

    # growth narrative facts
    growth = []
    annual = [p for p in hist if inc[p]["months"] == 12]
    for a, b in zip(annual, annual[1:]):
        growth.append({"from": a, "to": b, "pct": safe_div(inc[b]["revenue"] - inc[a]["revenue"], inc[a]["revenue"])})
    interim = [p for p in hist if inc[p]["months"] < 12]
    annualized = None
    if interim and annual:
        q = interim[-1]
        ann_rev = inc[q]["revenue"] * 12 / inc[q]["months"]
        annualized = {"period": q, "revenue": ann_rev, "vs": annual[-1],
                      "pct": safe_div(ann_rev - inc[annual[-1]]["revenue"], inc[annual[-1]]["revenue"])}

    # projection aggregate (e.g., Q1 actual + Q2-Q4 forecast = projected FYE)
    aggregate = None
    agg = deal.terms.projection_aggregate
    if not agg:
        agg = _auto_aggregate(s, inc)
    if agg and all(pid in inc for pid in agg["period_ids"]):
        keys = ["revenue", "cogs", "gross_profit", "operating_expenses", "operating_profit", "other_income",
                "nonrecurring_income", "other_expenses", "interest", "income_taxes", "net_income", "depreciation",
                "amortization", "ebitda", "ebitda_ex_nonrecurring"]
        a = {k: sum(inc[p][k] for p in agg["period_ids"]) for k in keys}
        lines = {}
        for p in agg["period_ids"]:
            for l in ds[p]["lines"]:
                lines[l["label"]] = lines.get(l["label"], 0.0) + l["amount"]
        a["debt_service_lines"] = [{"label": k, "amount": v} for k, v in lines.items()]
        a["debt_service"] = sum(lines.values())
        a["cfads"] = a["ebitda"] - a["debt_service"]
        a["dscr"] = safe_div(a["ebitda"], a["debt_service"])
        a["months"] = sum(inc[p]["months"] for p in agg["period_ids"])
        prior = annual[-1] if annual else None
        a["growth_vs_prior"] = safe_div(a["revenue"] - inc[prior]["revenue"], inc[prior]["revenue"]) if prior else None
        aggregate = {"label": agg.get("label", "Projected"), "period_ids": agg["period_ids"], "values": a, "prior": prior}

    bs_pids = [p for p in hist if any(s.has(p, k) for k in ("total_assets", "cash", "inventory"))]
    bs = _balance_sheet(deal, s, bs_pids, flags)
    ratios = _ratios(deal, bs, inc)
    tnw = _tnw(deal, s, bs)
    be = _break_even(inc, ds, annual)

    # debt schedule at latest balance-sheet date
    latest = bs_pids[-1] if bs_pids else None
    sched = []
    if latest:
        loc = s.get(latest, "line_of_credit", 0.0)
        loc_debt = next((d for d in s.debts if d.kind == "line_of_credit"), None)
        if loc:
            sched.append({"creditor": loc_debt.creditor if loc_debt else "Line of Credit", "balance": loc})
        for d in s.debts:
            if d.kind == "line_of_credit":
                continue
            bal = debt_balance(d, latest)
            if bal is not None:
                sched.append({"creditor": d.creditor, "balance": bal, "rate": d.interest_rate,
                              "monthly_payment": d.monthly_payment, "subordinated": d.subordinated,
                              "invest_detroit": d.is_invest_detroit})
        # reconcile schedule to balance sheet
        term_total = s.get(latest, "long_term_debt", 0.0) + s.get(latest, "current_portion_ltd", 0.0)
        sched_term = sum(x["balance"] for x in sched if x["creditor"] != (loc_debt.creditor if loc_debt else "Line of Credit"))
        if term_total and abs(term_total - sched_term) > 5:
            flags.append(Flag("warning", "consistency",
                              f"Debt schedule term debt ({fmt_money(sched_term)}) does not reconcile to balance sheet "
                              f"current + long-term debt ({fmt_money(term_total)}) at {latest}.", latest))
        # compare debt service lines to FS-note payments
        _check_note_payments(deal, s, flags)

    for pid, b in bs.items():
        if b["net_worth"] <= 0:
            flags.append(Flag("warning", "analysis", f"{pid}: net worth is negative ({fmt_money(b['net_worth'])}); debt-to-worth, return on equity "
                                                     f"and sales-to-worth are not meaningful.", pid))
    collateral = collateral_analysis(deal)
    nonrec_flags(inc, flags)
    _dscr_policy_flags(deal, inc, hist, aggregate, flags)

    return {"spread": s, "hist": hist, "proj": proj, "income": inc, "debt_service": ds, "growth": growth,
            "annualized": annualized, "aggregate": aggregate, "balance_sheet": bs, "bs_periods": bs_pids,
            "ratios": ratios, "tnw": tnw, "break_even": be, "debt_schedule": sched, "debt_schedule_date": latest,
            "collateral": collateral, "flags": flags}


def _auto_aggregate(s: Spread, inc: dict):
    """Interim actual + forecast periods that end the same fiscal year and total 12 months -> full-year forecast."""
    interim = [p for p in s.periods if p.kind == "interim" and p.id in inc]
    if not interim:
        return None
    it = interim[-1]
    parts = [it] + [p for p in s.periods if p.kind == "projection" and p.id in inc and p.end_date[:4] == it.end_date[:4]
                    and p.end_date > it.end_date]
    if sum(p.months for p in parts) != 12:
        return None
    end = parts[-1].end_date
    return {"label": f"Aggregate 12 Mos. Ending {end[5:7]}/{end[8:10]}/{end[2:4]}", "period_ids": [p.id for p in parts]}


def nonrec_flags(inc: dict, flags: list[Flag]) -> None:
    for pid, i in inc.items():
        if i["nonrecurring_income"]:
            flags.append(Flag("warning", "analysis",
                              f"{pid}: EBITDA includes {fmt_money(i['nonrecurring_income'])} of non-recurring income. "
                              f"DSCR is {fmt_x(i['dscr'])} including it and {fmt_x(i['dscr_ex_nonrecurring'])} excluding it.", pid))


def _dscr_policy_flags(deal: Deal, inc: dict, hist: list[str], aggregate, flags: list[Flag]) -> None:
    from ..guidelines import load_guidelines
    prod = load_guidelines()["products"].get(deal.terms.product, {})
    m = prod.get("min_dscr")
    if not m:
        return
    for pid in hist:
        d = inc[pid]["dscr"]
        if d is not None and d < m and inc[pid]["months"] == 12:
            flags.append(Flag("warning", "policy", f"{pid}: DSCR {fmt_x(d)} is below the {fmt_x(m)} guideline minimum.", pid))


def _check_note_payments(deal: Deal, s: Spread, flags: list[Flag]) -> None:
    """Compare underwriter debt-service lines with payments disclosed in the FS notes."""
    note_pay = {d.creditor: d.monthly_payment * 12 for d in s.debts
                if d.monthly_payment and not d.is_invest_detroit and d.kind != "line_of_credit"}
    if not note_pay or not deal.terms.debt_service_lines:
        return
    fs_total = sum(note_pay.values())
    entered = sum((dl.default_amount or 0) for dl in deal.terms.debt_service_lines if dl.basis == "scheduled")
    if entered and abs(fs_total - entered) / fs_total > 0.10:
        detail = "; ".join(f"{k}: {fmt_money(v)}" for k, v in note_pay.items())
        flags.append(Flag("warning", "consistency",
                          f"Scheduled debt service entered for other notes ({fmt_money(entered)}/yr) differs from payments "
                          f"disclosed in the financial statement notes ({fmt_money(fs_total)}/yr: {detail}). Confirm with the debt schedule.",
                          "terms.debt_service_lines"))


def collateral_analysis(deal: Deal) -> dict:
    items = []
    for c in deal.terms.collateral:
        disc = c.gross_value * c.advance_rate - c.prior_liens
        items.append({**c.model_dump(), "discounted_value": disc})
    gross = sum(c.gross_value for c in deal.terms.collateral)
    disc = sum(i["discounted_value"] for i in items)
    prior = sum(c.prior_liens for c in deal.terms.collateral)
    loan = deal.terms.proposed_loan.amount if deal.terms.proposed_loan else 0.0
    return {"items": items, "gross_value": gross, "discounted_value": disc, "prior_liens": prior, "loan": loan,
            "ltv_gross": safe_div(loan, gross), "cltv_gross": safe_div(loan + prior, gross),
            "ltv_discounted": safe_div(loan, disc + prior) if disc else None,
            "surplus_discounted": disc - loan, "surplus_gross": gross - prior - loan}


def summary_line(r: dict) -> str:
    last = r["hist"][-1] if r["hist"] else None
    if not last:
        return "No periods analyzed."
    i = r["income"][last]
    return f"{last}: sales {fmt_money(i['revenue'])}, EBITDA {fmt_money(i['ebitda'])}, DSCR {fmt_x(i['dscr'])}, GM {fmt_pct(safe_div(i['gross_profit'], i['revenue']))}"
