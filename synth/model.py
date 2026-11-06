"""Ground-truth financial model for synthetic borrowers.

Builds internally consistent multi-year statements from business drivers:
  - income statement from revenue growth, COGS %, fixed/variable opex, depreciation, other/non-recurring income
  - interest computed from month-by-month amortization of each debt + line-of-credit balances
  - balance sheet from working-capital days, fixed assets and debt schedules; cash is the balancing item
    (if cash would go negative the line of credit absorbs it), so assets == liabilities + equity by construction
  - CRE borrower pro formas from rent roll + borrower assumptions (unrounded truth; PDFs show rounded figures)
Nothing here imports the underwriting engine.
"""
from __future__ import annotations

import copy


def pmt(principal, annual_rate, months):
    r = annual_rate / 12
    if months <= 0:
        return principal * r
    if r == 0:
        return principal / months
    return principal * r / (1 - (1 + r) ** -months)


def amortize_year(balance, annual_rate, payment, months=12, io=False):
    """Returns (interest paid, principal paid, ending balance) over `months`."""
    r = annual_rate / 12
    interest = principal = 0.0
    for _ in range(months):
        if balance <= 0.005:
            break
        i = balance * r
        p = 0.0 if io else min(payment - i, balance)
        interest += i
        principal += p
        balance -= p
    return interest, principal, balance


