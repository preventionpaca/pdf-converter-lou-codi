from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def runtime_root() -> Path:
    """Return the directory containing resources shipped with the application."""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)
    return Path(__file__).resolve().parents[3]


def find_office_engine() -> Path | None:
    """Locate an optional LibreOffice installation without requiring or bundling it."""
    override = os.environ.get("LOU_CODI_OFFICE_RUNTIME")
    candidates = []
    if override:
        candidates.append(Path(override))

    # Compatibility with developer overrides and old test bundles only. Current public
    # installers never ship this directory.
    root = runtime_root() / "office-runtime"
    candidates.extend(
        (
            root / "program" / "soffice.exe",
            root / "program" / "soffice",
            root / "LibreOfficePortable" / "App" / "libreoffice" / "program" / "soffice.exe",
            root / "LibreOffice.app" / "Contents" / "MacOS" / "soffice",
        )
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate

    system_engine = shutil.which("libreoffice") or shutil.which("soffice")
    return Path(system_engine) if system_engine else None
