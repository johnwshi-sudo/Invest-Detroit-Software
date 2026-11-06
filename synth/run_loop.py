"""Generate all synthetic cases, run the underwriting pipeline, score against the oracle.

    python -m synth.run_loop            # score all scenarios, print summary, write synth/out/results.json
    python -m synth.run_loop --round 3  # also append a round entry to docs/test-loop-log.md
"""
from __future__ import annotations

import argparse
import copy
import io
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from underwriter.memo.docx_export import render_docx  # noqa: E402
from underwriter.pipeline import analyze  # noqa: E402
from underwriter.schema import Deal  # noqa: E402

from .oracle import counted, expected  # noqa: E402
from .scenarios import SCENARIOS  # noqa: E402
from .to_deal import build_case  # noqa: E402

OUT = ROOT / "synth" / "out"


class Score:
    def __init__(self, sid):
        self.sid = sid
        self.checks = []   # (category, name, ok, detail)

    def num(self, cat, name, exp, act, tol_abs=None, tol_rel=None):
        if exp is None and act is None:
            ok = True
        elif exp is None or act is None:
            ok = False
        else:
            tol = max(tol_abs or 0, abs(exp) * (tol_rel or 0))
            ok = abs(exp - act) <= tol
        self.checks.append((cat, name, ok, f"expected {_f(exp)} got {_f(act)}"))

    def flag(self, cat, name, ok, detail=""):
        self.checks.append((cat, name, bool(ok), detail))


def _f(v):
    if v is None:
        return "None"
    if isinstance(v, float) and abs(v) < 50:
        return f"{v:.4f}"
    if isinstance(v, (int, float)):
        return f"{v:,.0f}"
    return str(v)


MONEY_TOL = 3.0


def score_sb(spec, deal, pres, exp, out, sc: Score):
    A = out["analysis"]
    inc = A["income"]
    unit = pres["unit"]
    mt = max(MONEY_TOL, unit)
    for pid, e in exp["income"].items():
        a = inc.get(pid)
        if a is None:
            sc.flag("income", f"{pid} present", False, "period missing")
            continue
        sc.num("income", f"{pid} EBITDA", e["ebitda"], a["ebitda"], mt)
        sc.num("income", f"{pid} debt service", e["debt_service"], a["debt_service"], mt)
        sc.num("dscr", f"{pid} DSCR", e["dscr"], a["dscr"], 0.0005)
        sc.num("dscr", f"{pid} DSCR ex non-recurring", e["dscr_ex_nonrecurring"], a["dscr_ex_nonrecurring"], 0.0005)
        sc.num("income", f"{pid} CFADS", e["cfads"], a["cfads"], mt)
    for pid, e in exp["ratios"].items():
        a = A["ratios"].get(pid, {})
        for k, v in e.items():
            if k in ("working_capital", "net_worth", "ebitda_less_distributions"):
                sc.num("ratios", f"{pid} {k}", v, a.get(k), mt)
            else:
                sc.num("ratios", f"{pid} {k}", v, a.get(k), 0.0005, 0.0005)
    for pid, e in exp["break_even"].items():
        a = A["break_even"].get(pid)
        sc.num("break_even", f"{pid} break-even sales", e["revenue"], a and a["revenue"], mt)
    for i, g in enumerate(exp["growth"]):
        sc.num("growth", f"growth {i}", g, A["growth"][i]["pct"] if i < len(A["growth"]) else None, 0.0001)
    if exp["aggregate"]:
        ag = A.get("aggregate")
        sc.flag("projection", "full-year forecast column built", ag is not None)
        if ag:
            sc.num("projection", "aggregate EBITDA", exp["aggregate"]["ebitda"], ag["values"]["ebitda"], mt)
            sc.num("projection", "aggregate DSCR", exp["aggregate"]["dscr"], ag["values"]["dscr"], 0.0005)
    fl = " | ".join(f.message for f in out["flags"])
    from .oracle import growth_limit
    lim = growth_limit(spec["naics"])
    big = [g for _, g in exp["projection_growth"] if g is not None and g > lim]
    if exp["aggregate"] and exp["aggregate"]["growth_vs_prior"] and exp["aggregate"]["growth_vs_prior"] > lim:
        big.append(exp["aggregate"]["growth_vs_prior"])
    sc.flag("realism", "aggressive projection flagged" if big else "no false projection-growth flag",
            ("Projected revenue growth" in fl) == bool(big), f"oracle growth {big}")
    sc.flag("policy", "line of business", out["policy"]["line_of_business"]["line"] == exp["line_of_business"],
            f"expected {exp['line_of_business']} got {out['policy']['line_of_business']['line']}")
    sc.flag("policy", "start-up rules applied" if exp["startup"] else "no false start-up flag",
            ("start-up" in fl.lower()) == exp["startup"])
    if spec["quirks"].get("split_docs"):
        sc.flag("consistency", "restated year flagged", "differs between documents" in fl)
    _common(spec, deal, exp, out, sc)


