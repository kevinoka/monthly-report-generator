from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from reports.services.builder import period_bounds
from reports.services.formatting import month_year, sla_pct

from .forms import DowntimeForm
from .models import Component, Downtime, Project
from .sla import calculate_sla


def _month_from(value: str | None) -> date:
    try:
        y, m = map(int, (value or "").split("-"))
        return date(y, m, 1)
    except ValueError:
        return timezone.localdate().replace(day=1)


@login_required
@permission_required("core.view_downtime", raise_exception=True)
def downtime_list(request):
    month = _month_from(request.GET.get("month"))
    start, end = period_bounds(month)
    projects = Project.objects.filter(is_active=True).select_related("client")
    project_id = request.GET.get("project") or ""
    qs = (Downtime.objects.filter(start__lt=end, end__gt=start)
          .select_related("project__client", "created_by").prefetch_related("components").order_by("start"))
    project = None
    if project_id:
        project = get_object_or_404(Project, pk=project_id)
        qs = qs.filter(project=project)

    sla = calculate_sla(project, start, end) if project else None
    rows = [{
        "obj": d,
        "minutes": round((d.end - d.start).total_seconds() / 60),
        "components": ", ".join(c.name for c in d.components.all()) or "Seluruh project",
    } for d in qs]
    return render(request, "core/downtime_list.html", {
        "rows": rows,
        "projects": projects,
        "project": project,
        "project_id": project_id,
        "month_value": f"{month:%Y-%m}",
        "month_label": month_year(month),
        "sla": sla,
        "sla_actual": sla_pct(sla.actual) if sla else "",
        "sla_target": sla_pct(sla.target) if sla else "",
        "can_add": request.user.has_perm("core.add_downtime"),
        "can_change": request.user.has_perm("core.change_downtime"),
        "can_delete": request.user.has_perm("core.delete_downtime"),
    })


def _form_page(request, form, obj=None):
    comps = Component.objects.filter(is_active=True).select_related("project").order_by("project", "sort_order", "name")
    selected = {str(v) for v in (form["components"].value() or [])}
    return render(request, "core/downtime_form.html", {
        "form": form,
        "obj": obj,
        "component_choices": [
            {"pk": c.pk, "name": c.name, "project_id": c.project_id, "kind": c.get_kind_display(),
             "critical": c.is_critical, "checked": str(c.pk) in selected}
            for c in comps
        ],
    })


def _back_url(obj: Downtime) -> str:
    local = timezone.localtime(obj.start)
    return f"/downtime/?project={obj.project_id}&month={local:%Y-%m}"


@login_required
@permission_required("core.add_downtime", raise_exception=True)
def downtime_create(request):
    initial = {}
    if pid := request.GET.get("project"):
        initial["project"] = pid
    form = DowntimeForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.created_by = request.user
        obj.save()
        form.save_m2m()
        messages.success(request, "Downtime tersimpan.")
        return redirect(_back_url(obj))
    return _form_page(request, form)


@login_required
@permission_required("core.change_downtime", raise_exception=True)
def downtime_edit(request, pk):
    obj = get_object_or_404(Downtime, pk=pk)
    form = DowntimeForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Downtime diperbarui.")
        return redirect(_back_url(obj))
    return _form_page(request, form, obj)


@require_POST
@login_required
@permission_required("core.delete_downtime", raise_exception=True)
def downtime_delete(request, pk):
    obj = get_object_or_404(Downtime, pk=pk)
    back = _back_url(obj)
    obj.delete()
    messages.success(request, "Downtime dihapus.")
    return redirect(back)
