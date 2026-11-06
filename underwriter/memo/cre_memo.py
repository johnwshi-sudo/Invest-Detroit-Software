"""CRE Investment Summary, modeled on the Ballpoint Bagley sample."""
from __future__ import annotations

from ..engine.common import fmt_money, fmt_pct, fmt_x, safe_div
from ..guidelines import load_guidelines
from ..schema import REVENUE_KEYS, VACANCY_KEYS
from .blocks import bullets, kv, n, numbered, p, pc, placeholder, row, section, subhead, table, x
from .common_sections import (benchmarking_section, compliance_section, documents_section, header, qual,
                              term_sheet_section)

REV_ORDER = ["gross_retail_rent", "retail_vacancy", "gross_office_rent", "office_vacancy", "gross_residential_rent",
             "residential_vacancy", "other_gross_rent", "other_vacancy", "cam_reimbursement", "other_income", "general_vacancy"]


def _p1(v):
    return "" if v is None else f"{v * 100:.1f}%"


def projection_table(r: dict, which: str, title: str, deal) -> tuple[dict, list[str]]:
    """which = 'base' (ID-adjusted with base debt service) or 'sens' (sensitized)."""
    years = r["years"]
    n_ = len(years)
    L = r["id"]["lines"]
    labels = r["labels"]
    sens = r["sensitivity"] if which == "sens" else None
    rev = sens["revenue"] if sens else r["id"]["revenue"]
    noi = sens["noi"] if sens else r["id"]["noi"]
    exp = r["id"]["expenses"]
    ds = sens["debt_service"] if sens else r["ds_base"]
    head_first = "Borrower\nProjections" if which == "base" else "ID Sensitized\nProjections"
    cols = [""]
    for i, y in enumerate(years):
        cols += [(head_first if i == 0 else ("Projections" if which == "base" else "ID Sensitized\nProjections")) + f"\n{y}", "% of\nRevenue"]
    note_no = {}
    rows = [row(["Rental Revenue"] + [""] * (2 * n_), "bold")]
    for k in REV_ORDER:
        if k not in L:
            continue
        vals = list(L[k])
        if sens and k == sens["line"]:
            vals = [-v for v in sens["loss"]]
        cells = []
        for t in range(n_):
            cells += [n(vals[t]), ""]
        rows.append(row(["  " + labels.get(k, k)] + cells, "indent"))
    rows.append(row(["Total Revenue"] + sum([[n(rev[t]), "100.0%"] for t in range(n_)], []), "total"))
    rows.append(row(["Expenses*"] + [""] * (2 * n_), "bold"))
    exp_keys = [k for k in r["exp_keys"]]
    for k in exp_keys:
        cells = []
        for t in range(n_):
            cells += [n(L[k][t], False), _p1(safe_div(L[k][t], rev[t]))]
        rows.append(row(["  " + labels.get(k, k)] + cells, "indent"))
    rows.append(row(["Total Expenses"] + sum([[n(exp[t]), _p1(safe_div(exp[t], rev[t]))] for t in range(n_)], []), "total"))
    rows.append(row(["Net Operating Income"] + sum([[n(noi[t]), _p1(safe_div(noi[t], rev[t]))] for t in range(n_)], []), "bold"))
    rows.append(row(["Debt Service:"] + [""] * (2 * n_), "bold"))
    loan = deal.terms.proposed_loan if sens else (deal.terms.takeout_loan or deal.terms.proposed_loan)
    llabel = f"{loan.label} {fmt_money(loan.amount)} @ {loan.rate * 100:.1f}%, {loan.amort_months // 12} yr am" if loan else "Debt service"
    rows.append(row(["  " + llabel] + sum([[n(ds[t]), ""] for t in range(n_)], []), "indent"))
    rows.append(row(["Total Debt Service"] + sum([[n(ds[t]), ""] for t in range(n_)], []), "total"))
    cf = [noi[t] - ds[t] for t in range(n_)]
    rows.append(row(["Cash Flow After Debt Service"] + sum([[n(cf[t], False), ""] for t in range(n_)], [])))
    dscr = [safe_div(noi[t], ds[t]) for t in range(n_)]
    rows.append(row(["DSCR"] + sum([[f"{v:.2f}" if v is not None else "n/a", ""] for v in dscr], []), "bold"))
    return table(title, cols, rows, footnote="* Expenses as % of total revenue."), []


