"""Orchestrates one report: data ingestion -> SLA -> forecasting -> NLG -> DOCX/PDF."""
from __future__ import annotations

import logging
import tempfile
import threading
import traceback
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import close_old_connections
from django.utils import timezone
from docx.shared import Mm
from docxtpl import DocxTemplate, InlineImage

from core.sla import calculate_sla
from reports.models import ReportRun

from . import charts, demo, forecasting, jira, metrics, narrative
from .formatting import long_date, month_year, num, pct, short_date, sla_pct
from .pdf import PdfError, docx_to_pdf

log = logging.getLogger(__name__)
CHART_WIDTH = Mm(157)


def period_bounds(period: date) -> tuple[datetime, datetime]:
    """[first day 00:00, first day of next month 00:00) in the portal's time zone."""
    tz = ZoneInfo(settings.TIME_ZONE)
    start = datetime(period.year, period.month, 1, tzinfo=tz)
    nxt = datetime(period.year + (period.month == 12), period.month % 12 + 1, 1, tzinfo=tz)
    return start, nxt


def _fetch_tickets(project, start, end):
    if settings.DATA_SOURCE_MODE == "demo":
        return demo.tickets(project, start, end)
    return jira.fetch_tickets(project, start, end)


def _forecast_row(name: str, assessments: dict, fcs: dict) -> dict:
    """One row per component: a coloured status per metric, recommendations only where needed."""
    notes = []
    for m, a in assessments.items():
        if a.status in {"Kritis", "Perlu Perhatian", "Utilisasi Rendah"}:
            notes.append(f"{forecasting.METRIC_LABELS[m]}: {a.recommendation}")
        elif a.status == "-" and a.recommendation:
            notes.append(f"{forecasting.METRIC_LABELS[m]}: {a.recommendation}")
    if not notes:
        h = max((f.horizon_days for f in fcs.values() if f.available), default=0)
        notes.append(f"Kapasitas memadai untuk {h} hari ke depan." if h else "-")
    return {
        "component": name,
        "cpu": narrative.status_cell(assessments["cpu"].status),
        "memory": narrative.status_cell(assessments["memory"].status),
        "disk": narrative.status_cell(assessments["disk"].status),
        "recommendation": narrative.rich(" ".join(notes), size=18),
    }


def _client_logo(tpl: DocxTemplate, client):
    """Cover logo for the client: fit inside ~30 x 14 mm, or nothing when no logo is uploaded."""
    if not client.logo:
        return ""
    try:
        from PIL import Image

        with client.logo.open("rb") as f:
            w, h = Image.open(f).size
        path = client.logo.path
    except (OSError, ValueError, NotImplementedError):
        return ""
    if w / h > 30 / 14:
        return InlineImage(tpl, path, width=Mm(30))
    return InlineImage(tpl, path, height=Mm(14))


def _ticket_rows(tickets: list[jira.Ticket]) -> list[dict]:
    tz = ZoneInfo(settings.TIME_ZONE)
    return [{
        "key": t.key, "date": short_date(t.created.astimezone(tz)), "summary": t.summary,
        "description": t.description or "-", "reporter": t.reporter, "follow_up": t.follow_up, "status": t.status,
    } for t in tickets]


