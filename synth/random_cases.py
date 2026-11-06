"""Procedurally generated borrowers for broad testing (fictional; deterministic by seed)."""
from __future__ import annotations

import random

from .scenarios import cre, debt, fin, loan, people, sb, units

INDUSTRIES = [  # (naics, label, cogs range, opex_var, ar_days, inv_days, description)
    ("336390", "auto parts manufacturer", (0.72, 0.84), 0.02, 50, 45, "manufactures automotive components for Tier 1 suppliers"),
    ("332710", "machine shop", (0.62, 0.75), 0.02, 45, 30, "provides CNC machining services to industrial customers"),
    ("311812", "commercial bakery", (0.42, 0.52), 0.05, 20, 10, "bakes bread and pastries for grocery and restaurant accounts"),
    ("722511", "full-service restaurant", (0.28, 0.36), 0.14, 3, 6, "operates a full-service restaurant"),
    ("722515", "coffee shop", (0.30, 0.38), 0.12, 2, 8, "operates a neighborhood cafe and coffee roastery"),
    ("445110", "neighborhood grocery store", (0.70, 0.76), 0.06, 2, 20, "operates a full-service neighborhood grocery store"),
    ("458110", "clothing boutique", (0.50, 0.60), 0.05, 2, 90, "sells apparel and accessories"),
    ("513210", "software company", (0.15, 0.30), 0.06, 50, 0, "develops subscription software"),
    ("541512", "IT services firm", (0.50, 0.62), 0.03, 60, 0, "provides IT consulting and managed services"),
    ("541810", "advertising agency", (0.30, 0.42), 0.03, 60, 0, "provides marketing and advertising services"),
    ("624410", "child care center", (0.0, 0.0), 0.08, 15, 0, "operates licensed child care centers"),
    ("621111", "physician practice", (0.0, 0.0), 0.15, 40, 0, "operates a primary care medical practice"),
    ("713940", "fitness and recreation center", (0.0, 0.0), 0.10, 4, 0, "operates a fitness and recreation center"),
    ("713950", "bowling and entertainment center", (0.15, 0.22), 0.12, 4, 5, "operates a bowling and family entertainment center"),
    ("238220", "plumbing and HVAC contractor", (0.70, 0.80), 0.02, 70, 10, "performs plumbing and HVAC installation"),
    ("484121", "trucking company", (0.0, 0.0), 0.72, 40, 0, "operates a regional truckload carrier"),
    ("812111", "barber shop", (0.04, 0.08), 0.04, 0, 3, "operates a barber shop"),
    ("312120", "craft brewery", (0.38, 0.46), 0.06, 28, 45, "brews and distributes craft beer"),
    ("423120", "auto parts distributor", (0.74, 0.82), 0.03, 45, 70, "distributes automotive replacement parts"),
    ("811111", "auto repair shop", (0.40, 0.50), 0.05, 10, 15, "provides general automotive repair"),
    ("326199", "plastics molder", (0.78, 0.86), 0.02, 55, 45, "produces injection-molded plastic components"),
    ("561720", "commercial cleaning company", (0.0, 0.0), 0.62, 45, 0, "provides janitorial services to offices and schools"),
    ("611710", "education support services", (0.0, 0.0), 0.20, 30, 0, "provides tutoring and workforce training"),
    ("334513", "instrument manufacturer", (0.55, 0.65), 0.03, 55, 60, "manufactures industrial measurement instruments"),
]
FIRST = ["Lakeview", "Corktown", "Midtown", "Riverbend", "Woodward", "Gratiot", "Livernois", "Belle Isle", "Rosedale", "Jefferson",
         "Grand River", "Southwest", "North End", "Eastside", "Palmer Park", "Brush Park", "Delray", "Mexicantown", "Fenkell", "Conant"]
PEOPLE = ["Alex Morgan", "Jamie Lee", "Chris Patel", "Taylor Brooks", "Jordan Rivera", "Casey Nguyen", "Morgan Davis",
          "Riley Johnson", "Avery Wilson", "Quinn Carter", "Drew Hassan", "Sam Okoye", "Robin Kowalski", "Jesse Ramirez"]


