"""DOCX -> PDF via LibreOffice (headless)."""
from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings

log = logging.getLogger(__name__)
SCRIPT = Path(settings.BASE_DIR) / "scripts" / "lo_convert.py"


class PdfError(RuntimeError):
    pass


def docx_to_pdf(docx_path: Path, pdf_path: Path) -> None:
    """Preferred path refreshes the table of contents through UNO; falls back to plain --convert-to."""
    timeout = settings.PDF_TIMEOUT_SECONDS
    try:
        subprocess.run(
            [settings.UNO_PYTHON, str(SCRIPT), str(docx_path), str(pdf_path), settings.LIBREOFFICE_BINARY],
            check=True, capture_output=True, timeout=timeout,
        )
        return
    except (subprocess.SubprocessError, OSError) as exc:
        detail = getattr(exc, "stderr", b"") or b""
        log.warning("UNO conversion failed (%s), falling back to --convert-to: %s", exc, detail[-500:])

    with tempfile.TemporaryDirectory() as profile, tempfile.TemporaryDirectory() as outdir:
        try:
            subprocess.run(
                [settings.LIBREOFFICE_BINARY, "--headless", f"-env:UserInstallation={Path(profile).as_uri()}",
                 "--convert-to", "pdf", "--outdir", outdir, str(docx_path)],
                check=True, capture_output=True, timeout=timeout,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            raise PdfError(f"Konversi PDF gagal: {exc}") from exc
        produced = Path(outdir) / (docx_path.stem + ".pdf")
        if not produced.exists():
            raise PdfError("LibreOffice tidak menghasilkan PDF.")
        pdf_path.write_bytes(produced.read_bytes())
