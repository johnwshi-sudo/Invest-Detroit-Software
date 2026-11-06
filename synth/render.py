"""Render synthetic borrower packages to PDF (styled after the documents Invest Detroit sent).

    python -m synth.render            # writes synth/out/pdf/<scenario>/*.pdf (gitignored; regenerable)

Page numbers match those recorded in the extraction answer keys (synth/to_deal.py), so the packages can be used to
score live Claude extraction (scripts/eval_live_extraction.py style) once an API key is available.
About a third of packages are rasterized as "scans" (skew, noise, grayscale), and one projection page is rotated 90°.
"""
from __future__ import annotations

import io
import random
import subprocess
import sys
import tempfile
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from synth.scenarios import SCENARIOS  # noqa: E402
from synth.to_deal import build_case  # noqa: E402

OUT = ROOT / "synth" / "out" / "pdf"
SS = getSampleStyleSheet()
H = ParagraphStyle("h", parent=SS["Title"], fontName="Helvetica-Bold", fontSize=13, spaceAfter=4)
H2 = ParagraphStyle("h2", parent=SS["Normal"], fontName="Helvetica-Bold", fontSize=11, alignment=TA_CENTER, spaceAfter=10)
BODY = ParagraphStyle("b", parent=SS["Normal"], fontName="Helvetica", fontSize=10, leading=14, spaceAfter=8)
SMALL = ParagraphStyle("s", parent=BODY, fontSize=8.5, leading=11)


def money(v, unit=1, dollar=False):
    if v is None:
        return ""
    x = round(v / unit)
    s = f"{abs(x):,.0f}"
    if dollar:
        s = "$ " + s
    return f"({s})" if x < 0 else ("-" if x == 0 else s)


def fin_table(rows, colw, bold_rows=(), total_rows=()):
    t = Table(rows, colWidths=colw, hAlign="CENTER")
    st = [("FONT", (0, 0), (-1, -1), "Helvetica", 9), ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
          ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9), ("LINEBELOW", (1, 0), (-1, 0), 0.6, colors.black),
          ("BOTTOMPADDING", (0, 0), (-1, -1), 2), ("TOPPADDING", (0, 0), (-1, -1), 2)]
    for r in bold_rows:
        st.append(("FONT", (0, r), (-1, r), "Helvetica-Bold", 9))
    for r in total_rows:
        st.append(("LINEABOVE", (1, r), (-1, r), 0.6, colors.black))
    t.setStyle(TableStyle(st))
    return t


LETTERS = {
    "audit": "We have audited the accompanying financial statements ... In our opinion, the financial statements present fairly, "
             "in all material respects, the financial position of the Company in accordance with accounting principles generally "
             "accepted in the United States of America.",
    "review": "We have reviewed the accompanying financial statements. A review includes primarily applying analytical procedures to "
              "management's financial data and making inquiries of management. Based on our review, we are not aware of any material "
              "modifications that should be made to the accompanying financial statements.",
    "compilation": "Management is responsible for the accompanying financial statements. We have performed a compilation engagement. "
                   "We did not audit or review the financial statements, nor were we required to perform any procedures to verify the "
                   "accuracy or completeness of the information provided by management. Accordingly, we do not express an opinion, a "
                   "conclusion, nor provide any form of assurance on these financial statements.",
    "no_assurance": "We have prepared from information provided to us by management the accompanying financial statements. These "
                    "financial statements were not subjected to any audit, review or compilation standards. Accordingly we do not "
                    "express an opinion, a conclusion, nor provide any form of assurance on these financial statements.",
    "internal": "Internally prepared by management. Unaudited.",
    "tax_return": "U.S. Income Tax Return for an S Corporation (Form 1120-S) — summary of filed return prepared by paid preparer.",
}


