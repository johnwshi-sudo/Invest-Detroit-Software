"""Small Business / C&I Investment Summary, modeled on the Kirk's Automotive sample."""
from __future__ import annotations

from datetime import date

from ..engine.common import fmt_m, fmt_money, fmt_pct, fmt_x, safe_div
from .blocks import bullets, n, p, pc, placeholder, row, section, subhead, table, x
from .common_sections import (benchmarking_section, compliance_section, documents_section, flags_section, header,
                              qual, term_sheet_section)


def _plabel(s, pid) -> str:
    return s.period(pid).label


def _narr_label(s, pid) -> str:
    per = s.period(pid)
    if per.months == 12:
        return per.label if per.label.upper().startswith("FYE") else f"FYE {per.label}"
    return f"the {per.months} months ending {per.end_date[5:7]}/{per.end_date[8:10]}/{per.end_date[2:4]}"


def _col_header(s, pid) -> str:
    lab = _plabel(s, pid)
    for pre in ("FYE ", "3 Mos. Ending ", "Forecasted 3 Mos. Ending ", "Historical 3 Mos. Ending "):
        if lab.startswith(pre):
            return pre.strip() + "\n" + lab[len(pre):]
    return lab


def operating_table(r: dict, pids: list[str], title: str, extra_col=None) -> dict:
    s = r["spread"]
    inc, ds = r["income"], r["debt_service"]
    cols = [""]
    for pid in pids:
        cols += [_col_header(s, pid), "% Sales"]
    getters = []
    if extra_col:
        cols += [extra_col["label"], "% Sales"]

    def vals(key, pct=True, style=""):
        cells = []
        for pid in pids:
            v = inc[pid][key]
            cells += [n(v), pc(safe_div(v, inc[pid]["revenue"])) if pct else ""]
        if extra_col:
            v = extra_col["values"][key]
            cells += [n(v), pc(safe_div(v, extra_col["values"]["revenue"])) if pct else ""]
        return cells

    rows = [
        row(["Sales"] + vals("revenue")), row(["Cost of Goods Sold"] + vals("cogs")),
        row(["GROSS PROFIT"] + vals("gross_profit"), "total"),
        row(["Total Expenses"] + vals("operating_expenses")), row(["Operating Profit"] + vals("operating_profit"), "bold"),
        row(["Other Income"] + vals("other_income", False)), row(["Other Expenses"] + vals("other_expenses", False)),
    ]
    if any(inc[p]["income_taxes"] for p in pids) or (extra_col and extra_col["values"]["income_taxes"]):
        rows.append(row(["Income Taxes"] + vals("income_taxes", False)))
    rows += [row(["Net Income (Loss)"] + vals("net_income"), "total"), row([""] + [""] * (len(cols) - 1)),
             row(["Interest"] + vals("interest", False)), row(["Depreciation"] + vals("depreciation", False))]
    if any(inc[p]["income_taxes"] for p in pids):
        rows.append(row(["Income Taxes"] + vals("income_taxes", False)))
    if any(inc[p]["amortization"] for p in pids):
        rows.append(row(["Amortization"] + vals("amortization", False)))
    rows.append(row(["EBITDA"] + vals("ebitda"), "total"))
    rows.append(row(["Debt Service:"] + [""] * (len(cols) - 1), "bold"))
    labels = []
    for pid in pids:
        for l in ds[pid]["lines"]:
            if l["label"] not in labels:
                labels.append(l["label"])
    for lab in labels:
        cells = []
        for pid in pids:
            v = next((l["amount"] for l in ds[pid]["lines"] if l["label"] == lab), None)
            cells += [n(v, False), ""]
        if extra_col:
            v = next((l["amount"] for l in extra_col["values"]["debt_service_lines"] if l["label"] == lab), None)
            cells += [n(v, False), ""]
        rows.append(row(["  " + lab] + cells, "indent"))
    tds = []
    for pid in pids:
        tds += [n(ds[pid]["total"], False), ""]
    cf, dscr = [], []
    for pid in pids:
        cf += [n(inc[pid]["cfads"], False), ""]
        dscr += [x(inc[pid]["dscr"]), ""]
    if extra_col:
        v = extra_col["values"]
        tds += [n(v["debt_service"], False), ""]
        cf += [n(v["cfads"], False), ""]
        dscr += [x(v["dscr"]), ""]
    rows += [row(["Total Debt Service"] + tds, "total"), row([""] * len(cols)),
             row(["Cash Flow After Debt Service"] + cf, "bold"), row(["DSCR"] + dscr, "bold")]
    foot = None
    nr = [pid for pid in pids if inc[pid]["nonrecurring_income"]]
    if nr:
        foot = "; ".join(f"{_plabel(s, pid)} Other Income includes {fmt_money(inc[pid]['nonrecurring_income'])} of non-recurring income "
                         f"(DSCR excluding it: {fmt_x(inc[pid]['dscr_ex_nonrecurring'])})" for pid in nr) + \
               ". It is included in EBITDA because it was a real receipt of cash to the company."
    return table(title, cols, rows, footnote=foot)