def score_cre(spec, deal, pres, exp, out, sc: Score):
    A = out["analysis"]
    n = len(exp["years"])
    tol = 15.0
    for i, y in enumerate(exp["years"]):
        sc.num("cre_noi", f"{y} revenue", exp["revenue"][i], A["id"]["revenue"][i], tol, 0.0002)
        sc.num("cre_noi", f"{y} expenses", exp["expenses"][i], A["id"]["expenses"][i], tol, 0.0002)
        sc.num("cre_noi", f"{y} NOI", exp["noi"][i], A["id"]["noi"][i], tol, 0.0002)
        sc.num("cre_ds", f"{y} base debt service", exp["ds_base"][i], A["ds_base"][i], 2)
        sc.num("dscr", f"{y} base DSCR", exp["dscr_base"][i], A["dscr_base"][i], 0.002)
        sc.num("dscr", f"{y} ID-loan DSCR", exp["dscr_prop"][i], A["dscr_proposed"][i], 0.002)
        if exp["sens_pct"][i] is not None:
            s = A.get("sensitivity") or {}
            sc.num("sensitivity", f"{y} break-even vacancy", exp["sens_pct"][i], (s.get("pct") or [None] * n)[i], 0.002)
    sc.flag("cre_ds", "stabilized year", exp["stab"] == A["stabilized_index"], f"expected {exp['stab']} got {A['stabilized_index']}")
    s = A.get("sensitivity") or {}
    sc.flag("sensitivity", "sensitized line", s.get("line") == exp["sens_line"], f"expected {exp['sens_line']} got {s.get('line')}")
    su = A["sources_uses"]
    sc.num("sources_uses", "total uses", exp["su"]["total_uses"], su["total_uses"], 1)
    for k, ak in (("ltc", "ltc"), ("equity_pct", "equity_pct"), ("hard_pct", "hard_contingency_pct"), ("soft_pct", "soft_contingency_pct"), ("cost_psf", "total_cost_psf")):
        sc.num("sources_uses", k, exp["su"][k], su.get(ak), 0.0005, 0.0005)
    sc.num("collateral", "LTV", exp["ltv"], A["collateral"]["ltv_gross"], 0.0005)
    rk = out.get("risk_rating") or {"rows": []}
    auto = {r["key"]: r["auto_score"] for r in rk["rows"]}
    for k, v in exp["risk"].items():
        sc.flag("risk", f"auto score {k}", auto.get(k) == v, f"expected {v} got {auto.get(k)}")
    _common(spec, deal, exp, out, sc)


def _common(spec, deal, exp, out, sc: Score):
    pol = out["policy"]
    got = {e["item"] for e in pol["exceptions"]}
    missing, extra = exp["exceptions"] - got, got - exp["exceptions"]
    sc.flag("policy", "exception list", not missing and not extra, f"missing {sorted(missing)} extra {sorted(extra)}")
    sc.flag("policy", "Oversight Council trigger", pol["oversight_council_required"] == (counted(exp["exceptions"]) > 3),
            f"expected {counted(exp['exceptions']) > 3}")
    code = out["naics"]["code"]
    sc.flag("naics", "NAICS code", code == spec["naics"] or (spec["quirks"].get("no_naics_hint") if spec["kind"] == "small_business" else False) and code and code[:4] == spec["naics"][:4],
            f"expected {spec['naics']} got {code}")
    memo_qa(spec, deal, exp, out, sc)


NUM_RE = re.compile(r"(\(?-?\$[\d,]+(?:\.\d+)?[MK]?\)?|-?[\d,]*\.?\d+%|-?\d+\.\d+x|\b\d{1,3}(?:,\d{3})+\b)")


def _pool(*objs):
    vals = []
    def walk(o):
        if isinstance(o, bool):
            return
        if isinstance(o, (int, float)):
            vals.append(float(o))
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)
        elif isinstance(o, str):
            for m in re.findall(r"[\d,]+\.?\d*", o):
                try:
                    vals.append(float(m.replace(",", "")))
                except ValueError:
                    pass
    for o in objs:
        walk(o)
    return vals


