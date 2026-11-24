"""SLA (availability) calculation.

Availability = (total minutes in period - counted downtime minutes) / total minutes x 100

* Service hours are 24x7, so "total minutes" is every minute of the period.
* Only UNPLANNED downtime counts; planned maintenance and customer-caused
  downtime are listed in the report but excluded.
* Downtime is clipped to the reporting period.
* Overlapping downtime is merged so the same minute is never counted twice.

Methods (chosen per project):
    any_critical  The project is down while ANY critical component is down.
                  A downtime with no components selected = whole project down.
    average       Mean of each component's own availability.
    weighted      Same, weighted by Component.sla_weight.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_DOWN, Decimal

from .models import Downtime, Project

Interval = tuple[datetime, datetime]


def merge_intervals(intervals: list[Interval]) -> list[Interval]:
    merged: list[Interval] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def total_minutes(intervals: list[Interval]) -> Decimal:
    seconds = sum((e - s).total_seconds() for s, e in merge_intervals(intervals))
    return Decimal(str(seconds)) / Decimal(60)


def clip(start: datetime, end: datetime, p_start: datetime, p_end: datetime) -> Interval | None:
    s, e = max(start, p_start), min(end, p_end)
    return (s, e) if e > s else None


@dataclass
class SlaResult:
    period_start: datetime
    period_end: datetime
    target: Decimal
    method: str
    period_minutes: Decimal
    downtime_minutes: Decimal            # counted (unplanned) downtime used for availability
    excluded_minutes: Decimal            # planned / customer-caused, informational
    actual: Decimal                      # percent
    per_component: dict[str, Decimal] = field(default_factory=dict)
    downtimes: list[Downtime] = field(default_factory=list)

    @property
    def met(self) -> bool:
        return self.actual >= self.target


def _floor3(value: Decimal) -> Decimal:
    # Truncate (not round) so 99.4119 is never shown as meeting a 99.412 target.
    return value.quantize(Decimal("0.001"), rounding=ROUND_DOWN)


def availability(down_minutes: Decimal, period_minutes: Decimal) -> Decimal:
    if period_minutes <= 0:
        return Decimal("100")
    return _floor3((period_minutes - down_minutes) / period_minutes * 100)


def calculate_sla(project: Project, period_start: datetime, period_end: datetime) -> SlaResult:
    """``period_end`` is exclusive (e.g. 2026-11-01 00:00 for October)."""
    components = list(project.components.filter(is_active=True))
    downtimes = list(
        project.downtimes.filter(start__lt=period_end, end__gt=period_start)
        .prefetch_related("components")
        .order_by("start")
    )
    period_minutes = Decimal(str((period_end - period_start).total_seconds())) / Decimal(60)

    counted: list[Interval] = []
    excluded: list[Interval] = []
    per_comp_intervals: dict[int, list[Interval]] = {c.pk: [] for c in components}

    for dt in downtimes:
        iv = clip(dt.start, dt.end, period_start, period_end)
        if iv is None:
            continue
        if not dt.counts_for_sla:
            excluded.append(iv)
            continue
        selected = list(dt.components.all())
        affected = selected or components  # nothing selected = whole project
        for comp in affected:
            if comp.pk in per_comp_intervals:
                per_comp_intervals[comp.pk].append(iv)
        if not selected or any(c.is_critical for c in selected):
            counted.append(iv)

    per_component = {
        c.name: availability(total_minutes(per_comp_intervals[c.pk]), period_minutes) for c in components
    }

    if project.sla_method == Project.SlaMethod.ANY_CRITICAL or not components:
        down = total_minutes(counted)
        actual = availability(down, period_minutes)
    else:
        weights = {
            c.pk: (c.sla_weight if project.sla_method == Project.SlaMethod.WEIGHTED else Decimal(1))
            for c in components
        }
        total_w = sum(weights.values()) or Decimal(1)
        actual = _floor3(sum(per_component[c.name] * weights[c.pk] for c in components) / total_w)
        # equivalent project-level downtime, so the report's "Total downtime" is consistent
        down = (period_minutes * (Decimal(100) - actual) / Decimal(100)).quantize(Decimal("0.1"))

    return SlaResult(
        period_start=period_start,
        period_end=period_end,
        target=project.sla_target,
        method=project.sla_method,
        period_minutes=period_minutes,
        downtime_minutes=down,
        excluded_minutes=total_minutes(excluded),
        actual=actual,
        per_component=per_component,
        downtimes=downtimes,
    )

