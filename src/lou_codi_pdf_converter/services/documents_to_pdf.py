from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

OFFICE_SUFFIXES = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}


class LibreOfficeUnavailable(RuntimeError):
    pass


def convert_document_to_pdf(source: Path, target: Path) -> None:
    suffix = source.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        _image_to_pdf(source, target)
        return
    if suffix not in OFFICE_SUFFIXES:
        raise ValueError(f"Format non pris en charge : {source.suffix}")
    executable = shutil.which("libreoffice") or shutil.which("soffice")
    if not executable:
        raise LibreOfficeUnavailable("LibreOffice est requis pour convertir ce document.")

    with tempfile.TemporaryDirectory(prefix="lou-codi-pdf-") as temporary:
        result = subprocess.run(
            [
                executable,
                "--headless",
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

