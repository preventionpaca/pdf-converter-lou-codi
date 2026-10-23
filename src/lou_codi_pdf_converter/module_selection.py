from __future__ import annotations

import os
import sys
from pathlib import Path

SELECTABLE_MODULES = (
    "pdf_studio",
    "document_studio",
    "cutting_optimization",
    "code_lab",
    "codi_space",
)


def installation_root() -> Path:
    override = os.environ.get("LOU_CODI_INSTALL_ROOT")
    if override:
        return Path(override).expanduser()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def module_enabled(module_id: str) -> bool:
    """Return the installer selection while keeping source/dev installs complete."""
    selection = installation_root() / "selected-modules"
    if not selection.is_dir():
        return True
    return (selection / f"{module_id}.enabled").is_file()
