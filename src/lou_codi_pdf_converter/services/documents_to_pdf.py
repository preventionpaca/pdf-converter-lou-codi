from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote

from PIL import Image

from .office_runtime import find_office_engine
from .lightweight_office import LIGHTWEIGHT_SUFFIXES, convert_lightweight_office

OFFICE_SUFFIXES = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}


class LibreOfficeUnavailable(RuntimeError):
    pass


def conversion_engine_for(source: Path) -> str:
    suffix = source.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if find_office_engine():
        return "libreoffice"
    if suffix in LIGHTWEIGHT_SUFFIXES:
        return "lightweight"
    return "unavailable"


def convert_document_to_pdf(source: Path, target: Path) -> str:
    suffix = source.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        _image_to_pdf(source, target)
        return "image"
    if suffix not in OFFICE_SUFFIXES:
        raise ValueError(f"Format non pris en charge : {source.suffix}")
    executable = find_office_engine()
    if not executable:
        if suffix in LIGHTWEIGHT_SUFFIXES:
            convert_lightweight_office(source, target)
            return "lightweight"
        raise LibreOfficeUnavailable(
            f"{source.suffix.upper()} nécessite LibreOffice. Sans LibreOffice, le moteur "
            "léger accepte DOCX et XLSX."
        )

    with tempfile.TemporaryDirectory(prefix="lou-codi-pdf-") as temporary:
        profile = Path(temporary) / "profile"
        profile_uri = f"file://{quote(profile.as_posix())}"
        result = subprocess.run(
            [
                str(executable),
                "--headless",
                "--nologo",
                "--nodefault",
                "--nofirststartwizard",
                f"-env:UserInstallation={profile_uri}",
                "--convert-to",
                "pdf",
                "--outdir",
                temporary,
                str(source),
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=300,
        )
        produced = Path(temporary) / f"{source.stem}.pdf"
        if result.returncode or not produced.is_file():
            detail = result.stderr.strip() or result.stdout.strip() or "conversion impossible"
            raise RuntimeError(f"LibreOffice : {detail}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(produced), target)
    return "libreoffice"


def _image_to_pdf(source: Path, target: Path) -> None:
    with Image.open(source) as image:
        frames = []
        try:
            while True:
                frame = image.copy()
                if frame.mode in {"RGBA", "LA"}:
                    background = Image.new("RGB", frame.size, "white")
                    background.paste(frame, mask=frame.getchannel("A"))
                    frame = background
                elif frame.mode != "RGB":
                    frame = frame.convert("RGB")
                frames.append(frame)
                image.seek(image.tell() + 1)
        except EOFError:
            pass
        first, *rest = frames
        first.save(target, "PDF", save_all=True, append_images=rest, resolution=150)