def cash_flow_notes(deal, r: dict) -> list[str]:
    A = load_guidelines()["cre_underwriting_assumptions"]
    L = r["id"]["lines"]
    labels = r["labels"]
    notes = []
    rc = r.get("rent_cagr", {})
    if rc:
        vals = [v for v in rc.values() if v is not None]
        g = max(vals) if vals else None
        cap = A["rent_growth_max"]
        if g is not None:
            if abs(g - cap) <= 5e-4:
                notes.append(f"Rents increase by {g * 100:.1f}% annually per Invest Detroit's credit guidelines.")
            elif g < cap:
                notes.append(f"Rents increase by {g * 100:.1f}% annually per the borrower's projections (below Invest Detroit's {cap * 100:.0f}% maximum).")
            else:
                notes.append(f"Rents increase by {cap * 100:.0f}% annually per Invest Detroit's credit guidelines (borrower projected {g * 100:.1f}%).")
    vb = r["vacancy_by_line"]
    for k, v in vb.items():
        if v is not None:
            notes.append(f"{v * 100:.0f}% {labels.get(k, k).lower().replace('less: ', '').replace(' loss', '')} rate based on borrower's projections.")
    si = r["stabilized_index"]
    if si is not None and r["blended_vacancy"][si] is not None:
        ap = deal.cre.appraisal.vacancy_estimate
        bv, gl = r["blended_vacancy"][si], A["commercial_vacancy_min"]
        cmp_gl = "at or above" if bv >= gl - 5e-4 else "below"
        cmp_ap = ("at or above" if bv >= ap - 5e-4 else "below") if ap is not None else None
        verdict = " and is considered conservative." if cmp_gl == "at or above" and cmp_ap in (None, "at or above") else "."
        notes.append(f"Blended stabilized vacancy of {bv * 100:.1f}% (weighted by gross rent) is {cmp_gl} Invest Detroit's {gl * 100:.0f}% commercial "
                     f"vacancy guideline" + (f" and {cmp_ap} the appraiser's {ap * 100:.0f}% estimate" if ap is not None else "") + verdict
                     + (" The guideline applies to commercial space; residential vacancy is the borrower's assumption." if any(k == "residential_vacancy" for k in vb) else ""))
    if r["year1_general_vacancy"]:
        notes.append(f"{r['year1_general_vacancy'] * 100:.1f}% total vacancy in {r['years'][0]} based on borrower's projections and anticipated time for leasing activities.")
    ec = r.get("expense_cagr", {})
    if ec:
        vals = [v for v in ec.values() if v is not None]
        g = min(vals) if vals else None
        fl = A["expense_growth_min"]
        if g is not None:
            notes.append(f"Expenses increase by at least {fl * 100:.0f}% annually per Invest Detroit's credit guidelines" +
                         (f" (borrower projected as little as {g * 100:.1f}%; increased to {fl * 100:.0f}%)." if g < fl - 5e-4 else "."))
    for nt in r["notes"]:
        notes.append(nt["text"])
    sz = r.get("sizing")
    take = deal.terms.takeout_loan
    if take:
        t = f"Terms estimated by underwriter ({take.label} {fmt_money(take.amount)} @ {take.rate * 100:.2f}%, {take.amort_months // 12}-year amortization)."
        if sz:
            t += (f" Loan amount was based on {sz['target_dscr']:.2f}x DSC on {sz['year']} NOI of {fmt_money(sz['noi'])} (maximum {fmt_money(sz['max_loan'])}); "
                  f"under this scenario the LTC would be {r['takeout']['ltc'] * 100:.1f}%.")
        if deal.terms.qualitative.get("takeout_lenders"):
            t += " " + deal.terms.qualitative["takeout_lenders"]
        months = r["months"]
        part = [f"{months[i]} months" for i in range(len(months)) if 0 < months[i] < 12]
        if part:
            t += f" Only {part[0]} of debt service was estimated in {r['years'][months.index(int(part[0].split()[0]))]}."
        notes.append(t)
    if deal.terms.qualitative.get("interest_holdback"):
        notes.append("Please note, " + deal.terms.qualitative["interest_holdback"][0].lower() + deal.terms.qualitative["interest_holdback"][1:])
    return notes


