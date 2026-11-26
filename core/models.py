"""Master data: clients, their cloud projects, the components inside a project,
additional services, and manually recorded downtime (input for the SLA)."""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


def _split_emails(value: str) -> list[str]:
    return [e.strip().lower() for e in value.replace(";", ",").replace("\n", ",").split(",") if e.strip()]


class Client(models.Model):
    name = models.CharField("nama perusahaan", max_length=200, help_text="Contoh: PT ABC")
    short_name = models.CharField("singkatan", max_length=50, help_text="Contoh: ABC")
    contract_number = models.CharField("nomor kontrak", max_length=100, blank=True)
    logo = models.ImageField(
        "logo", upload_to="client-logos/", blank=True,
        help_text="Opsional. Tampil di cover laporan di samping nama client. PNG transparan paling bagus.",
    )
    allowed_email_domains = models.CharField(
        "domain email yang diizinkan",
        max_length=500,
        help_text="Pisahkan dengan koma, contoh: abc.co.id, abc.com. "
                  "Laporan hanya bisa dikirim ke alamat dengan domain ini (atau domain internal).",
    )
    is_active = models.BooleanField("aktif", default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "client"

    def __str__(self) -> str:
        return self.name

    @property
    def allowed_domains(self) -> list[str]:
        return [d.strip().lower().lstrip("@") for d in self.allowed_email_domains.split(",") if d.strip()]


class Project(models.Model):
    class SlaMethod(models.TextChoices):
        ANY_CRITICAL = "any_critical", "Project down jika ada komponen kritikal down (interval digabung)"
        AVERAGE = "average", "Rata-rata availability tiap komponen"
        WEIGHTED = "weighted", "Rata-rata berbobot tiap komponen"

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="projects")
    name = models.CharField("nama project", max_length=200, help_text="Contoh: Project Cloud XYZ")
    short_name = models.CharField("singkatan", max_length=50, help_text="Contoh: XYZ")

    sla_target = models.DecimalField(
        "target SLA (%)", max_digits=6, decimal_places=3,
        default=Decimal(settings.DEFAULT_SLA_TARGET),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
    )
    sla_method = models.CharField(
        "metode perhitungan SLA", max_length=20, choices=SlaMethod.choices, default=SlaMethod.ANY_CRITICAL
    )

    jira_base_jql = models.CharField(
        "JQL dasar Jira", max_length=500,
        help_text='Filter tiket milik project ini, contoh: project = SD AND labels = "client-abc"',
    )
    jira_incident_jql = models.CharField(
        "JQL tambahan insiden", max_length=300, blank=True,
        help_text="Kosongkan untuk memakai default (JIRA_DEFAULT_INCIDENT_JQL).",
    )
    jira_request_jql = models.CharField(
        "JQL tambahan permintaan", max_length=300, blank=True,
        help_text="Kosongkan untuk memakai default (JIRA_DEFAULT_REQUEST_JQL).",
    )

    recipients_to = models.TextField("penerima (To)", help_text="Pisahkan dengan koma.")
    recipients_cc = models.TextField("penerima (CC)", blank=True, help_text="Pisahkan dengan koma.")
    auto_send = models.BooleanField(
        "kirim otomatis", default=False,
        help_text="Jika aktif, laporan dari jadwal otomatis langsung dikirim tanpa approval. "
                  "Biarkan nonaktif sampai hasilnya terbukti konsisten.",
    )
    is_active = models.BooleanField("aktif", default=True)

    class Meta:
        ordering = ["client__name", "name"]
        unique_together = [("client", "name")]

    def __str__(self) -> str:
        return f"{self.client.short_name} / {self.name}"

    @property
    def to_list(self) -> list[str]:
        return _split_emails(self.recipients_to)

    @property
    def cc_list(self) -> list[str]:
        return _split_emails(self.recipients_cc)

    def invalid_recipients(self) -> list[str]:
        """Addresses whose domain is neither the client's nor an internal domain."""
        allowed = set(self.client.allowed_domains) | {d.lower() for d in settings.INTERNAL_EMAIL_DOMAINS}
        bad = []
        for addr in self.to_list + self.cc_list:
            domain = addr.rsplit("@", 1)[-1] if "@" in addr else ""
            if not domain or domain not in allowed:
                bad.append(addr)
        return bad

    def clean(self):
        if not self.to_list:
            raise ValidationError({"recipients_to": "Minimal satu penerima."})
        if self.client_id and (bad := self.invalid_recipients()):
            raise ValidationError(
                {"recipients_to": f"Domain tidak diizinkan untuk client ini: {', '.join(bad)}"}
            )