def render_fs(path, spec, fs, unit):
    q = spec["quirks"]
    per = fs["periods"]
    pids = [p["id"] for p in per]
    by = {(li["period_id"], li["key"], li["label"]): li["value"] for li in fs["line_items"]}
    def v(pid, key, label=None):
        if label:
            return by.get((pid, key, label))
        vals = [val for (p, k, l), val in by.items() if p == pid and k == key]
        return sum(vals) if vals else None
    labels = {li["key"]: li["label"] for li in fs["line_items"]}
    heads = [""] + [f"December 31,\n{p['end_date'][:4]}" if p["months"] == 12 else p["label"].replace(" Ending ", " Ending\n") for p in per]
    W = [2.9 * inch] + [1.3 * inch] * len(per)
    doc = SimpleDocTemplate(str(path), pagesize=letter, topMargin=0.8 * inch, bottomMargin=0.8 * inch)
    tax = q.get("assurance") == "tax_return"
    title = spec["name"].upper()
    unit_note = " (in thousands of dollars)" if unit == 1000 else ""
    E = []
    # p1 cover
    E += [Spacer(1, 2 * inch), Paragraph(title, H), Paragraph("Form 1120-S Summary" if tax else "Financial Statements", H2),
          Paragraph(" and ".join(h for h in heads[1:]), H2), PageBreak()]
    # p2 accountant's letter
    E += [Paragraph(fs["statement_info"].get("preparer") or "", H2), Paragraph("Independent Accountant's Report" if q.get("assurance") in ("audit", "review") else "Accountant's Report", H2),
          Paragraph(f"To the Board of Directors and Stockholders<br/>{spec['name']}<br/>Detroit, Michigan", BODY),
          Paragraph(LETTERS.get(q.get("assurance", "review"), ""), BODY),
          Paragraph("The financial statements are prepared on the " + {"tax": "income tax basis of accounting", "cash": "cash basis of accounting",
                    "gaap": "accrual basis in accordance with GAAP"}.get(q.get("basis", "gaap"), "") + ".", BODY), PageBreak()]
    # p3 balance sheet
    rows = [heads]
    order = [("cash", "Cash"), ("accounts_receivable", None), ("inventory", None), ("prepaid_expenses", None), ("other_receivables", None),
             ("total_current_assets", None)]
    bold, tot = [], []
    def add(key, label=None, b=False, t=False, lab_exact=None):
        if not any(v(p, key, lab_exact) is not None for p in pids):
            return
        rows.append([("   " if not b else "") + (label or labels.get(key, key))] + [money(v(p, key, lab_exact), unit) for p in pids])
        if b:
            bold.append(len(rows) - 1)
        if t:
            tot.append(len(rows) - 1)
    rows.append(["ASSETS"] + [""] * len(pids)); bold.append(1)
    for k, l in order:
        add(k, l, k.startswith("total"), k.startswith("total"))
    fa_labels = sorted({li["label"] for li in fs["line_items"] if li["key"] == "fixed_assets_gross"})
    for fl in fa_labels:
        add("fixed_assets_gross", fl, lab_exact=fl)
    add("accumulated_depreciation")
    add("net_fixed_assets", None, True, True)
    add("other_assets")
    add("total_assets", None, True, True)
    rows.append(["LIABILITIES AND EQUITY"] + [""] * len(pids)); bold.append(len(rows) - 1)
    for k in ("accounts_payable", "accrued_expenses", "line_of_credit", "current_portion_ltd"):
        add(k)
    add("total_current_liabilities", None, True, True)
    add("long_term_debt")
    add("total_liabilities", None, True, True)
    for k in ("common_stock", "retained_earnings", "current_year_income"):
        add(k)
    add("total_equity", None, True, True)
    add("total_liabilities_and_equity", None, True, True)
    E += [Paragraph(title, H), Paragraph(("SCHEDULE L - BALANCE SHEETS PER BOOKS" if tax else "BALANCE SHEETS") + unit_note, H2),
          fin_table(rows, W, bold, tot), PageBreak()]
    # p4 income statement
    rows = [heads]; bold, tot = [], []
    for k in ("revenue", "cogs", "gross_profit", "operating_expenses", "operating_income", "other_income", "nonrecurring_income",
              "interest_expense", "pretax_income", "income_taxes", "net_income"):
        add(k, None, k in ("gross_profit", "operating_income", "net_income"), k in ("gross_profit", "operating_income", "pretax_income", "net_income"))
    E += [Paragraph(title, H), Paragraph(("INCOME (LOSS) - FORM 1120-S PAGE 1" if tax else "STATEMENTS OF INCOME") + unit_note, H2),
          fin_table(rows, W, bold, tot), PageBreak()]
    # p5 cash flow (depreciation + distributions)
    rows = [heads]
    add("net_income", "Net income")
    if q.get("dep_location") == "cf_only":
        add("depreciation", "Depreciation")
    add("distributions", "Distributions to shareholders")
    rows.append(["   Changes in working capital and other items (net)"] + ["see notes" for _ in pids])
    E += [Paragraph(title, H), Paragraph("STATEMENTS OF CASH FLOWS (SUMMARY)" + unit_note, H2), fin_table(rows, W), PageBreak()]
    # p6-7 notes
    E += [Paragraph("NOTES TO FINANCIAL STATEMENTS", H2),
          Paragraph(f"1. Nature of business. {spec['description']}", BODY),
          Paragraph("2. Basis of presentation. " + {"tax": "Income tax basis; depreciation per MACRS.", "cash": "Cash basis.", "gaap": "GAAP accrual basis."}.get(q.get("basis", "gaap"), ""), BODY),
          PageBreak()]
    debt_txt = []
    for i, d in enumerate(fs["debts"]):
        bal = d["balances"][-1]["value"] if d["balances"] else 0
        if d["kind"] == "line_of_credit":
            debt_txt.append(f"Line of credit with a commercial bank, interest at prime plus 1%, secured by receivables and inventory. Balance {money(bal, 1, True)}.")
        else:
            debt_txt.append(f"Note payable, {d['creditor']}, interest at {d['interest_rate'] * 100:.2f}%, monthly principal and interest payments of "
                            f"${d['monthly_payment']:,.2f}{', subordinated' if d.get('subordinated') else ''}. Balance {money(bal, 1, True)}.")
    E += [Paragraph("3. Long-term debt", BODY)] + [Paragraph(f"({chr(97 + i)}) {t}", BODY) for i, t in enumerate(debt_txt)] + [PageBreak()]
    # p8 supplementary title
    E += [Spacer(1, 3 * inch), Paragraph("SUPPLEMENTARY INFORMATION", H2), PageBreak()]
    # p9 schedule of operating expenses
    rows = [heads]
    add("officer_compensation", "Officer compensation")
    if q.get("dep_location") != "cf_only":
        add("depreciation", "Depreciation")
    add("interest_included_above", "Interest expense")
    rows.append(["   All other operating expenses"] + [money((v(p, "operating_expenses") or 0) - (v(p, "officer_compensation") or 0)
                                                       - ((v(p, "depreciation") or 0) if q.get("dep_location") != "cf_only" else 0)
                                                       - (v(p, "interest_included_above") or 0), unit) for p in pids])
    add("operating_expenses", "Total operating expenses", True, True)
    E += [Paragraph(title, H), Paragraph("SCHEDULE OF OPERATING EXPENSES" + unit_note, H2), fin_table(rows, W)]
    doc.build(E)


