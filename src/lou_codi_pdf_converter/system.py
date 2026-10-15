from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def open_path(path: Path) -> None:
    """Open a file or directory with the platform's default application."""
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
        return
    command = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([command, str(path)])

