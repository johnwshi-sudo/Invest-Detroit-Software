"""Merge extracted financial statements into one spread (period -> key -> value) with provenance.

Rules
- Several printed lines with the same canonical key in one document are summed (e.g. scrap sales + discounts
  earned both map to other_income).
- If two documents report the same period, the document whose latest period ends last wins (comparative
  columns in newer statements reflect restatements). Differences are flagged.
- Stated totals (gross_profit, total_assets, net_income, ...) are kept for foot-checks, never used in place of
  a computable value without a flag.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from ..schema import Debt, Deal, FinancialStatements, Period
from .common import Flag, fmt_money

TOTAL_KEYS = {"gross_profit", "operating_income", "pretax_income", "net_income", "total_current_assets",
              "net_fixed_assets", "total_assets", "total_current_liabilities", "total_liabilities",
              "total_equity", "total_liabilities_and_equity"}


@dataclass
class Cell:
    value: float
    sources: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    items: list[tuple[str, float]] = field(default_factory=list)  # (label, value) detail


@dataclass
class Spread:
    periods: list[Period]
    cells: dict[str, dict[str, Cell]]          # period_id -> key -> Cell
    debts: list[Debt]
    flags: list[Flag]
    statement_info: dict[str, dict]            # doc -> info
    notes: list[str]

    def get(self, pid: str, key: str, default: Optional[float] = 0.0) -> Optional[float]:
        c = self.cells.get(pid, {}).get(key)
        return c.value if c is not None else default

    def has(self, pid: str, key: str) -> bool:
        return key in self.cells.get(pid, {})

    def src(self, pid: str, key: str) -> list[str]:
        c = self.cells.get(pid, {}).get(key)
        return c.sources if c else []

    def items(self, pid: str, key: str) -> list[tuple[str, float]]:
        c = self.cells.get(pid, {}).get(key)
        return c.items if c else []

    def period(self, pid: str) -> Period:
        return next(p for p in self.periods if p.id == pid)


def _ref(doc: Optional[str], page: Optional[int]) -> str:
    return f"{doc or 'document'} p.{page}" if page else (doc or "document")


def build_spread(deal: Deal) -> Spread:
    flags: list[Flag] = []
    docs = list(deal.financials)
    # rank docs: latest period end first
    def latest_end(fs: FinancialStatements) -> str:
        return max((p.end_date for p in fs.periods), default="")
    docs.sort(key=latest_end, reverse=True)

    periods: dict[str, Period] = {}
    cells: dict[str, dict[str, Cell]] = defaultdict(dict)
    owner: dict[tuple[str, str], str] = {}   # (pid,key) -> doc that supplied it
    for fs in docs:
        dname = fs.doc or "financial statements"
        for p in fs.periods:
            periods.setdefault(p.id, p)
        per_doc: dict[tuple[str, str], Cell] = {}
        for li in fs.line_items:
            k = (li.period_id, li.key)
            c = per_doc.setdefault(k, Cell(0.0))
            c.value += li.value
            c.sources.append(_ref(li.doc or dname, li.page))
            c.labels.append(li.label)
            c.items.append((li.label, li.value))
            if li.confidence is not None and li.confidence < 0.7:
                flags.append(Flag("warning", "data_quality",
                                  f"Low-confidence extraction ({li.confidence:.0%}) for '{li.label}' ({li.period_id}); verify against source.",
                                  _ref(li.doc or dname, li.page)))
        for (pid, key), c in per_doc.items():
            if (pid, key) in owner:
                prior = cells[pid][key]
                if abs(prior.value - c.value) > 1.0:
                    flags.append(Flag("warning", "consistency",
                                      f"{key.replace('_', ' ')} for {pid} differs between documents: "
                                      f"{fmt_money(prior.value)} ({owner[(pid, key)]}) vs {fmt_money(c.value)} ({dname}). "
                                      f"Using the more recent statement.", ", ".join(c.sources[:2])))
                continue
            cells[pid][key] = c
            owner[(pid, key)] = dname

    debts: list[Debt] = []
    seen = set()
    for fs in docs:
        for d in fs.debts:
            k = d.creditor.lower().strip()
            if k in seen:
                # merge balances from older docs
                tgt = next(x for x in debts if x.creditor.lower().strip() == k)
                have = {b.period_id for b in tgt.balances}
                tgt.balances.extend(b for b in d.balances if b.period_id not in have)
                continue
            seen.add(k)
            debts.append(d.model_copy(deep=True))

    ordered = sorted(periods.values(), key=lambda p: (p.end_date, p.months))
    info = {fs.doc or f"doc{i}": fs.statement_info.model_dump() for i, fs in enumerate(docs)}
    notes = [n for fs in docs for n in fs.notes]
    spread = Spread(ordered, dict(cells), debts, flags, info, notes)
    _foot_checks(spread)
    _assurance_flags(deal, spread)
    return spread


def _foot_checks(s: Spread) -> None:
    for p in s.periods:
        pid = p.id
        g = lambda k: s.get(pid, k, None)
        checks = []
        if g("revenue") is not None and g("gross_profit") is not None:
            checks.append(("gross profit", g("revenue") - (g("cogs") or 0.0), g("gross_profit")))
        if g("total_current_liabilities") is not None:
            cl_keys = ["accounts_payable", "accrued_expenses", "line_of_credit", "current_portion_ltd", "other_current_liabilities"]
            if any(s.has(pid, k) for k in cl_keys):
                checks.append(("total current liabilities", sum(s.get(pid, k) for k in cl_keys), g("total_current_liabilities")))
        if g("total_liabilities") is not None and g("total_current_liabilities") is not None:
            checks.append(("total liabilities", g("total_current_liabilities") + s.get(pid, "long_term_debt") + s.get(pid, "other_liabilities"), g("total_liabilities")))
        fa_keys = ["fixed_assets_gross", "accumulated_depreciation"]
        if g("net_fixed_assets") is not None and s.has(pid, "fixed_assets_gross"):
            acc = s.get(pid, "accumulated_depreciation")
            checks.append(("net fixed assets", s.get(pid, "fixed_assets_gross") - abs(acc), g("net_fixed_assets")))
        ca_keys = ["cash", "accounts_receivable", "inventory", "other_receivables", "prepaid_expenses", "other_current_assets"]
        if g("total_current_assets") is not None and any(s.has(pid, k) for k in ca_keys):
            checks.append(("total current assets", sum(s.get(pid, k) for k in ca_keys), g("total_current_assets")))
        if g("total_assets") is not None and g("total_liabilities_and_equity") is not None:
            checks.append(("balance sheet (assets vs liabilities + equity)", g("total_liabilities_and_equity"), g("total_assets")))
        if g("total_assets") is not None and g("total_liabilities") is not None and g("total_equity") is not None:
            checks.append(("total liabilities + equity", g("total_liabilities") + g("total_equity"), g("total_assets")))
        for name, computed, stated in checks:
            if abs(computed - stated) > 2:
                s.flags.append(Flag("warning", "consistency",
                                    f"{p.label}: {name} does not foot — computed {fmt_money(computed)} vs stated {fmt_money(stated)}.",
                                    pid))


def _assurance_flags(deal: Deal, s: Spread) -> None:
    for doc, info in s.statement_info.items():
        a = info.get("assurance")
        if a in ("no_assurance", "internal"):
            s.flags.append(Flag("warning", "data_quality",
                                f"{doc}: statements carry no CPA assurance (preparer: {info.get('preparer') or 'unknown'}). "
                                "Figures are management's; consider requiring reviewed statements.", doc))
        if info.get("basis") == "tax":
            s.flags.append(Flag("info", "data_quality",
                                f"{doc}: prepared on the income-tax basis (depreciation per MACRS, not GAAP useful lives).", doc))


def debt_balance(d: Debt, pid: str) -> Optional[float]:
    return next((b.value for b in d.balances if b.period_id == pid), None)
