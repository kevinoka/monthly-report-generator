"""Time-series forecasting of resource utilisation + rule-based recommendations.

Approach (kept deliberately simple and explainable):

1. Hourly history -> two daily series: daily mean and daily p95 (the "busy" level).
2. Horizon = 30/60/90 days, never longer than the history available
   (with one month of data the horizon is 30 days; it grows as the portal
   keeps collecting data every month).
3. Candidate models per series:
     - naive      : mean of the last 7 days, flat   (baseline)
     - linear     : linear trend (least squares)
     - holt_winters: additive damped trend (+ weekly seasonality when >= 3 weeks of data)
   Each is back-tested on the last days of history; the one with the lowest
   MAE is used. Accuracy of the chosen model vs the naive baseline is kept
   so it can be reviewed.
4. An 80% upper bound is derived from the back-test error.
5. Status + recommendation come from thresholds per metric.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd
from django.conf import settings

MODEL_LABELS = {"naive": "Naive (rata-rata 7 hari)", "linear": "Tren linear", "holt_winters": "Holt-Winters"}
METRIC_LABELS = {"cpu": "CPU", "memory": "Memori", "disk": "Disk"}
Z80 = 1.2816


@dataclass
class MonthStats:
    avg: float | None
    p95: float | None
    peak: float | None
    peak_at: pd.Timestamp | None


@dataclass
class Forecast:
    available: bool
    reason: str = ""
    model: str = ""
    horizon_days: int = 0
    history_days: int = 0
    mae: float | None = None
    naive_mae: float | None = None
    mean_forecast: float | None = None       # average of forecast daily means over the horizon
    p95_forecast_max: float | None = None    # highest forecast daily p95 over the horizon
    upper_bound: float | None = None         # 80% upper bound of that
    daily_growth: float | None = None        # slope of the daily-p95 forecast, % per day
    days_to_attention: int | None = None
    days_to_critical: int | None = None
    series_mean: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    series_p95: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    series_upper: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))


@dataclass
class Assessment:
    status: str          # Normal | Perlu Perhatian | Kritis | Utilisasi Rendah | -
    recommendation: str


# --------------------------------------------------------------------------- stats
def month_stats(series: pd.Series) -> MonthStats:
    s = series.dropna()
    if s.empty:
        return MonthStats(None, None, None, None)
    return MonthStats(float(s.mean()), float(s.quantile(0.95)), float(s.max()), s.idxmax())


def daily(history: pd.Series) -> tuple[pd.Series, pd.Series]:
    s = history.dropna()
    g = s.resample("1D")
    return g.mean().dropna(), g.quantile(0.95).dropna()


# --------------------------------------------------------------------------- models
def _fit_predict(y: pd.Series, model: str, steps: int) -> np.ndarray:
    values = y.to_numpy(dtype=float)
    if model == "naive":
        return np.repeat(values[-7:].mean(), steps)
    if model == "linear":
        x = np.arange(len(values))
        slope, intercept = np.polyfit(x, values, 1)
        return intercept + slope * np.arange(len(values), len(values) + steps)
    if model == "holt_winters":
        from statsmodels.tsa.holtwinters import ExponentialSmoothing

        seasonal = "add" if len(values) >= 21 else None
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = ExponentialSmoothing(
                values, trend="add", damped_trend=True, seasonal=seasonal,
                seasonal_periods=7 if seasonal else None, initialization_method="estimated",
            ).fit()
        return np.asarray(fit.forecast(steps))
    raise ValueError(model)


def _backtest(y: pd.Series, model: str, holdout: int) -> tuple[float, np.ndarray]:
    train, test = y.iloc[:-holdout], y.iloc[-holdout:]
    pred = _fit_predict(train, model, holdout)
    err = test.to_numpy() - pred
    return float(np.mean(np.abs(err))), err


def _choose(y: pd.Series) -> tuple[str, float, float, float]:
    """Return (model, mae, naive_mae, error_std) based on a back-test."""
    holdout = max(3, min(7, len(y) // 4))
    results = {}
    for m in ("naive", "linear", "holt_winters"):
        try:
            results[m] = _backtest(y, m, holdout)
        except Exception:  # model failed to converge etc. -> skip it
            continue
    best = min(results, key=lambda m: results[m][0])
    mae, err = results[best]
    return best, mae, results["naive"][0], float(np.std(err, ddof=0)) or mae


def _horizon(history_days: int) -> int:
    max_h = settings.FORECAST_MAX_HORIZON_DAYS
    for h in (90, 60, 30):
        if h <= max_h and history_days >= h:
            return h
    return min(history_days, settings.FORECAST_MIN_HORIZON_DAYS)


def _first_crossing(series: pd.Series, threshold: float) -> int | None:
    hits = np.nonzero(series.to_numpy() >= threshold)[0]
    return int(hits[0]) + 1 if len(hits) else None


def forecast(history: pd.Series, metric: str, kind: str = "vm") -> Forecast:
    d_mean, d_p95 = daily(history)
    history_days = len(d_mean)
    if history_days < 14:
        return Forecast(False, reason=f"Data historis baru {history_days} hari (minimal 14 hari).",
                        history_days=history_days)
    horizon = _horizon(history_days)
    start = d_mean.index[-1] + pd.Timedelta(days=1)
    idx = pd.date_range(start, periods=horizon, freq="1D")

    model_p95, mae, naive_mae, err_std = _choose(d_p95)
    model_mean, *_ = _choose(d_mean)
    p95 = pd.Series(np.clip(_fit_predict(d_p95, model_p95, horizon), 0, None), index=idx)
    mean = pd.Series(np.clip(_fit_predict(d_mean, model_mean, horizon), 0, None), index=idx)
    # uncertainty grows with distance from the last observation
    widen = np.sqrt(1 + np.arange(1, horizon + 1) / 7)
    upper = p95 + Z80 * err_std * widen
    # percentages of capacity cannot exceed 100; Kubernetes usage vs *request* can
    cap = None if (kind == "k8s" and metric != "disk") else 100.0
    p95, mean, upper = (s.clip(upper=cap) for s in (p95, mean, upper))

    attention, critical = settings.FORECAST_THRESHOLDS[metric]
    growth = float(np.polyfit(np.arange(horizon), p95.to_numpy(), 1)[0]) if horizon > 1 else 0.0
    return Forecast(
        available=True,
        model=model_p95,
        horizon_days=horizon,
        history_days=history_days,
        mae=mae,
        naive_mae=naive_mae,
        mean_forecast=float(mean.mean()),
        p95_forecast_max=float(p95.max()),
        upper_bound=float(upper.max()),
        daily_growth=growth,
        days_to_attention=_first_crossing(p95, attention),
        days_to_critical=_first_crossing(p95, critical),
        series_mean=mean,
        series_p95=p95,
        series_upper=upper,
    )


# --------------------------------------------------------------------------- recommendations
def _when(period_end: date, days: int) -> str:
    from .formatting import long_date

    return long_date(period_end + timedelta(days=days - 1))


def assess(kind: str, metric: str, stats: MonthStats, fc: Forecast, period_end: date) -> Assessment:
    if stats.avg is None:
        return Assessment("-", "Data metrik tidak tersedia untuk periode ini.")
    if not fc.available:
        return Assessment("-", fc.reason)

    attention, critical = settings.FORECAST_THRESHOLDS[metric]
    k8s = kind == "k8s"
    res = {"cpu": "vCPU", "memory": "memori (RAM)", "disk": "kapasitas disk"}[metric]

    if fc.days_to_critical:
        if stats.p95 is not None and stats.p95 >= critical:
            lead = f"Sudah di atas {critical:.0f}% pada periode ini."
        else:
            lead = f"Diperkirakan mencapai {critical:.0f}% sekitar {_when(period_end, fc.days_to_critical)}."
        if metric == "disk":
            action = f"Rencanakan penambahan {'*volume*' if k8s else 'kapasitas disk'} atau pembersihan data (*housekeeping*)."
        elif k8s:
            action = f"Naikkan *request* {METRIC_LABELS[metric]} *pod* untuk mencegah *throttling*/*out of memory*."
        else:
            action = f"Pertimbangkan penambahan {res}."
        return Assessment("Kritis", f"{lead} {action}")

    if fc.days_to_attention:
        when = _when(period_end, fc.days_to_attention)
        return Assessment(
            "Perlu Perhatian",
            f"Diperkirakan melewati {attention:.0f}% sekitar {when}. Pantau tren dan siapkan rencana penambahan "
            f"{'*resource request*' if k8s else res}.",
        )

    low = settings.FORECAST_UNDERUTILISED_P95
    if metric != "disk" and stats.p95 is not None and stats.p95 < low and (fc.p95_forecast_max or 0) < low + 5:
        if k8s:
            msg = ("Pemakaian jauh di bawah *resource request*. Pertimbangkan menurunkan *request* "
                   "untuk efisiensi biaya.")
        else:
            msg = f"Utilisasi rendah. Pertimbangkan pengurangan {res} untuk efisiensi biaya."
        return Assessment("Utilisasi Rendah", msg)

    return Assessment("Normal", f"Kapasitas memadai untuk {fc.horizon_days} hari ke depan.")