def _range_pct(vals):
    lo, hi = min(vals), max(vals)
    return f"{lo * 100:.0f}%-{hi * 100:.0f}%" if round(lo * 100) != round(hi * 100) else f"{lo * 100:.0f}%"


def financial_narrative(deal, r: dict) -> list:
    s, inc = r["spread"], r["income"]
    hist = r["hist"]
    annual = [pid for pid in hist if inc[pid]["months"] == 12]
    out = []
    # revenue
    sents = []
    for i, g in enumerate(r["growth"]):
        a, b = g["from"], g["to"]
        dirn = "increased" if g["pct"] >= 0 else "decreased"
        lead = "Revenues" if i == 0 else "Sales then"
        sents.append(f"{lead} {dirn} {abs(g['pct']) * 100:.1f}%, from {fmt_m(inc[a]['revenue'])} in {_narr_label(s, a)} to "
                     f"{fmt_m(inc[b]['revenue'])} during {_narr_label(s, b)}.")
    if not r["growth"] and annual:
        sents.append(f"Revenues were {fmt_m(inc[annual[-1]]['revenue'])} in {_narr_label(s, annual[-1])}.")
    drivers = deal.terms.qualitative.get("revenue_drivers")
    if drivers:
        sents.append(drivers)
    an = r.get("annualized")
    if an:
        word = "rebounded" if an["pct"] and an["pct"] > 0 and r["growth"] and r["growth"][-1]["pct"] < 0 else ("increased" if an["pct"] >= 0 else "declined")
        sents.append(f"Revenue has {word}, as the {inc[an['period']]['months']}-month sales figure (as of {s.period(an['period']).end_date[5:7]}/"
                     f"{s.period(an['period']).end_date[8:10]}/{s.period(an['period']).end_date[2:4]}) was {fmt_m(inc[an['period']]['revenue'])}, or "
                     f"{fmt_m(an['revenue'])} annualized (a {abs(an['pct']) * 100:.1f}% {'increase' if an['pct'] >= 0 else 'decrease'}).")
    agg = r.get("aggregate")
    if agg:
        sents.append(f"The company projects sales of {fmt_m(agg['values']['revenue'])} for the {agg['label'].lower().replace('aggregate 12 mos. ending', 'twelve months ending')} "
                     f"({agg['values']['growth_vs_prior'] * 100:+.1f}% vs. {_narr_label(s, agg['prior'])}) — please see Exhibit C - Projected.")
    out.append(p(" ".join(sents)))
    # COGS
    cogs_p = [(pid, safe_div(inc[pid]["cogs"], inc[pid]["revenue"])) for pid in hist]
    vals = [v for _, v in cogs_p]
    if len(vals) >= 2:
        rounded = [round(v * 100) for v in vals]
        trend = "steadily increased" if all(b >= a for a, b in zip(rounded, rounded[1:])) and rounded[-1] > rounded[0] else \
                "steadily decreased" if all(b <= a for a, b in zip(rounded, rounded[1:])) and rounded[-1] < rounded[0] else "fluctuated"
        parts = [f"{v * 100:.0f}% of sales during {_narr_label(s, pid)}" for pid, v in cogs_p]
        txt = f"Cost of Goods Sold have {trend} during the periods reviewed (from " + ", ".join(parts[:-1]) + f" to {parts[-1]})."
        if deal.terms.qualitative.get("cogs_drivers"):
            txt += " " + deal.terms.qualitative["cogs_drivers"]
        out.append(p(txt))
    # margins
    nm = [safe_div(inc[pid]["net_income"], inc[pid]["revenue"]) for pid in hist]
    em = [safe_div(inc[pid]["ebitda"], inc[pid]["revenue"]) for pid in hist]
    if nm and None not in nm and None not in em:
        steady = (max(nm) - min(nm) < 0.02) and (max(em) - min(em) < 0.02)
        def rng(v):
            r = _range_pct(v)
            return f"between {r}" if "-" in r else f"approximately {r}"
        out.append(p(f"The margins for net income and EBITDA have {'remained relatively constant' if steady else 'varied'} "
                     f"(net income {rng(nm)} of sales, while EBITDA has maintained a margin of {rng(em)} of sales)."))
    # non-recurring
    for pid in hist:
        if inc[pid]["nonrecurring_income"]:
            txt = deal.terms.qualitative.get("nonrecurring_note") or (
                f"During {_narr_label(s, pid)} the company recognized {fmt_money(inc[pid]['nonrecurring_income'])} of non-recurring income. "
                "As it provided cash to the company, it is not removed from the cash flows when calculating EBITDA.")
            out.append(p(txt + f" Excluding it, DSCR for {_narr_label(s, pid)} would be {fmt_x(inc[pid]['dscr_ex_nonrecurring'])}.", "computed"))
    # DSCR
    ds_vals = [inc[pid]["dscr"] for pid in hist]
    from ..guidelines import load_guidelines
    mind = load_guidelines()["products"].get(deal.terms.product, {}).get("min_dscr") or 1.15
    if ds_vals and None not in ds_vals:
        if min(ds_vals) < 1.0:
            lead = "Cash flows were not sufficient to service the obligations of the Borrower in every period."
        elif min(ds_vals) < mind:
            lead = "Although tight, cash flows are sufficient to service the obligations of the Borrower."
        else:
            lead = "Cash flows are sufficient to service the obligations of the Borrower."
        labels = [_narr_label(s, pid).replace("FYE ", "") for pid in hist]
        txt = (f"{lead} DSCR was {_join([fmt_x(v) for v in ds_vals])} during FYE {_join(labels)}, respectively.") if len(hist) > 1 else \
              f"{lead} DSCR was {fmt_x(ds_vals[0])} during {_narr_label(s, hist[0])}."
        txt = txt.replace("FYE the ", "the ")
        sal = [inc[pid].get("officer_compensation") for pid in hist]
        if all(v for v in sal):
            txt += f" Shareholder salaries for the same periods were {_join([fmt_money(v) for v in sal])}, respectively."
        out.append(p(txt))
    return out


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def debt_schedule_table(r: dict) -> dict:
    s = r["spread"]
    dt = r["debt_schedule_date"]
    rows = [row([d["creditor"], n(d["balance"], False)]) for d in r["debt_schedule"]]
    rows.append(row(["Total", n(sum(d["balance"] for d in r["debt_schedule"]), False)], "total"))
    return table("Debt Schedule", ["Creditor", f"Balance at {s.period(dt).end_date[5:7]}/{s.period(dt).end_date[8:10]}/{s.period(dt).end_date[2:4]}"], rows, kind="grid")