def render_interim(path, spec, fs):
    doc = SimpleDocTemplate(str(path), pagesize=letter)
    per = fs["periods"]
    by = {}
    for li in fs["line_items"]:
        by[(li["period_id"], li["key"])] = by.get((li["period_id"], li["key"]), 0) + li["value"]
    heads = [""] + [p["label"] for p in per]
    W = [2.6 * inch] + [1.7 * inch] * len(per)
    rows = [heads] + [[lab] + [money(by.get((p["id"], k)), 1) for p in per] for k, lab in
                      [("revenue", "Sales"), ("cogs", "Cost of sales"), ("gross_profit", "Gross profit"), ("operating_expenses", "Operating expenses"),
                       ("operating_income", "Operating income"), ("interest_expense", "Interest expense"), ("pretax_income", "Income before taxes"),
                       ("income_taxes", "Income taxes"), ("net_income", "Net income"), ("depreciation", "Depreciation (included above)"),
                       ("interest_included_above", "Interest (included in operating expenses)")] if any(by.get((p["id"], k)) for p in per)]
    E = [Paragraph(spec["name"].upper(), H), Paragraph("INTERNAL INCOME STATEMENT AND FORECAST (UNAUDITED)", H2), fin_table(rows, W), PageBreak()]
    bsp = [p for p in per if (p["id"], "total_assets") in by]
    if bsp:
        rows = [[""] + [p["label"] for p in bsp]] + [[lab] + [money(by.get((p["id"], k)), 1) for p in bsp] for k, lab in
                [("cash", "Cash"), ("accounts_receivable", "Accounts receivable"), ("inventory", "Inventory"), ("total_current_assets", "Total current assets"),
                 ("net_fixed_assets", "Net fixed assets"), ("total_assets", "Total assets"), ("accounts_payable", "Accounts payable"),
                 ("accrued_expenses", "Accrued expenses"), ("line_of_credit", "Line of credit"), ("current_portion_ltd", "Current portion LTD"),
                 ("total_current_liabilities", "Total current liabilities"), ("long_term_debt", "Long-term debt"), ("total_liabilities", "Total liabilities"),
                 ("total_equity", "Total equity")] if any(by.get((p["id"], k)) for p in bsp)]
        E += [Paragraph("INTERNAL BALANCE SHEET (UNAUDITED)", H2), fin_table(rows, [2.6 * inch] + [1.7 * inch] * len(bsp))]
    doc.build(E)


