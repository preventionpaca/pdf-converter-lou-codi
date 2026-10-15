from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter

from lou_codi_pdf_converter.services.pdf_decoration import (
    DecorationSettings,
    apply_pdf_decorations,
    parse_page_selection,
)


def make_pdf(path: Path, count: int = 2) -> None:
    writer = PdfWriter()
    for _ in range(count):
        writer.add_blank_page(width=595, height=842)
    with path.open("wb") as stream:
        writer.write(stream)


def test_parse_page_selection() -> None:
    assert parse_page_selection("", 5) is None
    assert parse_page_selection("1, 3-5", 5) == frozenset({0, 2, 3, 4})


def test_decoration_keeps_pages_and_adds_selected_text(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    target = tmp_path / "decorated.pdf"
    make_pdf(source)

    apply_pdf_decorations(
        source,
        target,
        DecorationSettings(
            selected_pages=frozenset({0}),
            watermark_text="CONFIDENTIEL",
            header_text="{document}",
            footer_text="Page {page} / {pages}",
        ),
    )

    pages = PdfReader(target).pages
    assert len(pages) == 2
    first_text = pages[0].extract_text()
    assert "CONFIDENTIEL" in first_text
    assert "source" in first_text
    assert "Page 1 / 2" in first_text
    assert not pages[1].extract_text()


def test_logo_can_be_positioned_independently(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    target = tmp_path / "with-logo.pdf"
    logo = tmp_path / "logo.png"
    make_pdf(source, count=1)
    Image.new("RGBA", (20, 20), "red").save(logo)

    apply_pdf_decorations(
        source,
        target,
        DecorationSettings(
            logo_image=logo,
            logo_x_mm=105,
            logo_y_mm=275,
            logo_width_mm=25,
        ),
    )

    page = PdfReader(target).pages[0]
    assert "/XObject" in page["/Resources"]
