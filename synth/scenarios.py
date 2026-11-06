"""Synthetic borrower scenarios (fictional companies, fictional people). Safe to commit.

Each scenario varies industry, size, profitability, leverage, statement quality and presentation so that the
test loop exercises different engine paths and guideline outcomes.
"""
from __future__ import annotations

IC = "2026-11-15"
Y3 = [2023, 2024, 2025]


def people(*rows):
    return [{"name": n, "role": r, "ownership_pct": p, "guarantor": g, "background_check": b if b is not None else g,
             "passive": not g and p is not None and p >= 0.2, "bio": bio}
            for n, r, p, g, b, bio in rows]


def sb(id, name, naics, description, fin, loan, *, years=Y3, product="small_business_term", owners=None, collateral=None,
       quirks=None, year_established=2008, employees=20, customers=None, forecast=None, interim=None, qual=None,
       re_secured=False, fee=0.015, expect=None, lien="Senior lien on all business assets"):
    return {"id": id, "kind": "small_business", "name": name, "naics": naics, "description": description, "fin": fin,
            "loan": loan, "years": years, "product": product, "owners": owners or [], "collateral": collateral or [],
            "quirks": quirks or {}, "year_established": year_established, "employees": employees,
            "customers": customers or [], "forecast": forecast, "interim": interim, "qual": qual or {},
            "re_secured": re_secured, "fee": fee, "expect": expect or {}, "lien": lien}


def fin(revenue0, growth, cogs_pct, opex_fixed, dep, *, opex_var=0.0, ar_days=30, inv_days=0, ap_days=25, debts=None,
        loc=None, loc_rate=0.08, equity0=300_000, fa_gross0=400_000, accum_dep0=150_000, capex=None, tax_rate=0.0,
        other_income=None, nonrecurring=None, distributions=None, officer_comp=None, prepaid=10_000,
        related_receivable=0.0, other_assets=0.0, fa_classes=None, min_cash=25_000):
    n = len(cogs_pct)
    return {"revenue0": revenue0, "growth": growth, "cogs_pct": cogs_pct, "opex_fixed": opex_fixed, "dep": dep,
            "opex_var": opex_var, "ar_days": ar_days, "inv_days": inv_days, "ap_days": ap_days, "debts": debts or [],
            "loc": loc or [0] * n, "loc_rate": loc_rate, "equity0": equity0, "fa_gross0": fa_gross0,
            "accum_dep0": accum_dep0, "capex": capex or [0] * n, "tax_rate": tax_rate,
            "other_income": other_income or [0] * n, "nonrecurring": nonrecurring or {},
            "distributions": distributions or [0] * n, "officer_comp": officer_comp or [0] * n, "prepaid": prepaid,
            "related_receivable": related_receivable, "other_assets": other_assets,
            "fa_classes": fa_classes or {"Machinery & equipment": 0.7, "Furniture & fixtures": 0.1, "Leasehold improvements": 0.2},
            "min_cash": min_cash}


def debt(creditor, balance0, rate, remaining_months, *, kind="term_loan", subordinated=False, related=False, io=False):
    return {"creditor": creditor, "balance0": balance0, "rate": rate, "remaining_months": remaining_months, "kind": kind,
            "subordinated": subordinated, "related": related, "io": io}


def loan(amount, rate, amort, term=None, io=0):
    return {"amount": amount, "rate": rate, "amort_months": amort, "term_months": term or amort, "io_months": io}


