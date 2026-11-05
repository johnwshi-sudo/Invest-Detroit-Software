"""Credit guideline / policy checks against config/credit_guidelines.yaml (Appendix B, C, E).

Output: exceptions (to disclose on page 1 of the Investment Summary), passed checks, document gaps,
line-of-business classification and the Oversight Council trigger.
"""
from __future__ import annotations

from typing import Optional

from ..guidelines import load_guidelines
from ..schema import Deal
from .common import fmt_money, fmt_pct, fmt_x

RISK_CATEGORIES = [
    ("borrower_sponsor", "Borrower / Sponsor Strength"),
    ("project_strength", "Project Strength"),
    ("project_financial", "Project Financial Criteria (LTV & LTC)"),
    ("payment_history", "Payment History / Interest Reserve Adequacy for Bridge Loans"),
    ("debt_service", "Debt Service"),
    ("construction", "Land Development / Construction"),
    ("hard_cost_contingency", "Hard Cost Contingency Reserves"),
    ("industry_market", "Industry / Market / Economy"),
]


def _exc(kind, item, requirement, actual, counts=True, mitigants=None, source="Appendix B"):
    return {"kind": kind, "item": item, "requirement": requirement, "actual": actual,
            "counts_toward_oversight": counts, "mitigants": mitigants or [], "source": source}