def rent_roll_table(r: dict) -> dict:
    rr = r["rent_roll"]
    rows = [row([u["unit"], f"{u['sf']:,.0f}" if u["sf"] else "", f"${u['rent_psf']:,.2f}" if u["rent_psf"] else "",
                 fmt_money(u["rent"]), fmt_money(u["loss"]), fmt_money(u["net"])]) for u in rr["rows"]]
    t = rr["total"]
    rows.append(row(["TOTALS:", f"{t['sf']:,.0f}", "", fmt_money(t["rent"]), fmt_money(t["loss"]), fmt_money(t["net"])], "total"))
    return table("Rent Roll", ["Description", "Sq. Ft.", "Rent/Sq. Ft.", "Rent", f"Loss ({rr['loss_rate'] * 100:.0f}%)", "Net Ann. Rent"], rows, kind="grid")


def leasing_section(deal, r: dict) -> dict:
    rr = r["rent_roll"]
    ap = deal.cre.appraisal
    blocks = []
    o = rr["by_use"].get("office")
    if o:
        blocks.append(subhead("Office Leases"))
        txt = f"The borrower's projections include average rent/sf for office/co-workspace of ${o['avg_psf']:,.0f}/sf (rounded; ${o['avg_psf']:,.2f}) on a gross basis."
        if ap.market_rent_office_psf:
            txt += f" For reference, the appraiser concluded the market rate for the office space to be ${ap.market_rent_office_psf:,.0f}/sf."
        if deal.terms.qualitative.get("office_leasing"):
            txt += " " + deal.terms.qualitative["office_leasing"]
        blocks.append(p(txt))
    rt = rr["by_use"].get("retail")
    if rt:
        blocks.append(subhead("Retail Leases"))
        txt = f"Retail rents are projected between ${rt['monthly_min']:,.0f}-${rt['monthly_max']:,.0f} per month (average ${rt['avg_psf']:,.2f}/sf)"
        nnn = [u for u in deal.cre.rent_roll if u.use == "retail" and u.lease_type == "nnn"]
        if nnn:
            txt += " on a NNN expense basis with tenant responsibilities for real estate taxes, utilities, CAM, and insurance expenses"
        txt += "."
        if ap.market_rent_retail_psf:
            loi_psf = [l["rent_psf"] for l in rr["lois"] if l["rent_psf"]]
            txt += f" For reference, the appraiser concluded a market rent of ${ap.market_rent_retail_psf:,.0f}/sf"
            if loi_psf:
                txt += f", which is lower than the rent indicated in the LOIs ({' & '.join(f'${v:,.2f}/sf' for v in loi_psf)})"
            txt += "."
        blocks.append(p(txt))
    lb = []
    for l in rr["lois"]:
        lb.append(f"{l['tenant']}{', ' + l['use'].lower() if l.get('use') else ''}, intends to occupy {l['unit'] or 'a unit'}, {l['sf']:,.0f} sf with a "
                  f"{l['term_years']:.0f}-year term. The stated rent in the LOI is {fmt_money(l['monthly_rent'])} per month (${l['rent_psf']:,.2f}/sf)"
                  f"{' on a NNN expense basis' if l['lease_type'] == 'nnn' else ''}{' with ' + l['renewal_options'] if l.get('renewal_options') else ''}.")
    if lb:
        blocks.append(bullets(lb, "extracted"))
    return section("leasing", "Leasing Terms", blocks)


