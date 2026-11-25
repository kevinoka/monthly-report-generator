"""Sending a finished report to the customer, with safety checks."""
from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone

from reports.models import ReportRun

from .formatting import month_year


class SendBlocked(RuntimeError):
    pass


def preflight(run: ReportRun, require_approval: bool = True) -> list[str]:
    """Return a list of problems; empty means the report may be sent."""
    problems = []
    if require_approval and run.status != ReportRun.Status.APPROVED:
        problems.append("Laporan belum disetujui (approve).")
    if run.status == ReportRun.Status.SENT:
        problems.append("Laporan ini sudah pernah dikirim.")
    if not run.pdf_file:
        problems.append("File PDF belum tersedia (LibreOffice belum terpasang di server?).")
    if not run.project.to_list:
        problems.append("Project tidak memiliki penerima (To).")
    if bad := run.project.invalid_recipients():
        problems.append("Domain penerima tidak sesuai dengan client: " + ", ".join(bad))
    return problems


def compose(run: ReportRun) -> EmailMessage:
    project, client = run.project, run.project.client
    period = month_year(run.period)
    body = (
        f"Yth. Bapak/Ibu {client.name},\n\n"
        f"Terlampir laporan bulanan layanan cloud untuk {project.name} periode {period}, berisi "
        f"ketersediaan layanan (SLA), utilisasi resource, prakiraan dan rekomendasi resource, serta "
        f"daftar insiden dan permintaan.\n\n"
        f"Apabila terdapat pertanyaan, silakan membalas email ini.\n\n"
        f"Hormat kami,\n{settings.PROVIDER_NAME}"
    )
    msg = EmailMessage(
        subject=f"[{settings.PROVIDER_SHORT}] Monthly Customer Report - {client.short_name} {project.short_name} - {period}",
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=project.to_list,
        cc=project.cc_list,
    )
    run.pdf_file.open("rb")
    try:
        msg.attach(run.pdf_file.name.rsplit("/", 1)[-1], run.pdf_file.read(), "application/pdf")
    finally:
        run.pdf_file.close()
    return msg


def send(run: ReportRun, user=None, require_approval: bool = True) -> None:
    if problems := preflight(run, require_approval):
        raise SendBlocked(" ".join(problems))
    msg = compose(run)
    msg.send(fail_silently=False)
    run.status = ReportRun.Status.SENT
    run.sent_at = timezone.now()
    run.sent_by = user
    run.sent_to = ", ".join(msg.to + msg.cc)
    run.save(update_fields=["status", "sent_at", "sent_by", "sent_to"])