def render_business_plan(path, spec, deal):
    doc = SimpleDocTemplate(str(path), pagesize=letter)
    t = deal["terms"]
    L = t["proposed_loan"]
    E = [Paragraph(f"{spec['name']} — Business Plan and Loan Request", H), Paragraph("Company overview", H2), Paragraph(spec["description"], BODY)]
    if spec.get("year_established"):
        E.append(Paragraph(f"Founded in {spec['year_established']}; approximately {spec.get('employees', 'n/a')} employees, most of whom live in Detroit.", BODY))
    if spec.get("customers"):
        E.append(Paragraph("Key customers: " + ", ".join(spec["customers"]) + ".", BODY))
    E.append(Paragraph("Ownership and management", H2))
    for o in deal["profile"]["people"]:
        own = f"{o['ownership_pct'] * 100:.1f}%" if o.get("ownership_pct") is not None else ""
        E.append(Paragraph(f"<b>{o['name']}</b>, {o.get('role') or ''} — {own} owner. {o.get('bio') or ''} "
                           f"{'Will personally guarantee the loan.' if o.get('guarantor') else 'Passive investor; will not guarantee.'}", BODY))
    E += [Paragraph("Loan request", H2),
          Paragraph(f"We request a loan of ${L['amount']:,.0f} from Invest Detroit at an expected rate of about {L['rate'] * 100:.2f}% with "
                    f"{'interest-only payments for ' + str(L.get('io_months')) + ' months, then ' if L.get('io_months') else ''}"
                    f"repayment over {L['amort_months']} months. Proposed collateral: {t.get('lien_position')}.", BODY)]
    doc.build(E)