def tnw_table(r: dict) -> dict:
    s = r["spread"]
    pids = r["bs_periods"]
    tn = r["tnw"]
    cols = ["Tangible Net Worth"] + [s.period(p).end_date[5:7] + "/" + s.period(p).end_date[8:10] + "/" + s.period(p).end_date[2:4] for p in pids]
    rows = [row(["Shareholders Equity"] + [n(tn[p]["shareholders_equity"], False) for p in pids]),
            row(["Invest Detroit Note"] + [n(tn[p]["id_note"], False) for p in pids])]
    names = [c for c, _ in tn[pids[-1]]["subordinated"]] if pids else []
    if names:
        rows.append(row(["Subordinated Shareholder Notes"] + [""] * len(pids), "bold"))
        for i, nm in enumerate(names):
            rows.append(row(["  " + nm] + [n(tn[p]["subordinated"][i][1] if i < len(tn[p]["subordinated"]) else None, False) for p in pids], "indent"))
    rows.append(row(["Excluded Assets"] + [""] * len(pids), "bold"))
    lab = {"other_receivables": "Loan Receivable - Other", "prepaid_expenses": "Prepaid Expense", "intangible_assets": "Intangible Assets"}
    for i, (k, _) in enumerate(tn[pids[-1]]["excluded"] if pids else []):
        rows.append(row(["  " + lab.get(k, k)] + [n(tn[p]["excluded"][i][1]) for p in pids], "indent"))
    rows.append(row(["Computed TNW"] + [n(tn[p]["computed_tnw"], False) for p in pids], "total"))
    return table("Capitalization and Leverage, Source: Company", cols, rows)


