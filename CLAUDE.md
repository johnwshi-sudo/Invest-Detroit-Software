# CLAUDE.md — Invest Detroit AI Underwriting Tool

U-M Business+Tech AI Sprint (Fall 2026). Client: **Invest Detroit**, a Michigan CDFI that fills
financing gaps banks won't (typically ~40% of a project behind a ~60% bank loan).
Claude Code writes the code; the team (PM, BA, ML eng, backend dev) are students.

Key dates: Nov 10 (final client meeting, deck work starts), Nov 17 (final live presentation).

## The problem
- Underwriters re-key borrower documents into a template by hand, then analyze by hand. ~17 days per analysis.
- Inputs: business plan, 3–5 yr projections / pro forma, financial statements, rent rolls, appraisals, budgets.
- Output: a **full Investment Summary** (Invest Detroit's underwriting memo) comparable in length and
  structure to their own — NOT a short summary — plus term-sheet-level structure.
- Client success criteria: concise, clear understanding of financial performance; high-quality analysis.

## What the samples taught us (read `docs/sample-findings.md` for detail)
- Two loan families, two different analyses:
  - **Small Business / C&I** (sample: Kirk's Automotive): operating highlights table, EBITDA, DSCR,
    debt schedule, capitalization/TNW, break-even sensitivity, collateral, guarantors, strengths/weaknesses,
    exhibits (projection, balance sheets, ratios).
  - **CRE** (sample: Ballpoint Bagley): sources & uses, projected cash flow & debt service
    (borrower projections adjusted by underwriter), rent roll, sensitivity (vacancy that drives DSCR to 1.00x),
    collateral/LTV, development budget, guideline exceptions, risk rating worksheet.
- The sample input PDFs are **image-only scans** → extraction needs a vision model (Claude reads PDFs as images).
- Credit Guidelines (rev. 4/2026) give the product matrix: min DSCR 1.15x (SB term, CRE term, construction),
  1.05x NMTC; max LTV/LTC; rate ranges; fees; ≥10% equity; guarantees from all ≥20% owners; contingencies
  (rehab 15% hard / 10% soft; new construction 10% / 5%). These live in `config/credit_guidelines.yaml`.
- DSCR (Invest Detroit's sample math) = EBITDA ÷ total debt service, where EBITDA = net income + interest +
  depreciation (+ taxes + amortization), and debt service = proposed ID loan P&I + LOC interest + other notes P&I.
  CRE DSCR = NOI ÷ debt service. Ratios use a 360-day year.

## Product goal
Upload a borrower PDF package → classify → extract to a fixed, versioned schema (every value carries
source file, page and confidence) → **compute everything in deterministic code** → NAICS benchmark /
realism checks → draft the full Investment Summary → underwriter reviews and edits → export Word.
The tool drafts; humans decide.

## Design principles (non-negotiable)
1. **The LLM reads and writes. Code does the math.** No number in the memo may come from the LLM.
   Narrative sentences containing numbers are generated from engine results.
2. **Every figure traces to a source page** or is marked as an input/assumption/derived value. Never guess a
   missing value — mark it missing and flag it.
3. **Surface uncertainty**: low-confidence extractions, missing documents, internal inconsistencies
   (e.g., statement doesn't foot, debt schedule ≠ FS notes), assumptions outside industry norms.
4. **Human in the loop**: output is a draft; every input is editable and recomputes.
5. **Sensitive data**: PDFs contain SSNs and tax returns. Log minimally; don't persist uploads longer
   than needed; never commit borrower data (repo is public — `samples/` and `*.pdf` are gitignored).
6. Demo-ready vertical slices beat breadth.

## Architecture
```
underwriter/            Python package (FastAPI backend + engine)
  schema.py             Pydantic extraction + deal-input models (versioned)
  guidelines.py         loads config/credit_guidelines.yaml
  engine/               deterministic math: finance.py, small_business.py, cre.py, policy.py, risk_rating.py
  naics/                NAICS inference + benchmark comparison (data in config/naics_benchmarks.json)
  extract/              Claude client, document classification, structured extraction
  memo/                 Investment Summary builder (sections), narrative, docx export
  pipeline.py           orchestrates extract → compute → benchmark → memo
  app.py                FastAPI app (serves frontend/)
frontend/               static HTML/JS review UI (no build step)
config/                 credit guidelines + NAICS benchmark data (public data only)
tests/                  unit tests (synthetic data, committed) + golden tests (run only if samples/ exists)
scripts/                CLI helpers (run a sample, live extraction test)
```

## Conventions
- Python 3.11+, FastAPI, Pydantic v2, python-docx. Run `pytest -q` before committing.
- Money in plain floats rounded only at display time; ratios computed from unrounded values.
- Model: Claude via `anthropic` SDK; key in `ANTHROPIC_API_KEY` env var, never committed.
  Default model set in `underwriter/extract/llm.py`.
- Golden fixtures for the sample deals live in `samples/fixtures/` (gitignored, real borrower data).

## Open questions (ranked)
1. Template: is the Investment Summary a Word doc with embedded Excel? (assumed Word)
2. Who uploads — staff or borrowers? (assumed staff; no borrower portal/auth yet)
3. May borrower docs be sent to an outside AI provider (Anthropic)? Need Invest Detroit's guidance.
4. Full risk-rating policy (we only have one completed CRE worksheet).
5. Older guideline values used in Ballpoint (2% rent growth, 3% expense growth, 15% commercial vacancy,
   $0.50/SF replacement reserves) are not in the 4/2026 guidelines — confirm current values.
6. Benchmark data: does Invest Detroit license RMA or similar? (we use free Census/IRS/BLS data)
7. Claude API usage cost vs sprint's free Codex credits.