SCENARIOS = [
    sb("sb01_auto_supplier", "Riverside Precision Stamping, Inc.", "336370",
       "Riverside Precision Stamping is a Tier 2 automotive supplier that produces metal stampings and welded assemblies "
       "for Tier 1 suppliers serving Ford, GM and Stellantis assembly plants in southeast Michigan.",
       fin(12_800_000, [0, 0.06, 0.04], [0.80, 0.79, 0.785], 1_350_000, [210_000, 225_000, 240_000], ar_days=48, inv_days=40,
           ap_days=35, tax_rate=0.21, equity0=1_900_000, fa_gross0=4_200_000, accum_dep0=2_300_000,
           debts=[debt("Huntington Bank equipment loan", 1_100_000, 0.065, 60)], loc=[600_000, 550_000, 500_000],
           officer_comp=[240_000, 250_000, 260_000], capex=[150_000, 300_000, 250_000]),
       loan(900_000, 0.0875, 84), owners=people(("Dana Okafor", "President", 0.55, True, None, "25 years in automotive stamping."),
                                                 ("Luis Ferreira", "VP Operations", 0.45, True, None, "Former plant manager.")),
       collateral=[{"description": "Press line equipment (new)", "valuation_source": "Vendor quote", "gross_value": 1_150_000, "advance_rate": 0.90}],
       quirks={"assurance": "review", "basis": "gaap"}, year_established=1987, employees=72,
       customers=["Lear Corporation", "Magna Seating", "Adient"], qual={"mission_alignment": "Retains 72 manufacturing jobs in Detroit's Delray neighborhood."},
       expect={"line_of_business": "C&I"}),
    sb("sb02_restaurant", "Fourteenth Street Kitchen LLC", "722511",
       "Fourteenth Street Kitchen is a full-service restaurant and bar in Corktown serving lunch, dinner and weekend brunch.",
       fin(1_650_000, [0, 0.08, 0.03], [0.33, 0.32, 0.325], 880_000, [38_000, 40_000, 42_000], opex_var=0.12, ar_days=3,
           inv_days=8, ap_days=20, equity0=120_000, fa_gross0=520_000, accum_dep0=240_000,
           debts=[debt("SBA 7(a) loan", 310_000, 0.0925, 96)], distributions=[40_000, 55_000, 60_000],
           officer_comp=[90_000, 95_000, 95_000]),
       loan(250_000, 0.095, 60), owners=people(("Maya Thompson", "Chef/Owner", 1.0, True, None, "Executive chef for 12 years.")),
       collateral=[{"description": "Kitchen equipment and FF&E", "valuation_source": "Cost less depreciation", "gross_value": 280_000, "advance_rate": 0.85}],
       quirks={"interest_location": "opex", "assurance": "compilation", "basis": "tax"}, year_established=2017, employees=34),
    sb("sb03_saas_startup", "Gridline Analytics, Inc.", "513210",
       "Gridline Analytics develops cloud software that helps municipal transit agencies schedule routes and "
       "forecast ridership. The company was founded in 2024 and sells annual subscriptions.",
       fin(450_000, [0, 1.60], [0.22, 0.20], 1_150_000, [12_000, 18_000], opex_var=0.05, ar_days=55, ap_days=30,
           equity0=1_600_000, fa_gross0=60_000, accum_dep0=5_000, prepaid=25_000),
       loan(400_000, 0.10, 60), years=[2024, 2025],
       owners=people(("Priya Raman", "CEO", 0.42, True, None, "Former transit data scientist."),
                     ("Marcus Bell", "CTO", 0.33, True, None, "Software engineer, 10 years."),
                     ("Motor City Seed Fund", "Investor", 0.25, False, False, None)),
       forecast={"years": [2026, 2027], "growth": [1.50, 0.90], "cogs_pct": [0.18, 0.17], "dep": [25_000, 30_000], "interest": [38_000, 32_000]},
       quirks={"assurance": "internal", "basis": "gaap"}, year_established=2024, employees=11,
       expect={"startup": True, "projection_flag": True}),
    sb("sb04_childcare", "Bright Steps Early Learning LLC", "624410",
       "Bright Steps operates two licensed child care centers on Detroit's east side serving infants through pre-K, "
       "with roughly 60% of enrollment funded by the state child care subsidy program.",
       fin(920_000, [0, 0.07, 0.05], [0.0, 0.0, 0.0], 790_000, [22_000, 24_000, 26_000], opex_var=0.08, ar_days=18, ap_days=15,
           equity0=95_000, fa_gross0=210_000, accum_dep0=60_000, nonrecurring={"2024": 85_000},
           debts=[debt("Community bank term loan", 120_000, 0.08, 48)], officer_comp=[70_000, 72_000, 75_000]),
       loan(180_000, 0.085, 60), owners=people(("Angela Rivers", "Director/Owner", 1.0, True, None, "Licensed early childhood educator.")),
       collateral=[{"description": "Furniture, fixtures and playground equipment", "gross_value": 140_000, "advance_rate": 0.85}],
       quirks={"assurance": "review", "basis": "gaap", "nonrec_label": "State child care stabilization grant"}, year_established=2015, employees=28),
    sb("sb05_brewery", "Eastern Market Brewing Co.", "312120",
       "Eastern Market Brewing Co. is a 15-barrel craft brewery with a taproom and wholesale distribution to "
       "120 bars and retailers in Michigan.",
       fin(2_250_000, [0, 0.05, 0.06], [0.42, 0.41, 0.40], 820_000, [110_000, 120_000, 135_000], opex_var=0.06, ar_days=28,
           inv_days=45, ap_days=30, equity0=480_000, fa_gross0=1_400_000, accum_dep0=520_000, tax_rate=0.21,
           debts=[debt("Equipment finance note", 420_000, 0.075, 60)], loc=[150_000, 175_000, 150_000], capex=[60_000, 120_000, 200_000]),
       loan(500_000, 0.0875, 84), owners=people(("Kevin Novak", "Head Brewer", 0.5, True, None, None), ("Sara Novak", "CEO", 0.5, True, None, None)),
       collateral=[{"description": "Brewhouse expansion equipment (new)", "gross_value": 560_000, "advance_rate": 0.90}],
       quirks={"assurance": "review", "basis": "gaap", "dep_location": "cf_only"}, year_established=2014, employees=26),
    sb("sb06_contractor", "Wolverine Electrical Contractors, Inc.", "238210",
       "Wolverine Electrical is a union electrical contractor performing commercial tenant build-outs and "
       "public works projects for the City of Detroit and Detroit Public Schools.",
       fin(6_400_000, [0, 0.12, 0.09], [0.76, 0.755, 0.75], 950_000, [65_000, 70_000, 80_000], ar_days=78, ap_days=45,
           equity0=1_100_000, fa_gross0=700_000, accum_dep0=380_000, tax_rate=0.21, loc=[700_000, 850_000, 900_000],
           debts=[debt("Truck loans", 180_000, 0.07, 36)], officer_comp=[180_000, 190_000, 200_000]),
       loan(750_000, 0.09, 60), owners=people(("Terrence Hall", "President", 0.8, True, None, "Master electrician."), ("Rosa Mendez", "Estimator", 0.2, True, None, None)),
       collateral=[{"description": "Accounts receivable and equipment (blanket lien)", "gross_value": 1_200_000, "advance_rate": 0.75}],
       quirks={"assurance": "review", "basis": "gaap"}, year_established=2001, employees=48, expect={"line_of_business": "C&I"}),
    sb("sb07_boutique", "Avenue Threads LLC", "458110",
       "Avenue Threads is a women's clothing and accessories boutique on the Avenue of Fashion (Livernois).",
       fin(415_000, [0, 0.04, 0.06], [0.55, 0.54, 0.54], 120_000, [6_000, 6_500, 7_000], opex_var=0.04, ar_days=2, inv_days=95,
           ap_days=30, equity0=60_000, fa_gross0=60_000, accum_dep0=25_000, distributions=[15_000, 18_000, 18_000]),
       loan(60_000, 0.10, 48), owners=people(("Tasha Greene", "Owner", 1.0, True, None, None)),
       quirks={"assurance": "compilation", "basis": "tax"}, year_established=2019, employees=4),
    sb("sb08_bigtech", "Northpoint Cloud Systems, Inc.", "541512",
       "Northpoint Cloud Systems is a national IT services and cloud integration firm opening a 300-person delivery "
       "center in downtown Detroit.",
       fin(85_000_000, [0, 0.11, 0.09], [0.58, 0.575, 0.57], 21_000_000, [1_800_000, 1_950_000, 2_100_000], ar_days=62, ap_days=30,
           equity0=24_000_000, fa_gross0=14_000_000, accum_dep0=6_500_000, tax_rate=0.25,
           debts=[debt("Syndicated term loan", 12_000_000, 0.072, 60)], loc=[2_000_000, 1_500_000, 1_000_000], officer_comp=[2_400_000, 2_600_000, 2_800_000]),
       loan(3_000_000, 0.08, 84), product="small_business_term",
       owners=people(("Northpoint Holdings LP", "Parent", 1.0, True, None, None)),
       collateral=[{"description": "Leasehold improvements and IT equipment", "gross_value": 3_400_000, "advance_rate": 0.85}],
       quirks={"assurance": "audit", "basis": "gaap", "units": 1000}, year_established=1998, employees=1400,
       expect={"line_of_business": "C&I", "exceptions": ["Loan amount"]}),
    sb("sb09_fitness", "Rise Up Fitness & Recreation LLC", "713940",
       "Rise Up operates a 22,000 SF fitness and recreation center with group classes, a youth basketball league and "
       "senior programs in the Brightmoor neighborhood.",
       fin(1_080_000, [0, -0.04, 0.02], [0.0, 0.0, 0.0], 840_000, [70_000, 72_000, 75_000], opex_var=0.10, ar_days=5, ap_days=20,
           equity0=140_000, fa_gross0=900_000, accum_dep0=310_000, distributions=[30_000, 20_000, 20_000],
           debts=[debt("Equipment lease", 160_000, 0.095, 36)]),
       loan(300_000, 0.0925, 72), owners=people(("Jerome Banks", "Owner", 0.65, True, None, None), ("Nicole Banks", "Owner", 0.35, True, None, None)),
       collateral=[{"description": "Fitness equipment", "gross_value": 260_000, "advance_rate": 0.85}],
       quirks={"assurance": "compilation", "basis": "tax"}, year_established=2012, employees=19, expect={"dscr_below_1": True}),
    sb("sb10_medical", "Westside Family Medicine PC", "621111",
       "Westside Family Medicine is a primary care practice with four physicians and two nurse practitioners, "
       "purchasing the building it currently leases.",
       fin(3_250_000, [0, 0.05, 0.05], [0.0, 0.0, 0.0], 2_050_000, [40_000, 42_000, 45_000], opex_var=0.18, ar_days=40, ap_days=15,
           equity0=520_000, fa_gross0=380_000, accum_dep0=200_000, officer_comp=[620_000, 650_000, 680_000],
           debts=[debt("Practice equipment loan", 90_000, 0.07, 30)]),
       loan(600_000, 0.0825, 300, term=84), re_secured=True, lien="1st mortgage on owner-occupied medical office building",
       owners=people(("Dr. Helen Cho", "Managing physician", 0.5, True, None, None), ("Dr. Samuel Adeyemi", "Physician", 0.5, True, None, None)),
       collateral=[{"description": "Medical office building (owner-occupied)", "valuation_source": "Appraisal (as-is)", "valuation_date": "2026-09-01", "gross_value": 780_000, "advance_rate": 1.0}],
       quirks={"assurance": "review", "basis": "cash"}, year_established=2006, employees=24),
    sb("sb11_trucking", "Lakeshore Freight Lines, Inc.", "484121",
       "Lakeshore Freight Lines is a regional truckload carrier with 38 tractors hauling automotive parts and "
       "consumer goods between Detroit, Ohio and Ontario.",
       fin(4_900_000, [0, 0.03, -0.02], [0.0, 0.0, 0.0], 380_000, [520_000, 540_000, 560_000], opex_var=0.74, ar_days=42, ap_days=20,
           equity0=900_000, fa_gross0=4_400_000, accum_dep0=2_100_000, tax_rate=0.21,
           debts=[debt("Tractor financing", 1_900_000, 0.068, 48)], loc=[250_000, 300_000, 300_000], capex=[500_000, 450_000, 400_000]),
       loan(850_000, 0.085, 60), fee=0.01, owners=people(("Gary Kowalski", "President", 1.0, True, None, None)),
       collateral=[{"description": "Tractors and trailers (used)", "gross_value": 1_050_000, "advance_rate": 0.85}],
       quirks={"assurance": "review", "basis": "gaap", "cpltd_shown": True}, year_established=1995, employees=52,
       expect={"exceptions": ["Origination / extension fee"]}),
    sb("sb12_struggling_mfg", "Dequindre Plastics Molding LLC", "326199",
       "Dequindre Plastics is an injection molder of plastic housings and trim components whose largest customer "
       "reduced orders in 2025.",
       fin(5_600_000, [0, -0.05, -0.12], [0.83, 0.85, 0.87], 650_000, [180_000, 185_000, 190_000], ar_days=55, inv_days=50, ap_days=48,
           equity0=700_000, fa_gross0=3_000_000, accum_dep0=1_800_000, debts=[debt("Equipment term loan", 950_000, 0.075, 54)],
           loc=[800_000, 950_000, 1_100_000]),
       loan(500_000, 0.095, 60), owners=people(("Frank DeLuca", "Owner", 0.7, True, None, None), ("Silent Partner LLC", "Investor", 0.3, False, False, None)),
       collateral=[{"description": "Molding machines (used)", "gross_value": 520_000, "advance_rate": 0.85}],
       quirks={"assurance": "review", "basis": "gaap"}, year_established=1999, employees=41, expect={"dscr_below_1": True, "declining": True}),
    sb("sb13_bakery_interim", "Hamtramck Avenue Bakery Inc.", "311812",
       "Hamtramck Avenue Bakery produces bread, paczki and pastries for its retail shop and for 40 grocery and "
       "restaurant wholesale accounts.",
       fin(1_900_000, [0, 0.07], [0.48, 0.47], 610_000, [55_000, 60_000], opex_var=0.05, ar_days=22, inv_days=12, ap_days=25,
           equity0=260_000, fa_gross0=650_000, accum_dep0=300_000, tax_rate=0.21, debts=[debt("Oven equipment loan", 200_000, 0.07, 48)]),
       loan(350_000, 0.0875, 84), years=[2024, 2025],
       interim={"year": 2026, "months": 6, "growth": 0.06, "cogs_pct": 0.465},
       forecast={"years": ["H2-2026"], "growth": [0.06], "cogs_pct": [0.46], "dep": [32_000], "interest": [24_000]},
       owners=people(("Ewa Nowak", "Owner", 1.0, True, None, None)),
       collateral=[{"description": "Bakery equipment", "gross_value": 410_000, "advance_rate": 0.85}],
       quirks={"assurance": "review", "basis": "gaap"}, year_established=1979, employees=22, expect={"aggregate": True}),
    sb("sb14_agency_erc", "Woodward Creative Group LLC", "541810",
       "Woodward Creative Group is a marketing and advertising agency serving regional healthcare and "
       "nonprofit clients.",
       fin(2_300_000, [0, -0.08, 0.05], [0.35, 0.37, 0.36], 1_250_000, [25_000, 26_000, 27_000], ar_days=65, ap_days=40,
           equity0=300_000, fa_gross0=180_000, accum_dep0=90_000, nonrecurring={"2023": 310_000},
           debts=[debt("EIDL loan", 150_000, 0.0375, 330)], officer_comp=[210_000, 200_000, 205_000]),
       loan(200_000, 0.095, 60), owners=people(("Jordan Wells", "Principal", 0.6, True, None, None), ("Ava Kim", "Principal", 0.4, True, None, None)),
       quirks={"assurance": "compilation", "basis": "tax", "nonrec_label": "Employee Retention Credit"}, year_established=2010, employees=17),
    sb("sb15_bowling", "Grand River Lanes & Entertainment LLC", "713950",
       "Grand River Lanes operates a 24-lane bowling center with an arcade, event space and restaurant, and is "
       "purchasing the building from its landlord.",
       fin(2_600_000, [0, 0.06, 0.04], [0.18, 0.18, 0.18], 1_350_000, [95_000, 98_000, 100_000], opex_var=0.12, ar_days=4, inv_days=6,
           ap_days=20, equity0=350_000, fa_gross0=1_200_000, accum_dep0=650_000, distributions=[60_000, 60_000, 70_000]),
       loan(950_000, 0.0775, 300, term=60), re_secured=True, lien="1st mortgage on 46,000 SF bowling center",
       owners=people(("Victor Russo", "Owner", 0.6, True, None, None), ("Linda Russo", "Owner", 0.4, True, None, None)),
       collateral=[{"description": "Bowling center real estate", "valuation_source": "Appraisal (as-is)", "valuation_date": "2026-08-15", "gross_value": 1_250_000, "advance_rate": 1.0}],
       quirks={"assurance": "review", "basis": "gaap"}, year_established=2003, employees=45),
    sb("sb16_restated", "Midtown Specialty Foods Inc.", "311999",
       "Midtown Specialty Foods manufactures shelf-stable sauces and spice blends sold to regional grocery chains.",
       fin(3_100_000, [0, 0.09, 0.07], [0.61, 0.60, 0.59], 780_000, [70_000, 75_000, 80_000], ar_days=40, inv_days=60, ap_days=35,
           equity0=650_000, fa_gross0=900_000, accum_dep0=400_000, tax_rate=0.21, debts=[debt("Equipment loan", 380_000, 0.07, 60)],
           loc=[200_000, 250_000, 300_000]),
       loan(450_000, 0.0875, 84), owners=people(("Omar Haddad", "CEO", 1.0, True, None, None)),
       collateral=[{"description": "Production equipment", "gross_value": 520_000, "advance_rate": 0.85}],
       quirks={"assurance": "review", "basis": "gaap", "split_docs": True}, year_established=2011, employees=30,
       expect={"restatement_flag": True}),
    sb("sb17_tax_return", "Fresh Cutz Barber Studio Inc.", "812111",
       "Fresh Cutz is a barber studio with eight chairs and a grooming product retail counter on the west side.",
       fin(510_000, [0, 0.05, 0.04], [0.06, 0.06, 0.06], 330_000, [9_000, 9_500, 10_000], opex_var=0.04, ar_days=0, ap_days=10,
           equity0=45_000, fa_gross0=90_000, accum_dep0=40_000, distributions=[25_000, 30_000, 30_000], officer_comp=[60_000, 62_000, 65_000]),
       loan(75_000, 0.10, 60), owners=people(("Darnell Price", "Owner", 1.0, True, None, None)),
       quirks={"assurance": "tax_return", "basis": "tax"}, year_established=2016, employees=9),
]


