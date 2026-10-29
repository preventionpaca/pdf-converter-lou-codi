from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from PIL import ExifTags, Image, UnidentifiedImageError


@dataclass(frozen=True)
class PhotoArchiveResult:
    directory: Path
    extracted: int
    duplicates: int
    manifest: Path


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _safe_title(value: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", value).strip().rstrip(".")
    return cleaned or "Album Google Photos"


def _safe_member_path(name: str) -> Path | None:
    candidate = Path(name.replace("\\", "/"))
    if candidate.is_absolute() or ".." in candidate.parts or not candidate.name:
        return None
    return candidate


def _metadata(path: Path) -> dict:
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            values = {
                ExifTags.TAGS.get(key, str(key)): value
                for key, value in exif.items()
                if ExifTags.TAGS.get(key, str(key)) in {
                    "DateTime", "DateTimeOriginal", "DateTimeDigitized", "Make", "Model",
                    "LensModel", "GPSInfo", "Orientation",
                }
            }
            return {
                "format": image.format,
                "width": image.width,
                "height": image.height,
                "exif": json.loads(json.dumps(values, default=str)),
            }
    except (OSError, UnidentifiedImageError, ValueError):
        return {}


def import_google_photos_archive(archive: Path, destination: Path, album_title: str) -> PhotoArchiveResult:
    """Safely extract an official Google Photos ZIP and build a verifiable manifest."""
    if not archive.is_file() or not zipfile.is_zipfile(archive):
        raise ValueError("Le fichier sélectionné n’est pas une archive ZIP valide.")
    destination.mkdir(parents=True, exist_ok=True)
    album_directory = destination / _safe_title(album_title)
    album_directory.mkdir(parents=True, exist_ok=True)
    extracted = 0
    duplicates = 0
    records = []
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            relative = _safe_member_path(member.filename)
            if relative is None or member.is_dir():
                continue
            # Unix symlinks inside ZIP files are ignored to keep extraction inside the archive folder.
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                continue
            target = album_directory / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(member) as source:
                temporary = target.with_name(f".{target.name}.loucodi-import")
                with temporary.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
            incoming_digest = _digest(temporary)
            if target.exists() and _digest(target) == incoming_digest:
                temporary.unlink()
                duplicates += 1
            else:
                if target.exists():
                    stem, suffix = target.stem, target.suffix
                    index = 2
                    while target.exists():
                        target = target.with_name(f"{stem} ({index}){suffix}")
                        index += 1
                temporary.replace(target)
                try:
                    timestamp = datetime(*member.date_time, tzinfo=timezone.utc).timestamp()
                    os.utime(target, (timestamp, timestamp))
                except (OSError, ValueError):
                    pass
                extracted += 1
            records.append({
                "path": str(target.relative_to(album_directory)),
                "size": target.stat().st_size,
                "sha256": incoming_digest,
                "metadata": _metadata(target),
            })
    manifest = album_directory / "manifest-lou-codi.json"
    manifest.write_text(json.dumps({
        "format": "lou-codi-photo-archive-v1",
        "album": album_title,
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "source_archive": {"name": archive.name, "size": archive.stat().st_size, "sha256": _digest(archive)},
        "files": records,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return PhotoArchiveResult(album_directory, extracted, duplicates, manifest)