def sources_uses_table(r: dict) -> dict:
    su = r["sources_uses"]
    srcs, uses = su["sources"], su["uses"]
    rows = []
    for i in range(max(len(srcs), len(uses))):
        s = srcs[i] if i < len(srcs) else None
        u = uses[i] if i < len(uses) else None
        psf = ""
        if u and u["key"] == "hard" and su["hard_cost_psf"]:
            psf = f"{su['hard_cost_psf']:,.2f}"
        rows.append(row([s["label"] if s else "", fmt_money(s["amount"]) if s else "", _p1(s["pct"]) if s else "",
                         u["label"] + (f" ({su['hard_contingency_pct'] * 100:.1f}%)" if u and u["key"] == "hard_contingency" else
                                       f" ({su['soft_contingency_pct'] * 100:.1f}%)" if u and u["key"] == "soft_contingency" else "") if u else "",
                         fmt_money(u["amount"]) if u else "", _p1(u["pct"]) if u else "", psf]))
    rows.append(row(["Total Sources", fmt_money(su["total_sources"]), "100.0%", "Total Uses", fmt_money(su["total_uses"]), "100.0%",
                     f"{su['total_cost_psf']:,.3f}" if su["total_cost_psf"] else ""], "total"))
    return table("Summary Sources and Uses of Funds", ["Sources", "", "", "Uses", "", "", "Cost/SF"], rows, kind="grid",
                 footnote=f"Cost/SF on {su['rentable_sf']:,.0f} rentable SF" + (f" ({su['gross_sf']:,.0f} gross SF: total ${su['total_cost_psf_gross']:,.2f}/SF)." if su.get("gross_sf") else "."))


def su_bullets(deal, r: dict) -> dict:
    G = load_guidelines()
    su = r["sources_uses"]
    rt = deal.cre.property.rehab_type
    req = G["contingencies"]["new_construction" if rt == "new_construction" else "rehab_construction"]
    lab = "new construction" if rt == "new_construction" else "rehab"
    items = [f"The owner's equity is {su['equity_pct'] * 100:.0f}%, which is {'greater than' if su['equity_pct'] >= G['all_products']['min_equity_total'] else 'below'} "
             f"Invest Detroit's credit guidelines of {G['all_products']['min_equity_total'] * 100:.0f}%."
             + (" " + deal.terms.qualitative["equity_spent"] if deal.terms.qualitative.get("equity_spent") else "")]
    if deal.terms.qualitative.get("fast_track"):
        items.append(deal.terms.qualitative["fast_track"])
    for kind in ("hard", "soft") if su.get("hard_base") and deal.cre.property.rehab_type != "acquisition" else ():
        act = su[f"{kind}_contingency_pct"]
        if act is None:
            continue
        lbl = su["labeled_contingency"].get(f"{kind}_contingency")
        shown = f"{act * 100:.1f}%" + (f" of {kind} costs (labeled {lbl * 100:.1f}% in the budget)" if lbl and abs(lbl - act) > 0.005 else "")
        items.append(f"{kind.title()} cost contingency is {shown}, which is {'below' if act < req[kind] else 'at or above'} Invest Detroit's credit guidelines of "
                     f"{req[kind] * 100:.0f}% for {lab} projects.")
    items.append(f"Invest Detroit's loan represents {su['ltc'] * 100:.1f}% of total project cost (LTC). Please see Exhibit C for the full development budget.")
    return bullets(items)


