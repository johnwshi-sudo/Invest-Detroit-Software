"""Field-by-field comparison of the engine's output against Invest Detroit's sample Investment Summaries.

Requires the gitignored sample fixtures (samples/fixtures/*.json + expected_values.py).
Writes samples/validation_report.md (contains borrower figures — keep it out of git) and prints a summary.

    python scripts/validate_samples.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIX = ROOT / "samples" / "fixtures"

from underwriter.pipeline import analyze  # noqa: E402
from underwriter.schema import Deal  # noqa: E402


def _load_expected():
    spec = importlib.util.spec_from_file_location("expected_values", FIX / "expected_values.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _decimals(v) -> int:
    d = Decimal(repr(v)).as_tuple().exponent
    return max(0, -d)


class Report:
    def __init__(self, known: dict):
        self.rows = []
        self.known = known

    def cmp(self, key: str, expected, actual, money: bool = False):
        status = None
        if expected is None and actual is None:
            status = "exact"
        elif expected is None or actual is None:
            status = "DIFF"
        elif money or isinstance(expected, int):
            diff = actual - expected
            status = "exact" if abs(diff) <= 0.5 else "rounding (±$1)" if abs(diff) <= 1.5 else \
                "very close (<0.01%)" if abs(diff) <= max(1.5, abs(expected) * 0.0001) else "DIFF"
        else:
            dp = _decimals(expected)
            unit = 10 ** -dp
            diff = round(actual, dp) - expected
            status = "exact" if abs(diff) < unit / 2 else "rounding" if abs(diff) <= unit * 1.01 else "DIFF"
        kk = next((k for k in self.known if key == k or key.startswith(k + ".")), None)
        if status == "DIFF" and kk:
            status = "explained"
        self.rows.append((key, expected, actual, status, self.known.get(kk, "") if kk else ""))

    def summary(self):
        from collections import Counter
        return Counter(r[3] for r in self.rows)


def _fmt(v):
    if v is None:
        return "—"
    if isinstance(v, float) and abs(v) < 20:
        return f"{v:.4f}"
    if isinstance(v, (int, float)):
        return f"{v:,.0f}"
    return str(v)


def validate() -> Report:
    E = _load_expected()
    R = Report(E.KNOWN)
    # ---------------- Kirk's (May 2021 IC data) ----------------
    d = Deal.model_validate(json.loads((FIX / "kirks_ic2021.json").read_text()))
    out = analyze(d)
    A = out["analysis"]
    inc = A["income"]
    for pid, exp in E.KIRKS_IC["operating"].items():
        for k, v in exp.items():
            act = inc[pid][k] if k in inc[pid] else None
            if k == "dscr":
                act = round(act, 2)
            R.cmp(f"kirks_ic.operating.{pid}.{k}", v, act, money=k != "dscr")
    agg = A["aggregate"]["values"]
    for k, v in E.KIRKS_IC["aggregate"].items():
        R.cmp(f"kirks_ic.aggregate.{k}", v, round(agg[k], 2) if k == "dscr" else agg[k], money=k != "dscr")
    for i, g in enumerate(E.KIRKS_IC["growth"]):
        R.cmp(f"kirks_ic.growth.{i}", g, A["growth"][i]["pct"])
    R.cmp("kirks_ic.annualized.pct", E.KIRKS_IC["annualized"]["pct"], A["annualized"]["pct"])
    for pid, v in E.KIRKS_IC["break_even"].items():
        R.cmp(f"kirks_ic.break_even.{pid}", v, A["break_even"][pid]["revenue"], money=True)
    for k, vals in E.KIRKS_IC["ratios"].items():
        for pid, v in zip(E.P4, vals):
            R.cmp(f"kirks_ic.ratios.{k}.{pid}", v, A["ratios"][pid][k], money=isinstance(v, int))
    for k, vals in E.KIRKS_IC["balance_sheet"].items():
        for pid, v in zip(E.P4, vals):
            R.cmp(f"kirks_ic.balance_sheet.{k}.{pid}", v, A["balance_sheet"][pid][k], money=True)
    for pid, v in zip(E.P4, E.KIRKS_IC["tnw"]):
        R.cmp(f"kirks_ic.tnw.{pid}", v, A["tnw"][pid]["computed_tnw"], money=True)
    R.cmp("kirks_ic.debt_schedule_total", E.KIRKS_IC["debt_schedule_total"], sum(x["balance"] for x in A["debt_schedule"]), money=True)
    R.cmp("kirks_ic.ltv", E.KIRKS_IC["ltv_approx"], round(A["collateral"]["ltv_gross"], 2))
    # ---------------- Kirk's (actual FS input PDF) — FY2020 column must equal the IS ----------------
    d = Deal.model_validate(json.loads((FIX / "kirks_fs2021.json").read_text()))
    A = analyze(d)["analysis"]
    for k, v in E.KIRKS_FS_FY2020.items():
        act = A["income"]["FY2020"][k]
        R.cmp(f"kirks_fs.FY2020.{k}", v, round(act, 2) if k == "dscr" else act, money=k != "dscr")
    for k, v in E.KIRKS_FS_FY2020_RATIOS.items():
        if k == "net_margin":
            continue
        R.cmp(f"kirks_fs.FY2020.ratios.{k}", v, A["ratios"]["FY2020"][k], money=isinstance(v, int))
    # ---------------- Ballpoint ----------------
    d = Deal.model_validate(json.loads((FIX / "ballpoint.json").read_text()))
    out = analyze(d)
    A = out["analysis"]
    B = E.BALLPOINT
    base = {"revenue": A["id"]["revenue"], "expenses": A["id"]["expenses"], "noi": A["id"]["noi"], "ds": A["ds_base"],
            "cfads": A["cfads_base"], "dscr": [None if v is None else round(v, 2) for v in A["dscr_base"]],
            "re_taxes": A["id"]["lines"]["re_taxes"], "leasing": A["id"]["lines"]["leasing_marketing"]}
    for k, vals in B["base"].items():
        for y, v, a in zip(A["years"], vals, base[k]):
            R.cmp(f"ballpoint.base.{k}.{y}", v, a, money=k != "dscr")
    S = A["sensitivity"]
    sens = {"office_loss": S["loss"], "revenue": S["revenue"], "noi": S["noi"], "ds": S["debt_service"],
            "dscr": [None if v is None else round(v, 2) for v in S["dscr"]], "cfads": S["cfads"]}
    for k, vals in B["sens"].items():
        if k == "office_vacancy_max":
            R.cmp("ballpoint.sens.office_vacancy_max", vals, round(S["max_stabilized_pct"], 2))
            continue
        for y, v, a in zip(A["years"], vals, sens[k]):
            if k == "dscr" and v is None:
                continue
            R.cmp(f"ballpoint.sens.{k}.{y}", v, a, money=k != "dscr")
    su = A["sources_uses"]
    for lab, (amt, pct) in B["uses"].items():
        u = next(x for x in su["uses"] if x["label"] == lab)
        R.cmp(f"ballpoint.uses.{lab}.amount", amt, u["amount"], money=True)
        R.cmp(f"ballpoint.uses.{lab}.pct", pct, u["pct"])
    for lab, (amt, pct) in B["sources"].items():
        s_ = next(x for x in su["sources"] if x["label"] == lab)
        R.cmp(f"ballpoint.sources.{lab}.amount", amt, s_["amount"], money=True)
        R.cmp(f"ballpoint.sources.{lab}.pct", pct, s_["pct"])
    R.cmp("ballpoint.total_cost", B["total_cost"], su["total_uses"], money=True)
    R.cmp("ballpoint.hard_cost_psf", B["hard_cost_psf"], su["hard_cost_psf"])
    R.cmp("ballpoint.total_cost_psf", B["total_cost_psf"], su["total_cost_psf"])
    R.cmp("ballpoint.hard_contingency", B["hard_contingency_label"], round(su["hard_contingency_pct"], 2))
    R.cmp("ballpoint.soft_contingency", B["soft_contingency"], su["soft_contingency_pct"])
    R.cmp("ballpoint.equity_pct", B["equity_pct"], su["equity_pct"])
    rr = A["rent_roll"]
    for k in ("sf", "rent", "loss", "net"):
        R.cmp(f"ballpoint.rent_roll.{k}", B["rent_roll"][k], rr["total"][k], money=True)
    R.cmp("ballpoint.rent_roll.office_avg_psf_rounded", B["rent_roll"]["office_avg_psf_rounded"], round(rr["by_use"]["office"]["avg_psf"]), money=True)
    R.cmp("ballpoint.ltv", B["ltv"], A["collateral"]["ltv_gross"])
    R.cmp("ballpoint.surplus", B["surplus"], A["collateral"]["surplus_gross"], money=True)
    R.cmp("ballpoint.takeout_ltc", B["takeout_ltc"], A["takeout"]["ltc"])
    R.cmp("ballpoint.year1_vacancy", B["year1_vacancy"], round(A["year1_general_vacancy"], 2))
    pol = {e["item"] for e in out["policy"]["exceptions"] if e["kind"] == "policy"}
    gl = {e["item"] for e in out["policy"]["exceptions"] if e["kind"] == "guideline" and e["counts_toward_oversight"]}
    R.rows.append(("ballpoint.policy_exceptions", sorted(B["policy_exceptions"]), sorted(pol),
                   "exact" if pol == B["policy_exceptions"] else "DIFF", ""))
    R.rows.append(("ballpoint.guideline_exceptions (counted)", sorted(B["guideline_exceptions"]), sorted(gl),
                   "exact" if gl == B["guideline_exceptions"] else "DIFF",
                   "Tool also lists the 1.00% commitment fee vs the 1.50% matrix fee (asterisked; not counted)."))
    rk = out["risk_rating"]
    for k, v in B["risk"].items():
        R.cmp(f"ballpoint.risk.{k}", v, rk[k], money=True)
    return R


def write_report(R: Report, path: Path):
    s = R.summary()
    lines = ["# Validation against Invest Detroit sample Investment Summaries", "",
             "CONFIDENTIAL — contains borrower figures. Generated by scripts/validate_samples.py.", "",
             f"Fields compared: **{len(R.rows)}** — " + ", ".join(f"{k}: {v}" for k, v in sorted(s.items())), "",
             "| Field | Sample | Tool | Result | Note |", "|---|---|---|---|---|"]
    for key, e, a, st, note in R.rows:
        lines.append(f"| {key} | {_fmt(e)} | {_fmt(a)} | {st} | {note} |")
    path.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    R = validate()
    write_report(R, FIX.parent / "validation_report.md")
    s = R.summary()
    print(f"{len(R.rows)} fields:", dict(s))
    for key, e, a, st, note in R.rows:
        if st in ("DIFF", "explained"):
            print(f"  {st:10s} {key}: sample={_fmt(e)} tool={_fmt(a)}  {note}")
    sys.exit(1 if s.get("DIFF") else 0)
