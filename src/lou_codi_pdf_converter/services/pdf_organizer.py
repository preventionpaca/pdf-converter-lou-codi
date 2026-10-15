from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from pypdf import PdfReader, PdfWriter


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