def cap_narrative(r: dict) -> dict:
    pids = r["bs_periods"]
    nw = [r["ratios"][p]["net_worth"] for p in pids]
    lev = [r["ratios"][p]["debt_to_worth"] for p in pids]
    tl = [r["balance_sheet"][p]["total_liabilities"] for p in pids]
    if len(pids) < 2:
        return p(f"Net worth was {fmt_money(nw[0])} with debt to worth of {fmt_x(lev[0])}.") if pids else None
    if all(b >= a for a, b in zip(nw, nw[1:])):
        s1 = "Net worth increased each year from the retention of earnings."
    elif nw[-1] > nw[0]:
        s1 = f"Net worth increased from {fmt_money(nw[0])} to {fmt_money(nw[-1])} over the period, though not every year."
    else:
        s1 = f"Net worth declined from {fmt_money(nw[0])} to {fmt_money(nw[-1])} over the period."
    chg = (max(tl) - min(tl)) / max(tl)
    s2 = f"Total liabilities have {'fluctuated slightly' if chg < 0.10 else 'changed materially'} over the periods reviewed and leverage (debt to worth) is " \
         f"{'improving' if lev[-1] < lev[0] else 'increasing'} ({fmt_x(lev[0])} to {fmt_x(lev[-1])})."
    return p(f"{s1} {s2} Please see Exhibit D - Historical Statements of Assets, Liabilities and Net Worth for further detail.")


def break_even_table(r: dict) -> dict:
    s = r["spread"]
    be = r["break_even"]
    pids = list(be)
    cols = ["Break Even"]
    for pid in pids:
        cols += [_col_header(s, pid) + f"\n{be[pid]['pct_of_sales'] * 100:.1f}% of Original Sales", "% Sales"]

    def vr(key, pct=True):
        out = []
        for pid in pids:
            v = be[pid][key]
            out += [n(v), pc(safe_div(v, be[pid]["revenue"])) if pct else ""]
        return out
    rows = [row(["Sales"] + vr("revenue")), row(["Cost of Goods Sold"] + vr("cogs")), row(["GROSS PROFIT"] + vr("gross_profit"), "total"),
            row(["Total Expenses"] + vr("operating_expenses")), row(["Operating Profit"] + vr("operating_profit"), "bold"),
            row(["Other Income"] + vr("other_income", False)), row(["Other Expenses"] + vr("other_expenses", False)),
            row(["Net Income (Loss)"] + vr("net_income"), "total"), row([""] * len(cols)),
            row(["Interest"] + vr("interest", False)), row(["Depreciation"] + vr("depreciation", False)),
            row(["EBITDA"] + vr("ebitda"), "total"),
            row(["Total Debt Service"] + sum([[n(be[p]["debt_service"]["total"], False), ""] for p in pids], []), "total"),
            row(["Cash Flow After Debt Service"] + sum([[n(be[p]["cfads"], False), ""] for p in pids], []), "bold"),
            row(["DSCR"] + sum([[x(be[p]["dscr"]), ""] for p in pids], []), "bold")]
    return table("Sensitivity/Break Even Analysis - Source: Company", cols, rows)


def break_even_narrative(r: dict) -> dict:
    be = r["break_even"]
    if not be:
        return None
    s = r["spread"]
    cush = [be[p]["cushion_pct"] for p in be]
    if min(cush) < 0:
        lead = "Historical operations have not generated enough cash flow to cover the proposed debt service in every year."
    elif max(cush) < 0.05:
        lead = "Our analysis indicates that historical operations have been at near break-even, allowing for only slight downward adjustments to gross sales."
    else:
        lead = "Our analysis indicates that historical operations can absorb a moderate decline in gross sales before debt service coverage falls to 1.00x."
    parts = []
    for pid in be:
        c = be[pid]["cushion_pct"]
        parts.append(f"sales could decline {c * 100:.1f}% in {_narr_label(s, pid)}" if c >= 0 else
                     f"sales would need to increase {-c * 100:.1f}% in {_narr_label(s, pid)}")
    detail = "For DSCR to reach 1.00x, " + _join(parts) + "."
    return p(f"{lead} {detail} Our model adjusts the cost of goods sold so that gross profit margins are consistent with historical levels. "
             "Operating expenses are treated as a fixed cost and are not adjusted to sales.")