def render_cre(folder, spec, deal, rotate=False):
    c = deal["cre"]
    P = c["projections"]
    yrs = P["years"]
    rows = [["", *[f"Borrower Projections {y}" for y in yrs]]]
    for ln in P["lines"]:
        rows.append([ln["label"]] + [money(v, 1) for v in ln["values"]])
    doc = SimpleDocTemplate(str(folder / P["doc"]), pagesize=landscape(letter))
    doc.build([Paragraph(f"{spec['name']} — Operating Projections", H), fin_table(rows, [2.6 * inch] + [1.25 * inch] * len(yrs),
                                                                                   total_rows=[i for i, r in enumerate(rows) if r[0] in ("Total Revenue", "Total Expenses", "Net Operating Income")])])
    rr = [["Unit", "Use", "Sq. Ft.", "Annual Rent"]] + [[u["unit"], u["use"], f"{u['sf']:,.0f}", money(u["annual_rent"], 1, True)] for u in c["rent_roll"]]
    rr.append(["TOTALS", "", f"{sum(u['sf'] for u in c['rent_roll']):,.0f}", money(sum(u["annual_rent"] for u in c["rent_roll"]), 1, True)])
    bud = [["Category", "Line item", "Amount"]] + [[b["category"].replace("_", " "), b["label"], money(b["amount"], 1, True)] for b in c["budget"]]
    bud.append(["", "TOTAL DEVELOPMENT COST", money(sum(b["amount"] for b in c["budget"]), 1, True)])
    src = [["Sources", "Amount"]] + [[s["label"], money(s["amount"], 1, True)] for s in c["sources"]]
    doc = SimpleDocTemplate(str(folder / f"{spec['id']}_rent_roll_and_budget.pdf"), pagesize=letter)
    doc.build([Paragraph("Proposed Rent Roll", H), fin_table(rr, [2.2 * inch, 1.2 * inch, 1 * inch, 1.4 * inch]), Spacer(1, 12),
               Paragraph("Development Budget", H), fin_table(bud, [1.6 * inch, 3.2 * inch, 1.4 * inch]), Spacer(1, 12),
               fin_table(src, [3 * inch, 1.6 * inch])])
    ap = c["appraisal"]
    doc = SimpleDocTemplate(str(folder / f"{spec['id']}_appraisal_summary.pdf"), pagesize=letter)
    txt = [f"As-stabilized market value: ${ap['as_stabilized_value']:,.0f}."]
    if ap.get("re_tax_estimate"):
        txt.append(f"Estimated real estate taxes at stabilization: ${ap['re_tax_estimate']:,.0f} per year.")
    if ap.get("vacancy_estimate") is not None:
        txt.append(f"Market vacancy and collection loss: {ap['vacancy_estimate'] * 100:.0f}%.")
    if ap.get("market_rent_retail_psf"):
        txt.append(f"Market retail rent: ${ap['market_rent_retail_psf']:,.0f} per square foot.")
    doc.build([Paragraph("Appraisal Report — Summary of Salient Facts", H), Paragraph(f"Subject: {spec['name']}, Detroit, Michigan", BODY)] +
              [Paragraph(t, BODY) for t in txt])
    render_business_plan(folder / f"{spec['id']}_business_plan.pdf", spec, deal)
    if rotate:
        _rotate(folder / P["doc"])


def _rotate(path):
    from pypdf import PdfReader, PdfWriter
    r, w = PdfReader(str(path)), PdfWriter()
    for pg in r.pages:
        pg.rotate(90)
        w.add_page(pg)
    with open(path, "wb") as f:
        w.write(f)


def scanify(path, rng):
    """Rasterize like a photocopy: grayscale, slight skew, speckle noise; image-only PDF (no text layer)."""
    from PIL import Image, ImageFilter
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["pdftoppm", "-r", "110", "-gray", "-png", str(path), f"{td}/p"], check=True)
        pages = []
        for png in sorted(Path(td).glob("p-*.png")):
            im = Image.open(png).convert("L")
            im = im.rotate(rng.uniform(-1.2, 1.2), expand=False, fillcolor=255, resample=Image.BICUBIC)
            px = im.load()
            w, h = im.size
            for _ in range(w * h // 400):
                x, y = rng.randrange(w), rng.randrange(h)
                px[x, y] = rng.choice((0, 90, 160))
            pages.append(im.filter(ImageFilter.GaussianBlur(0.4)).convert("RGB"))
        pages[0].save(str(path), save_all=True, append_images=pages[1:], resolution=110)


def render_all(only=None):
    rng = random.Random(7)
    OUT.mkdir(parents=True, exist_ok=True)
    made = []
    for i, spec in enumerate(SCENARIOS):
        if only and spec["id"] not in only:
            continue
        deal, pres, truth, _ = build_case(spec)
        folder = OUT / spec["id"]
        folder.mkdir(exist_ok=True)
        scanned = i % 3 == 1
        if spec["kind"] == "small_business":
            for fs in deal["financials"]:
                if fs["statement_info"].get("assurance") == "internal" and any(p["kind"] in ("interim", "projection") for p in fs["periods"]):
                    render_interim(folder / fs["doc"], spec, fs)
                else:
                    render_fs(folder / fs["doc"], spec, fs, pres["unit"])
            render_business_plan(folder / f"{spec['id']}_business_plan.pdf", spec, deal)
        else:
            render_cre(folder, spec, deal, rotate=spec["id"] == "cre02_community_center")
        if scanned:
            for pdf in folder.glob("*.pdf"):
                scanify(pdf, rng)
        (folder / "answer_key.deal.json").write_text(__import__("json").dumps(deal, indent=1))
        made.append((spec["id"], len(list(folder.glob("*.pdf"))), "scanned" if scanned else "digital"))
    return made


if __name__ == "__main__":
    for m in render_all(sys.argv[1:] or None):
        print(*m)
