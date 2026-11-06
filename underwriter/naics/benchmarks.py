"""NAICS identification and industry benchmarking (IRS SOI Table 5.1 aggregates).

- identify(): validates LLM-suggested codes against the official 2022 NAICS list, falls back to keyword
  scoring over the Census NAICS index (20k phrases) when no valid suggestion exists.
- compare_small_business(): borrower ratios vs. industry aggregates + realism checks on projections.
- compare_cre(): property metrics vs. lessor aggregates, guideline and appraisal benchmarks.

Thresholds for "too extreme" live in REALISM so the team can tune them with Invest Detroit.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Optional

from ..engine.common import Flag, fmt_pct, fmt_x, safe_div

CONFIG = Path(__file__).resolve().parents[2] / "config"

REALISM = {
    "growth_excess_pp": 0.10,        # projected growth more than industry growth + 10 pts -> flag
    "growth_abs_max": 0.25,          # or more than 25% in a year -> flag
    "margin_band_pp": 0.03,          # projected gross margin outside historical range +/- 3 pts -> flag
    "ratio_far_factor": 2.0,         # borrower ratio more than 2x / less than 0.5x industry -> note
}

STOP = set(("and or of the for in to a an with except other all nec products product services service operates operate operating "
            "provides provide providing offers offer sells sell selling company firm business full neighborhood local regional "
            "customers customer clients client based located detroit michigan new develops develop").split())


@lru_cache(maxsize=1)
def naics_data() -> dict:
    return json.loads((CONFIG / "naics_2022.json").read_text())


@lru_cache(maxsize=1)
def soi_data() -> dict:
    return json.loads((CONFIG / "irs_soi_benchmarks.json").read_text())


def title(code: str) -> Optional[str]:
    return naics_data()["codes"].get(str(code))


def _stem(w: str) -> str:
    for suf in ("ing", "ers", "er", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


ABBREV = {"it": "information technology computer", "hvac": "heating ventilation air conditioning", "cnc": "computer numerical control machining",
          "saas": "software publishers subscription", "pt": "physical therapy", "ev": "electric vehicle", "3pl": "third party logistics"}


def _clean_phrase(s: str) -> str:
    """Drop exclusion clauses: 'Delicatessens (except grocery store...)' must not match 'grocery store'."""
    s = re.sub(r"\((?:except|i\.e\.|e\.g\.)[^)]*\)", " ", s or "", flags=re.I)
    return re.split(r"\bexcept\b", s, flags=re.I)[0]


def _tokens(s: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", (s or "").lower())
    out = []
    for w in words:
        if w in ABBREV:
            out += ABBREV[w].split()
        elif w not in STOP and len(w) > 2 and not w.isdigit():
            out.append(w)
    return [_stem(w) for w in out]


@lru_cache(maxsize=1)
def _index():
    """code -> (token set over all index phrases + title, title tokens, example phrases); document frequency by code."""
    data = naics_data()
    by_code: dict[str, dict] = {}
    for code, phrase in data["index"]:
        e = by_code.setdefault(code, {"tokens": set(), "phrases": [], "bigrams": set()})
        tk = _tokens(_clean_phrase(phrase))
        e["tokens"] |= set(tk)
        e["bigrams"] |= set(zip(tk, tk[1:]))
        e["phrases"].append(phrase)
    for code, e in by_code.items():
        e["title_tokens"] = set(_tokens(data["codes"].get(code, "")))
        e["tokens"] |= e["title_tokens"]
    df = Counter()
    for e in by_code.values():
        df.update(e["tokens"])
    return by_code, df, len(by_code)


PLACES = ["Detroit", "Michigan", "Wayne County", "Corktown", "Midtown", "Downtown", "New Center", "Brush Park", "Palmer Park",
          "Rosedale Park", "Indian Village", "Lafayette Park", "Belle Isle", "Eastern Market", "Mexicantown", "Southwest", "Delray",
          "North End", "Eastside", "Westside", "Brightmoor", "Osborn", "Jefferson", "Chalmers", "Woodward", "Gratiot", "Livernois",
          "Grand River", "Michigan Avenue", "Fenkell", "Conant", "Hamtramck", "Highland Park", "Dearborn", "Riverbend", "Rouge Park",
          "Lakeview", "Avenue of Fashion", "University District", "Boston Edison", "Virginia Park", "Islandview", "Jefferson Chalmers"]
SUFFIXES = r"\b(llc|l\.l\.c\.|inc|incorporated|co|company|corp|corporation|group|holdings|enterprises|ltd|pllc|pc)\b\.?"


def keyword_candidates(text: str, k: int = 5, exclude: str = "") -> list[dict]:
    """Rank NAICS codes for a business description. Detroit place names and corporate suffixes are removed first
    (e.g. 'Brush Park' must not match 'aircraft parking'); industry words in a business name are kept."""
    import math
    by_code, df, N = _index()
    for place in sorted(PLACES, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(place)}\b", " ", text, flags=re.I)
    text = re.sub(SUFFIXES, " ", text, flags=re.I)
    qt = _tokens(text)
    q = set(qt)
    qb = set(zip(qt, qt[1:]))
    if not q:
        return []
    scored = []
    for code, e in by_code.items():
        common = q & e["tokens"]
        if not common or (len(common) < 2 and len(q) > 2 and not (common & e["title_tokens"])):
            continue
        s = sum(math.log(N / df[w]) * (1.6 if w in e["title_tokens"] else 1.0) for w in common)
        s += 2.5 * len(qb & e["bigrams"])
        s /= math.log(len(e["tokens"]) + 8)
        if s > 0:
            best = max(e["phrases"], key=lambda ph: len(q & set(_tokens(ph))))
            scored.append((s, code, best))
    scored.sort(reverse=True)
    top = scored[0][0] if scored else 1
    return [{"code": c, "title": title(c), "matched_phrase": ph, "score": round(s / top, 3),
             "source": "keyword match (Census NAICS index)"} for s, c, ph in scored[:k]]


def identify(profile, override: Optional[str] = None) -> dict:
    """Return {'code', 'title', 'source', 'candidates', 'flags'}."""
    flags = []
    cands = []
    for g in getattr(profile, "naics_suggestions", []) or []:
        t = title(g.code)
        if t is None:
            flags.append(Flag("warning", "naics", f"Suggested NAICS {g.code} is not a valid 2022 NAICS code; ignored."))
            continue
        cands.append({"code": g.code, "title": t, "rationale": g.rationale, "score": g.confidence,
                      "source": "document analysis (LLM)"})
    text = " ".join(filter(None, [profile.description, " ".join(profile.products_services or [])]))
    kw = keyword_candidates(text) if text else []
    if override:
        if title(override) is None:
            flags.append(Flag("warning", "naics", f"NAICS override {override} is not a valid 2022 NAICS code."))
        else:
            return {"code": override, "title": title(override), "source": "underwriter override", "candidates": cands + kw, "flags": flags}
    if cands:
        best = max(cands, key=lambda c: c.get("score") or 0)
        if kw and not any(k["code"][:4] == best["code"][:4] for k in kw[:3]):
            flags.append(Flag("info", "naics", f"Keyword matching suggests {kw[0]['code']} ({kw[0]['title']}); "
                                               f"document analysis chose {best['code']}. Confirm the code."))
        return {"code": best["code"], "title": best["title"], "source": best["source"], "candidates": cands + kw, "flags": flags}
    if kw:
        flags.append(Flag("warning", "naics", f"NAICS inferred by keyword only ({kw[0]['code']}); confirm with the borrower."))
        return {"code": kw[0]["code"], "title": kw[0]["title"], "source": kw[0]["source"], "candidates": kw, "flags": flags}
    return {"code": None, "title": None, "source": None, "candidates": [], "flags": flags +
            [Flag("warning", "naics", "Could not determine a NAICS code; benchmarking skipped.")]}


def industry_for(code: Optional[str]) -> Optional[dict]:
    if not code:
        return None
    best, blen = None, 0
    for ind in soi_data()["industries"]:
        for p in ind["naics_prefixes"]:
            if str(code).startswith(p) and len(p) > blen:
                best, blen = ind, len(p)
    return best


def _latest(ind: dict) -> tuple[str, dict]:
    y = max(ind["years"])
    return y, ind["years"][y]


def _assess(name, borrower, bench, higher_is_better: Optional[bool], fmt):
    if borrower is None or bench is None:
        return None
    ratio = safe_div(borrower, bench)
    if higher_is_better is None or ratio is None:
        verdict = "n/a"
    elif abs(borrower - bench) <= abs(bench) * 0.15:
        verdict = "in line"
    elif (borrower > bench) == higher_is_better:
        verdict = "favorable"
    else:
        verdict = "unfavorable"
    return {"metric": name, "borrower": borrower, "industry": bench, "verdict": verdict, "fmt": fmt}


def growth_limit(ind_avg: Optional[float]) -> float:
    """Projected annual revenue growth above this is flagged: the lower of 25% or industry average + 10 points."""
    if ind_avg is None:
        return REALISM["growth_abs_max"]
    return min(REALISM["growth_abs_max"], max(ind_avg + REALISM["growth_excess_pp"], 0.0))


def compare_small_business(analysis: dict, code: Optional[str]) -> dict:
    flags: list[Flag] = []
    ind = industry_for(code)
    if ind is None:
        return {"industry": None, "metrics": [], "realism": [], "flags": [Flag("info", "benchmark", "No industry benchmark available for this NAICS code.")]}
    year, b = _latest(ind)
    inc, rat = analysis["income"], analysis["ratios"]
    annual = [p for p in analysis["hist"] if inc[p]["months"] == 12]
    last = annual[-1] if annual else None
    metrics = []
    if last:
        i, r = inc[last], rat.get(last, {})
        bs = analysis["balance_sheet"].get(last)
        inv_days_cogs = safe_div(bs["current_assets"]["inventory"] * 360, i["cogs"]) if bs else None
        rows = [
            ("Gross margin", safe_div(i["gross_profit"], i["revenue"]), b["gross_margin"], True, "pct"),
            ("Net margin", safe_div(i["net_income"], i["revenue"]), b["net_margin"], True, "pct"),
            ("EBITDA margin", safe_div(i["ebitda"], i["revenue"]), b["ebitda_margin"], True, "pct"),
            ("EBITDA / interest", r.get("interest_coverage"), b["interest_coverage_ebitda"], True, "x"),
            ("Current ratio", r.get("current_ratio"), b["current_ratio"], True, "x"),
            ("Quick ratio", r.get("quick_ratio"), b["quick_ratio"], True, "x"),
            ("A/R days (360)", r.get("ar_days"), b["ar_days_360"], False, "days"),
            ("Inventory days (on COGS, 360)", inv_days_cogs, b["inventory_days_cogs_360"], False, "days"),
            ("A/P days (360)", r.get("ap_days"), b["ap_days_cogs_360"], None, "days"),
            ("Debt / worth", r.get("debt_to_worth"), b["debt_to_worth"], False, "x"),
            ("Sales / total assets", r.get("sales_to_assets"), b["sales_to_assets"], True, "x"),
            ("Officer compensation / sales", safe_div(i.get("officer_compensation"), i["revenue"]) if i.get("officer_compensation") else None,
             b["officer_comp_pct_sales"], None, "pct"),
        ]
        metrics = [m for m in (_assess(*row) for row in rows) if m]
    # growth comparison
    growth = []
    ig = ind.get("receipts_growth", {})
    for g in analysis.get("growth", []):
        growth.append({"label": f"{g['from']} to {g['to']}", "borrower": g["pct"]})
    realism = []
    agg = analysis.get("aggregate")
    ind_growth = list(ig.values())
    ind_avg = sum(ind_growth) / len(ind_growth) if ind_growth else None
    if agg and agg["values"].get("growth_vs_prior") is not None:
        pg = agg["values"]["growth_vs_prior"]
        extreme = pg > growth_limit(ind_avg)
        realism.append({"check": "Projected revenue growth", "projected": pg, "benchmark": ind_avg,
                        "benchmark_label": f"industry receipts growth avg {', '.join(ig.keys())}",
                        "result": "flag" if extreme else "reasonable"})
        if extreme:
            flags.append(Flag("warning", "benchmark", f"Projected revenue growth {fmt_pct(pg)} exceeds the realism limit "
                                                      f"(industry avg {fmt_pct(ind_avg)} + {REALISM['growth_excess_pp'] * 100:.0f} pts, max {fmt_pct(REALISM['growth_abs_max'], 0)})."))
        gms = [safe_div(inc[p]["gross_profit"], inc[p]["revenue"]) for p in annual]
        pgm = safe_div(agg["values"]["gross_profit"], agg["values"]["revenue"])
        lo, hi = min(gms) - REALISM["margin_band_pp"], max(gms) + REALISM["margin_band_pp"]
        ok = lo <= pgm <= hi
        realism.append({"check": "Projected gross margin vs history", "projected": pgm, "benchmark": (min(gms), max(gms)),
                        "benchmark_label": "historical range", "result": "reasonable" if ok else "flag",
                        "industry": b["gross_margin"]})
        if not ok:
            flags.append(Flag("warning", "benchmark", f"Projected gross margin {fmt_pct(pgm)} is outside the historical range {fmt_pct(min(gms))}-{fmt_pct(max(gms))}."))
        if pgm is not None and b["gross_margin"] and pgm > b["gross_margin"] * 1.3:
            flags.append(Flag("warning", "benchmark", f"Projected gross margin {fmt_pct(pgm)} is well above the industry aggregate {fmt_pct(b['gross_margin'])}."))
    # annual projection periods (e.g. start-up 3-year forecasts)
    prev = annual[-1] if annual else None
    s = analysis["spread"]
    for p in s.periods:
        if p.kind != "projection" or p.months != 12 or p.id not in inc or prev is None:
            continue
        pg = safe_div(inc[p.id]["revenue"] - inc[prev]["revenue"], inc[prev]["revenue"])
        if pg is not None:
            limit = growth_limit(ind_avg)
            extreme = pg > limit
            realism.append({"check": f"Projected revenue growth ({p.label})", "projected": pg, "benchmark": ind_avg,
                            "benchmark_label": f"industry receipts growth avg {', '.join(ig.keys())}", "result": "flag" if extreme else "reasonable"})
            if extreme:
                flags.append(Flag("warning", "benchmark", f"Projected revenue growth {fmt_pct(pg)} for {p.label} exceeds the realism limit of {fmt_pct(limit)} "
                                                          f"(lower of {fmt_pct(REALISM['growth_abs_max'], 0)} or industry average {fmt_pct(ind_avg)} + "
                                                          f"{REALISM['growth_excess_pp'] * 100:.0f} pts)."))
        prev = p.id
    for m in metrics:
        if m["verdict"] == "unfavorable" and m["industry"] and m["borrower"] is not None:
            far = m["borrower"] / m["industry"] if m["industry"] else None
            if far and (far >= REALISM["ratio_far_factor"] or far <= 1 / REALISM["ratio_far_factor"]):
                flags.append(Flag("info", "benchmark", f"{m['metric']} is far from the industry aggregate ({_f(m['borrower'], m['fmt'])} vs {_f(m['industry'], m['fmt'])})."))
    return {"industry": {"label": ind["label"], "sector": ind["sector"], "year": year, "returns": b.get("returns"),
                         "receipts_growth": ig, "prefixes": ind["naics_prefixes"], "is_sector_total": ind["is_sector_total"]},
            "metrics": metrics, "growth": growth, "realism": realism, "flags": flags, "source": soi_data()["meta"]}


def compare_cre(analysis: dict, deal, code: Optional[str]) -> dict:
    from ..guidelines import load_guidelines
    A = load_guidelines()["cre_underwriting_assumptions"]
    flags: list[Flag] = []
    ind = industry_for(code)
    metrics, realism = [], []
    si = analysis.get("stabilized_index")
    if si is None:
        return {"industry": None, "metrics": [], "realism": [], "flags": flags}
    rev, exp, noi = analysis["id"]["revenue"][si], analysis["id"]["expenses"][si], analysis["id"]["noi"][si]
    yr = analysis["years"][si]
    if ind:
        y, b = _latest(ind)
        opex_ratio_ind = 1 - b["ebitda_margin"] if b.get("ebitda_margin") is not None else None
        metrics.append(_assess("Operating expense ratio (stabilized)", safe_div(exp, rev), opex_ratio_ind, False, "pct"))
        metrics.append(_assess("NOI margin (stabilized)", safe_div(noi, rev), b.get("ebitda_margin"), True, "pct"))
    # vacancy realism
    blended = analysis["blended_vacancy"][si]
    ap = deal.cre.appraisal
    realism.append({"check": f"Stabilized blended vacancy ({yr})", "projected": blended, "benchmark": A["commercial_vacancy_min"],
                    "benchmark_label": "guideline commercial vacancy", "appraisal": ap.vacancy_estimate,
                    "result": "reasonable" if blended is not None and blended >= A["commercial_vacancy_min"] - 1e-9 else "flag"})
    for k, gr in analysis.get("rent_cagr", {}).items():
        if gr is not None:
            realism.append({"check": f"Rent growth ({analysis['labels'].get(k, k)})", "projected": gr, "benchmark": A["rent_growth_max"],
                            "benchmark_label": "guideline max", "result": "reasonable" if gr <= A["rent_growth_max"] + 5e-4 else "flag"})
    eg = [v for v in analysis.get("expense_cagr", {}).values() if v is not None]
    if eg:
        realism.append({"check": "Expense growth (min across lines)", "projected": min(eg), "benchmark": A["expense_growth_min"],
                        "benchmark_label": "guideline min", "result": "reasonable" if min(eg) >= A["expense_growth_min"] - 1e-4 else "flag"})
    for m in analysis["rent_roll"]["market"]:
        res = "reasonable" if (m["premium"] or 0) <= 0.10 else "flag"
        realism.append({"check": f"{m['use'].title()} rent vs appraisal market", "projected": m["avg_psf"], "benchmark": m["market_psf"],
                        "benchmark_label": "appraiser market rent $/SF", "result": res, "premium": m["premium"], "fmt": "psf"})
        if res == "flag":
            flags.append(Flag("warning", "benchmark", f"Projected {m['use']} rent ${m['avg_psf']:.2f}/SF is {fmt_pct(m['premium'])} above the appraiser's market rent of ${m['market_psf']:.2f}/SF."))
    sens = analysis.get("sensitivity")
    if sens and sens.get("min_stabilized_pct") is not None:
        realism.append({"check": "Break-even vacancy on the sensitized line", "projected": sens["min_stabilized_pct"],
                        "benchmark": ap.vacancy_estimate, "benchmark_label": "appraiser vacancy", "result": "cushion"})
    return {"industry": ({"label": ind["label"], "sector": ind["sector"], "year": _latest(ind)[0], "returns": _latest(ind)[1].get("returns"),
                          "prefixes": ind["naics_prefixes"], "is_sector_total": ind["is_sector_total"]} if ind else None),
            "metrics": [m for m in metrics if m], "realism": realism, "flags": flags, "source": soi_data()["meta"]}


def _f(v, fmt):
    if v is None:
        return "n/a"
    return {"pct": fmt_pct(v), "x": fmt_x(v), "days": f"{v:.0f} days", "psf": f"${v:,.2f}/SF"}.get(fmt, f"{v:,.2f}")
