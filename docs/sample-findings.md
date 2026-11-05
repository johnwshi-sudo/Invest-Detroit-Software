# What Invest Detroit's samples taught us

Findings from the five files Invest Detroit sent (two Investment Summaries, their source financials, and the
4/2026 Credit Guidelines). The rules are generalized here, and borrower figures are deliberately left out because
the repo is public.

## The inputs
* Four of the five PDFs are **image-only scans** with no text layer (one is rotated 90°). Text-based PDF parsing
  gets nothing from them; they need a vision model.
* The small business input (CPA-prepared statements) covers a later period than its Investment Summary, so the two
  overlap in only one fiscal year. That year is our end-to-end test, and the tool matches it exactly.
* The CRE projections PDF has the borrower's columns *and* Invest Detroit's "sensitized" columns. Only the
  borrower's columns are inputs; the sensitized ones are what the tool must reproduce.
* Several inputs the memos rely on were not provided: debt schedule, appraisal, development budget, rent roll,
  LOIs, credit reports, prior-year statements. The fixtures carry those values as transcribed from the memos.

## Small Business / C&I methodology (reverse-engineered, matched to the dollar)
* EBITDA = net income + interest + depreciation (+ taxes + amortization when present). Interest that sits inside
  operating expenses on interim statements is still added back.
* Debt service = proposed Invest Detroit loan P&I (applied pro forma to every historical year) + LOC interest +
  scheduled P&I on other notes. Interim periods are pro-rated by months.
* DSCR = EBITDA / total debt service. CFADS = EBITDA − debt service.
* Non-recurring income (PPP forgiveness) is **included** in EBITDA because it was a real receipt of cash. The tool
  keeps that practice and also reports DSCR excluding it.
* Break-even: sales are reduced until DSCR = 1.00x, with gross margin % held constant and operating expenses
  fixed. The sample used Excel goal-seek; we solve exactly.
* Balance sheet exhibit: term debt is shown by creditor below current liabilities, and Invest Detroit's own
  subordinated note is shown as quasi-equity ("Sub-Debt") in net worth. Both are configurable.
* Ratios: 360-day year. Inventory days and turnover use **sales** (template convention). Quick ratio = (cash + A/R +
  other receivables) / current liabilities. Interim ratios are not annualized. "Operating Profit" in the ratio
  exhibit is net income + interest.
* TNW = equity + ID note + subordinated shareholder notes − related-party receivables − prepaids.
* LTV = ID loan / (real estate value + equipment at cost), ignoring prior liens. The tool also reports combined LTV.

## CRE methodology
* Base case = borrower projections adjusted by the underwriter: RE taxes replaced by the appraiser's estimate
  (grown 3%), lease-up costs counted once, rent growth ≤ 2%, expense growth ≥ 3%, a vacancy floor, and replacement
  reserves unless capital reserves already exceed $0.50/SF.
* Debt service in the base case is a hypothetical take-out loan sized at 1.25x, with partial-year debt service
  during the interest-holdback period.
* Sensitized case: the ID loan stays in place, and the vacancy on the largest rent line is solved so DSCR = 1.00x.
* Sources & uses percentages and cost/SF are on rentable (not gross) SF. Contingency tests follow Appendix E
  (rehab: 15% hard, 10% soft).
* Risk-rating worksheet: 8 categories, preliminary rating = rounded average, with a management override.

## Spreadsheet errors found in the samples (the tool computes the correct value)
1. The ratio exhibit's "Net Margin" row repeats Gross Margin.
2. The capitalization (TNW) table's earlier columns do not tie to the memo's own balance sheet exhibit.
3. The CRE sensitivity table's "Cash Flow After Debt Service" row points at the real-estate-tax row.
4. Labeled vs computed percentages differ: "10%" hard contingency computes to 8.8%, "50%" lease-up vacancy to 49.4%,
   and "56%" takeout LTC to 55.4%.

## Guideline items the samples quote that are not in the 4/2026 guidelines
2% rent growth, 3% expense growth, 15% commercial vacancy, $0.50/SF reserves. These are kept as configurable
assumptions marked `verified: false`. Confirm them with Invest Detroit.
