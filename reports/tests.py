import io
import shutil
import tempfile
from datetime import date

import numpy as np
import pandas as pd
from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import Project
from reports.models import ReportRun
from reports.services import builder, forecasting, jira, mailer
from reports.services.formatting import num, sla_pct


def hourly(values_per_day: list[float], noise: float = 0.0) -> pd.Series:
    idx = pd.date_range("2026-08-01", periods=len(values_per_day) * 24, freq="1h", tz="UTC")
    rng = np.random.default_rng(1)
    vals = np.repeat(values_per_day, 24) + rng.normal(0, noise, len(idx))
    return pd.Series(vals, index=idx)


class FormattingTests(TestCase):
    def test_indonesian_numbers(self):
        self.assertEqual(num(1234.56), "1.234,6")
        self.assertEqual(sla_pct(__import__("decimal").Decimal("99.412")), "99,412%")
        self.assertEqual(sla_pct(__import__("decimal").Decimal("100.000")), "100%")


class ForecastTests(TestCase):
    def test_horizon_limited_by_history(self):
        fc = forecasting.forecast(hourly([40.0] * 31, noise=1), "cpu")
        self.assertTrue(fc.available)
        self.assertEqual(fc.horizon_days, 30)
        fc = forecasting.forecast(hourly([40.0] * 95, noise=1), "cpu")
        self.assertEqual(fc.horizon_days, 90)

    def test_too_little_history(self):
        fc = forecasting.forecast(hourly([40.0] * 10), "cpu")
        self.assertFalse(fc.available)

    def test_growing_disk_is_flagged_with_date(self):
        series = hourly(list(np.linspace(60, 75, 31)), noise=0.1)   # +0.5%/day
        fc = forecasting.forecast(series, "disk")
        self.assertEqual(fc.model, "linear")
        self.assertIsNotNone(fc.days_to_critical)
        a = forecasting.assess("vm", "disk", forecasting.month_stats(series), fc, date(2026, 11, 1))
        self.assertEqual(a.status, "Kritis")
        self.assertIn("kapasitas disk", a.recommendation)

    def test_low_cpu_is_underutilised(self):
        series = hourly([5.0] * 31, noise=0.5)
        fc = forecasting.forecast(series, "cpu")
        a = forecasting.assess("vm", "cpu", forecasting.month_stats(series), fc, date(2026, 11, 1))
        self.assertEqual(a.status, "Underutilized")


class JiraParsingTests(TestCase):
    def test_adf_and_ticket_mapping(self):
        issue = {"key": "SD-1", "fields": {
            "summary": "VM down", "created": "2026-10-05T10:00:00.000+0700",
            "description": {"type": "doc", "content": [{"type": "paragraph", "content": [
                {"type": "text", "text": "Server"}, {"type": "hardBreak"}, {"type": "text", "text": "mati"}]}]},
            "reporter": {"displayName": "Budi"}, "status": {"name": "Resolved"},
            "comment": {"comments": [{"body": {"type": "doc", "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "Sudah direstart"}]}]}}]},
        }}
        t = jira.to_ticket(issue)
        self.assertEqual((t.key, t.reporter, t.status), ("SD-1", "Budi", "Resolved"))
        self.assertEqual(t.description, "Server mati")
        self.assertEqual(t.follow_up, "Sudah direstart")


@override_settings(DATA_SOURCE_MODE="demo", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class EndToEndTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media = tempfile.mkdtemp()
        cls._media = override_settings(MEDIA_ROOT=cls.media)
        cls._media.enable()

    @classmethod
    def tearDownClass(cls):
        cls._media.disable()
        shutil.rmtree(cls.media, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        call_command("seed_demo", stdout=io.StringIO())
        self.project = Project.objects.get(short_name="XYZ")

    @classmethod
    def has_libreoffice(cls):
        return shutil.which("soffice") is not None

    def test_generate_approve_send(self):
        if not self.has_libreoffice():
            self.skipTest("LibreOffice not installed")
        run = builder.generate(ReportRun.objects.create(project=self.project, period=date(2026, 10, 1)))
        self.assertEqual(run.status, ReportRun.Status.GENERATED, run.log)
        self.assertTrue(run.pdf_file and run.docx_file)
        self.assertEqual(run.summary["sla"]["actual"], "100.000")

        # sending requires approval first
        self.assertIn("Laporan belum disetujui (approve).", mailer.preflight(run))
        approver = User.objects.get(username="approver")
        self.client.force_login(approver)
        self.client.post(reverse("reports:approve", args=[run.pk]))
        self.client.post(reverse("reports:send", args=[run.pk]), {"confirm": "on"})
        run.refresh_from_db()
        self.assertEqual(run.status, ReportRun.Status.SENT)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["it-ops@abc.co.id"])
        self.assertEqual(mail.outbox[0].attachments[0][2], "application/pdf")

    def test_operator_cannot_approve(self):
        run = ReportRun.objects.create(project=self.project, period=date(2026, 10, 1),
                                       status=ReportRun.Status.GENERATED)
        self.client.force_login(User.objects.get(username="operator"))
        resp = self.client.post(reverse("reports:approve", args=[run.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_pages_render(self):
        self.client.force_login(User.objects.get(username="operator"))
        self.assertEqual(self.client.get(reverse("reports:list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("reports:generate")).status_code, 200)


@override_settings(DATA_SOURCE_MODE="demo", LIBREOFFICE_BINARY="no-such-soffice", UNO_PYTHON="no-such-python")
class WithoutLibreOfficeTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, True)
        call_command("seed_demo", stdout=io.StringIO())

    def test_docx_still_produced_and_sending_blocked(self):
        with override_settings(MEDIA_ROOT=self.media):
            project = Project.objects.get(short_name="XYZ")
            run = builder.generate(ReportRun.objects.create(project=project, period=date(2026, 10, 1)))
        self.assertEqual(run.status, ReportRun.Status.GENERATED, run.log)
        self.assertTrue(run.docx_file)
        self.assertFalse(run.pdf_file)
        self.assertIn("LibreOffice tidak ditemukan", run.summary["pdf_error"])
        self.assertTrue(any("PDF" in p for p in mailer.preflight(run, require_approval=False)))
