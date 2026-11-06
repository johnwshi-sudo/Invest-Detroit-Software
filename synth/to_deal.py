"""Ground truth -> (presented documents, perfect-extraction Deal JSON).

`presented` holds what the PDFs show (rounded, footing like CPA statements). The oracle computes expected values
from `presented`, because an underwriter can only use what the documents show. The Deal JSON is what a correct
extractor would return, including the presentation quirks (interest inside opex, depreciation only in the cash
flow statement, $000s converted to dollars, restated comparative years, tax-return-only borrowers).
"""
from __future__ import annotations

import copy
from datetime import date

from .model import build_cre, build_small_business
from .scenarios import IC


def _r(v, unit=1):
    return round(v / unit) * unit


def _period(y, months=12, kind="actual", pid=None, label=None, end=None):
    if pid is None:
        pid = f"FY{y}"
    end = end or f"{y}-12-31"
    label = label or f"FYE 12/31/{str(y)[2:]}"
    return {"id": pid, "label": label, "end_date": end, "months": months, "kind": kind}


def present_sb(spec: dict, truth: dict) -> dict:
    """Rounded, footing statements per period (dollars)."""
    q = spec["quirks"]
    unit = q.get("units", 1)
    pres = {"periods": [], "is": {}, "bs": {}, "unit": unit}
    def is_block(t):
        R = lambda k: _r(t[k], unit)
        rev, cogs = R("revenue"), R("cogs")
        dep = R("depreciation")
        interest = R("interest")
        opex = R("opex")
        if q.get("interest_location") == "opex":
            opex_shown = opex + interest
        else:
            opex_shown = opex
        other = R("other_income")
        nonrec = R("nonrecurring")
        tax = R("tax")
        gp = rev - cogs
        op = gp - opex_shown
        pre = op + other + nonrec - (0 if q.get("interest_location") == "opex" else interest)
        ni = pre - tax
        return {"revenue": rev, "cogs": cogs, "gross_profit": gp, "opex_shown": opex_shown, "operating_income": op,
                "other_income": other, "nonrecurring": nonrec, "interest": interest, "interest_in_opex": q.get("interest_location") == "opex",
                "depreciation": dep, "pretax": pre, "tax": tax, "net_income": ni, "officer_comp": R("officer_comp"),
                "distributions": R("distributions")}

    def bs_block(b, ni, classes):
        R = lambda v: _r(v, unit)
        fa_items = {}
        rem = R(b["fa_gross"])
        keys = list(classes)
        for i, k in enumerate(keys):
            v = rem if i == len(keys) - 1 else R(b["fa_gross"] * classes[k])
            fa_items[k] = v
            rem -= v if i < len(keys) - 1 else 0
        acc = -R(b["accum_dep"])
        ca = {"cash": R(b["cash"]), "ar": R(b["ar"]), "inventory": R(b["inventory"]), "prepaid": R(b["prepaid"]),
              "related_receivable": R(b["related_receivable"])}
        tca = sum(ca.values())
        nfa = sum(fa_items.values()) + acc
        oa = R(b["other_assets"])
        ta = tca + nfa + oa
        ap, accr, loc, cpltd, ltd = R(b["ap"]), R(b["accrued"]), R(b["loc"]), R(b["cpltd"]), R(b["ltd"])
        tcl = ap + accr + loc + cpltd
        tl = tcl + ltd
        equity = ta - tl                      # equity is the balancing figure after rounding
        stock = R(min(10_000, abs(equity) / 10 + 1000))
        ni_r = R(ni)
        return {**ca, "tca": tca, "fa_items": fa_items, "accum": acc, "nfa": nfa, "other_assets": oa, "ta": ta,
                "ap": ap, "accrued": accr, "loc": loc, "cpltd": cpltd, "ltd": ltd, "tcl": tcl, "tl": tl,
                "common_stock": stock, "current_year_income": ni_r, "retained_earnings": equity - stock - ni_r, "equity": equity,
                "debt_balances": {k: R(v) for k, v in b["debt_balances"].items()},
                "debt_current": {k: R(v) for k, v in b.get("debt_current", {}).items()}}

    for y in spec["years"]:
        pres["periods"].append(_period(y))
        pres["is"][f"FY{y}"] = is_block(truth["is"][y])
        pres["bs"][f"FY{y}"] = bs_block(truth["bs"][y], truth["is"][y]["net_income"], truth["fa_classes"])
    if truth.get("interim"):
        it = truth["interim"]
        pid = it["id"]
        mm = it["months"]
        pres["periods"].append(_period(it["year"], mm, "interim", pid, f"{mm} Mos. Ending {mm:02d}/30/{str(it['year'])[2:]}",
                                       f"{it['year']}-{mm:02d}-30"))
        pres["is"][pid] = is_block(it["is"])
        pres["bs"][pid] = bs_block(it["bs"], it["is"]["net_income"], truth["fa_classes"])
    for y, t in (truth.get("forecast") or {}).items():
        if str(y).startswith("H2"):
            yr = int(str(y)[3:])
            pid = f"H2-{yr}P"
            pres["periods"].append(_period(yr, 6, "projection", pid, f"Forecasted 6 Mos. Ending 12/31/{str(yr)[2:]}"))
        else:
            pid = f"FY{y}P"
            pres["periods"].append(_period(y, 12, "projection", pid, f"Projected FYE 12/31/{str(y)[2:]}"))
        pres["is"][pid] = is_block(t)
    return pres


