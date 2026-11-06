"""Adversarial extraction errors: does the tool raise a flag an underwriter would see?

    python -m synth.adversarial [--random N]

Each test corrupts a correct extraction in one realistic way and checks for the expected kind of flag.
Reports detection rate per error type, plus false-alarm rate of the new checks on clean extractions.
"""
from __future__ import annotations

import argparse
import copy
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from underwriter.pipeline import analyze  # noqa: E402
from underwriter.schema import Deal  # noqa: E402

from .scenarios import SCENARIOS  # noqa: E402
from .to_deal import build_case  # noqa: E402


def _items(d, key=None, period=None, used_only=True):
    """Line items; by default only those from the document the engine uses for that period (newest statements)."""
    owner = {}
    for i, fs in enumerate(d["financials"]):
        end = max((p["end_date"] for p in fs["periods"]), default="")
        for p in fs["periods"]:
            if p["id"] not in owner or end > owner[p["id"]][1]:
                owner[p["id"]] = (i, end)
    for i, fs in enumerate(d["financials"]):
        for li in fs["line_items"]:
            if used_only and owner.get(li["period_id"], (i,))[0] != i:
                continue
            if (key is None or li["key"] == key) and (period is None or li["period_id"] == period):
                yield li


def units_not_converted(d, rng):
    """Every figure left in thousands (extractor forgot to multiply by 1,000)."""
    for li in _items(d, used_only=False):
        li["value"] = round(li["value"] / 1000)
    return "thousands", None


def misread_depreciation(d, rng):
    lis = [li for li in _items(d, "depreciation") if li["value"] > 20_000]
    if not lis:
        return None
    li = rng.choice(lis)
    li["value"] *= rng.choice([0.1, 3, 10])
    return "depreciation", li["period_id"]


def misread_interest(d, rng):
    lis = [li for li in _items(d) if li["key"] in ("interest_expense", "interest_included_above") and li["value"] > 20_000]
    if not lis:
        return None
    li = rng.choice(lis)
    li["value"] *= rng.choice([0.1, 4, 10])
    return "interest", li["period_id"]


def sign_flip_expense(d, rng):
    lis = [li for li in _items(d) if li["key"] in ("cogs", "operating_expenses") and li["value"] > 0]
    if not lis:
        return None
    li = rng.choice(lis)
    li["value"] = -li["value"]
    return "negative", li["period_id"]


def drop_subtotals(d, rng):
    keys = {"gross_profit", "operating_income", "pretax_income", "net_income", "total_current_assets", "net_fixed_assets", "total_assets",
            "total_current_liabilities", "total_liabilities", "total_equity", "total_liabilities_and_equity"}
    for fs in d["financials"]:
        fs["line_items"] = [li for li in fs["line_items"] if li["key"] not in keys]
    return "subtotals", None


def misread_with_no_totals(d, rng):
    """Totals missing AND a misread: undetectable by footing; the subtotal warning must still appear."""
    drop_subtotals(d, rng)
    lis = [li for li in _items(d, "revenue")]
    lis[-1]["value"] *= 1.1
    return "subtotals", None


def duplicate_document(d, rng):
    """Same statements uploaded twice: numbers must not double."""
    d["financials"].append(copy.deepcopy(d["financials"][-1]))
    return "__no_change__", None


TESTS = {"units_not_converted": units_not_converted, "misread_depreciation": misread_depreciation, "misread_interest": misread_interest,
         "sign_flip_expense": sign_flip_expense, "drop_subtotals": drop_subtotals, "misread_with_no_totals": misread_with_no_totals,
         "duplicate_document": duplicate_document}


def run(n_random=100, seed=99):
    rng = random.Random(seed)
    specs = [s for s in SCENARIOS if s["kind"] == "small_business"]
    if n_random:
        from .random_cases import random_scenarios
        specs += [s for s in random_scenarios(n_random, 0, seed) if s["kind"] == "small_business"]
    det = defaultdict(lambda: [0, 0])
    false_alarm = defaultdict(lambda: [0, 0])
    misses = defaultdict(list)
    for spec in specs:
        deal, pres, _, _ = build_case(spec)
        clean = analyze(Deal.model_validate(deal))
        clean_msgs = " | ".join(f.message for f in clean["flags"])
        for word in ("Verify depreciation", "Verify interest", "thousands", "has a negative sign", "no printed subtotals", "does not reconcile"):
            false_alarm[word][1] += 1
            false_alarm[word][0] += word in clean_msgs
        for name, fn in TESTS.items():
            d = copy.deepcopy(deal)
            r = fn(d, rng)
            if r is None:
                continue
            marker, pid = r
            out = analyze(Deal.model_validate(d))
            if marker == "__no_change__":
                a, b = clean["summary"], out["summary"]
                ok = all(abs((a.get(k) or 0) - (b.get(k) or 0)) < 1e-6 for k in ("revenue", "ebitda", "dscr"))
            elif pid is not None:
                # detected = any new consistency flag that points at the corrupted period (by id or label)
                label = next(p["label"] for fs in d["financials"] for p in fs["periods"] if p["id"] == pid)
                before = {f.message for f in clean["flags"]}
                ok = any(f.category == "consistency" and f.message not in before and (pid in (f.ref or "") or pid in f.message or label in f.message)
                         for f in out["flags"])
            else:
                msgs = " | ".join(f.message + " " + (f.ref or "") for f in out["flags"])
                words = {"thousands": "thousands", "depreciation": "depreciation", "interest": "interest expense",
                         "negative": "has a negative sign", "subtotals": "no printed subtotals"}
                ok = words[marker].lower() in msgs.lower() and (pid is None or pid in msgs or marker in ("thousands",))
            det[name][1] += 1
            det[name][0] += ok
            if not ok:
                misses[name].append(spec["id"])
    print(f"{len(specs)} small-business borrowers")
    for k, (o, t) in det.items():
        print(f"  {k:24s} detected {o}/{t} ({o / max(t, 1):.0%})  {'misses: ' + ', '.join(misses[k][:6]) if misses[k] else ''}")
    print("False alarms of the new checks on clean extractions:")
    for k, (o, t) in false_alarm.items():
        print(f"  {k:24s} {o}/{t}")
    return det, false_alarm, misses


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--random", type=int, default=100)
    a = ap.parse_args()
    run(a.random)
