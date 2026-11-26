"""Live progress + time-remaining estimate for a report being generated.

Two signals are combined:
* history  - how long recent successful runs took (same project first, else any project)
* pace     - elapsed time / fraction done for the current run

Early on only history is reliable; as the run advances, its own pace takes over.
"""
from __future__ import annotations

from statistics import median

from django.utils import timezone

from .models import ReportRun

DONE = {ReportRun.Status.GENERATED, ReportRun.Status.APPROVED, ReportRun.Status.SENT}


def typical_duration(run: ReportRun) -> float | None:
    """Median seconds of recent successful runs, preferring the same project."""
    base = ReportRun.objects.filter(status__in=DONE, started_at__isnull=False, finished_at__isnull=False)
    for qs in (base.filter(project_id=run.project_id), base):
        rows = list(qs.exclude(pk=run.pk).order_by("-finished_at").values_list("started_at", "finished_at")[:7])
        if rows:
            return median((f - s).total_seconds() for s, f in rows)
    return None


def payload(run: ReportRun) -> dict:
    busy = run.is_busy
    elapsed = (timezone.now() - run.started_at).total_seconds() if run.started_at else 0.0
    done_fraction = run.progress / 100
    typical = typical_duration(run) if busy else None

    remaining = None
    if busy:
        pace = elapsed / done_fraction - elapsed if done_fraction >= 0.1 else None
        from_history = max(typical - elapsed, 0) if typical else None
        if pace is not None and from_history is not None:
            remaining = (1 - done_fraction) * from_history + done_fraction * pace
        else:
            remaining = pace if pace is not None else from_history
        if remaining is not None:
            remaining = max(remaining, 1.0)

    # Smooth the bar through long single steps (PDF conversion) using the typical duration,
    # but never past what the worker has actually reported plus the step it is in.
    shown = run.progress
    if busy and typical:
        shown = max(shown, min(97, int(elapsed / typical * 100)))

    return {
        "id": run.pk,
        "status": run.status,
        "status_display": run.get_status_display(),
        "busy": busy,
        "progress": shown if busy else (100 if run.status in DONE else run.progress),
        "label": run.progress_label if busy else run.get_status_display(),
        "elapsed_seconds": round(elapsed),
        "remaining_seconds": round(remaining) if remaining is not None else None,
        "error": run.error,
    }
