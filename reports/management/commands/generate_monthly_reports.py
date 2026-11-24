"""Generate reports for all active projects (meant for cron / a scheduler).

Examples:
    python manage.py generate_monthly_reports                 # previous month, all active projects
    python manage.py generate_monthly_reports --period 2026-10 --project 3
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from core.models import Project
from reports.models import ReportRun
from reports.services import builder, mailer


class Command(BaseCommand):
    help = "Generate monthly reports (and auto-send for projects with auto_send enabled)."

    def add_arguments(self, parser):
        parser.add_argument("--period", help="YYYY-MM (default: previous month)")
        parser.add_argument("--project", type=int, action="append", help="Project id (repeatable)")
        parser.add_argument("--no-send", action="store_true", help="Never send, even if auto_send is on")

    def handle(self, *args, period=None, project=None, no_send=False, **opts):
        if period:
            try:
                y, m = map(int, period.split("-"))
                month = date(y, m, 1)
            except ValueError as exc:
                raise CommandError("--period harus berformat YYYY-MM") from exc
        else:
            today = date.today()
            month = date(today.year - (today.month == 1), (today.month - 2) % 12 + 1, 1)

        projects = Project.objects.filter(is_active=True, client__is_active=True).select_related("client")
        if project:
            projects = projects.filter(pk__in=project)
        failed = 0
        for p in projects:
            run = builder.generate(ReportRun.objects.create(project=p, period=month))
            if run.status != ReportRun.Status.GENERATED:
                failed += 1
                self.stderr.write(self.style.ERROR(f"{p}: GAGAL - {run.error}"))
                continue
            msg = f"{p}: OK (#{run.pk})"
            if p.auto_send and not no_send:
                try:
                    mailer.send(run, require_approval=False)
                    msg += f", terkirim ke {run.sent_to}"
                except mailer.SendBlocked as exc:
                    msg += f", TIDAK dikirim: {exc}"
            self.stdout.write(self.style.SUCCESS(msg))
        if failed:
            raise CommandError(f"{failed} laporan gagal dibuat")