def budget_exhibit(r: dict) -> dict:
    su = r["sources_uses"]
    cats = [("acquisition", "Acquisition"), ("hard", "Construction Costs"), ("hard_contingency", None), ("professional", "Professional Fees"),
            ("lender_carry", "Lender Costs & Carrying Costs"), ("developer_fee", "Developer Fee"), ("reserves", "Reserves"),
            ("other_soft", "Other Soft Costs"), ("soft_contingency", "Miscellaneous")]
    tot = su["total_uses"]
    rows = []
    budget = su["budget"]
    for key, title in cats:
        items = [b for b in budget if b["category"] == key]
        if not items:
            continue
        if title:
            rows.append(row([title, "", ""], "bold"))
        for b in items:
            rows.append(row(["  " + b["label"], fmt_money(b["amount"]), f"{safe_div(b['amount'], tot) * 100:.2f}%"], "indent"))
        if key in ("hard", "hard_contingency"):
            if key == "hard_contingency":
                sub = sum(b["amount"] for b in budget if b["category"] in ("hard", "hard_contingency"))
                rows.append(row(["Subtotal Construction Costs", fmt_money(sub), f"{sub / tot * 100:.2f}%"], "total"))
            continue
        sub = sum(b["amount"] for b in items)
        rows.append(row([f"Subtotal {title}", fmt_money(sub), f"{sub / tot * 100:.2f}%"], "total"))
    rows.append(row(["TOTAL DEVELOPMENT COSTS", fmt_money(tot), "100.00%"], "total2"))
    return table("Exhibit C - Development Budget", ["TOTAL DEVELOPMENT COSTS", "Amount", "% of TDC"], rows, kind="grid")


def collateral_tables(deal, r: dict) -> list:
    c = r["collateral"]
    rows = [row([i["description"], i.get("valuation_source") or "", fmt_money(i["gross_value"]), f"{i['advance_rate'] * 100:.0f}%",
                 fmt_money(i["prior_liens"]), fmt_money(i["discounted_value"])]) for i in c["items"]]
    rows.append(row(["", "Total Value", fmt_money(c["gross_value"]), "", fmt_money(c["prior_liens"]), fmt_money(c["discounted_value"])], "total"))
    rows.append(row(["", "", "", "Less Proposed Debt:", "Senior Debt", fmt_money(c["loan"])]))
    rows.append(row(["", "", "", "", "Total Debt", fmt_money(c["loan"])], "total"))
    rows.append(row(["", "", "", '"All In" - Discounted', "Surplus (Deficit)", fmt_money(c["surplus_discounted"])], "bold"))
    rows.append(row(["", "", "", "", "CLTV: Discounted", pc(c["ltv_discounted"], 1)]))
    rows.append(row(["", "", "", '"All In" - Gross', "Surplus (Deficit)", fmt_money(c["surplus_gross"])], "bold"))
    rows.append(row(["", "", "", "", "LTV: Gross", pc(c["ltv_gross"], 1)]))
    desc = [row(["Fee Real Estate", f"A perfected, {deal.terms.lien_position or 'first position mortgage'} on the property, including an assignment of leases and rents affecting the premises."])]
    if deal.terms.qualitative.get("collateral_contracts"):
        desc.append(row(["Contracts", deal.terms.qualitative["collateral_contracts"]]))
    return [p("The Loan shall be secured by the following:"), table(None, ["Collateral", "Description"], desc, kind="grid"),
            table(None, ["Collateral", "Valuation Source", "Gross Value", "Advance Rate", "Prior Liens", "Discounted Value"], rows, kind="grid")]


