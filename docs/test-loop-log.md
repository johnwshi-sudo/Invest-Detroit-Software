# Synthetic test loop — progress log

**Resume instructions for a new session:** read this file top to bottom, then run
`python -m synth.run_loop` from the repo root. The newest round is at the bottom; "Next steps" says what to do.

## Goal (from the user, 2026-11-06)
Generate many realistic synthetic borrower packages (PDFs like Invest Detroit's samples) across industries
(automotive, startups, community buildings, recreation, big tech, restaurants, CRE...) with varied finances.
After each round, score the software against an independent answer key, fix errors, repeat until accuracy is
very high. No Anthropic API key in this phase: the PDF-reading (LLM) step is NOT exercised; everything
downstream of extraction is (math, guideline checks, NAICS, memo text, Word export), plus robustness to
realistic presentation quirks and injected misreads.

## Design
- `synth/scenarios.py` — scenario specs (industry, drivers, loan request, owners, presentation quirks)
- `synth/model.py` — builds balanced multi-year financials / CRE pro formas from drivers (ground truth)
- `synth/render.py` — renders PDFs (CPA letter, statements, schedules, notes, projections, rent roll, budget);
  some rasterized as "scans" (rotation/noise)
- `synth/to_deal.py` — converts ground truth into what a perfect extractor would output, applying the
  scenario's presentation quirks (interest inside opex, depreciation only in cash flow, $000s, etc.)
- `synth/oracle.py` — INDEPENDENT expected values written from guideline definitions (not engine code)
- `synth/run_loop.py` — generate → run pipeline → score → append results here

## Rounds

### Round 1
- (first run; scorer bug crashed 17 small-business cases, numbers below are partial)
- 23 scenarios, 1587 checks, **1301 passed (82.0%)**; misread detection 0/0
- by category: break_even 49/49, collateral 5/5, crash 0/18, cre_ds 29/30, cre_noi 51/75, dscr 132/156, export 0/5, growth 32/32, income 159/159, memo 20/25, naics 5/5, policy 9/10, projection 0/1, ratios 756/950, risk 9/10, sensitivity 15/27, sources_uses 30/30
- failing: ratios (194), crash (18), projection (1), cre_noi (24), dscr (24), sensitivity (12), memo (5), export (5), cre_ds (1), risk (1), policy (1)

### Round 2
- 23 scenarios, 1883 checks, **1883 passed (100.0%)**; misread detection 17/17
- by category: break_even 49/49, collateral 6/6, consistency 1/1, cre_ds 36/36, cre_noi 90/90, dscr 166/166, export 23/23, growth 32/32, income 159/159, memo 167/167, naics 23/23, policy 80/80, projection 3/3, ratios 950/950, realism 17/17, risk 12/12, sensitivity 33/33, sources_uses 36/36

#### Fixes made after rounds 1-2
Engine / memo bugs found by the loop (all fixed):
1. Current portion of LTD was excluded from current liabilities by default (to mimic one Kirk's column). Default is now
   GAAP / Invest Detroit 2018-exhibit convention (CPLTD is current); the Kirk's fixture sets the old presentation explicitly.
   Current ratios had been overstated 20-40%.
2. Ratio exhibit lacked "EBITDA (-/+) Distributions/Contributions" (matters for S-corps) — added.
3. CRE: 15% vacancy floor was applied to residential units; guideline is commercial-only. Understated multifamily NOI
   by $11K-34K/yr and created a false DSCR exception. Now commercial-only, with an info flag for residential.
4. CRE: stabilized year came back undefined once the underwriter floor added vacancy; stabilization now keys off the
   borrower's lease-up vacancy.
5. CRE: replacement-reserve shortfall double-counted existing reserves; rent-growth cap left vacancy at the borrower's
   dollar amount instead of scaling with the reduced rent.
6. CRE: crash and false contingency exceptions on acquisition-only deals (no construction).
7. Break-even narrative said "sales could decline -8.2%" when sales must rise; now says "would need to increase".
8. Service businesses (no COGS line): engine derived a negative COGS from a stated gross profit, hiding a misread
   revenue figure. COGS is never derived now; gross profit, current liabilities, total liabilities and net fixed assets
   are foot-checked.
9. Appendix E start-up rules were never applied; now flagged (< 24 months or < 2 fiscal years).
10. Annual projections (start-up 3-year forecasts) were not realism-checked; now checked against
    min(25%, industry growth + 10 pts).
11. Interim actual + forecast periods are now combined into a full-year forecast column automatically.
Scorer/oracle bugs fixed along the way: Flag access, "nan" matching "financial", Word tables not searched,
"None identified" false positive, oracle stabilization rule (had the same flaw as the engine).

**Status after round 2:** 23 hand-designed scenarios, 1,883 checks, 100% pass; 17/17 injected misreads caught;
Invest Detroit sample validation unchanged (0 unexplained differences); 15 unit tests pass.

#### Rendered PDFs
`python -m synth.render` writes 80 PDFs for the 23 hand-designed packages to synth/out/pdf/ (CPA letter, statements,
schedules, notes, tax-return style, interim/forecast, business plans, CRE projections/rent roll/budget/appraisal).
~1/3 are rasterized "scans"; one projection page is rotated 90°. Each folder has answer_key.deal.json for scoring
live extraction later.

### Round 3
- 233 scenarios, 16632 checks, **16628 passed (100.0%)**; misread detection 501/501
- by category: break_even 413/413, collateral 66/66, consistency 15/16, cre_ds 396/396, cre_noi 990/990, dscr 1632/1632, export 233/233, growth 246/246, income 1458/1458, memo 1486/1486, naics 233/233, naics_fallback 17/20, policy 800/800, projection 3/3, ratios 7581/7581, realism 167/167, risk 132/132, sensitivity 364/364, sources_uses 396/396
- failing: naics_fallback (3), consistency (1)

#### Round 3 notes (233 scenarios = 23 designed + 150 random small business + 60 random CRE, seed 2026)
Bugs found and fixed:
1. Negative net worth: debt/worth, ROE and sales/worth were printed as meaningless numbers (e.g. -118x); now "n/a" with
   a warning, and the narrative says net worth is negative instead of "leverage is improving".
2. Existing Invest Detroit note shown as quasi-equity: its current portion stayed in CPLTD AND moved to net worth
   (double count) -> understated current ratios, negative LTD/fixed assets. Now split by the note's payment terms
   (warning if terms are missing).
3. NAICS keyword fallback: place names in business names ("Brush Park" -> "aircraft parking"), "except" clauses and
   abbreviations (IT, HVAC) caused misses. Fallback 4-digit accuracy on the 24 industry descriptions: 7/24 -> 20/24.
   It is only used when document reading gives no code, and it is always flagged for confirmation.
4. Replacement reserves no longer get the expense-growth floor before the reserve top-up (misleading note).
Judgment calls documented: CAM reimbursements are capped at the 2% rent-growth rate like rents (Ballpoint practice);
max-LTV test uses combined LTV when senior liens exist (conservative; Kirk's sample quoted LTV without the senior lien).
Harness fixes: restatement only generated when a year appears in two documents; oracle uses CLTV.

**Status after round 3:** 16,631 checks, 16,628 pass; the 3 misses are the keyword-only NAICS fallback (17/20, scored
separately). Misread detection 501/501. Invest Detroit samples unchanged; unit tests pass.

### Round 4
Generalization run on a FRESH seed (7777) with 2.4x more cases, before any further tuning:
583 scenarios, 40,954 checks, 40,944 pass; misread detection 1,251/1,251. Misses: keyword NAICS fallback (7) and
3 narrative checks (fixed below).

Adversarial extraction-error suite (`python -m synth.adversarial`, 117 small-business borrowers):
| injected error | detected | new-check false alarms on clean data |
|---|---|---|
| statements in $000s not converted | 117/117 | 0/117 |
| depreciation misread (x0.1, x3, x10) | 70/82 (85%) | 0/117 |
| interest misread (x0.1, x4, x10) | 70/71 (99%) | 0/117 |
| expense recorded with negative sign | 117/117 | 0/117 |
| no subtotals extracted (cannot foot) | 117/117 warned | 0/117 |
| duplicate upload | 117/117 numbers unchanged | — |

New engine checks: depreciation vs change in accumulated depreciation; depreciation > accumulated depreciation or
> 40% of gross fixed assets; interest vs debt balances x rates; year-over-year swings (>2.5x) not explained by the
balance sheet; implied interest rate > 25%; scale check for unconverted $000s (critical); expense sign check;
warning when no subtotals exist to foot. Reaching zero false alarms took several iterations (line-of-credit draws at
year end and loans paid off mid-year are normal and must not trigger alerts).
Found in Invest Detroit's own sample: the Kirk's May 2021 package reports $19,500 of Q1 depreciation while
accumulated depreciation rose only $12,001.
Narrative fix: amounts under $1M are now written in full dollars ("$186,745", not "$187K") so a stated % change can
be verified from the stated amounts.
Harness fix: generator line-of-credit interest now follows the average balance (was unrealistic).

**Status after round 4:** seed-2026 set 16,658/16,660 (2 = NAICS keyword fallback); unit tests and Invest Detroit
sample validation unchanged.

### Round 5
- 233 scenarios, 18178 checks, **18177 passed (100.0%)**; misread detection 501/501
- by category: break_even 410/410, collateral 66/66, consistency 12/12, cre_ds 396/396, cre_noi 990/990, dscr 1676/1676, export 233/233, growth 243/243, income 1524/1524, memo 3094/3094, naics 233/233, naics_fallback 25/26, policy 800/800, projection 3/3, ratios 7410/7410, realism 167/167, risk 132/132, sensitivity 367/367, sources_uses 396/396
- failing: naics_fallback (1)

#### Round 5 notes — memo wording QA
New scorer checks: required sections present and in Invest Detroit's order; qualitative claims must agree with the
numbers ("cash flows are sufficient" / "although tight" / "not sufficient" vs DSCR; "well within the takeout lender's
terms" only if base DSCR >= 1.25x; "more than enough cash flow" only with >30 pts of vacancy cushion; vacancy
"at or above / below" the guideline; "per guidelines" rent growth only when it equals the guideline); no "x%-y%"
ranges, no repeated clauses, no COGS paragraph for businesses without COGS.
Fixed: CRE sensitivity could say vacancy "can increase to -40%" and crashed when no year had full debt service;
blended vacancy was always called "conservative" (even below the 15% guideline); "Rents increase by 1% annually per
Invest Detroit's credit guidelines"; term loans called "construction loan"; "cash flow is thin" at 0.41x (now "does
not cover debt service"); new weaknesses for a >25% net-worth decline and debt/worth > 4x; gross-margin benchmark
suppressed when the borrower has no COGS; range and break-even phrasing. NAICS fallback: sector cues (store,
distributor, manufactures, tutoring) -> 21/24 on the industry set.
Fresh-seed run (seed 4242, 583 scenarios, before the last wording fixes): 43,039/43,051, all 12 misses NAICS fallback;
misread detection 834/834. Browser UI test re-run on Kirk's, Ballpoint and a synthetic deal: no errors, edits
recompute, Word export works.

**Status after round 5:** 18,177/18,178 (1 = NAICS keyword fallback); adversarial suite unchanged (0 false alarms);
Invest Detroit sample validation unchanged; unit tests pass.

#### Next steps
- Ask the user to allow `git push` (blocked by the session's permission check since round 4; commits are local).
- Possible further rounds: more industries/edge cases in the random generator (seasonal interim periods, fiscal years
  not ending in December, multiple guarantors with outside income, NMTC / bridge / predevelopment products).
- Live-extraction scoring on synth/out/pdf once an ANTHROPIC_API_KEY is available.
