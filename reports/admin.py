from django.contrib import admin

from .models import ReportRun


@admin.register(ReportRun)
class ReportRunAdmin(admin.ModelAdmin):
    list_display = ("project", "period", "status", "created_by", "created_at", "approved_by", "sent_at")
    list_filter = ("status", "project__client")
    date_hierarchy = "period"
    readonly_fields = [f.name for f in ReportRun._meta.fields]

    def has_add_permission(self, request):
        return False
