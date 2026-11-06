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
    _sign_checks(spread)
    _foot_checks(spread)
    _reasonableness_checks(deal, spread)
    _assurance_flags(deal, spread)
    return spread


EXPENSE_KEYS = {"cogs", "operating_expenses", "interest_expense", "other_expense", "income_taxes", "depreciation", "amortization",
                "officer_compensation", "rent_expense", "distributions", "interest_included_above"}
TOTAL_FOR_FOOTING = {"gross_profit", "operating_income", "net_income", "total_current_assets", "total_assets",
                     "total_current_liabilities", "total_liabilities", "total_equity"}


def _sign_checks(s: Spread) -> None:
    """Expenses are positive by convention; a negative expense is almost always an extraction sign error."""
    for p in s.periods:
        for k, c in s.cells.get(p.id, {}).items():
            if k in EXPENSE_KEYS and c.value < 0:
                s.flags.append(Flag("warning", "consistency", f"{p.label}: {k.replace('_', ' ')} has a negative sign ({fmt_money(c.value)}); "
                                    "expenses should be positive. Check the sign (value used as extracted).", p.id))


def _reasonableness_checks(deal: Deal, s: Spread) -> None:
    """Cross-checks an underwriter would make on lines that no printed total covers."""
    pids = [p.id for p in s.periods]
    # 1) depreciation vs change in accumulated depreciation
    for a, b in zip(pids, pids[1:]):
        if s.period(b).kind == "projection" or not (s.has(a, "accumulated_depreciation") and s.has(b, "accumulated_depreciation")):
            continue
        dep = s.get(b, "depreciation", None)
        if dep is None:
            continue
        delta = abs(s.get(b, "accumulated_depreciation")) - abs(s.get(a, "accumulated_depreciation"))
        if delta >= 0 and abs(dep - delta) > max(0.25 * max(dep, delta), 5_000):
            s.flags.append(Flag("warning", "consistency", f"{s.period(b).label}: depreciation {fmt_money(dep)} does not reconcile to the "
                                f"{fmt_money(delta)} increase in accumulated depreciation{' (disposals?)' if dep > delta else ''}. Verify depreciation.", b))
    # 2) interest expense vs debt implied interest (only when every term debt has a rate)
    rated = [d for d in s.debts if d.kind != "line_of_credit"]
    if rated and all(d.interest_rate is not None for d in rated):
        last = [p for p in s.periods if p.kind != "projection" and p.months == 12]
        if last:
            pid = last[-1].id
            term_bal = sum((next((x.value for x in d.balances if x.period_id == pid), None) or 0) for d in rated)
            if term_bal and all(any(x.period_id == pid for x in d.balances) for d in rated):
                est_term = sum((next(x.value for x in d.balances if x.period_id == pid)) * d.interest_rate for d in rated)
                loc = s.get(pid, "line_of_credit", 0.0) or 0.0
                # a line of credit may be drawn at year end (no interest yet), so it only widens the upper bound
                prior = [p for p in last[:-1]]
                prior_debt = (s.get(prior[-1].id, "line_of_credit", 0.0) or 0.0) + (s.get(prior[-1].id, "current_portion_ltd", 0.0) or 0.0) + \
                    (s.get(prior[-1].id, "long_term_debt", 0.0) or 0.0) if prior else 0.0
                lo = est_term * 0.5
                hi = max(est_term * 1.8 + loc * 0.14, prior_debt * 0.16) + 5_000
                rep = (s.get(pid, "interest_expense", 0.0) or 0.0) + (s.get(pid, "interest_included_above", 0.0) or 0.0)
                if rep and not lo <= rep <= hi:
                    s.flags.append(Flag("warning", "consistency", f"{s.period(pid).label}: interest expense {fmt_money(rep)} is outside the "
                                        f"{fmt_money(lo)}-{fmt_money(hi)} range implied by debt balances and rates. Verify interest.", pid))
    # 2b) year-over-year swings in depreciation / interest that the balance sheet does not explain
    ann = [p for p in s.periods if p.kind != "projection" and p.months == 12]
    debt_end = lambda pid: sum(s.get(pid, k, 0.0) or 0.0 for k in ("line_of_credit", "current_portion_ltd", "long_term_debt"))
    ann_ids = [p.id for p in ann]

    def debt_of(pid):   # interest accrues on the average balance over the year
        i = ann_ids.index(pid)
        prev = ann_ids[i - 1] if i > 0 and s.has(ann_ids[i - 1], "total_assets") else None
        return (debt_end(pid) + debt_end(prev)) / 2 if prev else debt_end(pid)
    fa_of = lambda pid: s.get(pid, "fixed_assets_gross", 0.0) or 0.0
    for key, base_fn, label in (("depreciation", fa_of, "gross fixed assets"), ("interest", debt_of, "total debt")):
        vals = {}
        for p in ann:
            v = (s.get(p.id, "interest_expense", 0.0) or 0.0) + (s.get(p.id, "interest_included_above", 0.0) or 0.0) if key == "interest" \
                else s.get(p.id, "depreciation", None)
            if v:
                vals[p.id] = v
        if len(vals) < 2:
            continue
        ids = list(vals)
        for pid in ids:
            others = sorted(vals[o] for o in ids if o != pid)
            med = others[len(others) // 2]
            ratio = vals[pid] / med if med else None
            if ratio is None or 1 / 2.5 <= ratio <= 2.5:
                continue
            bases = [base_fn(o) for o in ids if o != pid and base_fn(o)]
            base_ratio = base_fn(pid) / (sorted(bases)[len(bases) // 2]) if bases else None
            if base_ratio is not None and (base_ratio == 0 and ratio < 1 or base_ratio and 1 / 3 < ratio / base_ratio < 3):
                continue   # the balance sheet explains the change (e.g. debt paid off, assets added)
            s.flags.append(Flag("warning", "consistency", f"{s.period(pid).label}: {key} of {fmt_money(vals[pid])} is {ratio:.1f}x the other years "
                                f"({fmt_money(med)}) without a matching change in {label}. Verify {key}.", pid))
    for p in ann:
        i = ann_ids.index(p.id)
        debt = max(debt_end(p.id), debt_end(ann_ids[i - 1]) if i > 0 else 0.0)   # balances may be paid down during the year
        intr = (s.get(p.id, "interest_expense", 0.0) or 0.0) + (s.get(p.id, "interest_included_above", 0.0) or 0.0)
        if debt > 50_000 and intr / debt > 0.25:
            s.flags.append(Flag("warning", "consistency", f"{p.label}: interest of {fmt_money(intr)} implies a {intr / debt:.0%} rate on "
                                f"{fmt_money(debt)} of year-end debt. Verify interest.", p.id))
    for p in ann:
        dep, acc = s.get(p.id, "depreciation", None), abs(s.get(p.id, "accumulated_depreciation", 0.0) or 0.0)
        if dep and acc and dep > acc + 1:
            s.flags.append(Flag("warning", "consistency", f"{p.label}: depreciation {fmt_money(dep)} exceeds total accumulated depreciation "
                                f"({fmt_money(acc)}). Verify depreciation.", p.id))
    for p in ann:
        dep, fa = s.get(p.id, "depreciation", None), fa_of(p.id)
        if dep and fa and dep > 0.4 * fa:
            s.flags.append(Flag("warning", "consistency", f"{p.label}: depreciation {fmt_money(dep)} exceeds 40% of gross fixed assets "
                                f"({fmt_money(fa)}). Verify depreciation.", p.id))
    # 3) scale / units sanity ($000s not converted)
    L = deal.terms.proposed_loan
    annual = [p for p in s.periods if p.kind != "projection" and p.months == 12]
    if L and annual:
        pid = annual[-1].id
        rev, ta = s.get(pid, "revenue", 0.0) or 0.0, s.get(pid, "total_assets", 0.0) or 0.0
        emp = deal.profile.employees
        if (ta and L.amount > 3 * ta and rev and L.amount > 3 * rev) or (emp and rev and emp >= 5 and rev / emp < 5_000):
            s.flags.append(Flag("critical", "consistency", f"{s.period(pid).label}: reported sales {fmt_money(rev)} and assets {fmt_money(ta)} look too "
                                f"small for the request ({fmt_money(L.amount)}) or headcount ({emp or 'n/a'}). Check whether the statements are in "
                                "thousands and were not converted.", pid))
    # 4) nothing to foot
    for p in s.periods:
        if p.kind == "projection":
            continue
        have = set(s.cells.get(p.id, {}))
        if have and not (have & TOTAL_FOR_FOOTING):
            s.flags.append(Flag("warning", "data_quality", f"{p.label}: no printed subtotals were extracted, so figures cannot be foot-checked; "
                                "verify key lines against the source.", p.id))


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
