"""Chart rendering (matplotlib -> PNG) for the report.

Charts are drawn from the same numbers used in the tables and forecasts, so
everything in the report is consistent. Light theme for print.
"""
from __future__ import annotations

from io import BytesIO

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402
import pandas as pd  # noqa: E402

from .formatting import MONTHS_ID, num  # noqa: E402

SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
GRID = "#e4e3df"
SERIES = "#2a78d6"
FORECAST_BAND = "#2a78d6"
THRESH_ATT = "#c98500"
THRESH_CRIT = "#e34948"
DPI = 200
WIDTH_IN = 6.2
TZ = "Asia/Jakarta"
LABEL_BOX = dict(boxstyle="round,pad=0.2", fc=SURFACE, ec="none", alpha=0.9)  # keeps labels readable over data

plt.rcParams.update({
    "font.family": ["Inter", "DejaVu Sans"],
    "font.size": 7,
    "axes.edgecolor": GRID,
    "axes.labelcolor": TEXT_2,
    "xtick.color": TEXT_2,
    "ytick.color": TEXT_2,
    "axes.titlecolor": TEXT,
})


def _axes_style(ax):
    ax.set_facecolor(SURFACE)
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.tick_params(length=0)


def _png(fig) -> BytesIO:
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=DPI, facecolor=SURFACE)
    plt.close(fig)
    buf.seek(0)
    return buf


def _draw_usage(ax, series: pd.Series, title: str, unit_note: str = "%", xlabel: bool = True) -> None:
    """One metric over the reporting month, with average and peak annotated."""
    _axes_style(ax)
    s = series.dropna() if series is not None else pd.Series(dtype=float)
    if s.empty:
        ax.text(0.5, 0.5, "Data tidak tersedia", ha="center", va="center", color=TEXT_2, transform=ax.transAxes)
        ax.set_yticks([])
        ax.set_xticks([])
    else:
        s = s.tz_convert(TZ)
        ax.plot(s.index, s.values, color=SERIES, linewidth=0.9)
        ax.fill_between(s.index, s.values, color=SERIES, alpha=0.08, linewidth=0)
        avg, peak_t, peak = s.mean(), s.idxmax(), s.max()
        ax.axhline(avg, color=TEXT_2, linewidth=0.6, linestyle=(0, (3, 3)))
        ax.annotate(f"rata-rata {num(avg)}{unit_note}", (s.index[0], avg), xytext=(2, -3), va="top", bbox=LABEL_BOX,
                    textcoords="offset points", fontsize=6.5, color=TEXT_2)
        ax.plot([peak_t], [peak], marker="o", markersize=3.5, color=SERIES,
                markeredgecolor=SURFACE, markeredgewidth=1)
        # label above the peak; flip to the left when the peak is near the right edge
        near_right = (peak_t - s.index[0]) > 0.8 * (s.index[-1] - s.index[0])
        ax.annotate(f"puncak {num(peak)}{unit_note}", (peak_t, peak), xytext=(-4 if near_right else 4, 3),
                    textcoords="offset points", fontsize=6.5, color=TEXT, va="bottom",
                    ha="right" if near_right else "left", bbox=LABEL_BOX)
        top = max(100.0, peak * 1.12) if unit_note == "%" else peak * 1.12
        ax.set_ylim(0, top)
        ax.set_xlim(s.index[0], s.index[-1])
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=2, tz=s.index.tz))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d", tz=s.index.tz))
        if xlabel:
            ax.set_xlabel("Tanggal", fontsize=6.5)
    ax.set_title(title, loc="left", fontsize=7.5, fontweight="bold", pad=4)


def usage_panel(panels: list[tuple[pd.Series, str]]) -> BytesIO:
    """CPU / memory / disk stacked in one image so a component fits on one page."""
    fig, axes = plt.subplots(len(panels), 1, figsize=(WIDTH_IN, 1.42 * len(panels)))
    fig.patch.set_facecolor(SURFACE)
    for k, (ax, (series, title)) in enumerate(zip(axes, panels)):
        _draw_usage(ax, series, title, xlabel=(k == len(panels) - 1))
    fig.tight_layout(pad=0.4, h_pad=0.9)
    return _png(fig)


def _month_label(x, _pos=None) -> str:
    d = mdates.num2date(x)
    return MONTHS_ID[d.month - 1][:3]


def forecast_chart(panels: list[dict], title: str = "") -> BytesIO:
    """Small multiples: one panel per metric, daily p95 history + forecast + 80% upper bound.

    Each panel dict: title, hist (Series daily p95), fc (Series), upper (Series),
    attention, critical (thresholds) - fc/upper may be empty when no forecast.
    """
    fig, axes = plt.subplots(1, len(panels), figsize=(WIDTH_IN, 1.9), sharey=False)
    fig.patch.set_facecolor(SURFACE)
    for ax, p in zip(axes, panels):
        _axes_style(ax)
        hist = p["hist"].tail(45)
        if hist.empty:
            ax.text(0.5, 0.5, "Data tidak tersedia", ha="center", va="center", color=TEXT_2, transform=ax.transAxes)
            ax.set_xticks([])
        else:
            ax.plot(hist.index, hist.values, color=SERIES, linewidth=1.2)
            fc, upper = p["fc"], p["upper"]
            if not fc.empty:
                bridge = pd.concat([hist.tail(1), fc])
                ax.plot(bridge.index, bridge.values, color=SERIES, linewidth=1.2, linestyle=(0, (3, 2)))
                ax.fill_between(fc.index, fc.values, upper.values, color=FORECAST_BAND, alpha=0.12, linewidth=0)
                ax.axvline(hist.index[-1], color=TEXT_2, linewidth=0.5)
            peak = max(hist.max(), upper.max() if not upper.empty else 0)
            ax.set_ylim(0, max(100.0, peak * 1.08))
            for thr, color in ((p["attention"], THRESH_ATT), (p["critical"], THRESH_CRIT)):
                ax.axhline(thr, color=color, linewidth=0.6, linestyle=(0, (1, 2)))
            ax.xaxis.set_major_locator(mdates.MonthLocator())
            ax.xaxis.set_major_formatter(mticker.FuncFormatter(_month_label))
            ax.tick_params(axis="both", labelsize=6)
        ax.set_title(p["title"], loc="left", fontsize=7.5, fontweight="bold", pad=4)
    if title:
        fig.suptitle(title, x=0.005, ha="left", fontsize=8, fontweight="bold", color=TEXT)
    fig.text(0.005, 0.01, "Garis utuh: puncak harian aktual · putus-putus: prakiraan · area: rentang prakiraan "
             "· garis titik: batas perhatian (kuning) dan kritis (merah)", fontsize=5.8, color=TEXT_2)
    fig.tight_layout(pad=0.4, rect=(0, 0.06, 1, 0.97 if title else 1))
    return _png(fig)