def sb_line_items(pid, I, B, doc, pages, restate=None):
    L = []
    def li(key, label, val, page, conf=0.97):
        L.append({"key": key, "label": label, "period_id": pid, "value": float(val), "page": page, "doc": doc, "confidence": conf})
    if I:
        f = 1.0 if restate is None else restate
        rev = round(I["revenue"] * f)
        delta = rev - I["revenue"]
        li("revenue", "Sales", rev, pages["is"])
        if I["cogs"]:
            li("cogs", "Cost of sales", I["cogs"], pages["is"])
        li("gross_profit", "Gross profit", I["gross_profit"] + delta, pages["is"])
        li("operating_expenses", "Total operating expenses" + (" (including interest)" if I["interest_in_opex"] else ""), I["opex_shown"], pages["is"])
        li("operating_income", "Operating income (loss)", I["operating_income"] + delta, pages["is"])
        if I["other_income"]:
            li("other_income", "Other income", I["other_income"], pages["is"])
        if I["nonrecurring"]:
            li("nonrecurring_income", I.get("nonrec_label", "Non-recurring income"), I["nonrecurring"], pages["is"])
        if I["interest_in_opex"]:
            li("interest_included_above", "Interest expense (included in operating expenses)", I["interest"], pages["opex"])
        elif I["interest"]:
            li("interest_expense", "Interest expense", I["interest"], pages["is"])
        if I["tax"]:
            li("income_taxes", "Income taxes", I["tax"], pages["is"])
        li("pretax_income", "Income before taxes", I["pretax"] + delta, pages["is"])
        li("net_income", "Net income (loss)", I["net_income"] + delta, pages["is"])
        li("depreciation", "Depreciation", I["depreciation"], pages["dep"])
        if I["officer_comp"]:
            li("officer_compensation", "Officer compensation", I["officer_comp"], pages["opex"], 0.9)
        if I["distributions"]:
            li("distributions", "Distributions to shareholders", I["distributions"], pages["cf"])
    if B:
        p = pages["bs"]
        li("cash", "Cash", B["cash"], p)
        li("accounts_receivable", "Accounts receivable", B["ar"], p)
        if B["inventory"]:
            li("inventory", "Inventory", B["inventory"], p)
        if B["prepaid"]:
            li("prepaid_expenses", "Prepaid expenses", B["prepaid"], p)
        if B["related_receivable"]:
            li("other_receivables", "Due from shareholder", B["related_receivable"], p)
        li("total_current_assets", "Total current assets", B["tca"], p)
        for k, v in B["fa_items"].items():
            li("fixed_assets_gross", k, v, p)
        li("accumulated_depreciation", "Less accumulated depreciation", B["accum"], p)
        li("net_fixed_assets", "Net property and equipment", B["nfa"], p)
        if B["other_assets"]:
            li("other_assets", "Other assets", B["other_assets"], p)
        li("total_assets", "Total assets", B["ta"], p)
        li("accounts_payable", "Accounts payable", B["ap"], p)
        li("accrued_expenses", "Accrued expenses", B["accrued"], p)
        if B["loc"]:
            li("line_of_credit", "Line of credit", B["loc"], p)
        if B["cpltd"]:
            li("current_portion_ltd", "Current portion of long-term debt", B["cpltd"], p)
        li("total_current_liabilities", "Total current liabilities", B["tcl"], p)
        if B["ltd"]:
            li("long_term_debt", "Long-term debt, net of current portion", B["ltd"], p)
        li("total_liabilities", "Total liabilities", B["tl"], p)
        li("common_stock", "Common stock", B["common_stock"], p)
        li("retained_earnings", "Retained earnings", B["retained_earnings"], p)
        li("current_year_income", "Current year net income", B["current_year_income"], p)
        li("total_equity", "Total equity", B["equity"], p)
        li("total_liabilities_and_equity", "Total liabilities and equity", B["ta"], p)
    return L


