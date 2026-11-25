# monthly-report-generator

Web portal yang membuat **laporan bulanan pelanggan cloud** secara otomatis. Data metrik diambil dari
Prometheus (sumber data Grafana), tiket dari Jira Cloud, dan SLA dihitung dari data downtime. Portal juga
membuat prakiraan dan rekomendasi resource (time-series forecasting), menyusun DOCX/PDF dari template
perusahaan, lalu mengirimkannya ke pelanggan via email setelah di-approve.

## Alur kerja

```
Prometheus ──┐                              ┌─> DOCX (template perusahaan, bisa diedit)
Jira Cloud ──┼─> Ingestion ─> SLA ─> Forecast ─> NLG ─┤
Downtime  ───┘   (simpan histori per jam)               └─> PDF ─> Review ─> Approve ─> Email
```

| Modul (dokumen tugas) | Implementasi |
|---|---|
| Data Ingestion | `reports/services/prometheus.py` (PromQL `query_range`), `reports/services/jira.py` (`/rest/api/3/search/jql`), histori per jam di tabel `MetricPoint` |
| Predictive Engine | `reports/services/forecasting.py`: Naive, Tren linear, Holt-Winters; dipilih otomatis lewat backtest (MAE) |
| Document Generator (NLG) | `reports/services/narrative.py` (NLG berbasis template, data tidak keluar server), `charts.py`, `builder.py`, `templates/report_template.docx` |
| Admin Web Portal | Django: login, RBAC (grup Operator/Approver), master data, input downtime, generate, approve, kirim |
| SLA | `core/sla.py`: layanan 24x7, default target 99,412%, downtime diinput manual |

## Mencoba cepat (mode demo, tanpa akses Prometheus/Jira)

Butuh Python 3.12+. LibreOffice dibutuhkan untuk membuat PDF. Tanpa LibreOffice laporan tetap dibuat
dalam bentuk DOCX (bisa diunduh dan dicek), tetapi belum bisa dikirim ke pelanggan.

```bash
python -m venv .venv && . .venv/bin/activate
```

```bash
pip install -r requirements.txt
```

```bash
python manage.py migrate && python manage.py seed_demo
```

```bash
python manage.py runserver
```

Buka http://127.0.0.1:8000. Login `approver` / `approver12345` (bisa approve dan kirim) atau
`operator` / `operator12345` (hanya bisa generate). Di mode demo email hanya dicetak ke console.

## Konfigurasi produksi

Salin `.env.example` ke `.env`, isi nilainya, set `DATA_SOURCE_MODE=live`, lalu jalankan:

```bash
docker compose up -d --build
```

```bash
docker compose exec web python manage.py createsuperuser
```

Semua kredensial (Prometheus, Jira, SMTP) hanya ada di environment variable dan **tidak disimpan di database**.

### Master data (menu *Master data*)
1. **Client**: nama, singkatan, nomor kontrak, dan **domain email yang diizinkan**. Laporan tidak bisa
   dikirim ke alamat di luar domain ini atau `INTERNAL_EMAIL_DOMAINS`.
2. **Project**: target SLA (default 99,412%), metode SLA, JQL Jira, dan penerima email.
3. **Komponen** (per project): VM atau Kubernetes Autopilot, beserta *selector* Prometheus:
   - VM (node_exporter): `instance="10.0.0.5:9100"`
   - Kubernetes: `cluster="prod-autopilot",namespace="app-abc"`. Utilisasi dihitung terhadap *resource
     request* karena Autopilot ditagih berdasarkan request.

PromQL per metrik ada di `METRIC_QUERIES` (`portal/settings.py`). Sesuaikan dengan label di Prometheus kantor.

### SLA
- Downtime diinput manual di menu **Input downtime**: project, komponen terdampak (kosong berarti seluruh
  project), waktu mulai/selesai, kategori, dan nomor tiket.
- Hanya kategori *Unplanned* yang dihitung. *Planned maintenance* dan *disebabkan pelanggan* tetap
  ditampilkan di laporan tetapi dikecualikan.
- Metode per project:
  - `any_critical`: project dianggap down bila ada komponen kritikal yang down. Interval yang tumpang tindih
    digabung.
  - `average`: rata-rata availability tiap komponen.
  - `weighted`: rata-rata berbobot.
- Nilai availability dipotong (bukan dibulatkan) ke 3 desimal, supaya 99,4119% tidak tampil sebagai
  memenuhi target 99,412%.

### Prakiraan
- Setiap kali laporan dibuat, metrik disimpan per jam ke database. Dengan begitu histori terus bertambah
  walaupun retensi Prometheus pendek.
- Horizon prakiraan 30/60/90 hari, tidak pernah lebih panjang dari histori yang tersedia. Dengan data
  1 bulan, horizonnya 30 hari.
- Akurasi model (MAE vs baseline naive) ditampilkan di halaman detail laporan untuk evaluasi.

### Penjadwalan otomatis
Jalankan tiap tanggal 1 lewat cron atau systemd timer. Command ini membuat laporan bulan sebelumnya untuk
semua project aktif:

```bash
python manage.py generate_monthly_reports
```

Laporan masuk ke status *Menunggu approval*. Project dengan `auto_send` aktif langsung dikirim, tetap
dengan validasi domain penerima.

### Template laporan
`templates/report_template.docx` dibuat dari sampel di `templates/` oleh
`scripts/build_report_template.py`. Template ini bisa diedit langsung di Word selama tag `{{ ... }}`,
`{%p ... %}`, dan `{%tr ... %}` tidak diubah (sintaks [docxtpl](https://docxtpl.readthedocs.io)).

## Test

```bash
python manage.py test
```