def risk_table(rr: dict) -> list:
    rows = [row([x_["category"], "" if x_["score"] is None else f"{x_['score']:g}", x_["comment"] or ""]) for x_ in rr["rows"]]
    rows.append(row(["Total", f"{rr['total']:g}" if rr["total"] is not None else "", ""], "total"))
    rows.append(row(["Preliminary Risk Rating", f"{rr['preliminary']}" if rr["preliminary"] is not None else "", "round(average of category scores)"], "bold"))
    if rr.get("override"):
        rows.append(row(["Management Override", f"{rr['override']:g}", rr.get("override_comment") or ""], "bold"))
    return [table("Commercial Real Estate Worksheet", ["Category", "Score", "Comments / Rationale"], rows, kind="grid",
                  footnote="Project Financial Criteria, Debt Service and Hard Cost Contingency are scored automatically from the analysis using anchors from "
                           "Invest Detroit's sample worksheet (full rubric not yet provided); other categories are underwriter inputs.")]


def build_cre_memo(deal, r, policy, naics, bench, risk) -> dict:
    t = deal.terms
    secs = [{"key": "header", "title": "", "blocks": [header(deal, policy)]}]
    if t.exposure:
        rows = [row([e.borrower, fmt_money(e.amount), e.fund or "", e.risk_rating or ""]) for e in t.exposure]
        rows.append(row(["Total Loans:", fmt_money(sum(e.amount for e in t.exposure)), "", ""], "total"))
        anc = any((e.status or "").lower().startswith("approved not closed") for e in t.exposure)
        secs.append(section("exposure", "Exposure Summary", [table(None, ["Borrower Debt", "Commitment Amount", "Fund", "Risk Rating"], rows, kind="grid",
                                                                   footnote="ANC = Approved Not Closed" if anc else None)]))
    secs.append(section("mission", "Mission Alignment", [qual(deal, "mission_alignment", "mission alignment")]))
    ov = [deal.profile.description] if deal.profile.description else []
    for k in ("deal_overview", "demand", "competition"):
        if t.qualitative.get(k):
            ov.append(t.qualitative[k])
    if deal.cre.lois:
        ov.append("The developers have signed LOIs with " + " and ".join(f"{l.tenant} ({(l.use or '').lower()})" for l in deal.cre.lois) +
                  f" to occupy {len(deal.cre.lois)} of the retail units.")
    secs.append(section("overview", "Deal Overview", [bullets(ov, "input")] if ov else [placeholder("deal overview")]))
    own = []
    groups = {}
    for pp in deal.profile.people:
        groups.setdefault(pp.ownership_via or "Direct", []).append(pp)
    for g, members in groups.items():
        tot = sum(m.ownership_pct or 0 for m in members)
        own.append(f"{g} - {tot * 100:.2f}%: " + "; ".join(f"{m.name} {m.ownership_pct * 100:.2f}%" + (" (passive)" if m.passive else "")
                                                       for m in members if m.ownership_pct is not None))
    ob = [bullets(own, "extracted")] if own else [placeholder("ownership structure")]
    if t.qualitative.get("ownership_note"):
        ob.append(p(t.qualitative["ownership_note"], "input"))
    secs.append(section("borrower", "Borrower", ob))
    secs.append(section("request", "Request", [p((t.request_summary or "Approval of the requested loan") + " - please see the Draft Term Sheet below for details.", "input")]))
    sr = []
    if t.qualitative.get("repayment_debt_service"):
        sr.append("Loan Debt Service Payments: " + t.qualitative["repayment_debt_service"])
    if t.qualitative.get("repayment_principal"):
        sr.append("Loan Principal: " + t.qualitative["repayment_principal"])
    secs.append(section("repayment", "Sources of Repayment", [bullets(sr, "input")] if sr else [placeholder("sources of repayment")]))
    secs.append(section("sources_uses", "Summary Sources and Uses of Funds", [sources_uses_table(r), su_bullets(deal, r)]))
    tbl, _ = projection_table(r, "base", "Projected Cash Flow and Debt Service - Source: Company Prepared; adjusted by Underwriter", deal)
    si = r["stabilized_index"]
    tail = []
    if r.get("sizing") and si is not None and r["dscr_base"][si] and r["dscr_base"][si] >= r["sizing"]["target_dscr"] - 0.005:
        tail.append(p("Base case above demonstrates that the projections would be well within the takeout lender's typical terms."))
    secs.append(section("cash_flow", "Projected Cash Flow and Debt Service", [tbl, numbered(cash_flow_notes(deal, r))] + tail))
    secs.append(section("rent_roll", "Rent Roll", [rent_roll_table(r)]))
    secs.append(leasing_section(deal, r))
    sens = r["sensitivity"]
    if sens:
        stbl, _ = projection_table(r, "sens", "Sensitivity Analysis", deal)
        line = r["labels"].get(sens["line"], sens["line"]).lower().replace("less: ", "").replace(" loss", "")
        kind = "construction loan" if deal.terms.product in ("construction_mini_perm", "predevelopment") else "loan"
        Line = line[0].upper() + line[1:]
        sb = [("Sensitized case assumes the loans are not refinanced by a take-out lender and the proposed " + kind + " remains.")
              if deal.terms.takeout_loan else "Sensitized case tests the proposed " + kind + " at 1.00x DSC."]
        lo, hi = sens["min_stabilized_pct"], sens["max_stabilized_pct"]
        si_ = r["stabilized_index"]
        cur = r["vacancy_by_line"].get(sens["line"])
        if lo is None:
            sb.append("No stabilized year has a full year of debt service on the proposed loan, so a break-even vacancy is not computed.")
        elif lo <= 0:
            sb.append(f"Even with no {line}, net operating income does not cover debt service on the proposed {kind} in every stabilized year "
                      "(DSC below 1.00x); repayment depends on other sources.")
        else:
            rng = f"{lo * 100:.1f}%" if abs(hi - lo) < 0.0005 else f"{lo * 100:.1f}% to {hi * 100:.1f}%"
            sb.append(f"{Line} was adjusted to get to 1.00x DSC. {Line} can increase to {rng} in the stabilized years for DSC to be 1.00x"
                      + (f" (projected: {cur * 100:.1f}%)." if cur is not None else "."))
            margin = lo - (cur or 0)
            sb.append(f"Sensitized case above demonstrates that the projections would generate more than enough cash flow to cover the debt service on "
                      f"the proposed {kind}." if margin > 0.30 else
                      f"The sensitized case shows limited cushion on the proposed {kind} ({margin * 100:.1f} points of additional {line} before DSC reaches 1.00x).")
        if r.get("break_even_occupancy"):
            sb.append(f"Break-even occupancy on the base case is {r['break_even_occupancy'] * 100:.1f}% of gross potential rent in {r['years'][si]}.")
        secs.append(section("sensitivity", "Sensitivity Analysis", [stbl, bullets(sb)]))
    secs.append(benchmarking_section(naics, bench, "cre"))
    team = [f"{m.name} - {m.role}. {m.description or ''}".strip() for m in deal.cre.development_team]
    secs.append(section("team", "Development Team (Developer, GC, Architect)", [bullets(team, "extracted")] if team else [placeholder("development team")]))
    secs.append(section("principals", "Principals/Management Team", [qual(deal, "principals", "principal bios")] +
                        [p(f"{pp.name}: {pp.bio}", "extracted") for pp in deal.profile.people if pp.bio]))
    secs.append(section("property_manager", "Property Manager", [qual(deal, "property_manager", "property manager")]))
    secs.append(section("status", "Development Status", [p(deal.cre.development_status, "extracted") if deal.cre.development_status else placeholder("development status")]))
    secs.append(section("collateral", "Collateral", collateral_tables(deal, r)))
    secs.append(compliance_section(policy))
    secs.append(term_sheet_section(deal, r, policy))
    secs.append(section("exhibit_c", "Exhibit C - Development Budget", [budget_exhibit(r)]))
    if risk:
        secs.append(section("risk_rating", "Appendix A - Risk Rating", risk_table(risk)))
    secs.append(documents_section(policy))
    return {"title": "Investment Summary", "deal_type": "cre", "sections": secs}