def check_policy(deal: Deal, analysis: dict, naics_code: Optional[str] = None) -> dict:
    G = load_guidelines()
    t = deal.terms
    prod = G["products"].get(t.product)
    allp = G["all_products"]
    exceptions, passed, info = [], [], []
    if prod is None:
        info.append(f"Product '{t.product}' not in the loan product matrix; product checks skipped.")
        prod = {}
    loan = t.proposed_loan
    M = G["mitigants"]

    # ---------------- line of business ----------------
    lob = None
    if t.deal_type == "small_business":
        inc = analysis.get("income", {})
        annual = [p for p in analysis.get("hist", []) if inc[p]["months"] == 12]
        rev = inc[annual[-1]]["revenue"] if annual else None
        mfg = bool(naics_code and naics_code[:2] in ("31", "32", "33"))
        c_and_i = (rev or 0) >= G["line_of_business"]["c_and_i"]["min_revenue"] or mfg
        lob = {"line": "C&I" if c_and_i else "Small Business", "revenue": rev, "manufacturing": mfg,
               "reason": (f"Revenue {fmt_money(rev)} {'>=' if (rev or 0) >= 5e6 else '<'} $5M" +
                          ("; manufacturing NAICS" if mfg else ""))}
        if c_and_i and t.product == "small_business_term":
            info.append("Credit Guidelines classify this borrower as C&I (revenue >= $5M or industrial/manufacturing); "
                        "the product matrix has no separate C&I column, so Small Business Term parameters were applied.")
    else:
        lob = {"line": "CRE", "reason": "Investment real estate"}

    # ---------------- amount / term / amortization ----------------
    if loan:
        if prod.get("max_amount") and loan.amount > prod["max_amount"]:
            exceptions.append(_exc("guideline", "Loan amount", f"<= {fmt_money(prod['max_amount'])}", fmt_money(loan.amount),
                                   mitigants=M["structural_cash_flow"][:2]))
        elif prod.get("max_amount"):
            passed.append(("Loan amount", f"{fmt_money(prod.get('min_amount'))} - {fmt_money(prod['max_amount'])}", fmt_money(loan.amount)))
        if prod.get("min_amount") and loan.amount < prod["min_amount"]:
            exceptions.append(_exc("guideline", "Loan amount (minimum)", f">= {fmt_money(prod['min_amount'])}", fmt_money(loan.amount), counts=False))
        if loan.term_months and prod.get("max_term_months"):
            if loan.term_months > prod["max_term_months"]:
                exceptions.append(_exc("guideline", "Term", f"<= {prod['max_term_months']} months", f"{loan.term_months} months",
                                       mitigants=["Shorter term and/or accelerated amortization"]))
            else:
                passed.append(("Term", f"<= {prod['max_term_months']} months", f"{loan.term_months} months"))
        elif prod.get("max_term_months"):
            info.append("Loan term not provided; term limit not tested.")
        if prod.get("max_amortization_months") is not None and loan.amort_months:
            if loan.amort_months > prod["max_amortization_months"]:
                exceptions.append(_exc("guideline", "Amortization", f"<= {prod['max_amortization_months']} months", f"{loan.amort_months} months"))
            else:
                passed.append(("Amortization", f"<= {prod['max_amortization_months'] // 12} years", f"{loan.amort_months} months"))
        # rate (asterisked)
        rng = allp["interest_rate"]["real_estate_secured" if t.real_estate_secured else "non_real_estate_secured"]
        if not (rng[0] - 1e-9 <= loan.rate <= rng[1] + 1e-9):
            exceptions.append(_exc("guideline", "Interest rate", f"{fmt_pct(rng[0], 2)} - {fmt_pct(rng[1], 2)} "
                                   f"({'real estate' if t.real_estate_secured else 'non-real estate'} secured)",
                                   fmt_pct(loan.rate, 2), counts=False))
        else:
            passed.append(("Interest rate", f"{fmt_pct(rng[0], 2)} - {fmt_pct(rng[1], 2)}", fmt_pct(loan.rate, 2)))
        # fee (asterisked)
        req_fee = prod.get("origination_fee")
        if req_fee is not None and t.fee_pct is not None:
            if loan.amount < 100000:
                pass
            elif t.fee_pct + 1e-9 < req_fee:
                exceptions.append(_exc("guideline", "Origination / extension fee", prod.get("origination_fee_text") or fmt_pct(req_fee, 2),
                                       fmt_pct(t.fee_pct, 2), counts=False))
            else:
                passed.append(("Origination fee", fmt_pct(req_fee, 2), fmt_pct(t.fee_pct, 2)))

    # ---------------- DSCR ----------------
    min_dscr = prod.get("min_dscr")
    if min_dscr:
        if t.deal_type == "small_business":
            inc = analysis["income"]
            annual = [p for p in analysis["hist"] if inc[p]["months"] == 12]
            if annual:
                last = annual[-1]
                d = inc[last]["dscr"]
                agg = analysis.get("aggregate")
                proj_d = agg["values"]["dscr"] if agg else None
                if d is not None and d < min_dscr:
                    mit = list(allp["dscr_compensating_factors"])
                    if proj_d and proj_d >= min_dscr:
                        mit.insert(0, f"Projected DSCR {fmt_x(proj_d)} ({agg['label']}) meets the threshold")
                    exceptions.append(_exc("guideline", "Min DSCR", f">= {fmt_x(min_dscr)}",
                                           f"{fmt_x(d)} ({last})" + (f"; projected {fmt_x(proj_d)}" if proj_d else ""), mitigants=mit))
                elif d is not None:
                    passed.append(("Min DSCR", f">= {fmt_x(min_dscr)}", fmt_x(d)))
        else:
            si = analysis.get("stabilized_index")
            if si is not None:
                d = analysis["dscr_proposed"][si]
                yr = analysis["years"][si]
                if d is not None and d < min_dscr:
                    exceptions.append(_exc("guideline", "Min DSCR @ stabilization", f">= {fmt_x(min_dscr)}", f"{fmt_x(d)} ({yr})",
                                           mitigants=list(allp["dscr_compensating_factors"])))
                elif d is not None:
                    passed.append(("Min DSCR @ stabilization (ID loan)", f">= {fmt_x(min_dscr)}", f"{fmt_x(d)} ({yr})"))

    # ---------------- LTV / LTC / equity ----------------
    coll = analysis.get("collateral") or {}
    ltv = coll.get("cltv_gross") if coll.get("prior_liens") else coll.get("ltv_gross")
    if prod.get("max_ltv") and ltv is not None:
        if ltv > prod["max_ltv"]:
            exceptions.append(_exc("guideline", "Max LTV", f"<= {fmt_pct(prod['max_ltv'], 0)}", fmt_pct(ltv), mitigants=M["collateral_enhancement"][:3]))
        else:
            passed.append(("Max LTV", f"<= {fmt_pct(prod['max_ltv'], 0)}", fmt_pct(ltv)))
    su = analysis.get("sources_uses")
    if su:
        if prod.get("max_ltc") and su.get("ltc") is not None:
            if su["ltc"] > prod["max_ltc"]:
                exceptions.append(_exc("guideline", "Max LTC", f"<= {fmt_pct(prod['max_ltc'], 0)}", fmt_pct(su["ltc"])))
            else:
                passed.append(("Max LTC", f"<= {fmt_pct(prod['max_ltc'], 0)}", fmt_pct(su["ltc"])))
        if su.get("equity_pct") is not None:
            if su["equity_pct"] < allp["min_equity_total"]:
                exceptions.append(_exc("guideline", "Min equity", f">= {fmt_pct(allp['min_equity_total'], 0)}", fmt_pct(su["equity_pct"]),
                                       mitigants=["Increased borrower equity or cash injection"]))
            else:
                passed.append(("Min equity", f">= {fmt_pct(allp['min_equity_total'], 0)} total", fmt_pct(su["equity_pct"])))
        # contingencies (Appendix E)
        rt = deal.cre.property.rehab_type if deal.cre else "rehab"
        req = G["contingencies"]["new_construction" if rt == "new_construction" else "rehab_construction"]
        label = "new construction" if rt == "new_construction" else "rehab"
        for kind, pct_key in (("hard", "hard_contingency_pct"), ("soft", "soft_contingency_pct")):
            actual = su.get(pct_key)
            lab = su.get("labeled_contingency", {}).get(f"{kind}_contingency")
            shown = fmt_pct(actual) + (f" (budget labels it {fmt_pct(lab, 1)})" if lab and abs(lab - (actual or 0)) > 0.005 else "")
            if actual is None:
                continue
            if actual + 1e-9 < req[kind]:
                exceptions.append(_exc("guideline", f"{kind.title()} cost contingency for {label}", f">= {fmt_pct(req[kind], 0)}", shown,
                                       mitigants=["Additional owner equity available for overruns", "Fixed-price / GMP contract", "Completion guaranty"],
                                       source="Appendix E"))
            else:
                passed.append((f"{kind.title()} cost contingency ({label})", f">= {fmt_pct(req[kind], 0)}", shown))

    # ---------------- guarantees / background (policy) ----------------
    thr = allp["guarantee_ownership_threshold"]
    for p in deal.profile.people:
        if p.ownership_pct is not None and p.ownership_pct >= thr:
            if p.guarantor is False:
                exceptions.append(_exc("policy", f"Guarantee for owners > {fmt_pct(thr, 0)}", "Unlimited guarantee from all >= 20% owners",
                                       f"{p.name} ({fmt_pct(p.ownership_pct, 2)}) not guaranteeing" + (" - passive investor" if p.passive else ""),
                                       source="Loan Policy / Appendix B"))
            if p.background_check is False:
                exceptions.append(_exc("policy", "Background check", "Background check and credit report on >= 20% owners",
                                       f"Not obtained for {p.name}", source="Loan Policy"))

    counted = [e for e in exceptions if e["kind"] == "guideline" and e["counts_toward_oversight"]]
    trigger = G["exceptions"]["oversight_council_trigger"]
    return {"product": t.product, "product_label": prod.get("label", t.product), "line_of_business": lob,
            "exceptions": exceptions, "passed": passed, "info": info,
            "guideline_exception_count": len(counted), "oversight_council_required": len(counted) > trigger,
            "documents": document_checklist(deal)}