def build_small_business(spec: dict) -> dict:
    s = copy.deepcopy(spec)
    fin = s["fin"]
    years = s["years"]
    n = len(years)
    out = {"years": years, "is": {}, "bs": {}, "debts": [], "cf": {}}
    # --- term debts: balances at start of first year ---
    debts = []
    for d in fin.get("debts", []):
        pay = d.get("monthly_payment") or pmt(d["balance0"], d["rate"], d["remaining_months"])
        debts.append({**d, "monthly_payment": pay, "bal": d["balance0"], "hist": {}})
    rev = fin["revenue0"]
    prev_equity = fin["equity0"]
    accum = fin["accum_dep0"]
    fa_gross = fin["fa_gross0"]
    loc_rate = fin.get("loc_rate", 0.08)
    for t, y in enumerate(years):
        if t > 0:
            rev *= 1 + fin["growth"][t]
        cogs = rev * fin["cogs_pct"][t]
        dep = fin["dep"][t]
        opex = fin["opex_fixed"] * (1.03 ** t) + rev * fin.get("opex_var", 0.0) + dep  # opex includes depreciation
        other_inc = fin.get("other_income", [0] * n)[t]
        nonrec = fin.get("nonrecurring", {}).get(str(y), 0.0)
        # interest
        int_term = 0.0
        for d in debts:
            i, p, b = amortize_year(d["bal"], d["rate"], d["monthly_payment"], 12, d.get("io", False))
            d["hist"][y] = {"interest": i, "principal": p, "begin": d["bal"], "end": b}
            d["bal"] = b
            int_term += i
        loc_bal = fin.get("loc", [0] * n)[t]
        loc_int = loc_bal * loc_rate
        interest = int_term + loc_int
        pretax = rev - cogs - opex + other_inc + nonrec - interest
        tax = max(0.0, pretax * fin.get("tax_rate", 0.0))
        ni = pretax - tax
        dist = fin.get("distributions", [0] * n)[t]
        out["is"][y] = {"revenue": rev, "cogs": cogs, "gross_profit": rev - cogs, "opex": opex, "depreciation": dep,
                        "operating_income": rev - cogs - opex, "other_income": other_inc, "nonrecurring": nonrec,
                        "interest": interest, "interest_term": int_term, "interest_loc": loc_int, "pretax": pretax,
                        "tax": tax, "net_income": ni, "officer_comp": fin.get("officer_comp", [0] * n)[t],
                        "distributions": dist}
        # balance sheet
        capex = fin.get("capex", [0] * n)[t]
        fa_gross += capex
        accum += dep
        ar = rev * fin["ar_days"] / 360
        inv = cogs * fin.get("inv_days", 0) / 360
        ap = cogs * fin.get("ap_days", 0) / 360 if cogs else (opex - dep) * fin.get("ap_days", 0) / 360
        accrued = (opex - dep) * fin.get("accrued_pct", 0.04)
        prepaid = fin.get("prepaid", 0.0)
        other_rec = fin.get("related_receivable", 0.0)
        other_assets = fin.get("other_assets", 0.0)
        equity = prev_equity + ni - dist + fin.get("contributions", [0] * n)[t]
        cpltd = ltd = 0.0
        bal_by, cur_by = {}, {}
        for d in debts:
            # principal due next 12 months
            _, pnext, _ = amortize_year(d["bal"], d["rate"], d["monthly_payment"], 12, d.get("io", False))
            cpltd += pnext
            ltd += d["bal"] - pnext
            bal_by[d["creditor"]] = d["bal"]
            cur_by[d["creditor"]] = pnext
        liab_eq = ap + accrued + loc_bal + cpltd + ltd + equity
        net_fa = fa_gross - accum
        cash = liab_eq - (ar + inv + prepaid + other_rec + net_fa + other_assets)
        min_cash = fin.get("min_cash", 25_000)
        if cash < min_cash:
            add = min_cash - cash
            loc_bal += add
            fin.setdefault("loc", [0] * n)[t] = loc_bal
            cash = min_cash
        out["bs"][y] = {"cash": cash, "ar": ar, "inventory": inv, "prepaid": prepaid, "related_receivable": other_rec,
                        "fa_gross": fa_gross, "accum_dep": accum, "net_fa": net_fa, "other_assets": other_assets,
                        "total_assets": cash + ar + inv + prepaid + other_rec + net_fa + other_assets,
                        "ap": ap, "accrued": accrued, "loc": loc_bal, "cpltd": cpltd, "ltd": ltd,
                        "total_liabilities": ap + accrued + loc_bal + cpltd + ltd, "equity": equity,
                        "debt_balances": bal_by, "debt_current": cur_by}
        prev_equity = equity
    out["debts"] = [{k: v for k, v in d.items() if k != "bal"} for d in debts]
    out["fa_classes"] = fin.get("fa_classes", {"Equipment": 1.0})
    # interim period (YTD income statement + balance sheet)
    if s.get("interim"):
        it = s["interim"]
        m = it["months"]
        ann = out["is"][years[-1]]["revenue"] * (1 + it["growth"])
        r = ann * m / 12
        cogs = r * it["cogs_pct"]
        dep = fin["dep"][-1] * m / 12
        opex = (fin["opex_fixed"] * (1.03 ** n) + ann * fin.get("opex_var", 0.0)) * m / 12 + dep
        int_term = 0.0
        for d in debts:
            i, p, b = amortize_year(d["bal"], d["rate"], d["monthly_payment"], m, d.get("io", False))
            d["hist"][f"YTD{it['year']}"] = {"interest": i, "principal": p, "begin": d["bal"], "end": b}
            d["bal"] = b
            int_term += i
        loc_bal = fin["loc"][-1]
        interest = int_term + loc_bal * loc_rate * m / 12
        pre = r - cogs - opex - interest
        tax = max(0.0, pre * fin.get("tax_rate", 0.0))
        ni = pre - tax
        out["interim"] = {"id": f"YTD{it['year']}-{m:02d}", "year": it["year"], "months": m,
                          "is": {"revenue": r, "cogs": cogs, "gross_profit": r - cogs, "opex": opex, "depreciation": dep,
                                 "operating_income": r - cogs - opex, "other_income": 0.0, "nonrecurring": 0.0, "interest": interest,
                                 "interest_loc": loc_bal * loc_rate * m / 12, "pretax": pre, "tax": tax, "net_income": ni,
                                 "officer_comp": 0.0, "distributions": 0.0}}
        last = out["bs"][years[-1]]
        accum += dep
        ar, inv = ann * fin["ar_days"] / 360, ann * it["cogs_pct"] * fin.get("inv_days", 0) / 360
        ap = ann * it["cogs_pct"] * fin.get("ap_days", 0) / 360
        accrued = last["accrued"]
        equity = prev_equity + ni
        cpltd = ltd = 0.0
        bal_by, cur_by = {}, {}
        for d in debts:
            _, pnext, _ = amortize_year(d["bal"], d["rate"], d["monthly_payment"], 12, d.get("io", False))
            cpltd += pnext
            ltd += d["bal"] - pnext
            bal_by[d["creditor"]] = d["bal"]
            cur_by[d["creditor"]] = pnext
        net_fa = fa_gross - accum
        cash = ap + accrued + loc_bal + cpltd + ltd + equity - (ar + inv + last["prepaid"] + last["related_receivable"] + net_fa + last["other_assets"])
        out["interim"]["bs"] = {"cash": cash, "ar": ar, "inventory": inv, "prepaid": last["prepaid"], "related_receivable": last["related_receivable"],
                                "fa_gross": fa_gross, "accum_dep": accum, "net_fa": net_fa, "other_assets": last["other_assets"],
                                "total_assets": cash + ar + inv + last["prepaid"] + last["related_receivable"] + net_fa + last["other_assets"],
                                "ap": ap, "accrued": accrued, "loc": loc_bal, "cpltd": cpltd, "ltd": ltd,
                                "total_liabilities": ap + accrued + loc_bal + cpltd + ltd, "equity": equity, "debt_balances": bal_by, "debt_current": cur_by}
    # company forecast (projection periods, income statement only)
    if s.get("forecast"):
        f = s["forecast"]
        last = out["is"][years[-1]]
        r = last["revenue"]
        out["forecast"] = {}
        for k, y in enumerate(f["years"]):
            months = 6 if str(y).startswith("H2") else 12
            r = r * (1 + f["growth"][k]) if months == 12 else last["revenue"] * (1 + f["growth"][k])
            cogs = r * f["cogs_pct"][k]
            dep = f["dep"][k]
            opex = (fin["opex_fixed"] * (1.03 ** (n + k)) + r * fin.get("opex_var", 0.0)) * months / 12 + dep
            if months == 6:
                r, cogs = r / 2, cogs / 2
            interest = f["interest"][k]
            pre = r - cogs - opex + f.get("other_income", [0] * 9)[k] - interest
            tax = max(0.0, pre * fin.get("tax_rate", 0.0))
            out["forecast"][y] = {"revenue": r, "cogs": cogs, "gross_profit": r - cogs, "opex": opex, "depreciation": dep,
                                  "operating_income": r - cogs - opex, "other_income": f.get("other_income", [0] * 9)[k],
                                  "nonrecurring": 0.0, "interest": interest, "pretax": pre, "tax": tax, "net_income": pre - tax,
                                  "officer_comp": 0.0, "distributions": 0.0, "months": months}
    return out


