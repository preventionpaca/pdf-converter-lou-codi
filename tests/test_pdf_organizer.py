from pathlib import Path

from pypdf import PdfReader, PdfWriter

from lou_codi_pdf_converter.services.pdf_organizer import extract_pages, merge_pdfs, rotate_pages


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

