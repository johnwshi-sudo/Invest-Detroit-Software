"""Versioned data model for a deal.

Three layers:
  1. Extraction models (FinancialStatements, BusinessProfile, CREData): what the LLM reads out of borrower
     documents. LLM-facing models avoid dicts (structured-output friendly); every value has doc/page/confidence.
  2. DealTerms: what the loan officer/underwriter enters (request terms, existing debt service, collateral,
     qualitative facts not in borrower documents). Always editable in the review UI.
  3. Deal: the container that is saved, recomputed and exported.

The engine (underwriter/engine) never mutates these; it returns results with provenance.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0.0"

Confidence = Optional[float]


# ---------------------------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------------------------
class Period(BaseModel):
    id: str = Field(description="Stable id, e.g. 'FY2020', 'YTD2021-03', 'Q2-2021P'")
    label: str = Field(description="Display label as Invest Detroit writes it, e.g. 'FYE 12/31/20', '3 Mos. Ending 03/31/21'")
    end_date: str = Field(description="ISO date of period end, e.g. 2020-12-31")
    months: int = 12
    kind: Literal["actual", "interim", "projection"] = "actual"


# Canonical financial statement keys. Several printed lines may map to the same key (they are summed).
FSKey = Literal[
    # income statement
    "revenue", "cogs", "gross_profit", "operating_expenses", "operating_income",
    "other_income", "nonrecurring_income", "interest_expense", "other_expense", "income_taxes",
    "pretax_income", "net_income",
    # memo items (already included in the lines above; used for add-backs and analysis)
    "depreciation", "amortization", "officer_compensation", "rent_expense", "distributions",
    "interest_included_above",  # interest already inside operating expenses (common in interim statements)
    # balance sheet
    "cash", "accounts_receivable", "inventory", "other_receivables", "prepaid_expenses",
    "other_current_assets", "total_current_assets", "fixed_assets_gross", "accumulated_depreciation",
    "net_fixed_assets", "deposits", "other_assets", "intangible_assets", "total_assets",
    "accounts_payable", "accrued_expenses", "line_of_credit", "current_portion_ltd",
    "other_current_liabilities", "total_current_liabilities", "long_term_debt", "other_liabilities",
    "total_liabilities", "common_stock", "paid_in_capital", "retained_earnings", "current_year_income",
    "other_equity", "total_equity", "total_liabilities_and_equity",
]


class LineItem(BaseModel):
    key: FSKey
    label: str = Field(description="Line label exactly as printed")
    period_id: str
    value: float = Field(description="Signed dollars. Expenses/costs positive. Use negative only for contra items "
                                     "printed in parentheses (e.g. accumulated depreciation) or a loss.")
    page: Optional[int] = None
    doc: Optional[str] = None
    confidence: Confidence = None


class DebtBalance(BaseModel):
    period_id: str
    value: float
    page: Optional[int] = None


class Debt(BaseModel):
    creditor: str
    kind: Literal["line_of_credit", "term_loan", "mortgage", "vehicle", "shareholder_note", "estate_note",
                  "sba_ppp", "other"] = "other"
    balances: list[DebtBalance] = Field(default_factory=list)
    interest_rate: Optional[float] = Field(None, description="Decimal, e.g. 0.06")
    rate_description: Optional[str] = None
    monthly_payment: Optional[float] = None
    maturity: Optional[str] = None
    collateral: Optional[str] = None
    subordinated: bool = False
    related_party: bool = False
    is_invest_detroit: bool = Field(False, description="True if the creditor is Invest Detroit / Detroit Investment Fund (DIF)")
    cash_flow_change: Optional[float] = Field(None, description="Principal change in the latest period from the "
                                              "statement of cash flows (negative = repayment)")
    page: Optional[int] = None
    doc: Optional[str] = None
    notes: Optional[str] = None


class StatementInfo(BaseModel):
    preparer: Optional[str] = None
    report_date: Optional[str] = None
    assurance: Literal["audit", "review", "compilation", "no_assurance", "tax_return", "internal", "unknown"] = "unknown"
    basis: Literal["gaap", "tax", "cash", "unknown"] = "unknown"
    page: Optional[int] = None


class FinancialStatements(BaseModel):
    """Extraction result for one financial statement / tax return / interim / forecast document."""
    company_name: Optional[str] = None
    doc: Optional[str] = None
    statement_info: StatementInfo = Field(default_factory=StatementInfo)
    periods: list[Period] = Field(default_factory=list)
    line_items: list[LineItem] = Field(default_factory=list)
    debts: list[Debt] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list, description="Material disclosures (NOLs, related-party leases, "
                                                                "pension, contingencies), one sentence each, with page")


class NaicsGuess(BaseModel):
    code: str
    title: Optional[str] = None
    rationale: Optional[str] = None
    confidence: Confidence = None


class Person(BaseModel):
    name: str
    role: Optional[str] = None
    ownership_pct: Optional[float] = Field(None, description="Decimal share of the borrower, e.g. 0.30")
    ownership_via: Optional[str] = None
    bio: Optional[str] = None
    guarantor: Optional[bool] = None
    background_check: Optional[bool] = None
    credit_report: Optional[str] = None
    passive: Optional[bool] = None


class BusinessProfile(BaseModel):
    legal_name: Optional[str] = None
    dba: Optional[str] = None
    address: Optional[str] = None
    year_established: Optional[int] = None
    entity_type: Optional[str] = None
    description: Optional[str] = Field(None, description="What the business does, 2-4 sentences, from the documents")
    products_services: list[str] = Field(default_factory=list)
    customers: list[str] = Field(default_factory=list)
    market: Optional[str] = None
    employees: Optional[int] = None
    detroit_residents_employed: Optional[int] = None
    jobs_created: Optional[int] = None
    jobs_retained: Optional[int] = None
    people: list[Person] = Field(default_factory=list)
    naics_suggestions: list[NaicsGuess] = Field(default_factory=list)
    space_owned_or_leased: Optional[str] = None
    other_lenders: list[str] = Field(default_factory=list)
    source_pages: list[str] = Field(default_factory=list, description="'doc p.N' references used")


# ---------------------------------------------------------------------------------------------
# CRE extraction
# ---------------------------------------------------------------------------------------------
CREKey = Literal[
    "gross_retail_rent", "retail_vacancy", "gross_office_rent", "office_vacancy",
    "gross_residential_rent", "residential_vacancy", "other_gross_rent", "other_vacancy",
    "cam_reimbursement", "other_income", "general_vacancy",
    "total_revenue", "management_fee", "leasing_marketing", "insurance", "trash", "cleaning", "maintenance",
    "turns", "cable", "re_taxes", "tax_abatement", "water", "gas_electric", "utilities", "payroll",
    "capital_reserves", "accounting", "asset_management", "replacement_reserves", "other_expense",
    "total_expenses", "noi",
]
REVENUE_KEYS = {"gross_retail_rent", "gross_office_rent", "gross_residential_rent", "other_gross_rent",
                "cam_reimbursement", "other_income"}
VACANCY_KEYS = {"retail_vacancy", "office_vacancy", "residential_vacancy", "other_vacancy", "general_vacancy"}
CRE_TOTAL_KEYS = {"total_revenue", "total_expenses", "noi"}


class ProjectionLine(BaseModel):
    key: CREKey
    label: str
    values: list[Optional[float]] = Field(description="One value per projection year, aligned with `years`. "
                                                     "Vacancy/abatement as negative numbers if printed in parentheses.")
    page: Optional[int] = None
    confidence: Confidence = None


class CREProjections(BaseModel):
    years: list[int] = Field(default_factory=list)
    column_source: str = Field("borrower", description="'borrower' for borrower projections")
    lines: list[ProjectionLine] = Field(default_factory=list)
    doc: Optional[str] = None
    notes: list[str] = Field(default_factory=list)


class RentRollUnit(BaseModel):
    unit: str
    use: Literal["retail", "office", "residential", "industrial", "other"] = "other"
    sf: Optional[float] = None
    annual_rent: Optional[float] = None
    status: Literal["leased", "loi", "vacant", "proposed"] = "proposed"
    tenant: Optional[str] = None
    lease_type: Literal["nnn", "gross", "modified_gross", "unknown"] = "unknown"
    page: Optional[int] = None


class BudgetLine(BaseModel):
    category: Literal["acquisition", "hard", "hard_contingency", "professional", "lender_carry",
                      "soft_contingency", "developer_fee", "reserves", "other_soft"]
    label: str
    amount: float
    page: Optional[int] = None


class SourceOfFunds(BaseModel):
    label: str
    amount: float
    kind: Literal["invest_detroit", "senior_debt", "other_debt", "equity", "grant", "tax_credit", "other"] = "other"


class Appraisal(BaseModel):
    appraiser: Optional[str] = None
    effective_date: Optional[str] = None
    as_is_value: Optional[float] = None
    as_completed_value: Optional[float] = None
    as_stabilized_value: Optional[float] = None
    stabilized_date: Optional[str] = None
    market_rent_office_psf: Optional[float] = None
    market_rent_retail_psf: Optional[float] = None
    vacancy_estimate: Optional[float] = None
    re_tax_estimate: Optional[float] = None
    cap_rate: Optional[float] = None


class LOI(BaseModel):
    tenant: str
    unit: Optional[str] = None
    sf: Optional[float] = None
    monthly_rent: Optional[float] = None
    term_years: Optional[float] = None
    renewal_options: Optional[str] = None
    lease_type: Literal["nnn", "gross", "modified_gross", "unknown"] = "unknown"
    use: Optional[str] = None


class Property(BaseModel):
    address: Optional[str] = None
    gross_sf: Optional[float] = None
    rentable_sf: Optional[float] = None
    property_type: Optional[str] = None
    use_mix: Optional[str] = None
    rehab_type: Literal["new_construction", "rehab", "gut_rehab", "adaptive_reuse", "acquisition"] = "rehab"
    occupancy_status: Optional[str] = None
    owner_occupied: bool = False


class TeamMember(BaseModel):
    name: str
    role: str
    description: Optional[str] = None


class CREData(BaseModel):
    property: Property = Field(default_factory=Property)
    rent_roll: list[RentRollUnit] = Field(default_factory=list)
    projections: CREProjections = Field(default_factory=CREProjections)
    budget: list[BudgetLine] = Field(default_factory=list)
    sources: list[SourceOfFunds] = Field(default_factory=list)
    appraisal: Appraisal = Field(default_factory=Appraisal)
    lois: list[LOI] = Field(default_factory=list)
    development_team: list[TeamMember] = Field(default_factory=list)
    development_status: Optional[str] = None


# ---------------------------------------------------------------------------------------------
# Underwriter / loan officer inputs
# ---------------------------------------------------------------------------------------------
class LoanTerms(BaseModel):
    label: str = "Invest Detroit loan"
    amount: float
    rate: float
    amort_months: int = 0  # 0 = interest only
    term_months: Optional[int] = None
    io_months: int = 0
    annual_payment_override: Optional[float] = Field(None, description="Use a stated payment instead of computing it")
    day_count: Literal["30/360", "actual/360"] = "30/360"


class DebtServiceLine(BaseModel):
    label: str
    default_amount: Optional[float] = None
    amounts: dict[str, float] = Field(default_factory=dict, description="period_id -> annual debt service")
    basis: Literal["scheduled", "actual_interest", "estimated"] = "scheduled"
    note: Optional[str] = None


class CollateralItem(BaseModel):
    description: str
    valuation_source: Optional[str] = None
    valuation_date: Optional[str] = None
    gross_value: float
    advance_rate: float = 1.0
    prior_liens: float = 0.0
    lien_position: Optional[str] = None


class ExposureItem(BaseModel):
    borrower: str
    amount: float
    fund: Optional[str] = None
    risk_rating: Optional[str] = None
    status: Optional[str] = None


class RiskScore(BaseModel):
    score: Optional[float] = None
    comment: Optional[str] = None


class DealOptions(BaseModel):
    include_nonrecurring_in_ebitda: bool = Field(True, description="Invest Detroit's Kirk's memo counted PPP forgiveness as cash income")
    treat_id_note_as_equity: bool = Field(True, description="Show Invest Detroit's subordinated note as quasi-equity (Sub-Debt) as in the Kirk's exhibits")
    cpltd_in_current: bool = Field(False, description="Invest Detroit's exhibits show term debt by creditor below current liabilities")
    ratio_inventory_days_basis: Literal["sales", "cogs"] = "sales"  # sample exhibit used sales
    exclude_from_tnw: list[str] = Field(default_factory=lambda: ["other_receivables", "prepaid_expenses", "intangible_assets"])
    target_dscr_takeout: float = 1.25


class DealTerms(BaseModel):
    deal_type: Literal["small_business", "cre"]
    product: str = "small_business_term"
    fund_name: Optional[str] = None
    borrower_name: Optional[str] = None
    borrower_address: Optional[str] = None
    salesforce_id: Optional[str] = None
    loan_number: Optional[str] = None
    ic_date: Optional[str] = None
    lender: Optional[str] = None
    analyst: Optional[str] = None
    request_summary: Optional[str] = None
    purpose: Optional[str] = None
    is_renewal: bool = False
    fee_pct: Optional[float] = None
    real_estate_secured: bool = True
    lien_position: Optional[str] = None
    proposed_loan: Optional[LoanTerms] = None
    takeout_loan: Optional[LoanTerms] = None
    debt_service_lines: list[DebtServiceLine] = Field(default_factory=list)
    debt_service_months: dict[str, int] = Field(default_factory=dict, description="CRE: year -> months of debt service")
    collateral: list[CollateralItem] = Field(default_factory=list)
    guarantors: list[str] = Field(default_factory=list)
    exposure: list[ExposureItem] = Field(default_factory=list)
    naics_code: Optional[str] = None
    projection_aggregate: Optional[dict] = Field(None, description="{'label':..., 'period_ids': [...]} to build a full-year forecast column")
    analysis_period_ids: list[str] = Field(default_factory=list, description="Historical columns to show (default: all actual/interim)")
    qualitative: dict[str, str] = Field(default_factory=dict, description="Underwriter-entered narrative facts by section key")
    risk_scores: dict[str, RiskScore] = Field(default_factory=dict)
    options: DealOptions = Field(default_factory=DealOptions)
    # CRE specifics
    re_tax_year1_override: Optional[float] = None
    one_time_expense_keys: list[str] = Field(default_factory=lambda: ["leasing_marketing"])
    sensitivity_line: Optional[str] = None
    documents_received: list[str] = Field(default_factory=list, description="Keys from Appendix C document checklist")


class DocumentRecord(BaseModel):
    name: str
    doc_type: str
    pages: Optional[int] = None
    classification_confidence: Confidence = None
    text_layer: Optional[bool] = None
    status: str = "received"


class Deal(BaseModel):
    schema_version: str = SCHEMA_VERSION
    id: str
    terms: DealTerms
    profile: BusinessProfile = Field(default_factory=BusinessProfile)
    financials: list[FinancialStatements] = Field(default_factory=list)
    cre: Optional[CREData] = None
    documents: list[DocumentRecord] = Field(default_factory=list)
    extraction_mode: Literal["llm", "fixture", "manual"] = "manual"
    extraction_log: list[str] = Field(default_factory=list)