ASSURANCE_PREPARER = {"audit": "Plante Moran-style CPA firm (fictional): Lakes & Barrow CPAs", "review": "Lakes & Barrow CPAs, PLLC",
                      "compilation": "Corktown Accounting Group", "no_assurance": "Corktown Accounting Group",
                      "internal": "Company management", "tax_return": "Paid preparer (Form 1120-S)"}


def sb_deal(spec: dict):
    truth = build_small_business(spec)
    pres = present_sb(spec, truth)
    q = spec["quirks"]
    nonrec_label = q.get("nonrec_label", "Non-recurring income")
    for I in pres["is"].values():
        I["nonrec_label"] = nonrec_label
    pages = {"is": 4, "bs": 3, "cf": 5, "opex": 9, "dep": 5 if q.get("dep_location") == "cf_only" else 9}
    if q.get("no_bs_first_year"):
        pres["bs"].pop(f"FY{spec['years'][0]}", None)
    docs, financials = [], []
    ys = [f"FY{y}" for y in spec["years"]]
    assurance = q.get("assurance", "review")
    info = {"preparer": ASSURANCE_PREPARER.get(assurance), "assurance": assurance, "basis": q.get("basis", "gaap"), "page": 2}
    debts_all = _debts(spec, truth, pres)
    if assurance == "tax_return":
        groups = [[p] for p in ys]
    elif len(ys) >= 3:
        groups = [ys[:2], ys[1:]]
    else:
        groups = [ys]
    restated = {}
    for gi, g in enumerate(groups):
        doc = f"{spec['id']}_{'tax_return_' + g[0][2:] if assurance == 'tax_return' else 'financial_statements_' + g[-1][2:]}.pdf"
        L = []
        for pid in g:
            factor = None
            later = any(pid in g2 for g2 in groups[gi + 1:])
            if q.get("split_docs") and gi == 0 and later:
                factor = 0.985          # older document reports lower sales; newer statements restate them
                restated[pid] = doc
            L += sb_line_items(pid, pres["is"][pid], pres["bs"].get(pid), doc, pages, factor)
        per = [p for p in pres["periods"] if p["id"] in g]
        financials.append({"company_name": spec["name"], "doc": doc, "statement_info": info, "periods": per, "line_items": L,
                           "debts": debts_all if gi == len(groups) - 1 else [], "notes": []})
        docs.append({"name": doc, "doc_type": "tax_return" if assurance == "tax_return" else "financial_statements", "pages": 10})
    extra = [p for p in pres["periods"] if p["kind"] in ("interim", "projection")]
    if extra:
        doc = f"{spec['id']}_interim_and_forecast.pdf"
        L = []
        for p in extra:
            L += sb_line_items(p["id"], pres["is"][p["id"]], pres["bs"].get(p["id"]), doc, {"is": 1, "bs": 2, "cf": 1, "opex": 1, "dep": 1})
        financials.append({"company_name": spec["name"], "doc": doc, "statement_info": {"preparer": "Company management", "assurance": "internal", "basis": "gaap"},
                           "periods": extra, "line_items": L, "debts": [], "notes": []})
        docs.append({"name": doc, "doc_type": "projections" if any(p["kind"] == "projection" for p in extra) else "interim_financials"})
    # underwriter inputs
    n_all = [p["id"] for p in pres["periods"]]
    months = {p["id"]: p["months"] for p in pres["periods"]}
    lines = []
    for d in truth["debts"]:
        lines.append({"label": d["creditor"], "default_amount": round(d["monthly_payment"] * 12), "basis": "scheduled"})
    loc_int = {}
    for y in spec["years"]:
        if truth["is"][y]["interest_loc"]:
            loc_int[f"FY{y}"] = round(truth["is"][y]["interest_loc"])
    if truth.get("interim") and truth["interim"]["is"]["interest_loc"]:
        loc_int[truth["interim"]["id"]] = round(truth["interim"]["is"]["interest_loc"])
    if loc_int:
        last = loc_int.get(f"FY{spec['years'][-1]}", 0)
        for p in pres["periods"]:
            if p["kind"] == "projection" and p["id"] not in loc_int:
                loc_int[p["id"]] = round(last * months[p["id"]] / 12)
        lines.append({"label": "Interest Payment - LOC", "amounts": loc_int, "basis": "actual_interest"})
    owners = spec["owners"]
    profile = {"legal_name": spec["name"], "address": "Detroit, MI", "year_established": spec["year_established"],
               "description": spec["description"], "customers": spec["customers"], "employees": spec["employees"],
               "people": [{k: v for k, v in o.items()} for o in owners],
               "naics_suggestions": [] if q.get("no_naics_hint") else [{"code": spec["naics"], "rationale": "primary activity", "confidence": 0.8}]}
    L = spec["loan"]
    terms = {"deal_type": "small_business", "product": spec["product"], "fund_name": "INVEST DETROIT", "borrower_name": spec["name"],
             "borrower_address": "Detroit, MI", "ic_date": IC, "lender": "Synthetic Lender", "analyst": "Synthetic QA",
             "proposed_loan": {"label": "ID Loan", **L}, "debt_service_lines": lines, "fee_pct": spec["fee"],
             "real_estate_secured": spec["re_secured"], "lien_position": spec["lien"],
             "collateral": spec["collateral"], "guarantors": [o["name"] for o in owners if o["guarantor"]],
             "qualitative": spec["qual"], "documents_received": ["historical_financials"] + (["projections"] if truth.get("forecast") else []),
             "options": {"cpltd_in_current": True} if q.get("force_cpltd_current") else {}}
    deal = {"id": spec["id"], "terms": terms, "profile": profile, "financials": financials, "documents": docs, "extraction_mode": "fixture"}
    return deal, pres, truth, restated