def document_checklist(deal: Deal) -> dict:
    G = load_guidelines()
    amount = deal.terms.proposed_loan.amount if deal.terms.proposed_loan else 0
    col = "before_screen_le_250k" if amount <= 250000 else "before_screen_gt_250k"
    have = set(deal.terms.documents_received)
    for d in deal.documents:
        have |= {"financial_statements": {"historical_financials"}, "tax_return": {"historical_financials"},
                 "interim_financials": {"interim_financials"}, "projections": {"projections"}, "cre_projections": {"projections"},
                 "business_plan": {"business_plan"}, "debt_schedule": {"debt_schedule"}, "rent_roll": {"rent_roll"},
                 "appraisal": {"appraisal"}, "budget": {"construction_budget"}, "loi": {"loi"},
                 "bank_statements": {"bank_statements"}, "personal_financial_statement": {"guarantor_financials"}}.get(d.doc_type, set())
    is_re = deal.terms.deal_type == "cre"
    screen, uw = [], []
    for r in G["document_requirements"]:
        if r.get("real_estate_only") and not is_re:
            continue
        status = "received" if r["key"] in have else "missing"
        if r.get(col):
            screen.append({"item": r["item"], "requirement": r[col], "status": status})
        if r.get("underwriting"):
            uw.append({"item": r["item"], "requirement": r["underwriting"], "status": status})
    return {"before_screen": screen, "underwriting": uw,
            "missing_required_before_screen": [x["item"] for x in screen if x["status"] == "missing" and x["requirement"] == "required"]}