def balance_exhibit(r: dict) -> dict:
    s = r["spread"]
    pids = r["bs_periods"]
    B = r["balance_sheet"]
    cols = ["Statement of Assets, Liabilities and Net Worth"] + [s.period(p).end_date[5:7] + "/" + s.period(p).end_date[8:10] + "/" + s.period(p).end_date[2:4] for p in pids]
    def line(label, f, style=""):
        return row([label] + [n(f(B[p]), False) for p in pids], style)
    ca_lab = [("cash", "Cash"), ("accounts_receivable", "Account Receivable"), ("inventory", "Inventory"),
              ("other_receivables", "Loans Receivable, Other"), ("prepaid_expenses", "Prepaid Expenses"), ("other_current_assets", "Other Current Assets")]
    rows = [row(["Current Assets"] + [""] * len(pids), "bold")]
    rows += [line(lab, lambda b, k=k: b["current_assets"][k]) for k, lab in ca_lab if any(B[p]["current_assets"][k] for p in pids)]
    rows.append(line("Total Current Assets", lambda b: b["total_current_assets"], "total"))
    rows.append(row(["Property and Equipment"] + [""] * len(pids), "bold"))
    fa_labels = []
    for pp in pids:
        for lab, _ in B[pp]["fixed_asset_items"]:
            if lab not in fa_labels:
                fa_labels.append(lab)
    for lab in fa_labels:
        rows.append(row([lab] + [n(next((v for l, v in B[pp]["fixed_asset_items"] if l == lab), None), False) for pp in pids]))
    rows.append(line("Less: Accumulated Depreciation", lambda b: b["accumulated_depreciation"]))
    rows.append(line("Net Property and Equipment", lambda b: b["net_fixed_assets"], "total"))
    rows.append(row(["Other Assets"] + [""] * len(pids), "bold"))
    for k, lab in [("deposits", "Deposits"), ("other_assets", "Other Assets"), ("intangible_assets", "Intangible Assets")]:
        if any(B[p]["other_assets"][k] for p in pids):
            labels = s.cells.get(pids[-1], {}).get(k)
            rows.append(line(labels.labels[0] if labels and labels.labels else lab, lambda b, k=k: b["other_assets"][k]))
    rows.append(line("Total Other Assets", lambda b: b["total_other_assets"], "total"))
    rows.append(line("Total Assets", lambda b: b["total_assets"], "total2"))
    rows.append(row(["Liabilities & Stockholders Equity"] + [""] * len(pids), "bold"))
    cl_lab = [("accounts_payable", "Accounts Payable - Trade"), ("accrued_expenses", "Accrued Expenses"), ("line_of_credit", "Line of Credit"),
              ("current_portion_ltd", "CPLTD"), ("other_current_liabilities", "Other Current Liabilities")]
    for k, lab in cl_lab:
        if any(B[p]["current_liabilities"].get(k) for p in pids):
            rows.append(line(lab, lambda b, k=k: b["current_liabilities"].get(k, 0)))
    rows.append(line("Total Current Liabilities", lambda b: b["total_current_liabilities"], "total"))
    rows.append(row(["Long Term Obligations"] + [""] * len(pids), "bold"))
    rows.append(line("Notes Payable (other term debt)", lambda b: b["other_term_debt"]))
    rows.append(line("Subordinated Shareholder Notes", lambda b: b["subordinated_notes"]))
    if not any(B[p]["id_note"] for p in pids) or not r.get("id_as_equity", True):
        rows.append(line("Invest Detroit Note", lambda b: b["id_note"]))
    rows.append(line("Total Long Term Obligations", lambda b: b["lt_obligations"], "total"))
    rows.append(row(["Stockholders' Equity"] + [""] * len(pids), "bold"))
    rows.append(line("Stated Equity", lambda b: b["equity_stated"]))
    if any(B[p]["id_note"] for p in pids) and r.get("id_as_equity", True):
        rows.append(line("Sub-Debt - Invest Detroit", lambda b: b["id_note"]))
    rows.append(line("Total Stockholder Equity", lambda b: b["net_worth"], "total"))
    rows.append(line("Liabilities & Net Worth", lambda b: b["total_liabilities"] + b["net_worth"], "total2"))
    foot = None
    if r.get("id_as_equity", True) and any(B[p]["id_note"] for p in pids):
        foot = "Invest Detroit's subordinated note is presented as quasi-equity (Sub-Debt) consistent with Invest Detroit's exhibits."
    return table("Exhibit D - Historical Statements of Assets, Liabilities and Net Worth", cols, rows, footnote=foot)


