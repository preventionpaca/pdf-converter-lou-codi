from __future__ import annotations

import os
import subprocess
from pathlib import Path


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


def collision_free_target(directory: Path, stem: str, suffix: str) -> Path:
    """Choose a target that never overwrites an existing document."""
    target = directory / f"{stem}{suffix}"
    index = 2
    while target.exists():
        target = directory / f"{stem}_{index}{suffix}"
        index += 1
    return target

