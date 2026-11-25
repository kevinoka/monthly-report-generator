from django import forms

from .models import Component, Downtime, Project

DT_FORMAT = "%Y-%m-%dT%H:%M"


class DowntimeForm(forms.ModelForm):
    """Used by the portal page and by Django admin."""

    class Meta:
        model = Downtime
        fields = ("project", "components", "start", "end", "category", "jira_key", "notes")
        widgets = {
            "start": forms.DateTimeInput(attrs={"type": "datetime-local"}, format=DT_FORMAT),
            "end": forms.DateTimeInput(attrs={"type": "datetime-local"}, format=DT_FORMAT),
            "components": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["project"].queryset = Project.objects.filter(is_active=True).select_related("client")
        self.fields["components"].queryset = Component.objects.filter(is_active=True).select_related("project")
        for name in ("start", "end"):
            self.fields[name].input_formats = [DT_FORMAT, "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"]

    def clean(self):
        data = super().clean()
        project, comps = data.get("project"), data.get("components")
        if project and comps:
            wrong = [c.name for c in comps if c.project_id != project.pk]
            if wrong:
                raise forms.ValidationError(f"Komponen bukan milik project ini: {', '.join(wrong)}")
        return data
