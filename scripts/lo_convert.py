"""Convert a .docx to PDF with LibreOffice, refreshing the table of contents first.

Must run with a Python that can ``import uno`` (the system Python where
LibreOffice is installed, e.g. /usr/bin/python3 with python3-uno). The portal
calls it as a subprocess; see reports/services/pdf.py.

Usage: python3 lo_convert.py INPUT.docx OUTPUT.pdf [SOFFICE_BINARY]
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import uno
from com.sun.star.beans import PropertyValue
from com.sun.star.connection import NoConnectException


def prop(name, value):
    p = PropertyValue()
    p.Name, p.Value = name, value
    return p


def main(src: str, dst: str, soffice: str = "soffice") -> None:
    profile = tempfile.mkdtemp(prefix="lo-profile-")
    pipe = f"mrg-{uuid.uuid4().hex}"
    proc = subprocess.Popen(
        [soffice, "--headless", "--invisible", "--nologo", "--norestore", "--nodefault",
         f"-env:UserInstallation=file://{profile}", f"--accept=pipe,name={pipe};urp;"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        local = uno.getComponentContext()
        resolver = local.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local)
        ctx = None
        for _ in range(120):
            try:
                ctx = resolver.resolve(f"uno:pipe,name={pipe};urp;StarOffice.ComponentContext")
                break
            except NoConnectException:
                time.sleep(0.5)
        if ctx is None:
            raise RuntimeError("could not connect to LibreOffice")
        desktop = ctx.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
        doc = desktop.loadComponentFromURL(uno.systemPathToFileUrl(os.path.abspath(src)), "_blank", 0,
                                           (prop("Hidden", True),))
        # page numbers in the TOC depend on layout, so update twice
        for _ in range(2):
            indexes = doc.getDocumentIndexes()
            for i in range(indexes.getCount()):
                indexes.getByIndex(i).update()
            doc.getTextFields().refresh()
        doc.storeToURL(uno.systemPathToFileUrl(os.path.abspath(dst)), (prop("FilterName", "writer_pdf_Export"),))
        doc.close(True)
        try:
            desktop.terminate()
        except Exception:
            pass
    finally:
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
    if not Path(dst).exists():
        raise RuntimeError("PDF was not produced")


if __name__ == "__main__":
    main(*sys.argv[1:4])
