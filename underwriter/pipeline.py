"""Orchestration: Deal -> analysis -> NAICS benchmark -> policy -> risk rating -> memo."""
from __future__ import annotations

from .engine.common import Flag, jsonable
from .engine.cre import analyze_cre
from .engine.policy import check_policy, risk_rating
from .engine.small_business import analyze_small_business
from .memo.common_sections import flags_section
from .memo.cre_memo import build_cre_memo
from .memo.small_business_memo import build_small_business_memo
from .naics import benchmarks as nb
from .schema import Deal


def analyze(deal: Deal) -> dict:
    naics = nb.identify(deal.profile, deal.terms.naics_code)
    flags: list[Flag] = list(naics["flags"])
    if deal.terms.deal_type == "small_business":
        r = analyze_small_business(deal)
        r["id_as_equity"] = deal.terms.options.treat_id_note_as_equity
        bench = nb.compare_small_business(r, naics["code"])
        policy = check_policy(deal, r, naics["code"])
        risk = None
        memo = build_small_business_memo(deal, r, policy, naics, bench)
    else:
        if deal.cre is None:
            raise ValueError("CRE deal has no CRE data (projections, rent roll, budget).")
        r = analyze_cre(deal)
        bench = nb.compare_cre(r, deal, naics["code"])
        policy = check_policy(deal, r, naics["code"])
        risk = risk_rating(deal, r, policy)
        memo = build_cre_memo(deal, r, policy, naics, bench, risk)
    flags += r["flags"] + bench.get("flags", [])
    for e in policy["exceptions"]:
        flags.append(Flag("warning", "policy", f"{e['kind'].title()} exception: {e['item']} — required {e['requirement']}, actual {e['actual']}."))
    if policy.get("startup"):
        flags.append(Flag("warning", "policy", policy["startup"]["message"]))
    miss = policy["documents"]["missing_required_before_screen"]
    if miss:
        flags.append(Flag("warning", "missing", "Required before deal screen but not received: " + "; ".join(miss) + "."))
    if deal.extraction_mode == "fixture":
        flags.append(Flag("info", "data_quality", "Extraction loaded from a hand-verified fixture (not live LLM extraction)."))
    memo["sections"].append(flags_section(flags))
    summary = _summary(deal, r, policy, naics, risk)
    return {"deal_id": deal.id, "deal_type": deal.terms.deal_type, "summary": summary, "memo": memo,
            "policy": policy, "naics": {k: v for k, v in naics.items() if k != "flags"}, "benchmark": bench, "risk_rating": risk,
            "flags": flags, "analysis": _public_analysis(r, deal)}


def _summary(deal, r, policy, naics, risk) -> dict:
    out = {"borrower": deal.terms.borrower_name, "deal_type": deal.terms.deal_type, "product": policy["product_label"],
           "naics": f"{naics.get('code')} {naics.get('title') or ''}".strip(),
           "exceptions": len(policy["exceptions"]), "oversight_council": policy["oversight_council_required"]}
    L = deal.terms.proposed_loan
    if L:
        out["loan_amount"] = L.amount
    if deal.terms.deal_type == "small_business":
        hist = r["hist"]
        if hist:
            last = [p for p in hist if r["income"][p]["months"] == 12][-1:] or hist[-1:]
            i = r["income"][last[0]]
            out.update({"latest_period": r["spread"].period(last[0]).label, "revenue": i["revenue"], "ebitda": i["ebitda"], "dscr": i["dscr"],
                        "dscr_ex_nonrecurring": i["dscr_ex_nonrecurring"]})
        if r.get("aggregate"):
            out["projected_dscr"] = r["aggregate"]["values"]["dscr"]
        out["ltv"] = r["collateral"]["ltv_gross"]
    else:
        si = r["stabilized_index"]
        if si is not None:
            out.update({"stabilized_year": r["years"][si], "noi": r["id"]["noi"][si], "dscr": r["dscr_base"][si],
                        "dscr_id_loan": r["dscr_proposed"][si]})
        out["ltv"] = r["collateral"]["ltv_gross"]
        out["ltc"] = r["sources_uses"]["ltc"]
        if risk:
            out["risk_rating"] = risk["final"]
    return out


def _public_analysis(r: dict, deal) -> dict:
    """Strip non-serializable objects (spread) and keep the numbers the UI needs."""
    out = {k: v for k, v in r.items() if k not in ("spread", "flags")}
    if "spread" in r:
        s = r["spread"]
        out["periods"] = [p.model_dump() for p in s.periods]
        out["spread_cells"] = {pid: {k: {"value": c.value, "sources": c.sources, "labels": c.labels} for k, c in cells.items()}
                               for pid, cells in s.cells.items()}
    return jsonable(out)