def build_cre(spec: dict) -> dict:
    c = spec["cre"]
    yrs = c["years"]
    n = len(yrs)
    by_use = {}
    for u in c["units"]:
        by_use.setdefault(u["use"], 0.0)
        by_use[u["use"]] += u["annual_rent"]
    lines = {}
    gmap = {"retail": "gross_retail_rent", "office": "gross_office_rent", "residential": "gross_residential_rent", "other": "other_gross_rent"}
    vmap = {"retail": "retail_vacancy", "office": "office_vacancy", "residential": "residential_vacancy", "other": "other_vacancy"}
    g = c["rent_growth"]
    for use, base in by_use.items():
        lines[gmap[use]] = [base * (1 + g) ** t for t in range(n)]
        v = c["vacancy"].get(use, 0.0)
        lines[vmap[use]] = [0.0 if (t == 0 and c.get("year1_general_vacancy")) else -lines[gmap[use]][t] * v for t in range(n)]
    if c.get("cam"):
        lines["cam_reimbursement"] = [c["cam"] * (1 + g) ** t for t in range(n)]
    if c.get("year1_general_vacancy"):
        gross1 = sum(lines[gmap[u]][0] for u in by_use)
        lines["general_vacancy"] = [-gross1 * c["year1_general_vacancy"]] + [0.0] * (n - 1)
    eg = c.get("expense_growth", 0.03)
    gross_rev = [sum(lines[k][t] for k in lines) for t in range(n)]
    if c.get("mgmt_fee_pct"):
        lines["management_fee"] = [gross_rev[0] * c["mgmt_fee_pct"] * (1 + eg) ** t for t in range(n)]
    for k, base in c["expenses"].items():
        lines[k] = [base * (1 + eg) ** t for t in range(n)]
    if c.get("leasing_marketing"):
        lines["leasing_marketing"] = [c["leasing_marketing"] * (1 + eg) ** t for t in range(n)]  # borrower keeps it every year
    lines["re_taxes"] = [c["re_taxes_borrower"] * (1 + eg) ** t for t in range(n)]
    lines.setdefault("replacement_reserves", [c.get("replacement_reserves", 0.0) * (1 + eg) ** t for t in range(n)])
    rev_keys = [k for k in lines if k.startswith("gross_") or k.endswith("_vacancy") or k in ("cam_reimbursement", "general_vacancy", "other_gross_rent")]
    exp_keys = [k for k in lines if k not in rev_keys]
    total_rev = [sum(lines[k][t] for k in rev_keys) for t in range(n)]
    total_exp = [sum(lines[k][t] for k in exp_keys) for t in range(n)]
    return {"years": yrs, "lines": lines, "rev_keys": rev_keys, "exp_keys": exp_keys, "total_revenue": total_rev,
            "total_expenses": total_exp, "noi": [r - e for r, e in zip(total_rev, total_exp)], "by_use": by_use}
