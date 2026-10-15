"""Build excel/fab_hvac_calculator.xlsm from excel/FabHvac.bas (Windows + Excel only).

Requires 'Trust access to the VBA project object model' to be enabled by the user
(HKCU\\Software\\Microsoft\\Office\\16.0\\Excel\\Security\\AccessVBOM = 1). This script only
READS that setting; if it is off, the script stops and changes nothing.

After saving, personal metadata is removed from the package: document author /
last-modified-by are blanked through the object model and the <x15ac:absPath> element
(which records the local folder the file was saved in) is stripped from xl/workbook.xml.
"""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from excel_session import access_vbom_enabled, excel_app  # noqa: E402

BAS = ROOT / "excel" / "FabHvac.bas"
OUT = ROOT / "excel" / "fab_hvac_calculator.xlsm"
XL_OPENXML_MACRO = 52


def strip_package_metadata(path: Path) -> None:
    tmp = Path(tempfile.mkdtemp()) / path.name
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "xl/workbook.xml":
                text = data.decode("utf-8")
                text = re.sub(r"<mc:AlternateContent[^>]*>\s*<mc:Choice[^>]*>\s*<x15ac:absPath[^>]*/>\s*</mc:Choice>\s*</mc:AlternateContent>", "", text)
                text = re.sub(r"<x15ac:absPath[^>]*/>", "", text)
                data = text.encode("utf-8")
            if item.filename == "docProps/core.xml":
                text = data.decode("utf-8")
                text = re.sub(r"<dc:creator>.*?</dc:creator>", "<dc:creator></dc:creator>", text)
                text = re.sub(r"<cp:lastModifiedBy>.*?</cp:lastModifiedBy>", "<cp:lastModifiedBy></cp:lastModifiedBy>", text)
                data = text.encode("utf-8")
            zout.writestr(item, data)
    shutil.move(str(tmp), str(path))


def main() -> int:
    if not access_vbom_enabled():
        print("BLOCKED: 'Trust access to the VBA project object model' is not enabled "
              "(AccessVBOM != 1). Enable it in Excel Trust Center and rerun. Nothing was changed.")
        return 2
    # VBA import expects CRLF line endings
    tmpdir = Path(tempfile.mkdtemp())
    bas_crlf = tmpdir / "FabHvac.bas"
    bas_crlf.write_bytes(BAS.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    if OUT.exists():
        OUT.unlink()
    with excel_app() as (app, pid):
        wb = app.Workbooks.Add()
        wb.VBProject.VBComponents.Import(str(bas_crlf))
        app.Run(f"'{wb.Name}'!FillCalcSheet")
        app.Calculate()
        for name in ("Author", "Last Author", "Company", "Manager"):
            try:
                wb.BuiltinDocumentProperties(name).Value = ""
            except Exception:
                pass
        wb.SaveAs(str(OUT), FileFormat=XL_OPENXML_MACRO)
        wb.Close(SaveChanges=False)
    strip_package_metadata(OUT)
    shutil.rmtree(tmpdir, ignore_errors=True)
    print("written", OUT.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
