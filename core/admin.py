from django.contrib import admin

from .models import AdditionalService, Client, Component, Project


class ProjectInline(admin.TabularInline):
    model = Project
    fields = ("name", "short_name", "sla_target", "is_active")
    extra = 0
    show_change_link = True


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("name", "short_name", "contract_number", "allowed_email_domains", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "short_name")
    inlines = [ProjectInline]


class ComponentInline(admin.TabularInline):
    model = Component
    fields = ("sort_order", "kind", "name", "hostname", "ip_address", "prometheus_selector",
              "is_critical", "sla_weight", "is_active")
    extra = 0


class AdditionalServiceInline(admin.TabularInline):
    model = AdditionalService
    extra = 0


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "client", "sla_target", "sla_method", "auto_send", "is_active")
    list_filter = ("client", "sla_method", "auto_send", "is_active")
    search_fields = ("name", "short_name", "client__name")
    inlines = [ComponentInline, AdditionalServiceInline]
    fieldsets = (
        (None, {"fields": ("client", "name", "short_name", "is_active")}),
        ("SLA (layanan 24x7)", {"fields": ("sla_target", "sla_method")}),
        ("Jira Cloud", {"fields": ("jira_base_jql", "jira_incident_jql", "jira_request_jql")}),
        ("Pengiriman email", {"fields": ("recipients_to", "recipients_cc", "auto_send")}),
    )

# Downtime is managed on its own portal page (/downtime/), not in the admin.
