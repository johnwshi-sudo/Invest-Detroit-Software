"""Command-line runner.

  python scripts/run_deal.py --deal samples/fixtures/kirks_fs2021.json -o outputs/kirks.docx
  python scripts/run_deal.py --pdf a.pdf b.pdf -o outputs/new.docx      (live Claude extraction; needs ANTHROPIC_API_KEY)
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from underwriter.env import load_dotenv  # noqa: E402

load_dotenv()
from underwriter.memo.docx_export import render_docx  # noqa: E402
from underwriter.pipeline import analyze  # noqa: E402
from underwriter.schema import Deal  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--deal", help="saved Deal JSON")
ap.add_argument("--pdf", nargs="*", help="borrower PDFs for live extraction")
ap.add_argument("-o", "--out", default="outputs/investment_summary.docx")
ap.add_argument("--save-deal", help="write the extracted Deal JSON here")
a = ap.parse_args()
if a.pdf:
    from underwriter.extract.extractor import run_extraction
    deal = run_extraction([(Path(p).name, Path(p).read_bytes()) for p in a.pdf], "cli", progress=print)
    if a.save_deal:
        Path(a.save_deal).write_text(deal.model_dump_json(indent=1))
else:
    deal = Deal.model_validate_json(Path(a.deal).read_text())
out = analyze(deal)
Path(a.out).parent.mkdir(parents=True, exist_ok=True)
Path(a.out).write_bytes(render_docx(out["memo"], deal.terms.borrower_name or ""))
print(json.dumps(out["summary"], indent=1, default=str))
for f in out["flags"]:
    if f.severity != "info":
        print(f"[{f.severity}] {f.message}")
print("wrote", a.out)
