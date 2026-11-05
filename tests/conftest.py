"""Synthetic deals for tests (no real borrower data — safe to commit)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from underwriter.schema import Deal  # noqa: E402


def li(key, pid, value, label=None, page=1):
    return {"key": key, "label": label or key, "period_id": pid, "value": value, "page": page, "doc": "synthetic.pdf", "confidence": 0.95}


@pytest.fixture
def sb_deal() -> Deal:
    L = []
    for pid, rev, cogs, opex, oi, nonrec, intr, dep, tax in [("FY2022", 2_000_000, 1_200_000, 600_000, 10_000, 0, 40_000, 30_000, 0),
                                                            ("FY2023", 2_200_000, 1_320_000, 640_000, 12_000, 50_000, 38_000, 32_000, 5_000)]:
        ni = rev - cogs - opex + oi + nonrec - intr - tax
        L += [li("revenue", pid, rev), li("cogs", pid, cogs), li("operating_expenses", pid, opex), li("other_income", pid, oi),
              li("nonrecurring_income", pid, nonrec), li("interest_expense", pid, intr), li("income_taxes", pid, tax),
              li("net_income", pid, ni), li("depreciation", pid, dep), li("officer_compensation", pid, 120_000)]
    bs = {"FY2022": dict(cash=100_000, ar=250_000, inv=300_000, fa=500_000, acc=-200_000, ap=150_000, accr=50_000, loc=200_000, cpltd=0, ltd=400_000, te=150_000),
          "FY2023": dict(cash=120_000, ar=260_000, inv=310_000, fa=520_000, acc=-230_000, ap=160_000, accr=55_000, loc=180_000, cpltd=0, ltd=360_000, te=225_000)}
    for pid, v in bs.items():
        ta = v["cash"] + v["ar"] + v["inv"] + v["fa"] + v["acc"]
        L += [li("cash", pid, v["cash"]), li("accounts_receivable", pid, v["ar"]), li("inventory", pid, v["inv"]),
              li("fixed_assets_gross", pid, v["fa"], "Equipment"), li("accumulated_depreciation", pid, v["acc"]),
              li("total_assets", pid, ta), li("accounts_payable", pid, v["ap"]), li("accrued_expenses", pid, v["accr"]),
              li("line_of_credit", pid, v["loc"]), li("long_term_debt", pid, v["ltd"]),
              li("total_equity", pid, ta - v["ap"] - v["accr"] - v["loc"] - v["ltd"])]
    fs = {"doc": "synthetic.pdf", "statement_info": {"assurance": "review", "basis": "gaap"},
          "periods": [{"id": "FY2022", "label": "FYE 12/31/22", "end_date": "2022-12-31"},
                      {"id": "FY2023", "label": "FYE 12/31/23", "end_date": "2023-12-31"}],
          "line_items": L,
          "debts": [{"creditor": "Bank term loan", "kind": "term_loan", "balances": [{"period_id": "FY2023", "value": 360_000}],
                     "monthly_payment": 9_000}]}
    terms = {"deal_type": "small_business", "product": "small_business_term", "borrower_name": "Synthetic Widgets LLC",
             "proposed_loan": {"amount": 250_000, "rate": 0.09, "amort_months": 60, "term_months": 60},
             "debt_service_lines": [{"label": "Bank term loan", "default_amount": 108_000}],
             "collateral": [{"description": "Equipment", "gross_value": 400_000, "advance_rate": 0.85}],
             "fee_pct": 0.015, "real_estate_secured": False}
    profile = {"legal_name": "Synthetic Widgets LLC", "description": "Commercial bakery producing bread and pastries for wholesale customers.",
               "naics_suggestions": [{"code": "311812", "title": "Commercial Bakeries", "confidence": 0.8}],
               "people": [{"name": "Owner A", "ownership_pct": 0.6, "guarantor": True}, {"name": "Owner B", "ownership_pct": 0.4, "guarantor": False}]}
    return Deal.model_validate({"id": "synthetic-sb", "terms": terms, "profile": profile, "financials": [fs]})


@pytest.fixture
def cre_deal() -> Deal:
    yrs = [2026, 2027, 2028]
    g = lambda base, r: [round(base * (1 + r) ** t) for t in range(3)]
    lines = [
        {"key": "gross_office_rent", "label": "Office Rent", "values": g(200_000, 0.02)},
        {"key": "office_vacancy", "label": "Less: Office Vacancy", "values": [-v * 0.10 for v in g(200_000, 0.02)]},
        {"key": "general_vacancy", "label": "Less: Lease-up Vacancy", "values": [-60_000, 0, 0]},
        {"key": "management_fee", "label": "Management", "values": g(8_000, 0.03)},
        {"key": "insurance", "label": "Insurance", "values": g(10_000, 0.02)},   # below 3% growth -> floored
        {"key": "re_taxes", "label": "Real Estate Taxes", "values": g(15_000, 0.03)},
        {"key": "leasing_marketing", "label": "Leasing & Marketing", "values": g(5_000, 0.03)},
        {"key": "capital_reserves", "label": "Capital Reserves", "values": g(1_000, 0.03)},
    ]
    cre = {"property": {"gross_sf": 4000, "rentable_sf": 3500, "rehab_type": "rehab"},
           "rent_roll": [{"unit": "Suite 1", "use": "office", "sf": 3500, "annual_rent": 200_000}],
           "projections": {"years": yrs, "lines": lines, "doc": "proj.pdf"},
           "budget": [{"category": "acquisition", "label": "Land & building", "amount": 500_000},
                      {"category": "hard", "label": "Construction", "amount": 1_000_000},
                      {"category": "hard_contingency", "label": "Contingency (10%)", "amount": 100_000},
                      {"category": "professional", "label": "A&E", "amount": 100_000},
                      {"category": "soft_contingency", "label": "Soft contingency", "amount": 10_000}],
           "sources": [{"label": "Invest Detroit Loan", "amount": 1_000_000, "kind": "invest_detroit"},
                       {"label": "Owner Equity", "amount": 710_000, "kind": "equity"}],
           "appraisal": {"as_stabilized_value": 2_000_000, "re_tax_estimate": 20_000, "vacancy_estimate": 0.12, "market_rent_office_psf": 50}}
    terms = {"deal_type": "cre", "product": "construction_mini_perm", "borrower_name": "Synthetic Property LLC",
             "proposed_loan": {"label": "ID Loan", "amount": 1_000_000, "rate": 0.085, "amort_months": 300},
             "debt_service_months": {"2026": 6},
             "collateral": [{"description": "Real estate", "gross_value": 2_000_000}], "fee_pct": 0.015}
    profile = {"legal_name": "Synthetic Property LLC",
               "people": [{"name": "Sponsor", "ownership_pct": 0.5, "guarantor": True, "background_check": True},
                          {"name": "Passive Fund", "ownership_pct": 0.5, "guarantor": False, "background_check": False, "passive": True}]}
    return Deal.model_validate({"id": "synthetic-cre", "terms": terms, "profile": profile, "cre": cre})
