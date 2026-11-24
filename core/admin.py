from django import forms
from django.contrib import admin

from .models import AdditionalService, Client, Component, Downtime, Project


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


class DowntimeForm(forms.ModelForm):
    class Meta:
        model = Downtime
        fields = ("project", "components", "start", "end", "category", "jira_key", "notes")

    def clean(self):
        data = super().clean()
        project, comps = data.get("project"), data.get("components")
        if project and comps:
            wrong = [c.name for c in comps if c.project_id != project.pk]
            if wrong:
                raise forms.ValidationError(f"Komponen bukan milik project ini: {', '.join(wrong)}")
        return data


@admin.register(Downtime)
class DowntimeAdmin(admin.ModelAdmin):
    form = DowntimeForm
    list_display = ("project", "start", "end", "duration_minutes", "category", "jira_key", "created_by")
    list_filter = ("category", "project__client", "project")
    date_hierarchy = "start"
    search_fields = ("jira_key", "notes")
    filter_horizontal = ("components",)
    readonly_fields = ("created_by", "created_at")

    @admin.display(description="durasi (menit)")
    def duration_minutes(self, obj):
        return round((obj.end - obj.start).total_seconds() / 60, 1)

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