def _token_ok(tok, pool):
    t = tok.strip("()")
    neg = tok.startswith("(") or "-" in t
    t = t.replace("-", "").replace("$", "").replace(",", "")
    if t.endswith("%"):
        x = float(t[:-1]) / 100
        dp = len(t[:-1].split(".")[1]) if "." in t else 0
        tol = 0.5 * 10 ** -dp / 100 + 1e-9
        return any(abs(abs(v) - x) <= tol for v in pool)
    if t.endswith("x"):
        x = float(t[:-1])
        dp = len(t[:-1].split(".")[1])
        return any(abs(abs(v) - x) <= 0.5 * 10 ** -dp + 1e-9 for v in pool)
    mult = 1
    if t.endswith("M"):
        mult, t = 1e6, t[:-1]
    elif t.endswith("K"):
        mult, t = 1e3, t[:-1]
    x = float(t) * mult
    dp = len(t.split(".")[1]) if "." in t else 0
    tol = 0.5 * 10 ** -dp * mult + 0.5
    return any(abs(abs(v) - x) <= tol for v in pool)


def memo_qa(spec, deal, exp, out, sc: Score):
    from underwriter.guidelines import load_guidelines
    pool = _pool(out["analysis"], out["policy"], out["summary"], out["benchmark"], out.get("risk_rating"), deal, load_guidelines())
    pool += [abs(v) * 100 for v in pool if abs(v) < 5]  # values that templates print as whole percents
    bad, n_tok = [], 0
    texts = []
    for s in out["memo"]["sections"]:
        if s["key"] in ("review_flags", "compliance", "benchmarking", "documents", "term_sheet"):
            continue
        for b in s["blocks"]:
            if b["type"] == "p" and b.get("source") == "computed":
                texts.append(b["text"])
            elif b["type"] in ("bullets", "numbered") and b.get("source") == "computed":
                texts += b["items"]
    for tx in texts:
        for tok in NUM_RE.findall(tx):
            if re.fullmatch(r"\d{4}", tok.replace(",", "")):
                continue
            n_tok += 1
            if not _token_ok(tok, pool):
                bad.append(tok)
    sc.flag("memo", "every number in computed narrative traces to a value", not bad, f"{n_tok} numbers; untraceable: {bad[:8]}")
    joined = " ".join(texts)
    sc.flag("memo", "no negative 'decline' wording", not re.search(r"decline -|decline \(-", joined), "")
    sc.flag("memo", "no '-0.0%' / NaN artifacts", "-0.0%" not in joined and not re.search(r"\bnan\b|\bNone\b(?! identified)", joined), "")
    # direction words in revenue sentences match the numbers stated
    for m in re.finditer(r"(increased|decreased) ([\d.]+)%, from \$([\d.]+)M .*? to \$([\d.]+)M", joined):
        word, pct, a, b = m.group(1), float(m.group(2)), float(m.group(3)), float(m.group(4))
        ok = (b >= a) == (word == "increased") and abs(abs(b - a) / a * 100 - pct) < 0.2
        sc.flag("memo", f"revenue sentence consistent ({word} {pct}%)", ok, m.group(0)[:90])
    if "Net worth increased each year" in joined and spec["kind"] == "small_business":
        nw = [out["analysis"]["ratios"][p]["net_worth"] for p in out["analysis"]["bs_periods"]]
        sc.flag("memo", "'net worth increased each year' is true", all(b >= a for a, b in zip(nw, nw[1:])), str(nw))
    if "is improving" in joined and spec["kind"] == "small_business":
        lev = [out["analysis"]["ratios"][p]["debt_to_worth"] for p in out["analysis"]["bs_periods"]]
        sc.flag("memo", "'leverage improving' is true", lev[-1] < lev[0], str(lev))
    hdr = out["memo"]["sections"][0]["blocks"][0]
    pol_items = {e["item"] for e in out["policy"]["exceptions"] if e["kind"] == "policy"}
    sc.flag("memo", "page-1 policy exceptions match", set(hdr["policy_exceptions"]) - {"None identified"} == pol_items, str(hdr["policy_exceptions"]))
    gl = [e for e in out["policy"]["exceptions"] if e["kind"] == "guideline"]
    sc.flag("memo", "page-1 guideline exceptions match", len([x for x in hdr["guideline_exceptions"] if x != "None identified"]) == len(gl), "")
    try:
        from docx import Document
        d = Document(io.BytesIO(render_docx(out["memo"], spec["name"])))
        txt = "\n".join(p.text for p in d.paragraphs) + "\n".join(c.text for t_ in d.tables for r_ in t_.rows for c in r_.cells)
        sc.flag("export", "Word export opens and names borrower", spec["name"] in txt and len(d.tables) >= 5, f"{len(d.tables)} tables")
    except Exception as e:  # noqa: BLE001
        sc.flag("export", "Word export", False, str(e))


