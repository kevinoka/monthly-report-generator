from datetime import date

from django.conf import settings
from django.db import models

from core.models import Project


def report_upload_to(instance: "ReportRun", filename: str) -> str:
    return f"reports/{instance.period:%Y-%m}/{instance.project_id}/{filename}"


class ReportRun(models.Model):
    """One generated monthly report for one project and one month."""

    class Status(models.TextChoices):
        QUEUED = "queued", "Antre"
        GENERATING = "generating", "Sedang dibuat"
        GENERATED = "generated", "Menunggu approval"
        FAILED = "failed", "Gagal"
        APPROVED = "approved", "Disetujui"
        SENT = "sent", "Terkirim"

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="reports")
    period = models.DateField(help_text="Tanggal 1 pada bulan laporan.")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)

    docx_file = models.FileField(upload_to=report_upload_to, blank=True)
    pdf_file = models.FileField(upload_to=report_upload_to, blank=True)
    # Numbers behind the report (SLA, metric stats, forecasts, ticket counts) for audit/review
    summary = models.JSONField(default=dict, blank=True)
    log = models.TextField(blank=True)
    error = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    sent_to = models.TextField(blank=True)

    class Meta:
        ordering = ["-period", "project__client__name", "project__name", "-created_at"]
        permissions = [
            ("approve_reportrun", "Dapat menyetujui laporan"),
            ("send_reportrun", "Dapat mengirim laporan ke pelanggan"),
        ]

    def __str__(self) -> str:
        return f"{self.project} - {self.period:%Y-%m}"

    @property
    def is_busy(self) -> bool:
        return self.status in {self.Status.QUEUED, self.Status.GENERATING}

    def append_log(self, line: str) -> None:
        self.log = f"{self.log}{line}\n"


def first_of_month(d: date) -> date:
    return d.replace(day=1)
