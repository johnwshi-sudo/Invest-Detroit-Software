"""Prompts for document classification and extraction. Numbers are read, never calculated, by the model."""

SYSTEM = """You are a meticulous credit analyst's assistant at Invest Detroit, a Detroit CDFI. You read borrower \
documents (often scanned) and transcribe facts into a fixed JSON schema for underwriting.

Rules:
- Transcribe; do not calculate, estimate, or infer numbers that are not printed. If a value is not in the documents, \
omit it (or use null). Never guess.
- Every number must carry the 1-based PDF page number where you read it (the page index within that document, not \
the printed page label).
- Copy line labels exactly as printed.
- Numbers in parentheses are negative. Remove $ and commas. Values are whole dollars unless the document states \
thousands; if it does, convert to dollars and say so in a note.
- Set confidence below 0.7 whenever the scan is blurry, a digit is ambiguous, or the column alignment is uncertain.
- Documents may contain SSNs and account numbers: never copy them into any field.
"""

CLASSIFY = """Classify each document above for an underwriting file.
For each document give its doc_type, the periods it covers (e.g. 'FYE 12/31/2021', '3 months ending 3/31/21', \
'2025-2029 projections'), the company or property name, and a one-sentence summary.
doc_type options: financial_statements (annual CPA or internal statements), tax_return, interim_financials, \
projections (business forecast), cre_projections (property operating pro forma), business_plan, debt_schedule, \
rent_roll, appraisal, budget (development/construction budget or sources & uses), loi (letter of intent / lease), \
bank_statements, personal_financial_statement, investment_summary (an existing lender credit memo), \
credit_guidelines, other.
Then decide deal_type: 'cre' if repayment relies on property rents (investment real estate: rent roll, NOI pro \
forma, development budget), otherwise 'small_business' (repayment from business operations)."""

FS_KEYS = """Map every printed line to one canonical key (several lines may share a key; they will be summed):
INCOME STATEMENT: revenue (sales, net sales, total revenue), cogs (cost of sales/goods sold, total), gross_profit \
(stated total), operating_expenses (total G&A / operating expenses), operating_income (stated), other_income (each \
recurring non-operating income line, e.g. scrap sales, discounts earned, interest income), nonrecurring_income \
(debt forgiveness incl. PPP/EIDL forgiveness, gains on asset sales, insurance proceeds, ERC credits), \
interest_expense, other_expense (non-interest non-operating expense), income_taxes, pretax_income (stated), \
net_income (stated).
MEMO items (already included above; record them separately for add-backs): depreciation (wherever it appears, \
including inside cost of sales schedules or the cash flow statement), amortization, officer_compensation \
(officer/shareholder/administrative salaries of owners), rent_expense, distributions, interest_included_above \
(interest that is inside operating expenses rather than shown separately).
BALANCE SHEET: cash, accounts_receivable, inventory, other_receivables (loans/notes receivable, related-party \
receivables), prepaid_expenses, other_current_assets, total_current_assets, fixed_assets_gross (one line per asset \
class at cost), accumulated_depreciation (negative), net_fixed_assets, deposits, other_assets, intangible_assets, \
total_assets, accounts_payable (trade only), accrued_expenses (accruals, uninvoiced/other payables, payroll and \
taxes payable), line_of_credit, current_portion_ltd, other_current_liabilities, total_current_liabilities, \
long_term_debt (net of current portion), other_liabilities, total_liabilities, common_stock, paid_in_capital, \
retained_earnings, current_year_income, other_equity, total_equity, total_liabilities_and_equity.
Always include the stated subtotals/totals printed on the statements so they can be foot-checked.
For each period (column) create a Period with id like FY2021 (annual), YTD2021-03 (interim) or FY2022P (projection), \
a label in the style 'FYE 12/31/21' or '3 Mos. Ending 03/31/21', end_date, months and kind.
DEBTS: from the notes and debt schedules, list every loan/line/note with creditor, kind, balance per period (with \
page), interest rate (decimal), monthly payment, maturity, collateral, whether subordinated, related party, and \
is_invest_detroit (Invest Detroit, Detroit Investment Fund, DIF). If the statement of cash flows shows a principal \
change for a specific creditor (e.g. 'Reduction Note payable, DIF (163,589)'), put it in cash_flow_change.
STATEMENT INFO: preparer, report date, assurance level from the accountant's letter (audit / review / compilation / \
no_assurance if the letter says no audit, review or compilation standards were applied / tax_return / internal), \
and basis (gaap / tax / cash).
NOTES: material disclosures, one sentence each with page (NOL carryforwards, related-party leases, guarantees, \
contingencies, pension obligations, going concern, subsequent events)."""

EXTRACT_FS = "Extract the financial statements in the document(s) above.\n\n" + FS_KEYS

EXTRACT_PROFILE = """From all documents above, extract the business profile: legal name, address, year established, \
entity type, a 2-4 sentence description of what the business does, products/services, named customers, market, \
employee counts and jobs created/retained, Detroit residents employed, owners and managers (name, role, ownership \
share as a decimal, short bio, whether they will guarantee, any credit/background report summary), whether the space \
is owned or leased, other lenders. Use only facts in the documents.
Suggest up to three 2022 NAICS codes (6-digit) that best describe the PRIMARY revenue-generating activity, each with a \
one-sentence rationale citing the document and a confidence. For investment real estate, use the lessor code (e.g. \
531110 residential, 531120 nonresidential)."""

EXTRACT_CRE = """Extract the commercial real estate underwriting data from the documents above:
- property (address, gross SF, rentable SF, type, use mix, rehab_type, occupancy status)
- rent_roll: every unit with use (retail/office/residential/industrial/other), SF, annual rent, status (leased/loi/\
vacant/proposed), tenant, lease type
- projections: the BORROWER's operating projections only (not lender-sensitized columns). years = the projection \
years; one ProjectionLine per printed row with values aligned to years. Keys: gross_retail_rent, retail_vacancy, \
gross_office_rent, office_vacancy, gross_residential_rent, residential_vacancy, other_gross_rent, other_vacancy, \
cam_reimbursement, other_income, general_vacancy (a total/general vacancy line), total_revenue, management_fee, \
leasing_marketing, insurance, trash, cleaning, maintenance, turns, cable, re_taxes, tax_abatement, water, \
gas_electric, utilities, payroll, capital_reserves, accounting, asset_management, replacement_reserves, \
other_expense, total_expenses, noi. Vacancy losses negative. Include printed totals.
- budget: every development budget line with category (acquisition, hard, hard_contingency, professional, \
lender_carry, soft_contingency, developer_fee, reserves, other_soft). Use component lines rather than their subtotal.
- sources of funds with kind (invest_detroit, senior_debt, other_debt, equity, grant, tax_credit, other)
- appraisal (values, dates, market rents per SF, vacancy estimate, real estate tax estimate, cap rate)
- LOIs (tenant, unit, SF, monthly rent, term, renewal options, lease type, use)
- development team members and the development status."""
