from pathlib import Path

from pypdf import PdfReader

from lou_codi_pdf_converter.services.canvas_document import (
    CanvasDocument,
    FLOW_BREAK_TOKEN,
    PageObject,
    export_canvas_pdf,
    flowed_text_for_object,
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


def test_text_can_flow_between_linked_frames() -> None:
    first = PageObject("text", 0, 10, 10, 120, 24, text="Un texte assez long pour continuer dans la seconde zone", font_size=12)
    second = PageObject("text", 1, 10, 10, 240, 24, font_size=12)
    first.flow_next_id = second.object_id

    first_part = flowed_text_for_object(first, [first, second])
    second_part = flowed_text_for_object(second, [first, second])

    assert first_part
    assert second_part
    assert f"{first_part} {second_part}" == first.text


def test_text_flow_respects_explicit_line_breaks() -> None:
    first = PageObject("text", 0, 10, 10, 180, 18, text="Première ligne\nDeuxième ligne", font_size=12)
    second = PageObject("text", 0, 10, 40, 180, 40, font_size=12)
    first.flow_next_id = second.object_id

    assert flowed_text_for_object(first, [first, second]) == "Première ligne"
    assert flowed_text_for_object(second, [first, second]) == "Deuxième ligne"

    before_move = flowed_text_for_object(second, [first, second])
    second.x += 75
    second.y += 40
    assert flowed_text_for_object(second, [first, second]) == before_move


def test_text_flow_can_be_forced_to_next_frame() -> None:
    first = PageObject("text", 0, 10, 10, 300, 80, text=f"Premier{FLOW_BREAK_TOKEN}Second")
    second = PageObject("text", 0, 10, 100, 300, 80)
    first.flow_next_id = second.object_id

    assert flowed_text_for_object(first, [first, second]) == "Premier"
    assert flowed_text_for_object(second, [first, second]) == "Second"


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


def test_technical_shapes_are_saved_and_exported(tmp_path: Path) -> None:
    project = tmp_path / "schema.loucodi-document"
    target = tmp_path / "schema.pdf"
    document = CanvasDocument(
        objects=[
            PageObject("shape", 0, 40, 40, 120, 70, shape="rectangle", fill="#DCEBFA"),
            PageObject("shape", 0, 190, 40, 100, 70, shape="ellipse", border_style="dashed"),
            PageObject("shape", 0, 320, 40, 140, 70, shape="arrow", fill="#F9E8C8"),
        ]
    )

    document.save(project)
    restored = CanvasDocument.load(project)
    export_canvas_pdf(restored, target)

    assert [item.shape for item in restored.objects] == ["rectangle", "ellipse", "arrow"]
    assert len(PdfReader(target).pages) == 1
