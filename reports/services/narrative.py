"""Template-based Natural Language Generation (Bahasa Indonesia).

Sentences are assembled from rules and the computed numbers, so every number
in the text is guaranteed to match the tables. No data leaves the server.

English terms that have no good Indonesian equivalent are wrapped in *asterisks*;
``rich()`` turns those into italic runs for the Word template.
"""
from __future__ import annotations

from docxtpl import RichText

from .forecasting import METRIC_LABELS, Assessment, Forecast, MonthStats
from .formatting import datetime_id, month_year, pct, sla_pct

STATUS_COLORS = {
    "Normal": "00802B",
    "Perlu Perhatian": "B34D00",
    "Kritis": "C40000",
    "Utilisasi Rendah": "5C5C5C",
}


def rich(text: str, size: int | None = None, **style) -> RichText:
    """'*italic* parts' -> docxtpl RichText. ``size`` in half-points (18 = 9pt)."""
    rt = RichText()
    for i, chunk in enumerate(text.split("*")):
        if chunk:
            rt.add(chunk, italic=(i % 2 == 1), size=size, **style)
    return rt


def status_cell(status: str, size: int = 18) -> RichText:
    rt = RichText()
    rt.add(status, bold=True, color=STATUS_COLORS.get(status), size=size)
    return rt


def component_paragraph(name: str, kind: str, period_label: str,
                        stats: dict[str, MonthStats], forecasts: dict[str, Forecast],
                        assessments: dict[str, Assessment]) -> str:
    parts = []
    usage = []
    for m in ("cpu", "memory", "disk"):
        st = stats[m]
        if st.avg is None:
            continue
        unit = " dari *resource request*" if kind == "k8s" and m != "disk" else ""
        usage.append(f"{METRIC_LABELS[m]} rata-rata {pct(st.avg)}{unit} dengan puncak {pct(st.peak)} "
                     f"({datetime_id(st.peak_at.tz_convert('Asia/Jakarta'))} WIB)")
    if usage:
        parts.append(f"Selama periode {period_label}, utilisasi {name}: " + "; ".join(usage) + ".")
    else:
        parts.append(f"Data utilisasi {name} tidak tersedia untuk periode {period_label}.")

    flagged = [(m, a) for m, a in assessments.items() if a.status in {"Kritis", "Perlu Perhatian"}]
    under = [m for m, a in assessments.items() if a.status == "Utilisasi Rendah"]
    fc_any = next((f for f in forecasts.values() if f.available), None)
    if fc_any:
        if flagged:
            parts.append(" ".join(f"{METRIC_LABELS[m]}: {a.recommendation}" for m, a in flagged))
        else:
            parts.append(f"Berdasarkan prakiraan {fc_any.horizon_days} hari ke depan, tidak ada *resource* "
                         f"yang diperkirakan melewati ambang batas.")
        if under:
            parts.append(f"Utilisasi {', '.join(METRIC_LABELS[m] for m in under)} relatif rendah sehingga "
                         f"terdapat peluang efisiensi.")
    return " ".join(parts)


def executive_summary(project_name: str, period, sla, incidents: int, requests: int,
                      flagged: list[str], under: list[str]) -> list[str]:
    paras = []
    met = "memenuhi" if sla.met else "belum memenuhi"
    down = (f"total *downtime* yang dihitung {sla.downtime_minutes.normalize():f} menit"
            if sla.downtime_minutes else "tanpa *downtime* yang dihitung")
    paras.append(
        f"Pada periode {month_year(period)}, layanan {project_name} mencapai tingkat ketersediaan "
        f"{sla_pct(sla.actual)} ({down}), {met} target SLA {sla_pct(sla.target)}."
    )
    paras.append(
        f"Tercatat {incidents} insiden dan {requests} permintaan layanan selama periode ini."
        if incidents or requests else "Tidak terdapat insiden maupun permintaan layanan selama periode ini."
    )
    if flagged:
        paras.append("*Resource* yang perlu mendapat perhatian berdasarkan hasil prakiraan: "
                     + "; ".join(flagged) + ". Rincian rekomendasi tersedia pada bagian Prakiraan & "
                     "Rekomendasi *Resource*.")
    else:
        paras.append("Berdasarkan hasil prakiraan, kapasitas seluruh *resource* masih memadai untuk periode ke depan.")
    if under:
        paras.append("Terdapat peluang efisiensi pada *resource* dengan utilisasi rendah: " + "; ".join(under) + ".")
    return paras


def forecast_intro(horizon_days: int | None) -> str:
    if not horizon_days:
        return ("Prakiraan belum dapat dibuat karena data historis belum mencukupi. Prakiraan akan tersedia "
                "setelah data terkumpul minimal 14 hari.")
    return (f"Tabel berikut merangkum kondisi kapasitas setiap *resource* untuk {horizon_days} hari ke depan "
            "berdasarkan pola utilisasi historis. Status Normal berarti kapasitas memadai, Perlu Perhatian "
            "berarti utilisasi diperkirakan mendekati batas, dan Kritis berarti diperkirakan melewati batas "
            "sehingga perlu tindakan.")


def forecast_note(models_used: set[str]) -> str:
    # Model names stay in the portal (detail page); the customer only needs the caveat.
    return ("Catatan: prakiraan bersifat estimasi berdasarkan data historis dan dapat berbeda dari kondisi aktual, "
            "terutama bila terdapat perubahan beban kerja (misalnya aplikasi baru atau kampanye).")