def cre(id, name, naics, description, c, loan_, *, product, takeout=None, owners=None, ds_months=None, fee=0.015,
        expect=None, qual=None, lien="1st real estate mortgage"):
    return {"id": id, "kind": "cre", "name": name, "naics": naics, "description": description, "cre": c, "loan": loan_,
            "takeout": takeout, "product": product, "owners": owners or [], "ds_months": ds_months or {}, "fee": fee,
            "expect": expect or {}, "qual": qual or {}, "re_secured": True, "lien": lien}


def units(prefix, use, n, sf, rent_psf):
    return [{"unit": f"{prefix} {i + 1}", "use": use, "sf": sf, "annual_rent": round(sf * rent_psf, -1)} for i in range(n)]


SCENARIOS += [
    cre("cre01_mixed_use", "Trumbull Lofts LLC", "531110",
        "Rehabilitation of a vacant three-story building into 2 ground-floor retail units and 6 apartments.",
        {"years": [2026, 2027, 2028, 2029, 2030], "gross_sf": 9_800, "rehab_type": "rehab",
         "units": units("Retail", "retail", 2, 1_200, 24) + units("Apt", "residential", 6, 850, 21),
         "rent_growth": 0.03, "vacancy": {"retail": 0.05, "residential": 0.05}, "year1_general_vacancy": 0.40,
         "mgmt_fee_pct": 0.05, "expenses": {"insurance": 9_000, "maintenance": 7_500, "utilities": 6_000, "accounting": 2_500},
         "re_taxes_borrower": 14_000, "leasing_marketing": 8_000, "replacement_reserves": 0, "capital_reserves": 0,
         "budget": {"acquisition": [("Building purchase", 380_000)], "hard": [("Construction contract", 1_450_000)],
                    "hard_contingency": [("Hard cost contingency", 217_500)], "professional": [("Architecture & engineering", 110_000)],
                    "lender_carry": [("Construction interest", 95_000), ("Closing costs", 35_000)], "soft_contingency": [("Soft contingency", 14_000)]},
         "equity": 801_500, "appraisal": {"as_stabilized_value": 2_600_000, "re_tax_estimate": 24_000, "vacancy_estimate": 0.08,
                                          "market_rent_retail_psf": 22, "market_rent_office_psf": None}},
        loan(1_500_000, 0.085, 300, term=60, io=18), product="construction_mini_perm",
        takeout={"amount": 1_250_000, "rate": 0.095, "amort_months": 300}, ds_months={"2026": 0, "2027": 6},
        owners=people(("Keisha Lambert", "Managing member", 0.6, True, None, "Developer of 4 Corktown rehabs."),
                      ("Tom Brennan", "Member", 0.4, True, None, None)),
        expect={"adjust": ["rent_growth_cap", "vacancy_floor", "re_tax", "one_time", "replacement_reserves"]}),
    cre("cre02_community_center", "Osborn Community Commons Inc.", "531120",
        "Acquisition and light rehab of a former school building leased to four nonprofit tenants and a "
        "community event hall operator.",
        {"years": [2026, 2027, 2028, 2029, 2030], "gross_sf": 32_000, "rehab_type": "rehab",
         "units": units("Suite", "office", 4, 5_500, 13) + units("Event hall", "other", 1, 8_000, 9),
         "rent_growth": 0.02, "vacancy": {"office": 0.15, "other": 0.20}, "mgmt_fee_pct": 0.04,
         "expenses": {"insurance": 22_000, "utilities": 48_000, "maintenance": 30_000, "cleaning": 18_000}, "expense_growth": 0.02,
         "re_taxes_borrower": 0, "capital_reserves": 17_000,
         "budget": {"acquisition": [("Acquisition", 900_000)], "hard": [("Roof, HVAC and accessibility", 600_000)],
                    "hard_contingency": [("Contingency", 90_000)], "professional": [("A&E and permits", 60_000)],
                    "lender_carry": [("Closing and carry", 50_000)], "soft_contingency": [("Soft contingency", 11_000)]},
         "equity": 136_000, "appraisal": {"as_stabilized_value": 2_000_000, "re_tax_estimate": None, "vacancy_estimate": 0.15}},
        loan(1_575_000, 0.08, 300, term=60), product="cre_term",
        owners=people(("Osborn Neighborhood Alliance", "Sole member (nonprofit)", 1.0, True, None, None)),
        expect={"exceptions": ["Min equity"]}),
    cre("cre03_multifamily_new", "Grand Boulevard Residences LLC", "531110",
        "New construction of a 24-unit apartment building with 20% of units affordable at 80% AMI.",
        {"years": [2026, 2027, 2028, 2029, 2030], "gross_sf": 22_000, "rehab_type": "new_construction",
         "units": units("Unit", "residential", 24, 780, 22), "rent_growth": 0.02, "vacancy": {"residential": 0.07},
         "year1_general_vacancy": 0.55, "mgmt_fee_pct": 0.06,
         "expenses": {"insurance": 28_000, "utilities": 26_000, "maintenance": 22_000, "payroll": 30_000},
         "re_taxes_borrower": 48_000, "leasing_marketing": 15_000, "replacement_reserves": 7_200,
         "budget": {"acquisition": [("Land", 250_000)], "hard": [("GMP construction contract", 3_600_000)],
                    "hard_contingency": [("Hard contingency (10%)", 360_000)], "professional": [("A&E", 240_000), ("Permits", 60_000)],
                    "lender_carry": [("Construction interest", 210_000), ("Financing fees", 60_000)], "soft_contingency": [("Soft contingency (5%)", 28_500)]},
         "equity": 2_408_500, "appraisal": {"as_stabilized_value": 5_400_000, "re_tax_estimate": 52_000, "vacancy_estimate": 0.06}},
        loan(2_400_000, 0.0875, 300, term=84, io=24), product="construction_mini_perm",
        takeout={"amount": 2_300_000, "rate": 0.075, "amort_months": 360}, ds_months={"2026": 0, "2027": 6},
        owners=people(("Boulevard Housing Partners LLC", "Developer", 0.51, True, None, None),
                      ("Impact Equity Fund II", "LP investor", 0.49, False, False, None))),
    cre("cre04_warehouse", "Conner Creek Logistics Center LLC", "531120",
        "Acquisition of a 60,000 SF single-tenant warehouse leased on a NNN basis to a third-party logistics firm.",
        {"years": [2027, 2028, 2029, 2030, 2031], "gross_sf": 60_000, "rehab_type": "acquisition",
         "units": [{"unit": "Warehouse (single tenant)", "use": "other", "sf": 60_000, "annual_rent": 330_000}],
         "rent_growth": 0.025, "vacancy": {"other": 0.0}, "mgmt_fee_pct": 0.03,
         "expenses": {"insurance": 18_000, "maintenance": 12_000}, "re_taxes_borrower": 45_000, "capital_reserves": 10_000,
         "budget": {"acquisition": [("Purchase price", 2_300_000), ("Closing costs", 40_000)], "professional": [("Due diligence", 25_000)],
                    "lender_carry": [("Lender fees", 35_000)]},
         "equity": 400_000, "appraisal": {"as_stabilized_value": 2_500_000, "re_tax_estimate": 45_000, "vacancy_estimate": 0.10}},
        loan(2_000_000, 0.0825, 300, term=60), product="cre_term",
        owners=people(("Rachel Stein", "Managing member", 0.3, True, None, None), ("Conner Partners LP", "Investor", 0.7, True, None, None)),
        expect={"adjust": ["vacancy_floor", "rent_growth_cap"]}),
    cre("cre05_sports_complex", "Rouge Park Sports Complex LLC", "531120",
        "New construction of an indoor turf and court facility leased to a youth sports operator and a physical therapy clinic.",
        {"years": [2027, 2028, 2029, 2030, 2031], "gross_sf": 48_000, "rehab_type": "new_construction",
         "units": [{"unit": "Sports operator", "use": "other", "sf": 42_000, "annual_rent": 290_000},
                   {"unit": "PT clinic", "use": "office", "sf": 6_000, "annual_rent": 132_000}],
         "rent_growth": 0.03, "vacancy": {"other": 0.05, "office": 0.10}, "mgmt_fee_pct": 0.04,
         "expenses": {"insurance": 30_000, "utilities": 40_000, "maintenance": 25_000}, "re_taxes_borrower": 30_000, "expense_growth": 0.025,
         "replacement_reserves": 0, "capital_reserves": 0,
         "budget": {"acquisition": [("Land", 300_000)], "hard": [("Construction", 2_100_000)], "hard_contingency": [("Contingency", 168_000)],
                    "professional": [("A&E", 150_000)], "lender_carry": [("Interest reserve", 160_000)], "soft_contingency": [("Soft contingency", 9_000)]},
         "equity": 237_000, "appraisal": {"as_stabilized_value": 3_200_000, "re_tax_estimate": 61_000, "vacancy_estimate": 0.10}},
        loan(2_650_000, 0.09, 300, term=84, io=18), product="construction_mini_perm", ds_months={"2027": 6},
        owners=people(("Andre Coleman", "Managing member", 0.25, True, None, None), ("Westside Capital LLC", "Passive investor", 0.75, False, False, None)),
        expect={"oversight": True}),
    cre("cre06_office_conversion", "Lafayette Tower Residences LLC", "531110",
        "Adaptive reuse of a vacant 1920s office building into 40 apartments with ground-floor retail.",
        {"years": [2027, 2028, 2029, 2030, 2031], "gross_sf": 46_000, "rehab_type": "adaptive_reuse",
         "units": units("Apt", "residential", 40, 750, 24) + units("Retail", "retail", 2, 2_000, 20),
         "rent_growth": 0.02, "vacancy": {"residential": 0.08, "retail": 0.12}, "year1_general_vacancy": 0.50, "mgmt_fee_pct": 0.05,
         "expenses": {"insurance": 45_000, "utilities": 60_000, "maintenance": 40_000, "payroll": 55_000, "other_expense": 12_000},
         "re_taxes_borrower": 70_000, "leasing_marketing": 20_000, "replacement_reserves": 23_000,
         "budget": {"acquisition": [("Building", 1_200_000)], "hard": [("Rehab contract", 6_800_000)], "hard_contingency": [("Contingency (15%)", 1_020_000)],
                    "professional": [("A&E", 420_000), ("Historic consultant", 60_000)], "lender_carry": [("Interest and fees", 520_000)],
                    "soft_contingency": [("Soft contingency (10%)", 100_000)]},
         "equity": 7_520_000, "appraisal": {"as_stabilized_value": 11_500_000, "re_tax_estimate": 95_000, "vacancy_estimate": 0.07,
                                            "market_rent_retail_psf": 20}},
        loan(2_600_000, 0.085, 300, term=84, io=24), product="construction_mini_perm",
        takeout={"amount": 2_600_000, "rate": 0.075, "amort_months": 360}, ds_months={"2027": 0, "2028": 6},
        owners=people(("Lafayette Development LLC", "Developer", 1.0, True, None, None)),
        expect={"exceptions": ["Loan amount"]}),
]


def by_id(sid: str) -> dict:
    return next(s for s in SCENARIOS if s["id"] == sid)