def risk_rating(deal: Deal, analysis: dict, policy: dict) -> Optional[dict]:
    """CRE risk-rating worksheet. Quantitative categories are scored from the analysis using the only anchors
    known from the sample (UNVERIFIED rubric); qualitative categories come from underwriter input."""
    if deal.terms.deal_type != "cre":
        return None
    rs = deal.terms.risk_scores
    rows = []
    coll = analysis.get("collateral", {})
    ltv = coll.get("ltv_gross")
    senior_ltv = ltv  # ID is senior lender
    si = analysis.get("stabilized_index")
    dscr = analysis["dscr_proposed"][si] if si is not None else None
    su = analysis.get("sources_uses", {})
    G = load_guidelines()
    rt = deal.cre.property.rehab_type
    req_hc = G["contingencies"]["new_construction" if rt == "new_construction" else "rehab_construction"]["hard"]
    for key, label in RISK_CATEGORIES:
        auto, comment = None, None
        if key == "project_financial" and ltv is not None:
            auto = 1 if (ltv < 0.65 and senior_ltv < 0.55) else 2 if ltv < 0.75 else 3 if ltv < 0.85 else 4 if ltv <= 1.0 else 5
            comment = f"Construction: LTV {fmt_pct(ltv)} (< 65% for a 1); Senior Debt LTV {fmt_pct(senior_ltv)} (< 55% for a 1)."
        elif key == "debt_service" and dscr is not None:
            auto = 1 if dscr > 1.45 else 2 if dscr >= 1.30 else 3 if dscr >= 1.20 else 4 if dscr >= 1.15 else 5
            comment = f"Mortgage: stabilized DSCR {fmt_x(dscr)} on the Invest Detroit loan (Total > 1.40x and Senior > 1.45x for a 1)."
        elif key == "hard_cost_contingency" and su.get("hard_contingency_pct") is not None:
            ok = su["hard_contingency_pct"] + 1e-9 >= req_hc
            auto = 2 if ok else 4
            comment = (f"Hard cost contingency {fmt_pct(su['hard_contingency_pct'])} vs {fmt_pct(req_hc, 0)} required; "
                       "reserve for adaptive reuse projects less than 15% or new construction less than 10% scores a 4.")
        given = rs.get(key)
        score = given.score if (given and given.score is not None) else auto
        rows.append({"key": key, "category": label, "score": score, "auto_score": auto,
                     "comment": (given.comment if given and given.comment else comment), "source": "input" if given and given.score is not None else ("computed" if auto else "missing")})
    scores = [r["score"] for r in rows if r["score"] is not None]
    total = sum(scores) if scores else None
    prelim = int(total / len(scores) + 0.5) if scores else None
    ov = rs.get("management_override")
    return {"rows": rows, "total": total, "preliminary": prelim, "override": ov.score if ov else None,
            "override_comment": ov.comment if ov else None, "final": (ov.score if ov and ov.score else prelim),
            "complete": len(scores) == len(RISK_CATEGORIES), "rubric_verified": False}
