# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

project = Path(SPECPATH).resolve().parents[1]
source = project / "src"
datas = []
binaries = []
hiddenimports = []
for package in (
    "pypdf",
    "pdfplumber",
    "pdf2docx",
    "pymupdf",
    "openpyxl",
    "PIL",
    "reportlab",
    "arabic_reshaper",
    "bidi",
):
    package_datas, package_binaries, package_imports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_imports

datas += [
    (str(source / "lou_codi_pdf_converter" / "assets"), "lou_codi_pdf_converter/assets"),
    (str(project / "LICENSE"), "."),
    (str(project / "THIRD_PARTY_NOTICES.md"), "."),
    (str(project / "SOURCE_DISTRIBUTION.md"), "."),
]
office_runtime = project / "packaging" / "runtime" / "office-runtime"
if office_runtime.is_dir():
    datas.append((str(office_runtime), "office-runtime"))

a = Analysis(
    [str(project / "packaging" / "standalone" / "entrypoint.py")],
    pathex=[str(source)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="lou-codi-pdf-converter",
    console=False,
    icon=str(source / "lou_codi_pdf_converter" / "assets" / "croix-lou-codi.png"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="lou-codi-pdf-converter")
