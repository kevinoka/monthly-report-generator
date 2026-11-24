"""Turn the sample monthly report (.docx) into a docxtpl (Jinja) template.

The sample in ``templates/`` is a real, filled-in report. This script copies it
and replaces the customer-specific parts with Jinja placeholders so the
application can fill them in. It only needs to run again if the sample
layout changes; the generated ``templates/report_template.docx`` can also be
edited directly in Word (keep the ``{{ ... }}`` / ``{%tr ... %}`` tags intact).

Usage:
    python scripts/build_report_template.py [SAMPLE.docx] [OUTPUT.docx]
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import docx
from docx.enum.text import WD_BREAK
from docx.oxml.ns import qn
from docx.table import Table, _Row
from docx.text.paragraph import Paragraph

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SAMPLE = (
    ROOT
    / "templates"
    / "[Sample] Customer ABC - Oktober 2026 Monthly Customer Report.docx"
)
DEFAULT_OUTPUT = ROOT / "templates" / "report_template.docx"


# --------------------------------------------------------------------------- helpers
def set_text(paragraph: Paragraph, text: str) -> None:
    """Put ``text`` in the first run (keeping its formatting) and drop the other runs."""
    runs = paragraph.runs
    if not runs:
        paragraph.add_run(text)
        return
    runs[0].text = text
    for r in runs[1:]:
        r._r.getparent().remove(r._r)


def replace_across_runs(paragraph: Paragraph, old: str, new: str) -> int:
    """Replace ``old`` with ``new`` even when ``old`` is split over several runs.

    The replacement takes the formatting of the run where the match starts.
    Returns the number of replacements made.
    """
    count = 0
    while True:
        runs = paragraph.runs
        full = "".join(r.text for r in runs)
        idx = full.find(old)
        if idx < 0:
            return count
        end = idx + len(old)
        pos = 0
        first = True
        for r in runs:
            r_start, r_end = pos, pos + len(r.text)
            pos = r_end
            if r_end <= idx or r_start >= end:
                continue
            a = max(idx, r_start) - r_start
            b = min(end, r_end) - r_start
            if first:
                r.text = r.text[:a] + new + r.text[b:]
                first = False
            else:
                r.text = r.text[:a] + r.text[b:]
        count += 1


def replace_after_colon(paragraph: Paragraph, value: str) -> None:
    """For ``Label<TAB>: value`` lines: keep the label, replace everything after ':'."""
    runs = paragraph.runs
    for i, r in enumerate(runs):
        if ":" in r.text:
            r.text = r.text[: r.text.index(":")] + ": " + value
            for extra in runs[i + 1 :]:
                extra._r.getparent().remove(extra._r)
            return
    raise ValueError(f"no ':' in paragraph {paragraph.text!r}")


def clone_paragraph_after(
    anchor, source: Paragraph, text: str | None = None
) -> Paragraph:
    """Insert a copy of ``source`` after the XML element ``anchor``."""
    new_p = copy.deepcopy(source._p)
    anchor.addnext(new_p)
    p = Paragraph(new_p, source._parent)
    # drop drawings / breaks that came along with the copy
    for el in new_p.xpath(".//w:drawing|.//w:br"):
        el.getparent().remove(el)
    if text is not None:
        set_text(p, text)
    return p


def tag_paragraph_after(anchor, source: Paragraph, tag: str) -> Paragraph:
    """A paragraph holding only a docxtpl ``{%p ... %}`` tag (removed at render time)."""
    return clone_paragraph_after(anchor, source, tag)


def cell_text(cell, text: str) -> None:
    paras = cell.paragraphs
    set_text(paras[0], text)
    for p in paras[1:]:
        p._p.getparent().remove(p._p)


def make_loop_table(
    table, item: str, collection: str, fields: list[str], empty_text: str = "-"
) -> None:
    """Convert a table (header row + one example row) into a docxtpl row loop.

    Resulting rows:
        {%tr for item in collection %} / data row / {%tr endfor %}
        {%tr if not collection %} / "-" row / {%tr endif %}
    """
    rows = table.rows
    data_tr = rows[1]._tr
    # remove any extra example rows
    for r in list(rows)[2:]:
        r._tr.getparent().remove(r._tr)

    def new_row(texts: list[str]):
        tr = copy.deepcopy(data_tr)
        table._tbl.append(tr)
        row = _Row(tr, table)
        for cell, t in zip(row.cells, texts):
            cell_text(cell, t)
        return row

    n = len(fields)
    blank = [""] * (n - 1)
    data_row = rows[1]
    for cell, t in zip(data_row.cells, fields):
        cell_text(cell, t)
    # move the data row to the end so we can build rows in order
    table._tbl.remove(data_tr)
    new_row([f"{{%tr for {item} in {collection} %}}"] + blank)
    table._tbl.append(data_tr)
    new_row(["{%tr endfor %}"] + blank)
    new_row([f"{{%tr if not {collection} %}}"] + blank)
    new_row([empty_text] * n)
    new_row(["{%tr endif %}"] + blank)


def set_col_widths(table, widths_dxa: list[int]) -> None:
    """Set column widths (twentieths of a point) on the grid and every cell."""
    grid = table._tbl.tblGrid.findall(qn("w:gridCol"))
    for col, w in zip(grid, widths_dxa):
        col.set(qn("w:w"), str(w))
    for tr in table._tbl.findall(qn("w:tr")):
        for tc, w in zip(tr.findall(qn("w:tc")), widths_dxa):
            tcw = tc.get_or_add_tcPr().get_or_add_tcW()
            tcw.set(qn("w:w"), str(w))
            tcw.set(qn("w:type"), "dxa")


def set_header_row(table, headers: list[str]) -> None:
    for cell, h in zip(table.rows[0].cells, headers):
        cell_text(cell, h)


# --------------------------------------------------------------------------- main
def build(sample: Path, output: Path) -> None:
    d = docx.Document(str(sample))
    body = d.element.body
    P = list(d.paragraphs)
    T = list(d.tables)

    def find_para(predicate, start=0) -> int:
        for i in range(start, len(P)):
            if predicate(P[i]):
                return i
        raise LookupError("paragraph not found")

    def heading(text: str, level: int = 1, start: int = 0) -> int:
        return find_para(
            lambda p: p.style.name == f"Heading {level}"
            and p.text.strip().startswith(text),
            start,
        )

    # ---- cover
    cover_name, cover_period = T[0], T[1]
    set_text(cover_name.rows[0].cells[1].paragraphs[0], "{{ client_name }}")
    set_text(cover_name.rows[0].cells[1].paragraphs[1], "{{ project_name }}")
    set_text(cover_period.rows[1].cells[1].paragraphs[0], "{{ period_label }}")

    # ---- headers: "Prepared by PT. DEF"
    for section in d.sections:
        for hdr in (
            section.header,
            section.first_page_header,
            section.even_page_header,
        ):
            # iterate raw <w:p> so text boxes are included
            for p_el in hdr._element.iter(qn("w:p")):
                replace_across_runs(Paragraph(p_el, hdr), "PT. DEF", "{{ provider_name }}")

    # ---- document control table
    ctl = T[2]
    for cell, t in zip(
        ctl.rows[1].cells,
        [
            "{{ doc_version }}",
            "{{ doc_date }}",
            "{{ doc_description }}",
            "{{ prepared_by }}",
        ],
    ):
        cell_text(cell, t)

    # ---- 1. Informasi Umum: provider / client / contract names
    i_info = heading("Informasi")
    i_status = heading("Tingkat")
    for p in P[i_info:i_status]:
        replace_across_runs(
            p, "PT DEF (DEF)", "{{ provider_name }} ({{ provider_short }})"
        )
        replace_across_runs(p, "PT ABC (ABC)", "{{ client_name }} ({{ client_short }})")
        replace_across_runs(p, "XXX/XXXX/00-20XX", "{{ contract_number }}")
        replace_across_runs(p, "DEF", "{{ provider_short }}")
        replace_across_runs(p, " ABC", " {{ client_short }}")

    # ---- new: Ringkasan Eksekutif (before "Tingkat Ketersediaan Layanan")
    body_para = P[find_para(lambda p: p.text.startswith("Tujuan dari"))]
    h1 = P[i_status]
    anchor = P[i_status - 1]._p  # blank paragraph before the heading
    hp = clone_paragraph_after(anchor, h1, "Ringkasan Eksekutif")
    t1 = tag_paragraph_after(hp._p, body_para, "{%p for s in summary_paragraphs %}")
    sp = clone_paragraph_after(t1._p, body_para, "{{ s }}")
    t2 = tag_paragraph_after(sp._p, body_para, "{%p endfor %}")
    clone_paragraph_after(t2._p, P[i_status - 1], "")

    # ---- 2. Tingkat Ketersediaan Layanan
    def line(prefix: str) -> Paragraph:
        return P[find_para(lambda p: p.text.startswith(prefix), i_status)]

    replace_after_colon(
        line("Period date"), "{{ period_start_label }} to {{ period_end_label }}"
    )
    replace_after_colon(line("Total downtime"), "{{ sla.downtime_label }}")
    replace_after_colon(line("Agreed availability"), "{{ sla.target_label }}")
    actual = line("Actual availability")
    replace_after_colon(actual, "{{ sla.actual_label }}")

    # downtime detail table (only rendered when there is downtime)
    i_vm = heading("Daftar Virtual Machine")
    for p in P[P.index(actual) + 2 : i_vm]:  # trim the stack of blank lines, keep one
        if not p.text.strip():
            p._p.getparent().remove(p._p)
    incident_tbl = T[5]
    plain = P[find_para(lambda p: p.text.startswith("Data yang"))]
    t_if = tag_paragraph_after(actual._p, plain, "{%p if sla.entries %}")
    cap = clone_paragraph_after(
        t_if._p, plain, "Rincian downtime yang tercatat pada periode ini:"
    )
    dt_tbl = copy.deepcopy(incident_tbl._tbl)
    cap._p.addnext(dt_tbl)
    dt = Table(dt_tbl, incident_tbl._parent)
    set_header_row(
        dt,
        [
            "No",
            "Mulai",
            "Selesai",
            "Durasi (menit)",
            "Komponen",
            "Kategori",
            "Dihitung SLA",
            "Keterangan",
        ],
    )
    make_loop_table(
        dt,
        "e",
        "sla.entries",
        [
            "{{ loop.index }}",
            "{{ e.start }}",
            "{{ e.end }}",
            "{{ e.minutes }}",
            "{{ e.components }}",
            "{{ e.category }}",
            "{{ e.counted }}",
            "{{ e.notes }}",
        ],
    )
    set_col_widths(dt, [500, 1250, 1250, 900, 1400, 1150, 900, 1900])
    tag_paragraph_after(dt_tbl, plain, "{%p endif %}")

    # ---- 3. Daftar Virtual Machine
    set_text(P[i_vm], "Daftar Virtual Machine {{ project_short }}")
    make_loop_table(
        T[3],
        "c",
        "components",
        ["{{ c.name }}", "{{ c.hostname }}", "{{ c.ip_address }}"],
    )

    # ---- 4. Layanan Tambahan
    make_loop_table(
        T[4],
        "s",
        "services",
        ["{{ s.name }}", "{{ s.description }}", "{{ s.start }}", "{{ s.end }}"],
    )

    # ---- 5..7 Summary Penggunaan Resource <vm>  ->  one looped section
    i_vm1 = heading("Summary Penggunaan Resource")
    i_incident = heading("Daftar Insiden")
    i_vm2 = heading("Summary Penggunaan Resource", start=i_vm1 + 1)
    # remove page-break filler between "Layanan Tambahan" and the first VM section
    i_services = heading("Layanan")
    for p in P[i_services + 2 : i_vm1]:
        p._p.getparent().remove(p._p)
    # remove VM 2 and VM 3 example sections (everything up to the blank line before "Daftar Insiden")
    for p in P[i_vm2 : i_incident - 1]:
        p._p.getparent().remove(p._p)

    vm_heading = P[i_vm1]
    set_text(vm_heading, "Summary Penggunaan Resource {{ c.name }}")
    pb = clone_paragraph_after(vm_heading._p.getprevious(), plain, "")
    pb.runs[0].add_break(WD_BREAK.PAGE)
    tag_paragraph_after(pb._p.getprevious(), plain, "{%p for c in components %}")

    img_paras = [p for p in P[i_vm1:i_vm2] if p._p.xpath(".//a:blip")]
    for p, key in zip(img_paras, ["cpu", "memory", "disk"]):
        for r in list(p.runs):
            r._r.getparent().remove(r._r)
        p.add_run(f"{{{{ c.charts.{key} }}}}")

    h2 = P[heading("Disk Usage Monitoring", level=2, start=i_vm1)]
    last = img_paras[-1]
    fh = clone_paragraph_after(last._p, h2, "Ringkasan & Prakiraan")
    fimg = clone_paragraph_after(fh._p, last, "{{ c.charts.forecast }}")
    fnar = clone_paragraph_after(fimg._p, body_para, "{{ c.narrative }}")
    tag_paragraph_after(fnar._p, plain, "{%p endfor %}")

    # ---- new: Prakiraan & Rekomendasi Resource (before "Daftar Insiden")
    inc_h = P[i_incident]
    pb2 = clone_paragraph_after(inc_h._p.getprevious(), plain, "")
    pb2.runs[0].add_break(WD_BREAK.PAGE)
    fh1 = clone_paragraph_after(pb2._p, inc_h, "Prakiraan & Rekomendasi Resource")
    fi = clone_paragraph_after(fh1._p, body_para, "{{ forecast_intro }}")
    ft_xml = copy.deepcopy(incident_tbl._tbl)
    fi._p.addnext(ft_xml)
    ft = Table(ft_xml, incident_tbl._parent)
    set_header_row(
        ft,
        [
            "No",
            "Resource",
            "Metrik",
            "Rata-rata Bulan Ini",
            "Puncak Bulan Ini",
            "Prakiraan (rata-rata / batas atas)",
            "Status",
            "Rekomendasi",
        ],
    )
    make_loop_table(
        ft,
        "f",
        "forecast_rows",
        [
            "{{ loop.index }}",
            "{{ f.component }}",
            "{{ f.metric }}",
            "{{ f.avg }}",
            "{{ f.peak }}",
            "{{ f.forecast }}",
            "{{ f.status }}",
            "{{ f.recommendation }}",
        ],
    )
    set_col_widths(ft, [560, 1300, 950, 950, 950, 1250, 1050, 2240])
    note = clone_paragraph_after(ft_xml, plain, "{{ forecast_note }}")
    pb3 = clone_paragraph_after(note._p, plain, "")
    pb3.runs[0].add_break(WD_BREAK.PAGE)

    # ---- Daftar Insiden / Daftar Aktivitas Permintaan
    make_loop_table(
        T[5],
        "t",
        "incidents",
        [
            "{{ loop.index }}",
            "{{ t.key }}",
            "{{ t.date }}",
            "{{ t.summary }}",
            "{{ t.description }}",
            "{{ t.reporter }}",
            "{{ t.follow_up }}",
            "{{ t.status }}",
        ],
    )
    make_loop_table(
        T[6],
        "t",
        "requests",
        [
            "{{ loop.index }}",
            "{{ t.key }}",
            "{{ t.date }}",
            "{{ t.summary }}",
            "{{ t.reporter }}",
            "{{ t.follow_up }}",
            "{{ t.status }}",
        ],
    )

    # ---- ask Word to refresh the table of contents / page numbers on open
    settings = d.settings.element
    upd = settings.find(qn("w:updateFields"))
    if upd is None:
        upd = settings.makeelement(qn("w:updateFields"), {})
        settings.append(upd)
    upd.set(qn("w:val"), "true")

    output.parent.mkdir(parents=True, exist_ok=True)
    d.save(str(output))
    print(f"wrote {output}")


if __name__ == "__main__":
    sample = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SAMPLE
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT
    build(sample, out)
