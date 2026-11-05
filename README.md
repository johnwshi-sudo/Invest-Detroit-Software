# Invest Detroit AI Underwriting Assistant

U-M Business+Tech AI Sprint (Fall 2026), built for Invest Detroit's Credit Department.

Upload a borrower's PDF package and get back a draft **Investment Summary** in Invest Detroit's own format,
in minutes instead of ~17 days. The draft includes the operating highlights, DSCR, ratio exhibits, break-even or
vacancy sensitivity, sources & uses, rent roll, collateral and LTV, guideline exceptions, risk rating, a draft term
sheet, and a NAICS industry benchmark. An underwriter reviews it, edits any input, and exports it to Word.

**Claude reads the documents and code does the math.** Every number in the draft is computed in Python from
extracted values. Each extracted value carries its source document, page and confidence, and the review screen
opens the exact source page. Anything missing becomes a visible `[Underwriter to complete: ...]` placeholder and
is never filled in by the model.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env          # then put your ANTHROPIC_API_KEY in .env (never commit it)
uvicorn underwriter.app:app --port 8000
```

Open http://localhost:8000. Without an API key the app runs in **sample mode**: it loads hand-verified extractions of
Invest Detroit's example deals (if `samples/fixtures/` is present) and everything downstream runs live.

Command line:

```bash
python scripts/run_deal.py --pdf statements.pdf business_plan.pdf -o outputs/draft.docx   # live extraction
python scripts/run_deal.py --deal samples/fixtures/kirks_fs2021.json -o outputs/kirks.docx  # saved extraction
pytest -q                                   # unit tests (synthetic data) + golden tests if samples/ exists
python scripts/validate_samples.py          # field-by-field comparison with Invest Detroit's sample memos
python scripts/eval_live_extraction.py      # with a key: score Claude's extraction against the fixtures
```

## How it works

```
PDFs ──► intake checks (type, size, encryption, scanned vs text)
     ──► Claude: classify each document, decide Small Business vs CRE            underwriter/extract/
     ──► Claude: extract to a fixed schema (value + page + confidence)           underwriter/schema.py
     ──► spread + foot checks + restatement checks                               underwriter/engine/spread.py
     ──► deterministic analysis                                                  underwriter/engine/
           small business: EBITDA, debt service, DSCR (incl. ex non-recurring), ratios, TNW, break-even, forecast
           CRE: borrower pro forma -> underwriter adjustments -> DSCR (takeout & ID loan), vacancy sensitivity,
                S&U, cost/SF, LTC, contingencies, rent roll vs market, LOIs, collateral
     ──► credit guideline checks (4/2026 Loan Product Matrix, Appendix C/E)        underwriter/engine/policy.py
     ──► NAICS code + IRS SOI industry benchmarks + projection realism checks     underwriter/naics/
     ──► Investment Summary (same sections/tables/wording style as ID's samples)  underwriter/memo/
     ──► review UI (edit -> recompute) and Word export                            frontend/, underwriter/app.py
```

* Model: `claude-opus-5-5` (set `UNDERWRITER_MODEL` to change). The PDFs are sent as document blocks with prompt
  caching, output is constrained to a JSON schema and validated with Pydantic, and server-side refusal fallback is on.
* Credit guidelines live in `config/credit_guidelines.yaml`, transcribed from the 4/2026 PDF. Values that come from
  older guideline wording quoted in the samples are marked `verified: false`.
* Industry data: `config/irs_soi_benchmarks.json` (IRS Statistics of Income Table 5.1, tax years 2020-2022, 187
  industries) and `config/naics_2022.json` (Census 2022 NAICS codes + 20k index phrases). Rebuild them with
  `scripts/build_benchmarks.py`.

## Validation against Invest Detroit's samples

`scripts/validate_samples.py` compares **387 figures** from the two sample Investment Summaries (Kirk's Automotive,
Ballpoint Bagley) with the tool's output:

| Result | Fields |
|---|---|
| Exact | 353 |
| Within $1 (display rounding of the source PDFs) | 18 |
| Within 0.01% (break-even sales: the sample used Excel goal-seek, the tool solves exactly) | 3 |
| Rounded percent differs (takeout LTC 55.4% vs "56%") | 1 |
| Differs because the sample has a spreadsheet error (documented in the report) | 12 |
| Unexplained | **0** |

Running the tool on the actual input PDF (Kirk's FY2021/FY2020 statements) reproduces the memo's FY2020 column
exactly (EBITDA, DSCR, current/quick ratios, leverage, activity ratios). See `docs/sample-findings.md`.

## Data handling

* The repo is **public**. `samples/`, `data/`, `outputs/`, `*.pdf`, `*.docx` and `.env` are gitignored and must
  stay out of git.
* Uploads are stored in `data/uploads/` and deleted after `UNDERWRITER_RETENTION_HOURS` (default 24). Nothing
  borrower-specific is logged.
* Documents are sent to the Anthropic API for extraction. **Open item:** confirm with Invest Detroit that this is
  acceptable for production use.

## Status / limitations

* The live Claude extraction path is implemented and tested with a simulated client. It has **not yet been run
  against the real sample PDFs**, because no API key was available while building. Run `scripts/eval_live_extraction.py`
  first once a key is in `.env`.
* Facts that aren't in borrower documents (loan history, banking relationship, credit reports, exposure, risk
  scores) are underwriter inputs on the Inputs tab.
* Only the anchor scores seen in the one sample CRE worksheet are known, so the risk-rating rubric is partial.
* IRS SOI benchmarks are aggregates (sums across all corporations), not RMA-style medians.

See `CLAUDE.md` for the design principles and open questions.
