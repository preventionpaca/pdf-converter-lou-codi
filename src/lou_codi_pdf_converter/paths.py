from __future__ import annotations

import os
import subprocess
import sys
import unicodedata
from pathlib import Path


def application_data_directory(*, create: bool = True) -> Path:
    """Return the per-user, persistent Lou Còdi data directory on every desktop OS."""
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        directory = root / "LouCodi" / "PDFConverter"
    elif sys.platform == "darwin":
        directory = Path.home() / "Library" / "Application Support" / "LouCodi" / "PDFConverter"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        directory = root / "lou-codi-pdf-converter"
    if create:
        directory.mkdir(parents=True, exist_ok=True)
    return directory


def downloads_directory() -> Path:
    """Return the user's downloads directory without assuming an English locale."""
    if os.name != "nt":
        try:
            result = subprocess.run(
                ["xdg-user-dir", "DOWNLOAD"],
                capture_output=True,
                check=False,
                text=True,
                timeout=3,
            )
            candidate = Path(result.stdout.strip()).expanduser()
            if result.returncode == 0 and candidate.is_dir():
                return candidate
        except (OSError, subprocess.TimeoutExpired):
            pass

    for name in ("Téléchargements", "Downloads"):
        candidate = Path.home() / name
        if candidate.is_dir():
            return candidate
    return Path.home()


WORKSHOP_MODULE_DIRECTORIES = (
    "PDF vers Office",
    "Documents vers PDF",
    "Organiser les PDF",
    "Habillage PDF",
    "Document Studio",
    "Optimisation de découpe",
)


def workshop_directory(*, create: bool = True) -> Path:
    """Return the visible user workspace created below Downloads."""
    directory = downloads_directory() / "LouCodi"
    if create:
        directory.mkdir(parents=True, exist_ok=True)
    return directory


def module_output_directory(module_name: str, *, create: bool = True) -> Path:
    """Return one stable output directory per user-facing workshop module."""
    safe_name = "".join(
        character
        for character in unicodedata.normalize("NFC", module_name).strip()
        if character not in '<>:"/\\|?*' and ord(character) >= 32
    ).strip(". ") or "Autres"
    directory = workshop_directory(create=create) / safe_name
    if create:
        directory.mkdir(parents=True, exist_ok=True)
    return directory


def initialize_workshop_directories() -> Path:
    """Create the predictable output tree once, without touching existing files."""
    root = workshop_directory()
    for module_name in WORKSHOP_MODULE_DIRECTORIES:
        module_output_directory(module_name)
    return root


def collision_free_target(directory: Path, stem: str, suffix: str) -> Path:
    """Choose a target that never overwrites an existing document."""
    target = directory / f"{stem}{suffix}"
    index = 2
    while target.exists():
        target = directory / f"{stem}_{index}{suffix}"
        index += 1
    return target
