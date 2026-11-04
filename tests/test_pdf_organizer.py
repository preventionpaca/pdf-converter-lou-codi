from pathlib import Path

import pymupdf
from PIL import Image
from pypdf import PdfReader, PdfWriter

from lou_codi_pdf_converter.services.pdf_organizer import (
    PagePlan,
    assemble_pdf,
    compress_pdf,
    extract_pages,
    merge_pdfs,
    rotate_pages,
    suggested_organized_stem,
)


def make_pdf(path: Path, widths: list[float]) -> None:
    writer = PdfWriter()
    for width in widths:
        writer.add_blank_page(width=width, height=200)
    with path.open("wb") as stream:
        writer.write(stream)


def test_merge_extract_and_rotate(tmp_path: Path) -> None:
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    merged = tmp_path / "merged.pdf"
    extracted = tmp_path / "extracted.pdf"
    rotated = tmp_path / "rotated.pdf"
    make_pdf(first, [100, 110])
    make_pdf(second, [120])

    merge_pdfs([first, second], merged)
    assert [float(page.mediabox.width) for page in PdfReader(merged).pages] == [100, 110, 120]

    extract_pages(merged, extracted, [2, 0])
    assert [float(page.mediabox.width) for page in PdfReader(extracted).pages] == [120, 100]

    rotate_pages(extracted, rotated, [0], 90)
    assert PdfReader(rotated).pages[0].rotation == 90


def test_assemble_pdf_reorders_duplicates_rotates_and_adds_blank(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    target = tmp_path / "organized.pdf"
    make_pdf(source, [100, 120])

    assemble_pdf(
        [
            PagePlan(source, 1, rotation=90),
            PagePlan(None, None, width=200, height=300),
            PagePlan(source, 0),
            PagePlan(source, 0),
        ],
        target,
    )

    pages = PdfReader(target).pages
    assert len(pages) == 4
    assert pages[0].rotation == 90
    assert float(pages[1].mediabox.width) == 200
    assert [float(page.mediabox.width) for page in pages[2:]] == [100, 100]


def test_suggested_name_keeps_original_name() -> None:
    plans = [PagePlan(Path("Dossier de candidature.pdf"), 0), PagePlan(None, None)]
    assert suggested_organized_stem(plans) == "Dossier de candidature_modifié"
    assert suggested_organized_stem([PagePlan(None, None)]) == "document_modifié"


def test_compress_pdf_preserves_pages_and_reduces_image_pdf(tmp_path: Path) -> None:
    image_path = tmp_path / "noise.png"
    image = Image.effect_noise((1200, 1200), 100).convert("RGB")
    image.save(image_path, format="PNG")
    source = tmp_path / "scan.pdf"
    document = pymupdf.open()
    page = document.new_page(width=600, height=600)
    page.insert_image(page.rect, filename=str(image_path))
    document.save(source)
    document.close()

    target = tmp_path / "scan_compressé.pdf"
    result = compress_pdf(source, target, "strong")

    assert target.is_file()
    assert len(PdfReader(target).pages) == 1
    assert result.source_size == source.stat().st_size
    assert result.output_size == target.stat().st_size
    assert result.output_size < result.source_size
    assert result.saved_percent > 10


def test_compress_pdf_rejects_unknown_profile(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, [100])
    try:
        compress_pdf(source, tmp_path / "target.pdf", "impossible")
    except ValueError as exc:
        assert "inconnu" in str(exc)
    else:
        raise AssertionError("Un profil inconnu doit être refusé.")
