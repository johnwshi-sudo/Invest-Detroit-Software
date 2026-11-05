"""Memo building blocks (JSON-serializable) shared by the HTML view and the Word export."""
from __future__ import annotations

from typing import Optional

from ..engine.common import fmt_money, fmt_pct, fmt_x


def p(text: str, source: str = "computed") -> dict:
    return {"type": "p", "text": text, "source": source}


def placeholder(what: str) -> dict:
    return {"type": "placeholder", "text": f"[Underwriter to complete: {what}]"}


def bullets(items: list[str], source: str = "computed") -> dict:
    return {"type": "bullets", "items": [i for i in items if i], "source": source}


def numbered(items: list[str], source: str = "computed") -> dict:
    return {"type": "numbered", "items": [i for i in items if i], "source": source}


def subhead(text: str) -> dict:
    return {"type": "subhead", "text": text}


def kv(rows: list[tuple[str, str]]) -> dict:
    return {"type": "kv", "rows": [[a, b] for a, b in rows]}


def table(title: Optional[str], columns: list, rows: list, footnote: Optional[str] = None, kind: str = "fin",
          widths: Optional[list] = None) -> dict:
    """columns: list of header strings (may contain \\n). rows: list of {'cells': [...], 'style': str}."""
    return {"type": "table", "title": title, "columns": columns, "rows": rows, "footnote": footnote, "kind": kind,
            "widths": widths}


def row(cells: list, style: str = "") -> dict:
    return {"cells": cells, "style": style}


def section(key: str, title: str, blocks: list, level: int = 1) -> dict:
    return {"key": key, "title": title, "level": level, "blocks": [b for b in blocks if b]}


# number formatting for tables (Invest Detroit style: no $ inside cells, parentheses for negatives)
def n(v: Optional[float], dash_zero: bool = True) -> str:
    if v is None:
        return ""
    if dash_zero and round(v) == 0:
        return "-"
    return fmt_money(v, dollars=False)


def d(v: Optional[float]) -> str:
    return fmt_money(v)


def pc(v: Optional[float], digits: int = 0) -> str:
    return "" if v is None else fmt_pct(v, digits)


def x(v: Optional[float], digits: int = 2) -> str:
    return "n/a" if v is None else fmt_x(v, digits)
