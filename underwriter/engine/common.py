"""Shared primitives: loan math, flags, traceable numbers."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


# ------------------------------------------------------------------ loan math
def monthly_payment(principal: float, annual_rate: float, amort_months: int, day_count: str = "30/360") -> float:
    """Level P&I payment. amort_months == 0 -> interest only. actual/360 scales the rate by 365/360."""
    rate = annual_rate * (365 / 360 if day_count == "actual/360" else 1.0)
    r = rate / 12
    if amort_months <= 0:
        return principal * r
    if r == 0:
        return principal / amort_months
    return principal * r / (1 - (1 + r) ** -amort_months)


def annual_debt_service(principal: float, annual_rate: float, amort_months: int, day_count: str = "30/360") -> float:
    return monthly_payment(principal, annual_rate, amort_months, day_count) * 12


def max_loan_for_payment(annual_payment: float, annual_rate: float, amort_months: int) -> float:
    """Principal that a given annual debt service supports (used for DSCR-based loan sizing)."""
    r = annual_rate / 12
    m = annual_payment / 12
    if amort_months <= 0:
        return m / r
    return m * (1 - (1 + r) ** -amort_months) / r


def safe_div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return a / b


# ------------------------------------------------------------------ flags
@dataclass
class Flag:
    severity: str          # "critical" | "warning" | "info"
    category: str          # e.g. "data_quality", "consistency", "policy", "benchmark", "missing"
    message: str
    ref: Optional[str] = None   # "doc p.N" or field path

    def to_dict(self):
        return asdict(self)


@dataclass
class Trace:
    """A computed number with how it was produced. Every figure in the memo should be one of these."""
    value: Optional[float]
    formula: str = ""
    sources: list[str] = field(default_factory=list)
    kind: str = "computed"   # extracted | input | derived | assumption | computed

    def to_dict(self):
        return asdict(self)


def fmt_money(v: Optional[float], dollars=True, paren=True) -> str:
    if v is None:
        return "n/a"
    s = f"{abs(round(v)):,.0f}"
    if dollars:
        s = "$" + s
    if v < 0 and round(v) != 0:
        return f"({s})" if paren else "-" + s
    return s


def fmt_m(v: Optional[float], digits=3) -> str:
    """$9.335M style used in Invest Detroit narratives."""
    if v is None:
        return "n/a"
    if abs(v) >= 1_000_000:
        return f"${v / 1_000_000:.{digits}f}M"
    if abs(v) >= 1_000:
        return f"${v / 1_000:.0f}K"
    return f"${v:,.0f}"


def fmt_pct(v: Optional[float], digits=1) -> str:
    return "n/a" if v is None else f"{v * 100:.{digits}f}%"


def fmt_x(v: Optional[float], digits=2) -> str:
    return "n/a" if v is None else f"{v:.{digits}f}x"


def jsonable(obj: Any):
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    return obj
