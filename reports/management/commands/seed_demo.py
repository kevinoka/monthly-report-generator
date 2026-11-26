"""Create demo master data + users so the portal can be tried immediately."""
from django.contrib.auth.models import Group, Permission, User
from django.core.management.base import BaseCommand

from core.models import AdditionalService, Client, Component, Project


def ensure_groups() -> None:
    perms = {
        "Operator": ["view_reportrun", "add_reportrun", "view_client", "view_project", "view_component",
                     "view_downtime", "add_downtime", "change_downtime", "view_additionalservice"],
        "Approver": ["view_reportrun", "add_reportrun", "approve_reportrun", "send_reportrun",
                     "view_client", "view_project", "view_component", "view_downtime", "add_downtime",
                     "change_downtime", "delete_downtime", "view_additionalservice"],
    }
    for name, codenames in perms.items():
        g, _ = Group.objects.get_or_create(name=name)
        g.permissions.set(Permission.objects.filter(codename__in=codenames))


class Command(BaseCommand):
    help = "Seed demo data (client ABC / project XYZ, users admin/operator/approver)."

    def handle(self, *args, **opts):
        ensure_groups()
        client, _ = Client.objects.get_or_create(
            short_name="ABC",
            defaults={"name": "PT ABC", "contract_number": "XXX/XXXX/00-2026",
                      "allowed_email_domains": "abc.co.id"},
        )
        project, _ = Project.objects.get_or_create(
            client=client, name="Project Cloud XYZ",
            defaults={"short_name": "XYZ", "jira_base_jql": 'project = SD AND labels = "client-abc"',
                      "recipients_to": "it-ops@abc.co.id", "recipients_cc": ""},
        )
        specs = {1: (4, 8, 100), 2: (8, 16, 200), 3: (2, 4, 80)}
        for i in (1, 2, 3):
            vcpu, mem, disk = specs[i]
            comp, _ = Component.objects.get_or_create(
                project=project, name=f"xyz-vm-{i}",
                defaults={"hostname": f"xyz-vm-{i}", "ip_address": "139.255.xx.xx", "sort_order": i,
                          "prometheus_selector": f'instance="xyz-vm-{i}:9100"'},
            )
            if comp.vcpu is None:
                comp.vcpu, comp.memory_gb, comp.disk_gb = vcpu, mem, disk
                comp.save(update_fields=["vcpu", "memory_gb", "disk_gb"])
        Component.objects.get_or_create(
            project=project, name="xyz-gke-autopilot",
            defaults={"kind": Component.Kind.K8S, "hostname": "xyz-gke-autopilot", "sort_order": 4,
                      "is_critical": False,
                      "prometheus_selector": 'cluster="xyz-autopilot",namespace="xyz-app"'},
        )
        AdditionalService.objects.get_or_create(
            project=project, name="Subscription Red Hat",
            defaults={"description": "Red Hat Enterprise Linux Server, Premium"},
        )
        users = {"admin": None, "operator": "Operator", "approver": "Approver"}
        for username, group in users.items():
            if User.objects.filter(username=username).exists():
                continue
            u = User.objects.create_user(username, password=f"{username}12345",
                                         first_name=username.title(), is_staff=True,
                                         is_superuser=group is None)
            if group:
                u.groups.add(Group.objects.get(name=group))
        self.stdout.write(self.style.SUCCESS(
            "Demo data siap. Login: admin/admin12345, operator/operator12345, approver/approver12345"))
