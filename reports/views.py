from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import Client

from .forms import GenerateForm, SendForm
from .models import ReportRun
from .progress import payload
from .services import builder, mailer


@login_required
@permission_required("reports.view_reportrun", raise_exception=True)
def report_list(request):
    runs = ReportRun.objects.select_related("project__client", "created_by")
    client_id = request.GET.get("client")
    q = request.GET.get("q", "").strip()
    if client_id:
        runs = runs.filter(project__client_id=client_id)
    if q:
        runs = runs.filter(Q(project__name__icontains=q) | Q(project__client__name__icontains=q))
    return render(request, "reports/list.html", {
        "runs": runs[:200],
        "clients": Client.objects.filter(is_active=True),
        "client_id": client_id,
        "q": q,
    })


@login_required
@permission_required("reports.add_reportrun", raise_exception=True)
def generate(request):
    form = GenerateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        period = form.cleaned_data["period"]
        ids = []
        for project in form.cleaned_data["projects"]:
            run = ReportRun.objects.create(project=project, period=period, created_by=request.user)
            builder.generate_in_background(run.pk)
            ids.append(run.pk)
        messages.success(request, f"{len(ids)} laporan sedang dibuat.")
        return redirect("reports:detail", ids[0]) if len(ids) == 1 else redirect("reports:list")
    return render(request, "reports/generate.html", {"form": form})


@login_required
@permission_required("reports.view_reportrun", raise_exception=True)
def detail(request, pk):
    run = get_object_or_404(ReportRun.objects.select_related("project__client"), pk=pk)
    send_problems = mailer.preflight(run) if run.status == ReportRun.Status.APPROVED else []
    return render(request, "reports/detail.html", {
        "run": run,
        "send_form": SendForm(),
        "send_problems": send_problems,
        "can_approve": request.user.has_perm("reports.approve_reportrun"),
        "can_send": request.user.has_perm("reports.send_reportrun"),
        "can_generate": request.user.has_perm("reports.add_reportrun"),
    })


@login_required
@permission_required("reports.view_reportrun", raise_exception=True)
def download(request, pk, kind):
    run = get_object_or_404(ReportRun, pk=pk)
    f = {"pdf": run.pdf_file, "docx": run.docx_file}.get(kind)
    if not f:
        raise Http404
    inline = kind == "pdf" and request.GET.get("inline") == "1"
    return FileResponse(f.open("rb"), as_attachment=not inline, filename=f.name.rsplit("/", 1)[-1])


@require_POST
@login_required
@permission_required("reports.add_reportrun", raise_exception=True)
def regenerate(request, pk):
    old = get_object_or_404(ReportRun, pk=pk)
    if old.is_busy:
        messages.warning(request, "Laporan ini masih diproses.")
        return redirect("reports:detail", pk)
    run = ReportRun.objects.create(project=old.project, period=old.period, created_by=request.user)
    builder.generate_in_background(run.pk)
    messages.success(request, "Laporan dibuat ulang dengan data terbaru.")
    return redirect("reports:detail", run.pk)


@require_POST
@login_required
def approve(request, pk):
    if not request.user.has_perm("reports.approve_reportrun"):
        raise PermissionDenied
    run = get_object_or_404(ReportRun, pk=pk)
    if run.status != ReportRun.Status.GENERATED:
        messages.error(request, "Hanya laporan berstatus 'Menunggu approval' yang dapat disetujui.")
    else:
        run.status = ReportRun.Status.APPROVED
        run.approved_by, run.approved_at = request.user, timezone.now()
        run.save(update_fields=["status", "approved_by", "approved_at"])
        messages.success(request, "Laporan disetujui.")
    return redirect("reports:detail", pk)


@require_POST
@login_required
def send(request, pk):
    if not request.user.has_perm("reports.send_reportrun"):
        raise PermissionDenied
    run = get_object_or_404(ReportRun.objects.select_related("project__client"), pk=pk)
    form = SendForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Centang konfirmasi sebelum mengirim.")
        return redirect("reports:detail", pk)
    try:
        mailer.send(run, user=request.user)
    except mailer.SendBlocked as exc:
        messages.error(request, f"Tidak dikirim: {exc}")
    except Exception as exc:  # SMTP errors etc.
        messages.error(request, f"Gagal mengirim email: {exc}")
    else:
        messages.success(request, f"Laporan terkirim ke {run.sent_to}.")
    return redirect("reports:detail", pk)


@login_required
@permission_required("reports.view_reportrun", raise_exception=True)
def status(request, pk):
    """Polled by the detail page while a report is being generated."""
    return JsonResponse(payload(get_object_or_404(ReportRun, pk=pk)))


@login_required
@permission_required("reports.view_reportrun", raise_exception=True)
def status_many(request):
    """Polled by the list page for rows that are still being generated (?ids=1,2,3)."""
    ids = [int(x) for x in request.GET.get("ids", "").split(",") if x.strip().isdigit()][:50]
    runs = ReportRun.objects.filter(pk__in=ids)
    return JsonResponse({"runs": [payload(r) for r in runs]})
