from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader, PdfWriter


@dataclass(frozen=True)
class PagePlan:
    source: Path | None
    page_index: int | None
    rotation: int = 0
    width: float = 595
    height: float = 842


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


def _write(writer: PdfWriter, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as output:
        writer.write(output)