def ratio_exhibit(r: dict) -> dict:
    s = r["spread"]
    pids = r["bs_periods"]
    R = r["ratios"]
    cols = ["Ratios"] + [s.period(p).end_date[5:7] + "/" + s.period(p).end_date[8:10] + "/" + s.period(p).end_date[2:4] for p in pids]
    def ln(label, key, f):
        return row([label] + [f(R[p][key]) for p in pids])
    x3 = lambda v: "n/a" if v is None else f"{v:.3f}x"
    d3 = lambda v: "n/a" if v is None else f"{v:.3f}"
    p3 = lambda v: "n/a" if v is None else f"{v * 100:.3f}%"
    m = lambda v: n(v, False)
    rows = [row(["LIQUIDITY"] + [""] * len(pids), "bold"), ln("Working Capital", "working_capital", m), ln("Quick Ratio", "quick_ratio", x3),
            ln("Current Ratio", "current_ratio", x3), ln("Net Sales/Working Capital", "sales_to_working_capital", x3),
            row(["LEVERAGE"] + [""] * len(pids), "bold"), ln("Net Worth-Actual", "net_worth", m), ln("Tang Net Worth-Actual", "tangible_net_worth", m),
            ln("Debt/Worth", "debt_to_worth", x3), ln("Debt/Tang Worth", "debt_to_tangible_worth", x3),
            ln("LT Debt/Net Fixed Assets", "lt_debt_to_net_fixed_assets", x3), ln("Total Liabilities/Total Assets", "liabilities_to_assets", x3),
            row(["COVERAGE"] + [""] * len(pids), "bold"), ln("Interest Coverage (EBITDA/Interest)", "interest_coverage", x3),
            ln("EBITDA (-/+) Distributions/Contributions", "ebitda_less_distributions", m),
            ln("EBITDA", "ebitda", m), ln("EBIDA", "ebida", m), ln("Debt Coverage Ratio", "dscr", x3),
            row(["PROFITABILITY (%)"] + [""] * len(pids), "bold"), ln("Return on Assets", "return_on_assets", p3),
            ln("Return on Equity", "return_on_equity", p3), ln("Gross Margin", "gross_margin", p3),
            ln("EBIT (Net Income + Interest)", "ebit", m), ln("Net Margin", "net_margin", p3),
            row(["ACTIVITY"] + [""] * len(pids), "bold"), ln("Gross Accounts Receivable Days", "ar_days", d3),
            ln("Accounts Receivable Turnover", "ar_turnover", x3), ln("Inventory Days on Hand", "inventory_days", d3),
            ln("Inventory Turnover", "inventory_turnover", x3), ln("Accounts Payable Days", "ap_days", d3),
            ln("Net Sales/Total Assets", "sales_to_assets", x3), ln("Net Sales/Net Worth", "sales_to_net_worth", x3),
            ln("Cash to Net Sales", "cash_to_sales", p3)]
    interim = [p for p in pids if s.period(p).months < 12]
    foot = "Days ratios use a 360-day year; inventory days and turnover are on sales (Invest Detroit template)."
    if interim:
        foot += " Interim-period ratios are not annualized."
    return table("Exhibit E - Ratios", cols, rows, footnote=foot)


