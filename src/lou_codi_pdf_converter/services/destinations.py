from __future__ import annotations

import json
from pathlib import Path

from ..i18n import settings_path
from ..paths import module_output_directory

MAX_FAVORITES = 12


def resolve_existing_directory(directory: Path) -> Path | None:
    """Resolve a folder selected through a portal that hid trailing whitespace.

    Some cloud mounts legitimately expose names ending in a space. Linux file
    choosers may remove that invisible character from their returned path.
    """
    candidate = directory.expanduser()
    if candidate.is_dir():
        return candidate
    parent = candidate.parent
    if not parent.is_dir():
        return None
    expected = candidate.name.rstrip()
    try:
        matches = [child for child in parent.iterdir() if child.name.rstrip() == expected and child.is_dir()]
    except OSError:
        return None
    return matches[0] if len(matches) == 1 else None


def _read(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write(path: Path, values: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")


def favorite_destinations(path: Path | None = None) -> list[tuple[str, Path]]:
    values = _read(path or settings_path()).get("favorite_destinations", [])
    if not isinstance(values, list):
        return []
    favorites: list[tuple[str, Path]] = []
    for value in values[:MAX_FAVORITES]:
        if not isinstance(value, dict):
            continue
        label, raw_path = value.get("label"), value.get("path")
        if isinstance(label, str) and label.strip() and isinstance(raw_path, str) and raw_path.strip():
            favorites.append((label.strip(), Path(raw_path).expanduser()))
    return favorites


def save_favorite_destinations(
    favorites: list[tuple[str, Path]], path: Path | None = None
) -> None:
    target = path or settings_path()
    values = _read(target)
    values["favorite_destinations"] = [
        {"label": label.strip(), "path": str(directory.expanduser())}
        for label, directory in favorites[:MAX_FAVORITES]
        if label.strip()
    ]
    _write(target, values)


def document_destination(path: Path | None = None) -> Path:
    values = _read(path or settings_path())
    raw_path = values.get("document_destination")
    if isinstance(raw_path, str) and raw_path.strip():
        candidate = Path(raw_path).expanduser()
        resolved = resolve_existing_directory(candidate)
        if resolved is not None:
            return resolved
    return module_output_directory("Document Studio")


def set_document_destination(directory: Path, path: Path | None = None) -> None:
    target = path or settings_path()
    values = _read(target)
    values["document_destination"] = str(directory.expanduser())
    _write(target, values)


def toolbar_size(path: Path | None = None) -> str:
    value = _read(path or settings_path()).get("document_toolbar_size", "large")
    return value if value in {"compact", "large"} else "compact"


def set_toolbar_size(size: str, path: Path | None = None) -> None:
    if size not in {"compact", "large"}:
        raise ValueError("Taille de barre d’outils incorrecte.")
    target = path or settings_path()
    values = _read(target)
    values["document_toolbar_size"] = size
    _write(target, values)