def build_report(run: ReportRun) -> None:
    project = run.project
    client = project.client
    start, end = period_bounds(run.period)
    period_label = month_year(run.period)
    last_day = end.date().fromordinal(end.date().toordinal() - 1)
    tpl = DocxTemplate(str(settings.REPORT_TEMPLATE_PATH))

    components = list(project.components.filter(is_active=True))
    n = max(len(components), 1)

    # Progress budget, roughly proportional to measured time: SLA 5% · components 5-60%
    # (split evenly) · Jira 60-66% · document 66-72% · PDF 72-100% (LibreOffice is about a
    # third of the total). The PDF step is opaque, so the page smooths the bar through it
    # using the duration of previous runs.
    # ---- SLA
    run.set_progress(2, "Menghitung SLA dari data downtime")
    sla = calculate_sla(project, start, end)
    run.append_log(f"SLA: {sla.actual}% (target {sla.target}%), downtime {sla.downtime_minutes} menit")
    tz = ZoneInfo(settings.TIME_ZONE)
    sla_entries = [{
        "start": dt.start.astimezone(tz).strftime("%d/%m/%Y %H:%M"),
        "end": dt.end.astimezone(tz).strftime("%d/%m/%Y %H:%M"),
        "minutes": num((min(dt.end, end) - max(dt.start, start)).total_seconds() / 60, 0),
        "components": ", ".join(c.name for c in dt.components.all()) or "Seluruh project",
        "category": dt.get_category_display().split(" (")[0],
        "counted": "Ya" if dt.counts_for_sla else "Tidak",
        "notes": " ".join(x for x in (dt.jira_key, dt.notes) if x) or "-",
    } for dt in sla.downtimes]
    down_label = f"{sla.downtime_minutes.normalize():f} menit"
    if sla.excluded_minutes:
        down_label += f" (tidak termasuk {num(sla.excluded_minutes, 0)} menit yang dikecualikan)"

    # ---- components: metrics, forecasts, charts, narrative
    comp_ctx, forecast_rows, flagged, under = [], [], [], []
    models_used: set[str] = set()
    horizons: list[int] = []
    summary_components = {}
    for idx, comp in enumerate(components):
        run.set_progress(5 + 55 * idx / n, f"Mengambil metrik & membuat prakiraan {comp.name} ({idx + 1}/{n})")
        run.append_log(f"Metrik {comp.name}: mengambil data")
        data = metrics.collect(comp, start, end)
        stats, fcs, assessments = {}, {}, {}
        for m in metrics.METRICS:
            stats[m] = forecasting.month_stats(data.raw.get(m))
            fcs[m] = forecasting.forecast(data.history.get(m), m, comp.kind)
            assessments[m] = forecasting.assess(comp.kind, m, stats[m], fcs[m], end.date())
            fc = fcs[m]
            if fc.available:
                models_used.add(fc.model)
                horizons.append(fc.horizon_days)
            a = assessments[m]
            if a.status in {"Kritis", "Perlu Perhatian"}:
                flagged.append(f"{comp.name} ({forecasting.METRIC_LABELS[m]}, {a.status.lower()})")
            elif a.status == "Utilisasi Rendah":
                under.append(f"{comp.name} ({forecasting.METRIC_LABELS[m]})")
        forecast_rows.append(_forecast_row(comp.name, assessments, fcs))

        k8s = comp.kind == "k8s"
        req = " dari $\\it{request}$" if k8s else ""
        panels = [
            (data.raw.get("cpu"), f"Penggunaan CPU (%{req})"),
            (data.raw.get("memory"), f"Penggunaan Memori (%{req})"),
            (data.raw.get("disk"), "Penggunaan $\\it{Volume}$ (%)" if k8s else "Penggunaan Disk (%) – partisi terpenuh"),
        ]
        chart_imgs = {"usage": InlineImage(tpl, charts.usage_panel(panels), width=CHART_WIDTH)}
        fc_panels = []
        for m in metrics.METRICS:
            _, hist_p95 = forecasting.daily(data.history.get(m))
            att, crit = settings.FORECAST_THRESHOLDS[m]
            fc_panels.append({"title": forecasting.METRIC_LABELS[m], "hist": hist_p95, "fc": fcs[m].series_p95,
                              "upper": fcs[m].series_upper, "attention": att, "critical": crit})
        fc_h = max((f.horizon_days for f in fcs.values() if f.available), default=0)
        chart_imgs["forecast"] = InlineImage(
            tpl, charts.forecast_chart(fc_panels, f"Prakiraan {fc_h} hari ke depan" if fc_h else "Prakiraan"),
            width=CHART_WIDTH)

        comp_ctx.append({
            "name": comp.name,
            "hostname": comp.hostname or "-",
            "ip_address": comp.ip_address or ("Kubernetes Autopilot" if k8s else "-"),
            "vcpu": comp.vcpu or "-",
            "memory_gb": num(comp.memory_gb, 0) if comp.memory_gb else "-",
            "disk_gb": num(comp.disk_gb, 0) if comp.disk_gb else "-",
            "charts": chart_imgs,
            "narrative": narrative.rich(
                narrative.component_paragraph(comp.name, comp.kind, period_label, stats, fcs, assessments)),
        })
        summary_components[comp.name] = {
            m: {
                "avg": stats[m].avg, "p95": stats[m].p95, "peak": stats[m].peak,
                "forecast_available": fcs[m].available, "model": fcs[m].model,
                "horizon_days": fcs[m].horizon_days, "history_days": fcs[m].history_days,
                "mae": fcs[m].mae, "naive_mae": fcs[m].naive_mae,
                "mean_forecast": fcs[m].mean_forecast, "upper_bound": fcs[m].upper_bound,
                "status": assessments[m].status,
            } for m in metrics.METRICS
        }

    # ---- tickets
    run.set_progress(60, "Mengambil tiket insiden & permintaan dari Jira")
    run.append_log("Jira: mengambil tiket insiden & permintaan")
    incidents, requests_ = _fetch_tickets(project, start, end)
    run.append_log(f"Jira: {len(incidents)} insiden, {len(requests_)} permintaan")

    horizon = min(horizons) if horizons else None
    user = run.created_by
    context = {
        "provider_name": settings.PROVIDER_NAME,
        "provider_short": settings.PROVIDER_SHORT,
        "client_name": client.name,
        "client_short": client.short_name,
        "client_logo": _client_logo(tpl, client),
        "contract_number": client.contract_number or "-",
        "project_name": project.name,
        "project_short": project.short_name,
        "period_label": period_label,
        "period_start_label": long_date(start),
        "period_end_label": long_date(last_day),
        "doc_version": "1.0",
        "doc_date": long_date(timezone.localdate()),
        "doc_description": "Dokumen awal",
        "prepared_by": (user.get_full_name() or user.get_username()) if user else settings.REPORT_PREPARED_BY,
        "summary_paragraphs": [narrative.rich(p) for p in narrative.executive_summary(
            project.name, run.period, sla, len(incidents), len(requests_), flagged, under)],
        "sla": {
            "downtime_label": down_label,
            "target_label": sla_pct(sla.target),
            "actual_label": sla_pct(sla.actual),
            "entries": sla_entries,
        },
        "components": comp_ctx,
        "services": [{
            "name": s.name, "description": s.description or "-",
            "start": short_date(s.start_date), "end": short_date(s.end_date),
        } for s in project.additional_services.all()],
        "forecast_intro": narrative.rich(narrative.forecast_intro(horizon)),
        "forecast_rows": forecast_rows,
        "forecast_note": narrative.forecast_note(models_used),
        "incidents": _ticket_rows(incidents),
        "requests": _ticket_rows(requests_),
    }

    run.set_progress(66, "Menyusun dokumen laporan")
    run.append_log("Menyusun dokumen")
    tpl.render(context, autoescape=True)
    base = f"{client.short_name} - {project.short_name} - {period_label} Monthly Customer Report"
    with tempfile.TemporaryDirectory() as tmp:
        docx_path, pdf_path = Path(tmp) / "report.docx", Path(tmp) / "report.pdf"
        tpl.save(str(docx_path))
        run.docx_file.save(f"{base}.docx", ContentFile(docx_path.read_bytes()), save=False)
        run.set_progress(72, "Mengonversi dokumen ke PDF")
        run.append_log("Konversi ke PDF")
        pdf_error = ""
        try:
            docx_to_pdf(docx_path, pdf_path)
            run.pdf_file.save(f"{base}.pdf", ContentFile(pdf_path.read_bytes()), save=False)
        except PdfError as exc:
            # Keep the DOCX; the report can still be reviewed, it just cannot be e-mailed yet.
            pdf_error = str(exc)
            run.append_log(f"PDF tidak dibuat: {exc}")

    run.summary = {
        "sla": {
            "target": str(sla.target), "actual": str(sla.actual), "met": sla.met, "method": sla.method,
            "downtime_minutes": str(sla.downtime_minutes), "excluded_minutes": str(sla.excluded_minutes),
            "per_component": {k: str(v) for k, v in sla.per_component.items()},
        },
        "tickets": {"incidents": len(incidents), "requests": len(requests_)},
        "components": summary_components,
        "flagged": flagged,
        "underutilised": under,
        "data_source": settings.DATA_SOURCE_MODE,
        "pdf_error": pdf_error,
    }


def generate(run: ReportRun) -> ReportRun:
    """Run the full pipeline synchronously and record the outcome on ``run``."""
    run.status = ReportRun.Status.GENERATING
    run.error = ""
    run.log = ""
    run.progress, run.progress_label = 0, "Memulai"
    run.started_at = timezone.now()
    run.save(update_fields=["status", "error", "log", "progress", "progress_label", "started_at"])
    try:
        build_report(run)
        run.status = ReportRun.Status.GENERATED
        run.progress, run.progress_label = 100, "Selesai"
        run.append_log("Selesai")
    except Exception as exc:  # recorded for the operator, not swallowed silently
        log.exception("Report %s failed", run.pk)
        run.status = ReportRun.Status.FAILED
        run.error = f"{type(exc).__name__}: {exc}"
        run.append_log(traceback.format_exc())
    run.finished_at = timezone.now()
    run.save()
    return run


def generate_in_background(run_id: int) -> None:
    def target():
        close_old_connections()
        try:
            generate(ReportRun.objects.select_related("project__client", "created_by").get(pk=run_id))
        finally:
            close_old_connections()

    threading.Thread(target=target, daemon=True, name=f"report-{run_id}").start()
