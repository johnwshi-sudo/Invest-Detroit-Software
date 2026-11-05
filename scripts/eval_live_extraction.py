"""Score live Claude extraction against the hand-verified fixtures (run when ANTHROPIC_API_KEY is set).

  python scripts/eval_live_extraction.py            # Kirk's FS PDF + Ballpoint projections PDF
Prints field-level accuracy: every fixture line item (period, key) is looked up in the live extraction.
Cost: one classification + a few extraction calls per document.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from underwriter.env import load_dotenv  # noqa: E402

load_dotenv()
from underwriter.extract.extractor import run_extraction  # noqa: E402
from underwriter.schema import Deal  # noqa: E402

INP, FIX = ROOT / "samples" / "inputs", ROOT / "samples" / "fixtures"


def sums(fs_list):
    out = defaultdict(float)
    for fs in fs_list:
        for li in fs.line_items:
            out[(li.period_id, li.key)] += li.value
    return out


def score_fs():
    pdf = INP / "Kirks_Automotive_Small_Business_Financial_Statements.pdf"
    live = run_extraction([(pdf.name, pdf.read_bytes())], "eval-kirks", progress=print)
    (FIX / "live_kirks_fs2021.json").write_text(live.model_dump_json(indent=1))
    truth = sums(Deal.model_validate_json((FIX / "kirks_fs2021.json").read_text()).financials)
    got = sums(live.financials)
    ok = sum(1 for k, v in truth.items() if k in got and abs(got[k] - v) <= 1)
    missing = [k for k in truth if k not in got]
    wrong = [(k, truth[k], got[k]) for k in truth if k in got and abs(got[k] - truth[k]) > 1]
    print(f"\nKirk's FS: {ok}/{len(truth)} (period, key) totals correct; {len(missing)} missing; {len(wrong)} wrong")
    for w in wrong[:30]:
        print("  wrong", w)
    for m in missing[:30]:
        print("  missing", m)
    print("assurance:", live.financials[0].statement_info.assurance if live.financials else None,
          "| NAICS:", [g.code for g in live.profile.naics_suggestions])


def score_cre():
    pdf = INP / "Ballpoint_Commercial_Real_Estate_Financial_Projections.pdf"
    live = run_extraction([(pdf.name, pdf.read_bytes())], "eval-bp", progress=print)
    (FIX / "live_ballpoint.json").write_text(live.model_dump_json(indent=1))
    truth = Deal.model_validate_json((FIX / "ballpoint.json").read_text()).cre.projections
    got = {l.key: l.values for l in (live.cre.projections.lines if live.cre else [])}
    n = ok = 0
    for ln in truth.lines:
        for t, v in enumerate(ln.values):
            n += 1
            g = got.get(ln.key, [None] * 5)
            ok += int(t < len(g) and g[t] is not None and abs(g[t] - (v or 0)) <= 1)
    print(f"\nBallpoint projections: {ok}/{n} cells correct (borrower columns only)")


if __name__ == "__main__":
    score_fs()
    score_cre()