def _owners(rng):
    k = rng.choice([1, 1, 2, 2, 3])
    shares = [rng.random() + 0.2 for _ in range(k)]
    tot = sum(shares)
    shares = [round(s / tot, 2) for s in shares]
    shares[-1] = round(1 - sum(shares[:-1]), 2)
    rows = []
    names = rng.sample(PEOPLE, k)
    for i, (nm, sh) in enumerate(zip(names, shares)):
        g = i == 0 or rng.random() < 0.8
        b = g or rng.random() < 0.5
        rows.append((nm, "Owner" if g else "Investor", sh, g, b, None))
    return people(*rows)


def random_sb(i: int, rng: random.Random):
    naics, label, (c0, c1), opv, ar, inv, desc = rng.choice(INDUSTRIES)
    size = 10 ** rng.uniform(5.2, 7.9)              # $160K .. $80M revenue
    n = rng.choice([1, 2, 3, 3, 3])
    years = [2026 - n + k for k in range(n)]
    growth = [0] + [rng.uniform(-0.25, 0.35) for _ in range(n - 1)]
    cogs = [rng.uniform(c0, c1) if c1 else 0.0 for _ in range(n)]
    target = rng.uniform(-0.08, 0.22)               # EBITDA margin before fixed-cost calibration
    gm = 1 - sum(cogs) / n
    dep = [size * rng.uniform(0.005, 0.05)] * n
    opex_fixed = max(size * (gm - opv - target), size * 0.03)
    debts = []
    for k in range(rng.choice([0, 1, 1, 2, 3])):
        debts.append(debt(rng.choice(["Bank term loan", "Equipment note", "SBA 7(a) loan", "Vehicle loans", "Seller note"]) + f" {k + 1}",
                          size * rng.uniform(0.02, 0.25), rng.uniform(0.04, 0.11), rng.randrange(18, 120),
                          subordinated=rng.random() < 0.15, related=rng.random() < 0.1))
    has_id = rng.random() < 0.15
    if has_id:
        debts.append({**debt("Invest Detroit (existing loan)", size * rng.uniform(0.03, 0.12), 0.07, rng.randrange(24, 72)), "is_id": True})
    loc = [size * rng.uniform(0, 0.12) if rng.random() < 0.5 else 0.0 for _ in range(n)]
    f = fin(size, growth, cogs, opex_fixed, dep, opex_var=opv, ar_days=ar * rng.uniform(0.6, 1.4), inv_days=inv * rng.uniform(0.5, 1.5),
            ap_days=rng.uniform(15, 50), debts=debts, loc=loc, equity0=size * rng.uniform(-0.05, 0.5),
            fa_gross0=size * rng.uniform(0.05, 0.6), accum_dep0=size * rng.uniform(0.02, 0.3), tax_rate=rng.choice([0, 0, 0.21]),
            nonrecurring={str(years[-1]): size * rng.uniform(0.01, 0.08)} if rng.random() < 0.2 else {},
            distributions=[size * rng.uniform(0, 0.04)] * n if rng.random() < 0.35 else None,
            officer_comp=[size * rng.uniform(0.02, 0.1)] * n if rng.random() < 0.6 else None,
            related_receivable=size * 0.02 if rng.random() < 0.15 else 0.0, other_assets=size * 0.01 if rng.random() < 0.3 else 0.0,
            other_income=[size * rng.uniform(0, 0.01)] * n if rng.random() < 0.3 else None)
    product = "revolving_loc" if rng.random() < 0.12 else "small_business_term"
    amt = round(min(max(size * rng.uniform(0.03, 0.3), 25_000), 3_500_000), -3)
    if product == "revolving_loc":
        L = loan(min(amt, 1_200_000), rng.uniform(0.075, 0.105), 0, term=rng.choice([12, 18, 24]))
    else:
        am = rng.choice([36, 48, 60, 84, 120])
        L = loan(amt, rng.choice([rng.uniform(0.075, 0.105), rng.uniform(0.06, 0.12)]), am, term=rng.choice([am, 60, 84, 96]))
    re_sec = rng.random() < 0.3
    quirks = {"assurance": rng.choice(["audit", "review", "review", "compilation", "no_assurance", "internal", "tax_return"]),
              "basis": rng.choice(["gaap", "tax", "cash"]), "interest_location": "opex" if rng.random() < 0.25 else "other",
              "dep_location": "cf_only" if rng.random() < 0.3 else "schedule", "units": 1000 if size > 2e7 and rng.random() < 0.6 else 1,
              "split_docs": n >= 3 and rng.random() < 0.15, "no_naics_hint": rng.random() < 0.15, "no_bs_first_year": n >= 2 and rng.random() < 0.15}
    est = rng.choice([1950, 1985, 2002, 2012, 2018, 2021, 2024, 2025]) if n < 3 else rng.choice([1950, 1985, 2002, 2012, 2018])
    est = min(est, years[0])
    forecast = None
    if rng.random() < 0.25:
        k = rng.choice([1, 2, 3])
        forecast = {"years": [2026 + j for j in range(k)], "growth": [rng.uniform(-0.05, 0.9) for _ in range(k)],
                    "cogs_pct": [cogs[-1]] * k, "dep": [dep[-1]] * k, "interest": [size * 0.01] * k}
    coll = [{"description": "Business assets" if not re_sec else "Owner-occupied real estate", "gross_value": amt * rng.uniform(0.6, 2.0),
             "advance_rate": rng.choice([1.0, 0.9, 0.85]), "prior_liens": amt * rng.uniform(0, 0.5) if rng.random() < 0.2 else 0.0}]
    name = f"{rng.choice(FIRST)} {label.title()} {rng.choice(['LLC', 'Inc.', 'Co.'])}"
    return sb(f"r{i:03d}_sb", name, naics, f"{name} {desc} in Detroit.", f, L, years=years, product=product, owners=_owners(rng),
              collateral=coll, quirks=quirks, year_established=est, employees=max(2, int(size / 120_000)), forecast=forecast,
              re_secured=re_sec, fee=rng.choice([0.015, 0.015, 0.01, 0.02, None]))


