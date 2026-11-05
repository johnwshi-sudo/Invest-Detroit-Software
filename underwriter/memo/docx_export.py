"""Render a memo (JSON blocks) to a Word document laid out like Invest Detroit's Investment Summaries."""
from __future__ import annotations

import io

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

FONT = "Arial"
GREY = RGBColor(0x55, 0x55, 0x55)
AMBER = RGBColor(0x9A, 0x5B, 0x00)


def _set_cell_border(cell, **kw):
    tcPr = cell._tc.get_or_add_tcPr()
    borders = tcPr.find(qn("w:tcBorders"))
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tcPr.append(borders)
    for edge, val in kw.items():
        el = borders.find(qn(f"w:{edge}"))
        if el is None:
            el = OxmlElement(f"w:{edge}")
            borders.append(el)
        el.set(qn("w:val"), val.get("val", "single"))
        el.set(qn("w:sz"), str(val.get("sz", 4)))
        el.set(qn("w:color"), val.get("color", "000000"))


def _shade(cell, hex_fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tcPr.append(shd)


def _run(par, text, bold=False, italic=False, size=10.5, underline=False, color=None):
    r = par.add_run(text)
    r.bold, r.italic, r.underline = bold, italic, underline
    r.font.size = Pt(size)
    r.font.name = FONT
    if color:
        r.font.color.rgb = color
    return r


def _para(doc, text="", bold=False, italic=False, size=10.5, align=None, space_after=6, underline=False, color=None):
    par = doc.add_paragraph()
    par.paragraph_format.space_after = Pt(space_after)
    par.paragraph_format.space_before = Pt(0)
    if align:
        par.alignment = align
    if text:
        _run(par, text, bold, italic, size, underline, color)
    return par


def _cell_text(cell, text, bold=False, size=8, align=None, italic=False):
    cell.text = ""
    par = cell.paragraphs[0]
    par.paragraph_format.space_after = Pt(0)
    par.paragraph_format.space_before = Pt(0)
    for i, line in enumerate(str(text).split("\n")):
        if i:
            par.add_run().add_break()
        _run(par, line, bold=bold, size=size, italic=italic)
    if align:
        par.alignment = align


def _widths(blk, avail: float) -> list[float]:
    cols = blk["columns"]
    ncol = len(cols)
    if blk.get("widths"):
        return blk["widths"]
    if blk.get("kind") == "grid":
        lens = []
        for j in range(ncol):
            m = max([len(str(cols[j]))] + [len(str(r["cells"][j])) for r in blk["rows"] if j < len(r["cells"])])
            lens.append(min(max(m, 7), 60) ** 0.8)
        tot = sum(lens)
        return [max(avail * l / tot, 0.55) for l in lens]
    label = min(2.0, avail * 0.26) if ncol <= 9 else 1.45
    pct = [j for j in range(1, ncol) if str(cols[j]).strip().startswith("%")]
    pw = 0.44 if ncol > 9 else 0.5
    vw = (avail - label - pw * len(pct)) / max(1, ncol - 1 - len(pct))
    return [label] + [pw if j in pct else vw for j in range(1, ncol)]


def _table(doc, blk, avail: float = 6.8):
    cols = blk["columns"]
    ncol = len(cols)
    if blk.get("title"):
        _para(doc, blk["title"], bold=True, italic=True, size=10.5, space_after=2, underline=True)
    size = 8 if ncol <= 7 else 7.5 if ncol <= 9 else 6
    t = doc.add_table(rows=1, cols=ncol)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    widths = _widths(blk, avail)
    grid = blk.get("kind") == "grid"
    if grid:
        t.style = "Table Grid"
    hdr = t.rows[0].cells
    for j, c in enumerate(cols):
        _cell_text(hdr[j], c, bold=True, size=size, align=WD_ALIGN_PARAGRAPH.CENTER if j else WD_ALIGN_PARAGRAPH.LEFT)
        if grid:
            _shade(hdr[j], "D9D9D9")
        else:
            _set_cell_border(hdr[j], bottom={"sz": 6})
    for rw in blk["rows"]:
        cells = t.add_row().cells
        st = rw.get("style", "")
        for j, val in enumerate(rw["cells"]):
            if j >= ncol:
                break
            bold = st in ("bold", "total", "total2") and (j == 0 or st != "bold" or True)
            _cell_text(cells[j], val, bold=bold, size=size,
                       align=WD_ALIGN_PARAGRAPH.LEFT if j == 0 or not _numeric(val) else WD_ALIGN_PARAGRAPH.RIGHT)
            if st in ("total", "total2") and j > 0 and not grid:
                _set_cell_border(cells[j], top={"sz": 4})
            if st == "total2" and j > 0 and not grid:
                _set_cell_border(cells[j], top={"sz": 4}, bottom={"val": "double", "sz": 4})
            if st in ("critical", "flag"):
                _shade(cells[j], "FCE4D6")
            elif st == "warning":
                _shade(cells[j], "FFF2CC")
    _apply_widths(t, widths)
    if not grid:
        # outer box like the samples
        for r_i, rw in enumerate(t.rows):
            for j, c in enumerate(rw.cells):
                kw = {}
                if r_i == 0:
                    kw["top"] = {"sz": 8}
                if r_i == len(t.rows) - 1:
                    kw["bottom"] = {"sz": 8}
                if j == 0:
                    kw["left"] = {"sz": 8}
                if j == ncol - 1:
                    kw["right"] = {"sz": 8}
                if kw:
                    _set_cell_border(c, **kw)
    if blk.get("footnote"):
        _para(doc, blk["footnote"], italic=True, size=7.5, space_after=6)
    else:
        _para(doc, "", space_after=4)


def _apply_widths(t, widths):
    tblPr = t._tbl.tblPr
    lay = OxmlElement("w:tblLayout")
    lay.set(qn("w:type"), "fixed")
    tblPr.append(lay)
    grid = t._tbl.tblGrid
    for j, gc in enumerate(grid.findall(qn("w:gridCol"))):
        if j < len(widths):
            gc.set(qn("w:w"), str(int(widths[j] * 1440)))
    for j, col in enumerate(t.columns):
        if j < len(widths):
            col.width = Inches(widths[j])
    for rw_ in t.rows:
        for j, c in enumerate(rw_.cells):
            if j < len(widths):
                c.width = Inches(widths[j])


def _numeric(v) -> bool:
    s = str(v).strip().replace(",", "").replace("$", "").replace("(", "").replace(")", "").replace("%", "").replace("x", "")
    if s in ("-", "n/a", ""):
        return True
    try:
        float(s)
        return True
    except ValueError:
        return False


def _header(doc, h):
    _para(doc, h["fund"], bold=True, size=11, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=10)
    t = doc.add_table(rows=1, cols=2)
    _apply_widths(t, [3.3, 3.5])
    left, right = t.rows[0].cells
    _cell_text(left, "BORROWER", bold=True, size=10.5)
    for ln in [x for x in h["left"] if x]:
        par = left.add_paragraph()
        _run(par, ln, size=10.5)
        par.paragraph_format.space_after = Pt(0)
    par = left.add_paragraph()
    par.paragraph_format.space_before = Pt(8)
    _run(par, "REQUEST:", bold=True, underline=True, size=10.5)
    par = left.add_paragraph()
    _run(par, h["request"], size=10.5)
    _cell_text(right, h["right"][0], bold=True, size=10.5)
    for ln in h["right"][1:]:
        par = right.add_paragraph()
        _run(par, ln, size=10.5)
        par.paragraph_format.space_after = Pt(0)
    for title, items in (("POLICY EXCEPTIONS", h["policy_exceptions"]), ("GUIDELINE EXCEPTIONS", h["guideline_exceptions"])):
        par = right.add_paragraph()
        par.paragraph_format.space_before = Pt(6)
        _run(par, title, bold=True, size=10.5)
        for it in items:
            par = right.add_paragraph()
            par.paragraph_format.space_after = Pt(0)
            _run(par, "* " + it, size=9.5)
    if h.get("oversight"):
        par = right.add_paragraph()
        _run(par, "OVERSIGHT COUNCIL APPROVAL REQUIRED (>3 guideline exceptions)", bold=True, size=9.5, color=AMBER)
    par = right.add_paragraph()
    par.paragraph_format.space_before = Pt(10)
    _run(par, "APPROVED: ______________________  Date: ________", bold=True, size=10)
    _para(doc, "", space_after=4)


def render_docx(memo: dict, deal_name: str = "") -> bytes:
    doc = Document()
    sec = doc.sections[0]
    sec.left_margin = sec.right_margin = Inches(0.85)
    sec.top_margin = sec.bottom_margin = Inches(0.8)
    st = doc.styles["Normal"]
    st.font.name = FONT
    st.font.size = Pt(10.5)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    footer = sec.footer.paragraphs[0]
    _run(footer, f"DRAFT — generated by the Invest Detroit AI underwriting assistant for underwriter review. {deal_name}", size=7, italic=True, color=GREY)
    for s in memo["sections"]:
        wide = False
        first = next((b for b in s["blocks"]), None)
        dup = first is not None and first.get("type") == "table" and (first.get("title") or "").startswith(s.get("title") or "\0")
        if s.get("title") and not dup:
            _para(doc, s["title"], bold=True, italic=s["key"] not in ("financial_review",), size=11, space_after=3,
                  underline=s["key"] in ("request_hdr",))
        for b in s["blocks"]:
            tp = b["type"]
            if tp == "header":
                _header(doc, b)
            elif tp == "p":
                _para(doc, b["text"], size=10.5)
            elif tp == "placeholder":
                _para(doc, b["text"], italic=True, size=10.5, color=AMBER)
            elif tp == "subhead":
                _para(doc, b["text"], italic=True, size=10.5, space_after=2)
            elif tp in ("bullets", "numbered"):
                style = "List Bullet" if tp == "bullets" else "List Number"
                for it in b["items"]:
                    par = doc.add_paragraph(style=style)
                    par.paragraph_format.space_after = Pt(2)
                    _run(par, it, size=10.5)
                _para(doc, "", space_after=2)
            elif tp == "kv":
                t = doc.add_table(rows=0, cols=2)
                t.style = "Table Grid"
                for k, v in b["rows"]:
                    c = t.add_row().cells
                    _cell_text(c[0], k, bold=True, size=9)
                    _cell_text(c[1], v, size=9)
                _apply_widths(t, [1.8, 5.0])
                _para(doc, "", space_after=4)
            elif tp == "table":
                _table(doc, b, 9.6 if wide else 6.8)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
