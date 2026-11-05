"""Build config/irs_soi_benchmarks.json and config/naics_2022.json from public source files.

Sources (public, free):
  - IRS Statistics of Income, Corporation Complete Report, Table 5.1 "Returns of Active Corporations:
    Balance Sheet, Income Statement, Tax, and Selected Other Items, by Major Industry" (tax years 2020-2022)
    https://www.irs.gov/pub/irs-soi/22co51ccr.xlsx (and 21co51ccr.xlsx, 20co51ccr.xlsx)
  - U.S. Census Bureau 2022 NAICS codes and index file
    https://www.census.gov/naics/2022NAICS/2-6%20digit_2022_Codes.xlsx
    https://www.census.gov/naics/2022NAICS/2022_NAICS_Index_File.xlsx

Usage:
  mkdir -p data/raw && (download the files above into data/raw/)
  python scripts/build_benchmarks.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "config"

SOI_URL = "https://www.irs.gov/pub/irs-soi/{yy}co51ccr.xlsx"
YEARS = [2020, 2021, 2022]

# SOI Table 5.1 industry column label -> 2022 NAICS prefixes it covers.
# Lookup uses the longest matching prefix, so sector totals act as fallbacks.
INDUSTRY_NAICS: dict[str, list[str]] = {
    # sector totals (sector name -> 2-digit codes)
    "Agriculture, forestry, fishing, and hunting|Total": ["11"],
    "Mining|Total": ["21"],
    "Utilities|Total": ["22"],
    "Construction|Total": ["23"],
    "Manufacturing|Total": ["31", "32", "33"],
    "Wholesale trade|Total": ["42"],
    "Retail trade|Total": ["44", "45"],
    "Transportation and warehousing|Total": ["48", "49"],
    "Information|Total": ["51"],
    "Real estate and rental and leasing|Total": ["53"],
    "Professional, scientific, and technical services|Total": ["54"],
    "Management of companies (holding companies)|Total": ["55"],
    "Administrative and support and waste management and remediation services|Total": ["56"],
    "Educational services|": ["61"],
    "Health care and social assistance|Total": ["62"],
    "Arts, entertainment, and recreation|Total": ["71"],
    "Accommodation and food services|Total": ["72"],
    "Other services|Total": ["81"],
    # agriculture / mining / utilities
    "Agricultural production": ["111", "112"],
    "Forestry and logging": ["113"],
    "Support activities and fishing, hunting, and trapping": ["114", "115"],
    "Oil and gas extraction": ["211"],
    "Coal mining": ["2121"],
    "Metal ore mining": ["2122"],
    "Nonmetallic mineral mining and quarrying": ["2123"],
    "Support activities for mining": ["213"],
    "Electric power generation, transmission, and distribution": ["2211"],
    "Natural gas distribution": ["2212"],
    "Water, sewage, and other systems": ["2213"],
    # construction
    "Construction of buildings": ["236"],
    "Heavy and civil engineering construction": ["237"],
    "Land subdivision": ["2372"],
    "Electrical contractors": ["23821"],
    "Plumbing, heating, and air-conditioning contractors": ["23822"],
    "Other specialty trade contractors": ["238"],
    # manufacturing
    "Animal food manufacturing and grain and oilseed milling": ["3111", "3112"],
    "Sugar and confectionery product": ["3113"],
    "Fruit and vegetable preserving and specialty food manufacturing": ["3114"],
    "Dairy product": ["3115"],
    "Meat and seafood processing": ["3116", "3117"],
    "Bakeries and tortilla manufacturing": ["3118"],
    "Other food (including coffee, tea, flavorings, and seasonings)": ["3119"],
    "Soft drink and ice": ["31211"],
    "Breweries": ["31212"],
    "Wineries and distilleries": ["31213", "31214"],
    "Tobacco manufacturing": ["3122"],
    "Textile mills": ["313"],
    "Textile product mills": ["314"],
    "Apparel knitting mills": ["3151"],
    "Cut and sew apparel contractors and manufacturers": ["3152"],
    "Apparel accessories and other apparel mfg": ["3159"],
    "Leather and allied product manufacturing": ["316"],
    "Wood product manufacturing": ["321"],
    "Pulp, paper, and paperboard mills": ["3221"],
    "Converted paper product": ["3222"],
    "Printing and related support activities": ["323"],
    "Petroleum refineries (including integrated)": ["32411"],
    "Asphalt paving, roofing, other petroleum and coal products": ["32412", "32419"],
    "Basic chemical": ["3251"],
    "Resin, synthetic rubber, and artificial and synthetic fibers and filaments": ["3252"],
    "Pharmaceutical and medicine": ["3254"],
    "Paint, coating, and adhesive": ["3255"],
    "Soap, cleaning compound, and toilet preparation": ["3256"],
    "Other chemical product and preparation": ["3253", "3259"],
    "Plastics product": ["3261"],
    "Rubber product": ["3262"],
    "Clay, refractory, and other nonmetallic mineral product": ["3271", "3279"],
    "Glass and glass product": ["3272"],
    "Cement, concrete, lime, and gypsum product": ["3273", "3274"],
    "Iron, steel mills, and steel product": ["3311", "3312"],
    "Nonferrous metal production and processing": ["3313", "3314"],
    "Foundries": ["3315"],
    "Forging and stamping": ["3321"],
    "Cutlery, hardware, spring and wire, machine shops; screw, nut, and bolt": ["3322", "3325", "3326", "3327"],
    "Architectural and structural metals": ["3323"],
    "Boiler, tank, and shipping container": ["3324"],
    "Coating, engraving, heat treating, and allied activities": ["3328"],
    "Other fabricated metal product": ["3329"],
    "Agriculture, construction, and mining machinery": ["3331"],
    "Industrial machinery": ["3332"],
    "Commercial and service industry machinery": ["3333"],
    "Ventilation, heating, air-conditioning, and commercial refrigeration equipment": ["3334"],
    "Metalworking machinery": ["3335"],
    "Engine, turbine, and power transmission equipment": ["3336"],
    "Other general purpose machinery": ["3339"],
    "Computer and peripheral equipment": ["3341"],
    "Communications equipment": ["3342"],
    "Audio and video equipment manufacturing and reproducing magnetic and optical media": ["3343", "3346"],
    "Semiconductor and other electronic component": ["3344"],
    "Navigational, measuring, electromedical, and control instruments": ["3345"],
    "Electrical lighting equipment and household appliance": ["3351", "3352"],
    "Electrical equipment": ["3353"],
    "Other electrical equipment and component": ["3359"],
    "Motor vehicles and parts": ["3361", "3362", "3363"],
    "Aerospace product and parts": ["3364"],
    "Ship and boat building": ["3366"],
    "Other transportation equipment and railroad rolling stock": ["3365", "3369"],
    "Furniture and related product manufacturing": ["337"],
    "Medical equipment and supplies": ["3391"],
    "Other miscellaneous manufacturing": ["3399"],
    # wholesale
    "Motor vehicle and motor vehicle parts and supplies": ["4231"],
    "Lumber and other construction materials": ["4233"],
    "Professional and commercial equipment and supplies": ["4234"],
    "Metal and mineral (except petroleum)": ["4235"],
    "Electrical and electronic goods": ["4236"],
    "Hardware, plumbing, heating equipment, and supplies": ["4237"],
    "Machinery, equipment, and supplies": ["4238"],
    "Furniture, sports, toys, recycle, jewelry, and other durable goods": ["4232", "4239"],
    "Paper and paper product": ["4241"],
    "Drugs and druggists' sundries": ["4242"],
    "Apparel, piece goods, and notions": ["4243"],
    "Grocery and related product": ["4244"],
    "Farm product raw material": ["4245"],
    "Chemical and allied products": ["4246"],
    "Petroleum and petroleum products": ["4247"],
    "Beer, wine, and distilled alcoholic beverage": ["4248"],
    "Miscellaneous nondurable goods": ["4249"],
    "Wholesale trade agents and brokers": ["425"],
    # retail (2022 NAICS retail restructure)
    "New and used car dealers": ["4411"],
    "Other motor vehicle and parts dealers": ["4412", "4413"],
    "Home centers; paint and wallpaper retailers": ["44411", "44412"],
    "Hardware retailers": ["44414"],
    "Other building materials dealers": ["44418"],
    "Lawn and garden equipment and supplies retailers": ["4442"],
    "Food and beverage retailers": ["445"],
    "Beer, wine, and liquor retailers": ["4453"],
    "Furniture and home furnishings retailers": ["4491"],
    "Electronics and appliance retailers (including computers)": ["4492"],
    "General merchandise retailers": ["455"],
    "Health and personal care retailers": ["456"],
    "Gasoline stations and fuel dealers": ["457"],
    "Clothing and clothing accessories retailers": ["458"],
    "Sporting goods, hobby, book, music and miscellaneous retailers": ["459"],
    # transportation
    "Air transportation": ["481"],
    "Rail transportation": ["482"],
    "Water transportation": ["483"],
    "Truck transportation": ["484"],
    "Transit and ground passenger transportation": ["485"],
    "Pipeline transportation": ["486"],
    "Other transportation and support activities": ["487", "488", "492"],
    "Warehousing and storage": ["493"],
    # information
    "Motion picture and video industries (except video rental)": ["5121"],
    "Sounds recording industries": ["5122"],
    "Newspaper publishers": ["51311"],
    "Periodical publishers": ["51312"],
    "Book publishers": ["51313"],
    "Database directory and other publishers": ["51314", "51319"],
    "Software publishers": ["5132"],
    "Boradcasting & Content Providers": ["516"],
    "Telecommunications": ["517"],
    "Computing infrastructure providers": ["518"],
    "Web search portals": ["519"],
    # real estate
    "Lessors of buildings (including equity REITs)": ["5311", "53111", "53112"],
    "Lessors of miniwarehouses, self-storage units, and other real estate": ["53113", "53119"],
    "Offices of real estate agents and brokers": ["5312"],
    "Other real estate activities": ["5313"],
    "Automotive equipment rental and leasing": ["5321"],
    "Other consumer goods and general rental centers": ["5322", "5323"],
    "Commercial and industrial machinery and equipment rental and leasing": ["5324"],
    "Lessors of nonfinancial intangible assets (except copyrighted works)": ["533"],
    # professional
    "Legal services": ["5411"],
    "Accounting, tax preparation, bookkeeping, and payroll services": ["5412"],
    "Architectural, engineering, and related services": ["5413"],
    "Specialized design services": ["5414"],
    "Computer systems design and related services": ["5415"],
    "Management, scientific, and technical consulting services": ["5416"],
    "Scientific research and development services": ["5417"],
    "Advertising and related services": ["5418"],
    "Other professional, scientific, and technical services": ["5419"],
    # admin / health / arts / food / other
    "Employment services": ["5613"],
    "Travel arrangement and reservation services": ["5615"],
    "Other administrative and support services": ["5611", "5612", "5614", "5616", "5617", "5619"],
    "Waste management and remediation services": ["562"],
    "Offices of physicians": ["6211"],
    "Offices of dentists": ["6212"],
    "Offices of other health practitioners": ["6213"],
    "Outpatient care centers": ["6214"],
    "Miscellaneous health care and social assistance": ["6215", "6216", "6219", "624"],
    "Hospitals, nursing, and residential care facilities": ["622", "623"],
    "Other arts, entertainment, and recreation": ["711", "712"],
    "Amusement, gambling, and recreation industries": ["713"],
    "Accommodation": ["721"],
    "Food services and drinking places": ["722"],
    "Automotive repair and maintenance": ["8111"],
    "Other repair and maintenance": ["8112", "8113", "8114"],
    "Personal and laundry services": ["812"],
    "Religious, grantmaking, civic, professional, and similar organizations": ["813"],
}

ROW_KEYS = {
    "Number of returns": "returns",
    "Total assets": "total_assets",
    "Cash": "cash",
    "Trade notes and accounts receivable": "receivables",
    "Less:  Allowance for bad debts": "bad_debt_allowance",
    "Inventories": "inventories",
    "U.S. government obligations": "us_gov_obligations",
    "Tax-exempt securities": "tax_exempt_securities",
    "Other current assets": "other_current_assets",
    "Depreciable assets": "depreciable_assets",
    "Less:  Accumulated depreciation": "accumulated_depreciation",
    "Land": "land",
    "Accounts payable": "accounts_payable",
    "Mortgages, notes, bonds payable in less than 1 year": "short_term_debt",
    "Other current liabilities": "other_current_liabilities",
    "Loans from shareholders": "loans_from_shareholders",
    "Mortgages, notes, bonds payable in 1 year or more": "long_term_debt",
    "Net worth, total": "net_worth",
    "Total receipts": "total_receipts",
    "Business receipts": "business_receipts",
    "Gross rents": "gross_rents",
    "Cost of goods sold": "cogs",
    "Compensation of officers": "officer_comp",
    "Salaries and wages": "salaries",
    "Repairs and maintenance": "repairs",
    "Rents paid": "rents_paid",
    "Taxes and licenses": "taxes_licenses",
    "Interest paid": "interest_paid",
    "Amortization": "amortization",
    "Depreciation": "depreciation",
    "Advertising": "advertising",
    "Total receipts less total deductions": "pretax_income",
    "Net income (less deficit)": "net_income",
}


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _num(v):
    if v is None or isinstance(v, str):
        return None  # 'd' = suppressed, '*' etc.
    return float(v)


def read_soi(path: Path) -> dict[str, dict]:
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True).active
    rows = list(ws.iter_rows(values_only=True))
    # find header rows (sector row has 'All Industries')
    hdr = next(i for i, r in enumerate(rows[:15]) if r and any(_norm(c) == "all industries" for c in r if c))
    sector_row, sub_row = rows[hdr], rows[hdr + 1]
    # map row label -> key
    row_index = {}
    for i, r in enumerate(rows):
        lab = str(r[0] or "").strip()
        for k, key in ROW_KEYS.items():
            if lab.startswith(k) and key not in row_index:
                if k == "Total receipts" and "less" in lab:
                    continue
                row_index[key] = i
    out = {}
    sector = ""
    for j in range(1, len(sector_row)):
        if sector_row[j]:
            sector = str(sector_row[j]).replace("\n", " ").strip()
        sub = str(sub_row[j] or "").replace("\n", " ").strip()
        if not sector and not sub:
            continue
        vals = {key: _num(rows[i][j]) for key, i in row_index.items() if j < len(rows[i])}
        if vals.get("total_assets") is None and vals.get("total_receipts") is None:
            continue
        out[f"{_norm(sector)}|{_norm(sub)}"] = {"sector": sector, "label": sub or sector, **vals}
    return out


def ratios(v: dict) -> dict:
    def div(a, b, mult=1.0):
        a, b = v.get(a) if isinstance(a, str) else a, v.get(b) if isinstance(b, str) else b
        if a is None or b in (None, 0):
            return None
        return round(a / b * mult, 4)

    ar = None if v.get("receivables") is None else v["receivables"] - (v.get("bad_debt_allowance") or 0)
    ca_parts = [v.get(k) for k in ("cash", "inventories", "us_gov_obligations", "tax_exempt_securities", "other_current_assets")]
    ca = None if None in (ar, v.get("cash")) else ar + sum(p or 0 for p in ca_parts)
    cl_parts = [v.get(k) for k in ("accounts_payable", "short_term_debt", "other_current_liabilities")]
    cl = None if all(p is None for p in cl_parts) else sum(p or 0 for p in cl_parts)
    ebitda = None
    if v.get("pretax_income") is not None:
        ebitda = v["pretax_income"] + (v.get("interest_paid") or 0) + (v.get("depreciation") or 0) + (v.get("amortization") or 0)
    liab = None if None in (v.get("total_assets"), v.get("net_worth")) else v["total_assets"] - v["net_worth"]
    br = v.get("business_receipts")
    gm = None if None in (br, v.get("cogs")) or not br else round((br - v["cogs"]) / br, 4)
    return {
        "gross_margin": gm,
        "pretax_margin": div("pretax_income", "total_receipts"),
        "net_margin": div("net_income", "total_receipts"),
        "ebitda_margin": None if ebitda is None else div(ebitda, "total_receipts"),
        "interest_coverage_ebitda": None if ebitda is None else div(ebitda, "interest_paid"),
        "current_ratio": None if None in (ca, cl) or not cl else round(ca / cl, 4),
        "quick_ratio": None if None in (ar, cl) or not cl else round((ar + (v.get("cash") or 0)) / cl, 4),
        "ar_days_360": None if ar is None else div(ar, "business_receipts", 360),
        "inventory_days_cogs_360": div("inventories", "cogs", 360),
        "inventory_days_sales_360": div("inventories", "business_receipts", 360),
        "ap_days_cogs_360": div("accounts_payable", "cogs", 360),
        "debt_to_worth": None if liab is None else div(liab, "net_worth"),
        "liabilities_to_assets": None if liab is None else div(liab, "total_assets"),
        "sales_to_assets": div("total_receipts", "total_assets"),
        "officer_comp_pct_sales": div("officer_comp", "business_receipts"),
        "rent_pct_sales": div("rents_paid", "business_receipts"),
        "depreciation_pct_sales": div("depreciation", "business_receipts"),
        "interest_pct_receipts": div("interest_paid", "total_receipts"),
    }


def build_benchmarks():
    per_year = {y: read_soi(RAW / f"{str(y)[2:]}co51ccr.xlsx") for y in YEARS}
    latest = per_year[YEARS[-1]]
    # match mapping keys to SOI columns by normalized label (prefix match handles truncated labels)
    industries = []
    for map_label, prefixes in INDUSTRY_NAICS.items():
        if "|" in map_label:
            sec, sub = map_label.split("|")
            want = f"{_norm(sec)}|{_norm(sub)}"
            match = lambda key: key == want or (key.startswith(_norm(sec)[:30]) and key.split("|")[1] == _norm(sub))
        else:
            want_sub = _norm(map_label)
            match = lambda key, w=want_sub: key.split("|")[1] == w or key.split("|")[1].startswith(w[:40])
        years = {}
        label = map_label.split("|")[0] if "|" in map_label else map_label
        sector = None
        for y in YEARS:
            key = next((k for k in per_year[y] if match(k)), None)
            if key is None:
                continue
            v = per_year[y][key]
            sector = v["sector"]
            years[str(y)] = {
                "returns": v.get("returns"),
                "business_receipts_thousands": v.get("business_receipts"),
                "total_receipts_thousands": v.get("total_receipts"),
                **ratios(v),
            }
        if not years:
            print("WARN: no SOI column matched", map_label)
            continue
        growth = {}
        ys = sorted(years)
        for a, b in zip(ys, ys[1:]):
            ra, rb = years[a].get("business_receipts_thousands"), years[b].get("business_receipts_thousands")
            if ra and rb:
                growth[f"{a}-{b}"] = round(rb / ra - 1, 4)
        industries.append({"label": label, "sector": sector, "naics_prefixes": prefixes,
                           "is_sector_total": "|" in map_label, "years": years, "receipts_growth": growth})
    meta = {
        "source": "IRS Statistics of Income, Corporation Complete Report, Table 5.1 (Returns of Active Corporations: "
                  "Balance Sheet, Income Statement, Tax, and Selected Other Items, by Major Industry)",
        "urls": [SOI_URL.format(yy=str(y)[2:]) for y in YEARS],
        "tax_years": YEARS,
        "notes": [
            "Ratios are aggregate (sum of all corporations in the industry), not medians; large firms dominate.",
            "Days ratios use a 360-day year to match Invest Detroit's ratio exhibit.",
            "Receipts growth compares SOI sample estimates across years and is directional only.",
            "Dollar amounts in SOI are thousands of dollars.",
        ],
    }
    OUT.mkdir(exist_ok=True)
    (OUT / "irs_soi_benchmarks.json").write_text(json.dumps({"meta": meta, "industries": industries}, indent=1))
    print("wrote", len(industries), "industries")


def build_naics():
    ws = openpyxl.load_workbook(RAW / "naics.xlsx", read_only=True).active
    codes = {}
    for r in ws.iter_rows(values_only=True):
        if r[1] is None or r[2] is None:
            continue
        code = str(r[1]).strip()
        if re.fullmatch(r"\d{2,6}|\d{2}-\d{2}", code):
            codes[code] = str(r[2]).strip().rstrip("T").strip()
    idx = []
    ws = openpyxl.load_workbook(RAW / "naics_index.xlsx", read_only=True).active
    for r in ws.iter_rows(values_only=True):
        if r[0] and str(r[0]).isdigit() and r[1]:
            idx.append([str(r[0]), str(r[1]).strip()])
    data = {"meta": {"source": "U.S. Census Bureau, 2022 NAICS", "urls": [
        "https://www.census.gov/naics/2022NAICS/2-6%20digit_2022_Codes.xlsx",
        "https://www.census.gov/naics/2022NAICS/2022_NAICS_Index_File.xlsx"]},
        "codes": codes, "index": idx}
    (OUT / "naics_2022.json").write_text(json.dumps(data, separators=(",", ":")))
    print("wrote", len(codes), "codes,", len(idx), "index entries")


if __name__ == "__main__":
    build_naics()
    build_benchmarks()
