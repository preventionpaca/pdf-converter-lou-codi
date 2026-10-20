from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class FontFace:
    family: str
    path: Path
    style: str = "Regular"


def normalize_font_name(name: str) -> str:
    """Turn embedded PDF font names into a human-readable family name."""
    value = re.sub(r"^[A-Z]{6}\+", "", name or "")
    value = re.sub(
        r"[-, ](?:bolditalicmt|boldobliquemt|boldmt|italicmt|obliquemt|bolditalic|boldoblique|semibold|demibold|bold|italic|oblique|regular|roman|medium)$",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value)
    return re.sub(r"\s+", " ", value.replace("_", " ")).strip() or "Sans-serif"


@lru_cache(maxsize=1)
def installed_fonts() -> tuple[FontFace, ...]:
    faces: dict[tuple[str, str], FontFace] = {}
    if shutil.which("fc-list"):
        result = subprocess.run(
            ["fc-list", "--format=%{family[0]}\t%{style[0]}\t%{file}\n"],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
        for line in result.stdout.splitlines():
            parts = line.split("\t", 2)
            if len(parts) != 3:
                continue
            family, style, filename = (part.strip() for part in parts)
            path = Path(filename)
            if family and path.is_file():
                faces.setdefault((family.casefold(), style.casefold()), FontFace(family, path, style))
    return tuple(sorted(faces.values(), key=lambda face: (face.family.casefold(), face.style.casefold())))


def installed_families() -> tuple[str, ...]:
    return tuple(dict.fromkeys(face.family for face in installed_fonts()))


def closest_family(requested: str, families: tuple[str, ...] | None = None) -> str | None:
    choices = families if families is not None else installed_families()
    if not choices:
        return None
    wanted = normalize_font_name(requested)
    exact = next((family for family in choices if family.casefold() == wanted.casefold()), None)
    if exact:
        return exact
    return max(
        choices,
        key=lambda family: SequenceMatcher(None, wanted.casefold(), family.casefold()).ratio(),
    )


def font_file(family: str, *, bold: bool = False, italic: bool = False) -> Path | None:
    wanted = closest_family(family)
    if not wanted:
        return None
    candidates = [face for face in installed_fonts() if face.family.casefold() == wanted.casefold()]
    def score(face: FontFace) -> int:
        style = face.style.casefold()
        return int(bold and "bold" in style) * 2 + int(italic and ("italic" in style or "oblique" in style)) * 2
    return max(candidates, key=score).path if candidates else None
