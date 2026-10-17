# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

project = Path(SPECPATH).resolve().parents[1]
source = project / "src"
datas = []
binaries = []
# These imports are deliberately lazy in the application. The other packages are
# discovered normally by PyInstaller and must not use collect_all, which used to pull
# test data and optional modules into every installer.
hiddenimports = ["pdf2docx", "pdfplumber"]
bundle_speech = os.environ.get("LOU_CODI_BUNDLE_SPEECH") == "1"
if bundle_speech:
    for package in ("vosk", "sounddevice"):
        package_datas, package_binaries, package_imports = collect_all(package)
        datas += package_datas
        binaries += package_binaries
        hiddenimports += package_imports

datas += [
    (str(source / "lou_codi_pdf_converter" / "assets"), "lou_codi_pdf_converter/assets"),
    (str(project / "LICENSE"), "."),
    (str(project / "licenses"), "licenses"),
    (str(project / "THIRD_PARTY_NOTICES.md"), "."),
    (str(project / "SOURCE_DISTRIBUTION.md"), "."),
]
speech_models = project / "packaging" / "runtime" / "speech-models"
if bundle_speech and speech_models.is_dir():
    datas.append((str(speech_models), "speech-models"))
audio_runtime = project / "packaging" / "runtime" / "audio-runtime"
if bundle_speech and sys.platform.startswith("linux") and audio_runtime.is_dir():
    datas.append((str(audio_runtime), "audio-runtime"))

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
        info_plist={"NSHighResolutionCapable": True},
    )
