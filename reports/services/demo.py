"""Synthetic data so the portal can be tried without Prometheus/Jira access.

Deterministic per component, so regenerating a report gives the same numbers.
"""
from __future__ import annotations

import zlib
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from core.models import Component, Project

from .jira import Ticket


def _rng(*parts) -> np.random.Generator:
    return np.random.default_rng(zlib.crc32("|".join(map(str, parts)).encode()))


def component_metrics(component: Component, start: datetime, end: datetime, step_seconds: int = 900) -> dict[str, pd.Series]:
    idx = pd.date_range(pd.Timestamp(start).tz_convert("UTC"), pd.Timestamp(end).tz_convert("UTC"),
                        freq=f"{step_seconds}s", inclusive="left")
    # time since a fixed epoch so consecutive months join up smoothly
    days = (idx - pd.Timestamp("2026-01-01", tz="UTC")).total_seconds().to_numpy() / 86400
    hour = (idx.hour + 7) % 24  # WIB working-hours pattern
    weekday = ((idx + pd.Timedelta(hours=7)).dayofweek < 5).astype(float)
    r = _rng(component.pk, component.name)
    base_cpu, base_mem, base_disk = r.uniform(8, 35), r.uniform(35, 60), r.uniform(15, 40)
    growth_disk = r.uniform(0.01, 0.12)  # % per day

    noise = _rng(component.pk, start.isoformat()).normal
    work = np.exp(-((hour - 13) ** 2) / 18) * (0.6 + 0.4 * weekday)
    cpu = base_cpu + 25 * work + noise(0, 3, len(idx))
    spikes = _rng(component.pk, "spike", start.isoformat()).random(len(idx)) < 0.01
    cpu = cpu + spikes * r.uniform(20, 45)
    mem = base_mem + 0.02 * days + 6 * work + noise(0, 1.2, len(idx))
    disk = base_disk + growth_disk * days + np.floor(days / 9) * 0.3 + noise(0, 0.05, len(idx))
    clip = lambda a: pd.Series(np.clip(a, 0, 100), index=idx)  # noqa: E731
    return {"cpu": clip(cpu), "memory": clip(mem), "disk": clip(disk)}


_INCIDENTS = [
    ("VM tidak dapat diakses melalui SSH", "Pelanggan melaporkan VM tidak dapat diakses.", "Restart service sshd dan pengecekan security group. VM normal kembali."),
    ("Utilisasi CPU tinggi", "Alert CPU > 90% selama 15 menit.", "Ditemukan proses backup berjalan di jam kerja, jadwal dipindah ke malam hari."),
    ("Disk /var hampir penuh", "Alert disk usage > 85%.", "Housekeeping log aplikasi, retensi log diatur 14 hari."),
]
_REQUESTS = [
    ("Penambahan user VPN", "Ditambahkan 2 user VPN baru sesuai permintaan."),
    ("Pembukaan port 443 untuk aplikasi baru", "Rule firewall ditambahkan dan diverifikasi bersama pelanggan."),
    ("Snapshot VM sebelum upgrade aplikasi", "Snapshot dibuat dan dikonfirmasi ke pelanggan."),
    ("Perpanjangan sertifikat SSL", "Sertifikat diperbarui, berlaku hingga 1 tahun ke depan."),
]


def tickets(project: Project, start: datetime, end: datetime) -> tuple[list[Ticket], list[Ticket]]:
    r = _rng(project.pk, start.isoformat(), "tickets")
    span = (end - start).total_seconds()

    def make(prefix: str, n: int, catalogue, with_desc: bool) -> list[Ticket]:
        out = []
        for i in sorted(r.choice(len(catalogue), size=n, replace=False)):
            item = catalogue[i]
            created = start + timedelta(seconds=float(r.uniform(0, span)))
            out.append(Ticket(
                key=f"{prefix}-{int(r.integers(1000, 9999))}",
                created=created,
                summary=item[0],
                description=item[1] if with_desc else "",
                reporter="Tim IT " + project.client.short_name,
                follow_up=item[-1],
                status="Resolved",
            ))
        return sorted(out, key=lambda t: t.created)

    return (
        make("INC", int(r.integers(0, 3)), _INCIDENTS, True),
        make("REQ", int(r.integers(1, 5)), _REQUESTS, False),
    )
