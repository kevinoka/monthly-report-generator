"""Indonesian formatting helpers (month names, decimal comma)."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

MONTHS_ID = [
    "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]


def month_year(d: date) -> str:
    return f"{MONTHS_ID[d.month - 1]} {d.year}"


def long_date(d: date | datetime) -> str:
    return f"{d.day} {MONTHS_ID[d.month - 1]} {d.year}"


def datetime_id(d: datetime) -> str:
    return f"{d.day} {MONTHS_ID[d.month - 1][:3]} {d.year} {d:%H:%M}"


def short_date(d: date | datetime | None) -> str:
    return f"{d.day}/{d.month}/{d.year}" if d else "-"


def num(value: float | Decimal | None, decimals: int = 1) -> str:
    """1234.5 -> '1.234,5' (Indonesian separators)."""
    if value is None:
        return "-"
    s = f"{float(value):,.{decimals}f}"
    return s.replace(",", "_").replace(".", ",").replace("_", ".")


def pct(value: float | Decimal | None, decimals: int = 1) -> str:
    return "-" if value is None else f"{num(value, decimals)}%"


def sla_pct(value: Decimal) -> str:
    """99.412 -> '99,412%', 100.000 -> '100%' (as in the existing report)."""
    v = Decimal(value).normalize()
    if v == v.to_integral():
        return f"{int(v)}%"
    return f"{format(v, 'f').replace('.', ',')}%"
