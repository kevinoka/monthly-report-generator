from datetime import date

from django import forms

from core.models import Project


def _month_choices(n: int = 13) -> list[tuple[str, str]]:
    from .services.formatting import month_year

    today = date.today()
    out = []
    y, m = today.year, today.month
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append((f"{y}-{m:02d}", month_year(date(y, m, 1))))
    return out


class GenerateForm(forms.Form):
    period = forms.ChoiceField(label="Periode")
    projects = forms.ModelMultipleChoiceField(
        label="Project",
        queryset=Project.objects.filter(is_active=True, client__is_active=True).select_related("client"),
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["period"].choices = _month_choices()

    def clean_period(self) -> date:
        y, m = map(int, self.cleaned_data["period"].split("-"))
        return date(y, m, 1)


class SendForm(forms.Form):
    confirm = forms.BooleanField(
        label="Saya sudah memeriksa isi laporan dan daftar penerima di atas.", required=True
    )