def misread_test(spec, deal, rng) -> tuple[bool, str] | None:
    """Corrupt one digit of a statement line; the tool should raise a consistency flag for that period."""
    if spec["kind"] != "small_business":
        return None
    d = copy.deepcopy(deal)
    fs = d["financials"][-1] if spec["quirks"].get("assurance") != "tax_return" else d["financials"][-1]
    cands = [li for li in fs["line_items"] if li["key"] in ("revenue", "cogs", "operating_expenses", "cash", "accounts_receivable",
                                                             "inventory", "accounts_payable", "accrued_expenses", "line_of_credit",
                                                             "other_income", "interest_expense", "fixed_assets_gross") and abs(li["value"]) >= 1000]
    li = rng.choice(cands)
    s = str(int(abs(li["value"])))
    pos = rng.randrange(0, max(1, len(s) - 2))
    new = s[:pos] + str((int(s[pos]) + rng.choice([1, 2, 3, 5])) % 10) + s[pos + 1:]
    li["value"] = float(new) * (1 if li["value"] >= 0 else -1)
    out = analyze(Deal.model_validate(d))
    hit = any(f.category == "consistency" and li["period_id"] in (f.message + (f.ref or "")) for f in out["flags"])
    return hit, f"{li['period_id']} {li['key']} {s}->{new}"


def run(round_no=None, only=None, verbose=False):
    OUT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(42)
    all_scores, misreads, errors = [], [], []
    for spec in SCENARIOS:
        if only and spec["id"] not in only:
            continue
        deal_json, pres, truth, _ = build_case(spec)
        (OUT / f"{spec['id']}.deal.json").write_text(json.dumps(deal_json, indent=1))
        sc = Score(spec["id"])
        try:
            deal = Deal.model_validate(deal_json)
            out = analyze(deal)
            exp = expected(spec, deal_json, pres)
            (score_sb if spec["kind"] == "small_business" else score_cre)(spec, deal_json, pres, exp, out, sc)
            mr = misread_test(spec, deal_json, rng)
            if mr:
                misreads.append((spec["id"], *mr))
        except Exception as e:  # noqa: BLE001
            import traceback
            errors.append((spec["id"], traceback.format_exc(limit=6)))
            sc.flag("crash", "pipeline ran", False, repr(e))
        all_scores.append(sc)
    # summary
    by_cat = defaultdict(lambda: [0, 0])
    fails = []
    for sc in all_scores:
        for cat, name, ok, det in sc.checks:
            by_cat[cat][0] += ok
            by_cat[cat][1] += 1
            if not ok:
                fails.append((sc.sid, cat, name, det))
    total_ok = sum(v[0] for v in by_cat.values())
    total = sum(v[1] for v in by_cat.values())
    mr_hit = sum(1 for m in misreads if m[1])
    res = {"total": total, "passed": total_ok, "by_category": {k: v for k, v in sorted(by_cat.items())},
           "misread_detection": [mr_hit, len(misreads)], "misreads": misreads, "failures": fails, "errors": errors,
           "scenarios": len(all_scores)}
    (OUT / "results.json").write_text(json.dumps(res, indent=1, default=str))
    print(f"{len(all_scores)} scenarios, {total} checks: {total_ok} passed ({total_ok / max(total, 1):.1%}); "
          f"misread detection {mr_hit}/{len(misreads)}")
    for k, (o, t) in sorted(by_cat.items()):
        print(f"  {k:14s} {o:4d}/{t:<4d} {'' if o == t else '<-- ' + str(t - o) + ' failing'}")
    for e in errors:
        print("ERROR", e[0], e[1][-600:])
    shown = Counter()
    for sid, cat, name, det in fails:
        shown[(cat, name.split(" ", 1)[-1] if cat != "policy" else name)] += 1
    if fails:
        print("Failures (first 60):")
        for f in fails[: (len(fails) if verbose else 60)]:
            print("  ", f)
    for m in misreads:
        if not m[1]:
            print("  misread NOT caught:", m[0], m[2])
    if round_no is not None:
        append_log(round_no, res)
    return res


def append_log(round_no, res):
    log = ROOT / "docs" / "test-loop-log.md"
    lines = [f"\n### Round {round_no}", f"- {res['scenarios']} scenarios, {res['total']} checks, **{res['passed']} passed "
             f"({res['passed'] / max(res['total'], 1):.1%})**; misread detection {res['misread_detection'][0]}/{res['misread_detection'][1]}",
             "- by category: " + ", ".join(f"{k} {o}/{t}" for k, (o, t) in res["by_category"].items())]
    if res["failures"]:
        cats = Counter(f[1] for f in res["failures"])
        lines.append("- failing: " + ", ".join(f"{k} ({v})" for k, v in cats.items()))
    log.write_text(log.read_text() + "\n".join(lines) + "\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("-v", action="store_true")
    a = ap.parse_args()
    run(a.round, a.only, a.v)
