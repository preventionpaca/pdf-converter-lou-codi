# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys

project = Path(SPECPATH).resolve().parents[1]
source = project / "src"
datas = []
binaries = []
# These imports are deliberately lazy in the application. The other packages are
# discovered normally by PyInstaller and must not use collect_all, which used to pull
# test data and optional modules into every installer.
hiddenimports = ["pdf2docx", "pdfplumber"]

datas += [
    (str(source / "lou_codi_pdf_converter" / "assets"), "lou_codi_pdf_converter/assets"),
    (str(project / "LICENSE"), "."),
    (str(project / "licenses"), "licenses"),
    (str(project / "THIRD_PARTY_NOTICES.md"), "."),
    (str(project / "SOURCE_DISTRIBUTION.md"), "."),
]
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

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Lou Còdi Workshop.app",
        bundle_identifier="org.loucodi.workshop",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "Document Lou Còdi",
                "CFBundleTypeExtensions": ["cod", "loucodi-document"],
                "CFBundleTypeRole": "Editor",
            }],
        },
    )
