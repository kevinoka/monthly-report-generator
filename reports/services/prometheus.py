"""Prometheus HTTP API client (the same data Grafana displays)."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import requests
from django.conf import settings

from core.models import Component


class PrometheusError(RuntimeError):
    pass


def build_query(component: Component, metric: str) -> str:
    template = settings.METRIC_QUERIES[component.kind][metric]
    return template.format(selector=component.prometheus_selector)


def _session() -> requests.Session:
    s = requests.Session()
    s.verify = settings.PROMETHEUS_VERIFY_TLS
    if settings.PROMETHEUS_BEARER_TOKEN:
        s.headers["Authorization"] = f"Bearer {settings.PROMETHEUS_BEARER_TOKEN}"
    elif settings.PROMETHEUS_USERNAME:
        s.auth = (settings.PROMETHEUS_USERNAME, settings.PROMETHEUS_PASSWORD)
    return s


def query_range(query: str, start: datetime, end: datetime, step: int | None = None) -> pd.Series:
    """Run a range query that must return a single series. Returns a UTC-indexed Series."""
    if not settings.PROMETHEUS_URL:
        raise PrometheusError("PROMETHEUS_URL belum diset.")
    step = step or settings.PROMETHEUS_STEP_SECONDS
    resp = _session().post(
        settings.PROMETHEUS_URL.rstrip("/") + "/api/v1/query_range",
        data={"query": query, "start": start.timestamp(), "end": end.timestamp(), "step": step},
        timeout=settings.PROMETHEUS_TIMEOUT_SECONDS,
    )
    try:
        payload = resp.json()
    except ValueError as exc:
        raise PrometheusError(f"HTTP {resp.status_code}: respons bukan JSON") from exc
    if resp.status_code != 200 or payload.get("status") != "success":
        raise PrometheusError(f"HTTP {resp.status_code}: {payload.get('error', payload)}")
    result = payload["data"]["result"]
    if not result:
        return pd.Series(dtype=float)
    if len(result) > 1:
        raise PrometheusError(
            f"Query mengembalikan {len(result)} series, seharusnya 1. Periksa selector/agregasi: {query}"
        )
    values = result[0]["values"]
    idx = pd.to_datetime([float(t) for t, _ in values], unit="s", utc=True)
    return pd.Series([float(v) for _, v in values], index=idx).clip(lower=0)


def fetch_component_metrics(component: Component, start: datetime, end: datetime) -> dict[str, pd.Series]:
    return {m: query_range(build_query(component, m), start, end) for m in ("cpu", "memory", "disk")}
