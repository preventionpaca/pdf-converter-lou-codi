from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from pypdf import PdfReader, PdfWriter


@dataclass(frozen=True)
class PagePlan:
    source: Path | None
    page_index: int | None
    rotation: int = 0
    width: float = 595
    height: float = 842


@dataclass(frozen=True)
class CompressionResult:
    source_size: int
    output_size: int

    @property
    def saved_percent(self) -> float:
        if self.source_size <= 0:
            return 0.0
        return max(0.0, (1 - self.output_size / self.source_size) * 100)


COMPRESSION_PROFILES = {
    "lossless": None,
    "balanced": {"dpi_threshold": 180, "dpi_target": 150, "quality": 72},
    "strong": {"dpi_threshold": 140, "dpi_target": 110, "quality": 52},
}


def suggested_organized_stem(pages: Sequence[PagePlan]) -> str:
    """Keep the first source name and make the modified nature explicit."""
    first_source = next((page.source for page in pages if page.source is not None), None)
    return f"{first_source.stem}_modifié" if first_source else "document_modifié"


def assemble_pdf(pages: Sequence[PagePlan], target: Path) -> None:
    """Build a PDF from source pages and blanks in the requested order."""
    writer = PdfWriter()
    readers: dict[Path, PdfReader] = {}
    for planned in pages:
        if planned.source is None:
            page = writer.add_blank_page(width=planned.width, height=planned.height)
        else:
            reader = readers.setdefault(planned.source, PdfReader(planned.source))
            if planned.page_index is None:
                raise ValueError("Une page source doit posséder un index.")
            writer.add_page(reader.pages[planned.page_index])
            page = writer.pages[-1]
        if planned.rotation:
            page.rotate(planned.rotation)
    _write(writer, target)


def merge_pdfs(sources: Iterable[Path], target: Path) -> None:
    writer = PdfWriter()
    for source in sources:
        writer.append(str(source))
    _write(writer, target)


def extract_pages(source: Path, target: Path, page_indices: Sequence[int]) -> None:
    reader = PdfReader(source)
    writer = PdfWriter()
    for index in page_indices:
        writer.add_page(reader.pages[index])
    _write(writer, target)


def reorder_pages(source: Path, target: Path, page_indices: Sequence[int]) -> None:
    extract_pages(source, target, page_indices)


def rotate_pages(source: Path, target: Path, page_indices: Iterable[int], degrees: int) -> None:
    if degrees not in {90, 180, 270}:
        raise ValueError("La rotation doit être de 90, 180 ou 270 degrés.")
    selected = set(page_indices)
    reader = PdfReader(source)
    writer = PdfWriter()
    for index, page in enumerate(reader.pages):
        if index in selected:
            page.rotate(degrees)
        writer.add_page(page)
    _write(writer, target)


def compress_pdf(source: Path, target: Path, profile: str = "balanced") -> CompressionResult:
    """Compress a PDF locally while preserving its page structure and text layer."""
    if profile not in COMPRESSION_PROFILES:
        raise ValueError("Niveau de compression inconnu.")
    source = Path(source)
    target = Path(target)
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.resolve() == target.resolve():
        raise ValueError("Le fichier de sortie doit être différent du PDF d’origine.")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.compression.tmp")
    temporary.unlink(missing_ok=True)
    try:
        document = pymupdf.open(source)
        try:
            if document.needs_pass:
                raise ValueError("Ce PDF est protégé par un mot de passe.")
            settings = COMPRESSION_PROFILES[profile]
            if settings is not None:
                document.rewrite_images(
                    **settings,
                    lossy=True,
                    lossless=True,
                    bitonal=True,
                    color=True,
                    gray=True,
                )
            document.save(
                temporary,
                garbage=4,
                clean=True,
                deflate=True,
                deflate_images=True,
                deflate_fonts=True,
                use_objstms=1,
                compression_effort=100,
                encryption=pymupdf.PDF_ENCRYPT_KEEP,
            )
        finally:
            document.close()
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    temporary.replace(target)
    return CompressionResult(source.stat().st_size, target.stat().st_size)


def _write(writer: PdfWriter, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as output:
        writer.write(output)
