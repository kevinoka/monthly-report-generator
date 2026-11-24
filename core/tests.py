from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase

from core.models import Client, Component, Downtime, Project
from core.sla import calculate_sla, merge_intervals

TZ = ZoneInfo("Asia/Jakarta")
OCT_START = datetime(2026, 10, 1, tzinfo=TZ)
NOV_START = datetime(2026, 11, 1, tzinfo=TZ)
OCT_MINUTES = 31 * 24 * 60  # 44,640


def at(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)


class SlaTests(TestCase):
    def setUp(self):
        client = Client.objects.create(name="PT ABC", short_name="ABC", allowed_email_domains="abc.co.id")
        self.project = Project.objects.create(client=client, name="Project XYZ", short_name="XYZ",
                                              jira_base_jql="project = SD", recipients_to="ops@abc.co.id")
        self.vm1 = Component.objects.create(project=self.project, name="vm-1", prometheus_selector='instance="a"')
        self.vm2 = Component.objects.create(project=self.project, name="vm-2", prometheus_selector='instance="b"')
        self.aux = Component.objects.create(project=self.project, name="aux", is_critical=False,
                                            prometheus_selector='instance="c"')

    def down(self, start, end, comps=(), category=Downtime.Category.UNPLANNED):
        d = Downtime.objects.create(project=self.project, start=start, end=end, category=category)
        d.components.set(comps)
        return d

    def sla(self):
        return calculate_sla(self.project, OCT_START, NOV_START)

    def test_default_target_and_no_downtime(self):
        r = self.sla()
        self.assertEqual(r.target, Decimal("99.412"))
        self.assertEqual(r.actual, Decimal("100.000"))
        self.assertEqual(r.period_minutes, OCT_MINUTES)
        self.assertTrue(r.met)

    def test_overlapping_downtime_is_not_double_counted(self):
        self.down(at(5, 10), at(5, 11), [self.vm1])            # 60 min
        self.down(at(5, 10, 30), at(5, 11, 30), [self.vm2])    # overlaps 30 min -> 90 min total
        r = self.sla()
        self.assertEqual(r.downtime_minutes, Decimal(90))
        expected = (Decimal(OCT_MINUTES - 90) / OCT_MINUTES * 100).quantize(Decimal("0.001"), "ROUND_DOWN")
        self.assertEqual(r.actual, expected)

    def test_planned_and_customer_downtime_excluded(self):
        self.down(at(7, 1), at(7, 3), [], Downtime.Category.PLANNED)
        self.down(at(8, 1), at(8, 2), [self.vm1], Downtime.Category.CUSTOMER)
        r = self.sla()
        self.assertEqual(r.downtime_minutes, 0)
        self.assertEqual(r.excluded_minutes, Decimal(180))
        self.assertEqual(r.actual, Decimal("100.000"))

    def test_non_critical_component_does_not_take_project_down(self):
        self.down(at(9, 0), at(9, 5), [self.aux])
        self.assertEqual(self.sla().downtime_minutes, 0)

    def test_downtime_clipped_to_period(self):
        self.down(datetime(2026, 9, 30, 23, 0, tzinfo=TZ), at(1, 1), [])   # only 60 min fall in October
        self.assertEqual(self.sla().downtime_minutes, Decimal(60))

    def test_target_boundary_is_truncated_not_rounded(self):
        # 263 minutes -> 99.41084...% must not display as meeting 99.412
        self.down(at(10, 0), at(10, 4, 23), [])
        r = self.sla()
        self.assertEqual(r.actual, Decimal("99.410"))
        self.assertFalse(r.met)

    def test_average_method(self):
        self.project.sla_method = Project.SlaMethod.AVERAGE
        self.project.save()
        self.down(at(5, 0), at(5, 3), [self.vm1])  # 180 min on one of three components
        r = self.sla()
        vm1 = (Decimal(OCT_MINUTES - 180) / OCT_MINUTES * 100).quantize(Decimal("0.001"), "ROUND_DOWN")
        self.assertEqual(r.per_component["vm-1"], vm1)
        self.assertEqual(r.actual, ((vm1 + 200) / 3).quantize(Decimal("0.001"), "ROUND_DOWN"))

    def test_merge_intervals(self):
        self.assertEqual(merge_intervals([(at(1, 2), at(1, 3)), (at(1, 1), at(1, 2))]), [(at(1, 1), at(1, 3))])


class RecipientValidationTests(TestCase):
    def test_foreign_domain_rejected(self):
        client = Client.objects.create(name="PT ABC", short_name="ABC", allowed_email_domains="abc.co.id")
        p = Project(client=client, name="P", short_name="P", jira_base_jql="x",
                    recipients_to="ops@abc.co.id, someone@other.com")
        self.assertEqual(p.invalid_recipients(), ["someone@other.com"])
