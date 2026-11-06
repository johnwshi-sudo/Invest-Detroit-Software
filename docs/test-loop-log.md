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

#### Next steps
- Render the synthetic PDFs (synth/render.py) — needed for future live-extraction tests.
- Round 3+: procedurally generated borrowers (hundreds), edge cases (no debt, negative equity, missing balance
  sheet, existing Invest Detroit loan, interest-only, $000s), several misreads per case incl. undetectable ones.