def strengths_weaknesses(deal, r, policy, bench) -> tuple[list, list]:
    s, inc = r["spread"], r["income"]
    hist = r["hist"]
    annual = [pid for pid in hist if inc[pid]["months"] == 12]
    W, S = [], []
    if len(annual) >= 2 and inc[annual[-1]]["revenue"] < inc[annual[-2]]["revenue"]:
        txt = f"Revenue and profitability decreased during {_narr_label(s, annual[-1])}"
        an, agg = r.get("annualized"), r.get("aggregate")
        mit = []
        if an and an["pct"] > 0:
            mit.append(f"a strong rebound in sales during {_narr_label(s, an['period'])}")
        if agg:
            mit.append(f"the company expects revenues of {fmt_m(agg['values']['revenue'])} for the {agg['label'].lower().replace('aggregate 12 mos. ending', 'twelve months ending')}")
        W.append(txt + ("; however, this is mitigated by " + " and ".join(mit) + "." if mit else "."))
    mind = next((e for e in policy["exceptions"] if e["item"].startswith("Min DSCR")), None)
    if mind:
        W.append(f"Debt service coverage of {mind['actual']} is below the {mind['requirement'].replace('>= ', '')} guideline minimum; cash flow is thin.")
    for pid in hist:
        if inc[pid]["nonrecurring_income"] and inc[pid]["dscr_ex_nonrecurring"] is not None and inc[pid]["dscr_ex_nonrecurring"] < 1:
            W.append(f"{_narr_label(s, pid)} coverage relied on {fmt_money(inc[pid]['nonrecurring_income'])} of non-recurring income "
                     f"(DSCR {fmt_x(inc[pid]['dscr_ex_nonrecurring'])} without it).")
    for m in bench.get("metrics", []):
        if m["verdict"] == "unfavorable" and m["metric"].startswith(("Net margin", "Inventory days")):
            from ..naics.benchmarks import _f
            W.append(f"{m['metric']} of {_f(m['borrower'], m['fmt'])} compares unfavorably with the industry aggregate of {_f(m['industry'], m['fmt'])}.")
    for c in deal.terms.collateral:
        if c.valuation_date and c.valuation_date[:4].isdigit():
            ref = int((deal.terms.ic_date or str(date.today()))[:4])
            if ref - int(c.valuation_date[:4]) >= 3:
                W.append(f"Collateral valuation for {c.description.split(' - ')[0].split('(')[0].strip().lower()} is dated {c.valuation_date[:4]}; an updated valuation would strengthen the collateral analysis.")
    for doc, info in s.statement_info.items():
        if info.get("assurance") == "no_assurance":
            W.append("The most recent financial statements were prepared by the CPA without audit, review or compilation assurance.")
            break
    yr = deal.profile.year_established
    if yr:
        S.append(f"Company has been in business since {yr}.")
    if deal.terms.qualitative.get("strengths_extra"):
        S.append(deal.terms.qualitative["strengths_extra"])
    ds = [inc[p]["dscr"] for p in annual if inc[p]["dscr"] is not None]
    if ds and min(ds) >= 1.0:
        txt = "Historical financial performance demonstrates the company's ability to service its obligations."
        if deal.terms.is_renewal:
            txt += " The loan with Invest Detroit has historically been paid as agreed." if "as agreed" in (deal.terms.qualitative.get("loan_history", "")) else ""
        S.append(txt)
    if len(r["bs_periods"]) >= 2:
        lev = [r["ratios"][p]["debt_to_worth"] for p in r["bs_periods"]]
        if lev[-1] < lev[0]:
            S.append(f"Leverage has improved (debt to worth from {fmt_x(lev[0])} to {fmt_x(lev[-1])}).")
    coll = r["collateral"]
    if coll.get("ltv_gross") and coll["ltv_gross"] <= 0.75:
        S.append(f"Collateral coverage: loan to value of approximately {coll['ltv_gross'] * 100:.0f}%.")
    if len(deal.profile.customers) >= 5:
        S.append(f"Diversified, established customer base ({len(deal.profile.customers)} named customers including {', '.join(deal.profile.customers[:3])}).")
    for m in bench.get("metrics", []):
        if m["verdict"] == "favorable" and m["metric"] in ("Debt / worth", "Current ratio"):
            from ..naics.benchmarks import _f
            S.append(f"{m['metric']} of {_f(m['borrower'], m['fmt'])} is better than the industry aggregate ({_f(m['industry'], m['fmt'])}).")
    return W, S