def _debts(spec, truth, pres):
    out = []
    last = pres["periods"][-1]
    bs_ids = [p["id"] for p in pres["periods"] if p["id"] in pres["bs"]]
    for d in truth["debts"]:
        bals = [{"period_id": pid, "value": pres["bs"][pid]["debt_balances"].get(d["creditor"], 0.0), "page": 7}
                for pid in (bs_ids if d.get("is_id") else bs_ids[-1:])]
        last_y = spec["years"][-1]
        chg = -d["hist"][last_y]["principal"] if last_y in d["hist"] else None
        out.append({"creditor": d["creditor"], "kind": d["kind"], "balances": bals, "interest_rate": d["rate"],
                    "monthly_payment": round(d["monthly_payment"], 2), "subordinated": d["subordinated"], "related_party": d["related"],
                    "is_invest_detroit": bool(d.get("is_id")),
                    "cash_flow_change": round(chg) if chg is not None and not pres.get("interim") else None, "page": 7})
    loc_ids = [p for p in bs_ids if pres["bs"][p]["loc"]]
    if loc_ids:
        out.insert(0, {"creditor": "Bank line of credit", "kind": "line_of_credit",
                       "balances": [{"period_id": p, "value": pres["bs"][p]["loc"], "page": 3} for p in loc_ids[-1:]], "page": 7})
    return out


# ------------------------------------------------------------------ CRE
CRE_LABELS = {"gross_retail_rent": "Annual Gross Retail Rent", "retail_vacancy": "Less: Retail Vacancy Loss",
              "gross_office_rent": "Annual Gross Office Rent", "office_vacancy": "Less: Office Vacancy Loss",
              "gross_residential_rent": "Gross Residential Rent", "residential_vacancy": "Less: Residential Vacancy",
              "other_gross_rent": "Other Gross Rent", "other_vacancy": "Less: Other Vacancy", "cam_reimbursement": "Plus: CAM",
              "general_vacancy": "Less: Lease-up Vacancy", "management_fee": "Management Fee", "leasing_marketing": "Leasing & Marketing",
              "re_taxes": "Real Estate Taxes", "replacement_reserves": "Replacement Reserves", "capital_reserves": "Capital Reserves",
              "insurance": "Insurance", "maintenance": "Maintenance", "utilities": "Utilities", "accounting": "Accounting",
              "cleaning": "Cleaning", "payroll": "Payroll", "other_expense": "Other Operating Expense"}