class Component(models.Model):
    class Kind(models.TextChoices):
        VM = "vm", "Virtual Machine"
        K8S = "k8s", "Kubernetes (Autopilot)"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="components")
    kind = models.CharField("jenis", max_length=10, choices=Kind.choices, default=Kind.VM)
    name = models.CharField("nama", max_length=200)
    hostname = models.CharField(max_length=200, blank=True)
    ip_address = models.CharField("IP address", max_length=100, blank=True)
    # Current size, shown in the report so recommendations ("add vCPU") have context
    vcpu = models.PositiveSmallIntegerField("vCPU", null=True, blank=True)
    memory_gb = models.DecimalField("memori (GB)", max_digits=7, decimal_places=1, null=True, blank=True)
    disk_gb = models.PositiveIntegerField("disk (GB)", null=True, blank=True)
    prometheus_selector = models.CharField(
        "selector Prometheus", max_length=300,
        help_text='Label selector tanpa kurung kurawal. VM: instance="10.0.0.5:9100". '
                  'Kubernetes: cluster="prod-autopilot",namespace="app-abc"',
    )
    is_critical = models.BooleanField(
        "kritikal untuk SLA", default=True,
        help_text="Metode 'any_critical': project dianggap down jika komponen kritikal down.",
    )
    sla_weight = models.DecimalField("bobot SLA", max_digits=5, decimal_places=2, default=Decimal("1"))
    sort_order = models.PositiveIntegerField("urutan", default=0)
    is_active = models.BooleanField("aktif", default=True)

    class Meta:
        ordering = ["project", "sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class AdditionalService(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="additional_services")
    name = models.CharField("nama layanan", max_length=200)
    description = models.CharField("deskripsi", max_length=500, blank=True)
    start_date = models.DateField("start date", null=True, blank=True)
    end_date = models.DateField("end date", null=True, blank=True)

    class Meta:
        ordering = ["project", "name"]
        verbose_name = "layanan tambahan"
        verbose_name_plural = "layanan tambahan"

    def __str__(self) -> str:
        return self.name


class Downtime(models.Model):
    class Category(models.TextChoices):
        UNPLANNED = "unplanned", "Unplanned (dihitung SLA)"
        PLANNED = "planned", "Planned maintenance (dikecualikan)"
        CUSTOMER = "customer", "Disebabkan pelanggan (dikecualikan)"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="downtimes")
    components = models.ManyToManyField(
        Component, related_name="downtimes", blank=True,
        help_text="Komponen yang terdampak. Kosongkan jika seluruh project terdampak.",
    )
    start = models.DateTimeField("mulai")
    end = models.DateTimeField("selesai")
    category = models.CharField("kategori", max_length=20, choices=Category.choices, default=Category.UNPLANNED)
    jira_key = models.CharField("nomor tiket Jira", max_length=50, blank=True)
    notes = models.CharField("keterangan", max_length=500, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start"]

    def __str__(self) -> str:
        return f"{self.project} {self.start:%Y-%m-%d %H:%M} ({self.get_category_display()})"

    @property
    def counts_for_sla(self) -> bool:
        return self.category == self.Category.UNPLANNED

    def clean(self):
        if self.start and self.end and self.end <= self.start:
            raise ValidationError({"end": "Waktu selesai harus setelah waktu mulai."})


class MetricPoint(models.Model):
    """Hourly metric history kept by the portal itself.

    Prometheus retention is often short (default 15 days), so every ingestion
    stores hourly averages here. Forecasts use this growing history instead of
    only the last month.
    """
    component = models.ForeignKey(Component, on_delete=models.CASCADE, related_name="metric_points")
    metric = models.CharField(max_length=10)  # cpu | memory | disk
    ts = models.DateTimeField()
    value = models.FloatField()

    class Meta:
        unique_together = [("component", "metric", "ts")]
        indexes = [models.Index(fields=["component", "metric", "ts"])]
