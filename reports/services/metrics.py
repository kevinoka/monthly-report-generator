"""Collect metrics for a component and keep an hourly history in the database."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd
from django.conf import settings

from core.models import Component, MetricPoint

from . import demo, prometheus

METRICS = ("cpu", "memory", "disk")
DEMO_BACKFILL_DAYS = 90


@dataclass
class ComponentData:
    raw: dict[str, pd.Series]       # reporting month at Prometheus step resolution (for charts/stats)
    history: dict[str, pd.Series]   # hourly history up to the end of the month (for forecasting)


def _fetch(component: Component, start: datetime, end: datetime) -> dict[str, pd.Series]:
    if settings.DATA_SOURCE_MODE == "demo":
        return demo.component_metrics(component, start, end, settings.PROMETHEUS_STEP_SECONDS)
    return prometheus.fetch_component_metrics(component, start, end)


def store_hourly(component: Component, series: dict[str, pd.Series]) -> int:
    points = []
    for metric, s in series.items():
        if s.empty:
            continue
        hourly = s.resample("1h").mean().dropna()
        points += [MetricPoint(component=component, metric=metric, ts=ts.to_pydatetime(), value=float(v))
                   for ts, v in hourly.items()]
    MetricPoint.objects.bulk_create(
        points, batch_size=2000,
        update_conflicts=True, unique_fields=["component", "metric", "ts"], update_fields=["value"],
    )
    return len(points)


def load_history(component: Component, end: datetime, days: int) -> dict[str, pd.Series]:
    rows = (MetricPoint.objects.filter(component=component, ts__gte=end - timedelta(days=days), ts__lt=end)
            .order_by("ts").values_list("metric", "ts", "value"))
    df = pd.DataFrame(list(rows), columns=["metric", "ts", "value"])
    out = {}
    for m in METRICS:
        part = df[df.metric == m]
        out[m] = pd.Series(part.value.to_numpy(), index=pd.to_datetime(part.ts, utc=True), dtype=float)
    return out


def collect(component: Component, start: datetime, end: datetime) -> ComponentData:
    raw = _fetch(component, start, end)
    store_hourly(component, raw)
    if settings.DATA_SOURCE_MODE == "demo":
        # pretend the portal has been collecting for a while, so forecasts have history to use
        back_start = start - timedelta(days=DEMO_BACKFILL_DAYS)
        if not MetricPoint.objects.filter(component=component, ts__lt=start, ts__gte=back_start).exists():
            store_hourly(component, demo.component_metrics(component, back_start, start, 3600))
    history = load_history(component, end, settings.FORECAST_HISTORY_DAYS)
    return ComponentData(raw=raw, history=history)
