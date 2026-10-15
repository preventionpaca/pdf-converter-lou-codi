from pathlib import Path

from pypdf import PdfReader

from lou_codi_pdf_converter.services.canvas_document import (
    CanvasDocument,
    PageObject,
    export_canvas_pdf,
    pages_for_object,
    resolve_dynamic_text,
)


def test_canvas_document_round_trip_and_pdf_export(tmp_path: Path) -> None:
    project = tmp_path / "modele.loucodi-document"
    target = tmp_path / "resultat.pdf"
    document = CanvasDocument(
        objects=[
            PageObject("mask", 0, 20, 20, 120, 30),
            PageObject("text", 0, 35, 28, 300, 50, text="Bonjour Lou Còdi", bold=True),
        ]
    )
    document.save(project)
    restored = CanvasDocument.load(project)
    export_canvas_pdf(restored, target)

    assert restored.objects[1].text == "Bonjour Lou Còdi"
    assert len(PdfReader(target).pages) == 1


def test_page_scope_supports_all_and_ranges() -> None:
    item = PageObject("text", 0, 0, 0, 100, 30, text="Entête", pages="all")
    assert pages_for_object(item, 4) == [0, 1, 2, 3]

    item.pages = "1,3-4"
    assert pages_for_object(item, 5) == [0, 2, 3]


def test_dynamic_page_fields_are_resolved() -> None:
    assert resolve_dynamic_text("Page {{PAGE}} / {{PAGES}}", 1, 4) == "Page 2 / 4"


def test_landscape_document_and_linked_charts_export(tmp_path: Path) -> None:
    table = PageObject("table", 0, 30, 30, 250, 100, text="Janvier\t10\nFévrier\t20")
    bars = PageObject("chart", 0, 30, 160, 250, 160, source_id=table.object_id, fill="bar")
    pie = PageObject("chart", 0, 310, 160, 250, 160, source_id=table.object_id, fill="pie")
    document = CanvasDocument(
        objects=[table, bars, pie],
        page_width=841.89,
        page_height=595.28,
    )
    target = tmp_path / "graphiques.pdf"

    export_canvas_pdf(document, target)

    page = PdfReader(target).pages[0]
    assert float(page.mediabox.width) > float(page.mediabox.height)