def build_small_business_memo(deal, r, policy, naics, bench) -> dict:
    s, inc = r["spread"], r["income"]
    hist = r["hist"]
    secs = []
    secs.append({"key": "header", "title": "", "blocks": [header(deal, policy)]})
    secs.append(section("mission", "Mission Alignment", [qual(deal, "mission_alignment", "mission alignment (jobs, Detroit residents)",
                         _mission_default(deal))]))
    secs.append(section("overview", "Deal Overview", [p(deal.profile.description, "extracted") if deal.profile.description else placeholder("business description"),
                         p(f"NAICS {naics['code']}: {naics['title']}.", "computed") if naics.get("code") else None]))
    cust = deal.terms.qualitative.get("customer_base")
    blocks = [p(cust, "input")] if cust else []
    if deal.profile.customers:
        blocks.append(p("Named customers include: " + ", ".join(deal.profile.customers) + ".", "extracted"))
    secs.append(section("customers", "Customer Base", blocks or [placeholder("customer base / concentration")]))
    if deal.terms.is_renewal or deal.terms.qualitative.get("loan_history"):
        secs.append(section("loan_history", "Loan History", [qual(deal, "loan_history", "loan history with Invest Detroit")]))
    secs.append(section("request", "Request", [qual(deal, "request_detail", "request detail (purpose, structure, fees, guarantees)", deal.terms.request_summary),
                         p(deal.terms.qualitative["warrant"], "input") if deal.terms.qualitative.get("warrant") else None]))
    secs.append(section("banking", "Banking Relationship", [qual(deal, "banking_relationship", "senior lender / banking relationship",
                         ("Other lenders: " + "; ".join(deal.profile.other_lenders)) if deal.profile.other_lenders else None)]))
    mgmt = [p(f"{pp.name} — {pp.role}. {pp.bio or ''}".strip(), "extracted") for pp in deal.profile.people if pp.role or pp.bio]
    secs.append(section("management", "Management", mgmt or [placeholder("management bios")]))
    # financial review
    fr = [operating_table(r, hist, "Operating Highlights - Income Statement")] + financial_narrative(deal, r)
    if r["debt_schedule"]:
        fr.append(debt_schedule_table(r))
    if r["bs_periods"]:
        fr += [tnw_table(r), cap_narrative(r)]
    if r["break_even"]:
        fr += [break_even_table(r), break_even_narrative(r)]
    secs.append(section("financial_review", "Financial Review, Source: Company", fr))
    secs.append(benchmarking_section(naics, bench, "small_business"))
    # collateral
    coll = r["collateral"]
    cb = [qual(deal, "collateral_notes", "collateral description")]
    if coll["items"]:
        parts = [f"{c['description']}: {fmt_money(c['gross_value'])} ({c.get('valuation_source') or 'source n/a'})" for c in coll["items"]]
        cb.append(p("Collateral values: " + "; ".join(parts) + f". Loan to value is approximately {coll['ltv_gross'] * 100:.0f}% "
                    f"({fmt_money(coll['loan'])} / {fmt_money(coll['gross_value'])})."
                    + (f" Including prior liens of {fmt_money(coll['prior_liens'])}, combined LTV is {fmt_pct(coll['cltv_gross'])}." if coll["prior_liens"] else "")))
    secs.append(section("collateral", "Collateral Analysis", cb))
    g = [qual(deal, "guarantors", "guarantors and personal financial statements")]
    for pp in deal.profile.people:
        if pp.guarantor and pp.credit_report:
            g.append(p(f"{pp.name}: {pp.credit_report}", "input"))
        elif pp.guarantor:
            g.append(placeholder(f"credit report summary for {pp.name}"))
    secs.append(section("guarantors", "Guarantors", g))
    W, S = strengths_weaknesses(deal, r, policy, bench)
    secs.append(section("weaknesses", "Weaknesses", [bullets(W)] if W else [p("None identified.")]))
    secs.append(section("strengths", "Strengths", [bullets(S)] if S else [placeholder("strengths")]))
    secs.append(compliance_section(policy))
    secs.append(term_sheet_section(deal, r, policy))
    # exhibits
    if r.get("aggregate"):
        agg = r["aggregate"]
        secs.append(section("exhibit_c", "Exhibit C - Projected", [operating_table(r, agg["period_ids"], agg["label"], {"label": agg["label"].replace("Aggregate ", "Aggregate\n"), "values": agg["values"]})]))
    if r["bs_periods"]:
        secs.append(section("exhibit_d", "Exhibit D - Historical Statements of Assets, Liabilities and Net Worth", [balance_exhibit(r)]))
        secs.append(section("exhibit_e", "Exhibit E - Ratios", [ratio_exhibit(r)]))
    secs.append(documents_section(policy))
    return {"title": "Investment Summary", "deal_type": "small_business", "sections": secs}


def _mission_default(deal):
    pr = deal.profile
    bits = []
    if pr.employees:
        bits.append(f"employs approximately {pr.employees} people")
    if pr.jobs_created:
        bits.append(f"expects to create {pr.jobs_created} jobs")
    if pr.detroit_residents_employed:
        bits.append(f"employs {pr.detroit_residents_employed} Detroit residents")
    return f"{pr.legal_name or 'The borrower'} is a Detroit based business that " + _join(bits) + "." if bits else None