def random_cre(i: int, rng: random.Random):
    mix = rng.choice([["retail"], ["office"], ["residential"], ["other"], ["retail", "residential"], ["retail", "office"],
                      ["office", "other"], ["residential", "retail", "office"]])
    us = []
    rent = {"retail": (14, 38), "office": (12, 160), "residential": (14, 30), "other": (5, 14)}
    for use in mix:
        k = rng.randrange(1, 30 if use == "residential" else 8)
        sf = rng.uniform(400, 1_100) if use == "residential" else rng.uniform(500, 20_000 if use == "other" else 4_000)
        us += units(use.title(), use, k, round(sf, -1), rng.uniform(*rent[use]))
    rsf = sum(u["sf"] for u in us)
    gross_rent = sum(u["annual_rent"] for u in us)
    rehab = rng.choice(["rehab", "adaptive_reuse", "gut_rehab", "new_construction", "acquisition"])
    yrs = [2027 + k for k in range(5)]
    hard = 0 if rehab == "acquisition" else rsf * rng.uniform(80, 320)
    acq = rsf * rng.uniform(20, 120) if rehab != "new_construction" else rsf * rng.uniform(5, 30)
    prof = hard * rng.uniform(0.04, 0.10) + 15_000
    carry = (hard + acq) * rng.uniform(0.03, 0.08)
    budget = {"acquisition": [("Acquisition", round(acq, -2))], "professional": [("Professional fees", round(prof, -2))],
              "lender_carry": [("Lender and carrying costs", round(carry, -2))]}
    if hard:
        budget["hard"] = [("Construction", round(hard, -2))]
        budget["hard_contingency"] = [("Hard contingency", round(hard * rng.uniform(0.0, 0.2), -2))]
        budget["soft_contingency"] = [("Soft contingency", round((prof + carry) * rng.uniform(0.0, 0.14), -2))]
    total = sum(a for v in budget.values() for _, a in v)
    loan_amt = round(total * rng.uniform(0.35, 0.95), -3)
    equity = total - loan_amt
    noi_guess = gross_rent * 0.55
    value = noi_guess / rng.uniform(0.065, 0.10)
    io = rng.choice([0, 0, 12, 18, 24]) if rehab != "acquisition" else 0
    takeout = {"amount": round(loan_amt * rng.uniform(0.8, 1.2), -3), "rate": rng.uniform(0.065, 0.11), "amort_months": rng.choice([300, 360])} \
        if rng.random() < 0.5 else None
    lease_up = rng.choice([0, 0, 0.3, 0.5, 0.6]) if rehab != "acquisition" else 0
    c = {"years": yrs, "gross_sf": round(rsf * rng.uniform(1.0, 1.4)), "rehab_type": rehab, "units": us,
         "rent_growth": rng.choice([0.01, 0.02, 0.02, 0.03, 0.04]), "vacancy": {u: rng.choice([0, 0.05, 0.1, 0.15, 0.2]) for u in mix},
         "year1_general_vacancy": lease_up, "mgmt_fee_pct": rng.choice([0.03, 0.04, 0.05, 0.06]),
         "cam": gross_rent * 0.1 if "retail" in mix and rng.random() < 0.5 else 0,
         "expenses": {"insurance": gross_rent * rng.uniform(0.03, 0.08), "maintenance": gross_rent * rng.uniform(0.03, 0.08),
                      "utilities": gross_rent * rng.uniform(0.0, 0.1)},
         "expense_growth": rng.choice([0.02, 0.025, 0.03, 0.03, 0.035]), "re_taxes_borrower": gross_rent * rng.uniform(0.05, 0.14),
         "leasing_marketing": gross_rent * 0.03 if rng.random() < 0.4 else 0, "replacement_reserves": rsf * rng.choice([0, 0, 0.25, 0.5, 0.75]),
         "capital_reserves": rsf * rng.choice([0, 0, 0.3, 0.6]), "budget": budget, "equity": equity,
         "appraisal": {"as_stabilized_value": round(value, -3), "re_tax_estimate": gross_rent * rng.uniform(0.05, 0.16) if rng.random() < 0.6 else None,
                       "vacancy_estimate": rng.choice([0.05, 0.08, 0.1, 0.12])}}
    if not c["capital_reserves"]:
        c.pop("capital_reserves")
    else:
        c["expenses"]["capital_reserves"] = c.pop("capital_reserves")
    product = "construction_mini_perm" if rehab in ("rehab", "adaptive_reuse", "gut_rehab", "new_construction") else "cre_term"
    ds_months = {}
    if io:
        ds_months = {"2027": 0 if io >= 12 else 6, "2028": 12 if io < 18 else 6}
    L = loan(loan_amt, rng.uniform(0.07, 0.10), rng.choice([300, 300, 360]), term=rng.choice([60, 84, 96]), io=io)
    nm = f"{rng.choice(FIRST)} {rng.choice(['Commons', 'Lofts', 'Center', 'Building', 'Residences', 'Plaza'])} LLC"
    naics = "531110" if mix == ["residential"] else "531120"
    return cre(f"r{i:03d}_cre", nm, naics, f"{rehab.replace('_', ' ').title()} project: {', '.join(mix)} space in Detroit.", c, L,
               product=product, takeout=takeout, owners=_owners(rng), ds_months=ds_months, fee=rng.choice([0.015, 0.01, 0.02]))


def random_scenarios(n_sb=150, n_cre=60, seed=2026):
    rng = random.Random(seed)
    return [random_sb(i, rng) for i in range(n_sb)] + [random_cre(i, rng) for i in range(n_cre)]