def cre_deal(spec: dict):
    c = spec["cre"]
    truth = build_cre(spec)
    n = len(truth["years"])
    lines = []
    pres = {"years": truth["years"], "lines": {}, "total_revenue": [], "total_expenses": [], "noi": []}
    for k, vals in truth["lines"].items():
        if all(abs(v) < 0.5 for v in vals) and k not in ("replacement_reserves",):
            continue
        rv = [float(round(v)) for v in vals]
        pres["lines"][k] = rv
        lines.append({"key": k, "label": CRE_LABELS.get(k, k), "values": rv, "page": 1, "confidence": 0.95})
    # stated totals from unrounded spreadsheet values (like the Ballpoint sample)
    pres["total_revenue"] = [float(round(v)) for v in truth["total_revenue"]]
    pres["total_expenses"] = [float(round(v)) for v in truth["total_expenses"]]
    pres["noi"] = [float(round(v)) for v in truth["noi"]]
    lines += [{"key": "total_revenue", "label": "Total Revenue", "values": pres["total_revenue"], "page": 1},
              {"key": "total_expenses", "label": "Total Expenses", "values": pres["total_expenses"], "page": 1},
              {"key": "noi", "label": "Net Operating Income", "values": pres["noi"], "page": 1}]
    budget = []
    for cat, items in c["budget"].items():
        for label, amt in items:
            budget.append({"category": cat, "label": label, "amount": float(amt), "page": 3})
    L = spec["loan"]
    sources = [{"label": "Invest Detroit Loan", "amount": float(L["amount"]), "kind": "invest_detroit"},
               {"label": "Owner Equity", "amount": float(c["equity"]), "kind": "equity"}]
    ap = c["appraisal"]
    rsf = sum(u["sf"] for u in c["units"])
    cre = {"property": {"address": "Detroit, MI", "gross_sf": c["gross_sf"], "rentable_sf": rsf, "rehab_type": c["rehab_type"]},
           "rent_roll": [{**u, "status": "proposed", "lease_type": "nnn" if u["use"] in ("retail", "other") else "gross", "page": 2} for u in c["units"]],
           "projections": {"years": truth["years"], "lines": lines, "doc": f"{spec['id']}_operating_projections.pdf"},
           "budget": budget, "sources": sources,
           "appraisal": {k: v for k, v in ap.items()}, "lois": [], "development_team": [], "development_status": None}
    owners = spec["owners"]
    profile = {"legal_name": spec["name"], "address": "Detroit, MI", "description": spec["description"],
               "people": owners, "naics_suggestions": [{"code": spec["naics"], "confidence": 0.85}]}
    terms = {"deal_type": "cre", "product": spec["product"], "fund_name": "INVEST DETROIT", "borrower_name": spec["name"],
             "borrower_address": "Detroit, MI", "ic_date": IC, "lender": "Synthetic Lender", "analyst": "Synthetic QA",
             "proposed_loan": {"label": "ID Loan", **L}, "fee_pct": spec["fee"], "real_estate_secured": True,
             "lien_position": spec["lien"],
             "takeout_loan": ({"label": "Perm Mtg", **spec["takeout"]} if spec.get("takeout") else None),
             "debt_service_months": spec["ds_months"],
             "collateral": [{"description": "Real estate", "valuation_source": "Appraisal (as stabilized)",
                             "gross_value": ap["as_stabilized_value"], "advance_rate": 1.0}],
             "guarantors": [o["name"] for o in owners if o["guarantor"]], "qualitative": spec["qual"],
             "risk_scores": {k: {"score": v} for k, v in {"borrower_sponsor": 2, "project_strength": 3, "payment_history": 2,
                                                          "construction": 3, "industry_market": 3}.items()},
             "documents_received": ["projections", "rent_roll", "appraisal", "construction_budget"]}
    deal = {"id": spec["id"], "terms": terms, "profile": profile, "cre": cre, "financials": [],
            "documents": [{"name": cre["projections"]["doc"], "doc_type": "cre_projections"}], "extraction_mode": "fixture"}
    return deal, pres, truth, {}


def build_case(spec: dict):
    return sb_deal(spec) if spec["kind"] == "small_business" else cre_deal(spec)
