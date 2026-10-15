from pathlib import Path
from zipfile import ZipFile

from lou_codi_pdf_converter.services.canvas_document import CanvasDocument, PageObject
from lou_codi_pdf_converter.services.docx_canvas import export_editable_docx


def test_docx_keeps_text_as_editable_textbox(tmp_path: Path) -> None:
    target = tmp_path / "document.docx"
    document = CanvasDocument(
        objects=[PageObject("text", 0, 50, 70, 250, 60, text="Texte modifiable", bold=True)]
    )

    export_editable_docx(document, target)

    with ZipFile(target) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    assert "v:textbox" in xml
    assert "Texte modifiable" in xml


def test_repeated_footer_is_numbered_on_every_docx_page(tmp_path: Path) -> None:
    target = tmp_path / "pages.docx"
    footer = PageObject(
        "text",
        0,
        50,
        790,
        400,
        30,
        text="Page {{PAGE}} / {{PAGES}}",
        pages="all",
    )
    export_editable_docx(CanvasDocument(page_count=3, objects=[footer]), target)

    with ZipFile(target) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    assert "Page 1 / 3" in xml
    assert "Page 2 / 3" in xml
    assert "Page 3 / 3" in xml
