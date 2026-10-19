from pathlib import Path
from time import monotonic

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX
from docx.shared import Pt, RGBColor
from PIL import Image

from lou_codi_pdf_converter.services.canvas_document import PageObject
from lou_codi_pdf_converter.services.docx_import import (
    _fit_nearly_empty_last_page,
    import_docx_as_canvas,
)


def test_docx_import_keeps_text_lists_and_character_styles(tmp_path: Path) -> None:
    source = tmp_path / "source.docx"
    document = Document()
    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title.add_run("Titre important")
    title_run.bold = True
    title_run.italic = True
    title_run.underline = True
    title_run.font.size = Pt(16)
    title_run.font.color.rgb = RGBColor(0xCC, 0x00, 0x00)
    title_run.font.highlight_color = WD_COLOR_INDEX.YELLOW
    bullet = document.add_paragraph(style="List Bullet")
    bullet.add_run("Premier point")
    document.save(source)

    imported = import_docx_as_canvas(source)

    root = imported.objects[0]
    assert root.text == "Titre important\n• Premier point"
    assert root.text_styles[0] == {
        "start": 0,
        "end": 15,
        "bold": True,
        "italic": True,
        "underline": True,
        "strikethrough": False,
        "font_family": "Sans-serif",
        "font_size": 16.0,
        "color": "#CC0000",
        "highlight": "#FFF176",
    }
    assert root.paragraph_alignments == [
        {"start": 0, "end": 15, "align": "center"}
    ]
    assert imported.page_count >= 1


def test_docx_import_keeps_images_as_editable_independent_objects(tmp_path: Path) -> None:
    picture = tmp_path / "illustration.png"
    Image.new("RGB", (240, 120), "#E83E8C").save(picture)
    source = tmp_path / "source-avec-image.docx"
    document = Document()
    document.add_paragraph("Texte avant l’image")
    paragraph = document.add_paragraph()
    paragraph.add_run().add_picture(str(picture), width=Pt(180))
    document.add_paragraph("Texte après l’image")
    document.save(source)

    imported = import_docx_as_canvas(source)

    text_objects = [item for item in imported.objects if item.kind == "text"]
    image_objects = [item for item in imported.objects if item.kind == "image"]
    assert "Texte avant l’image" in text_objects[0].text
    assert "Texte après l’image" in text_objects[0].text
    assert len(image_objects) == 1
    assert Path(image_objects[0].image_path).is_file()
    assert Image.open(image_objects[0].image_path).size == (240, 120)
    assert image_objects[0].width == 180
    assert image_objects[0].height == 90
    assert image_objects[0].page == 0


def test_docx_import_keeps_tables_merges_and_cell_images_editable(
    tmp_path: Path,
) -> None:
    picture = tmp_path / "cellule.png"
    Image.new("RGB", (80, 40), "#4A90E2").save(picture)
    source = tmp_path / "source-avec-tableau.docx"
    document = Document()
    document.add_paragraph("Texte avant le tableau")
    table = document.add_table(rows=2, cols=2)
    heading = table.cell(0, 0).merge(table.cell(0, 1))
    heading.text = "En-tête fusionné"
    heading.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    heading.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    table.cell(1, 0).text = "Valeur modifiable"
    table.cell(1, 1).paragraphs[0].add_run().add_picture(
        str(picture), width=Pt(40)
    )
    document.save(source)

    imported = import_docx_as_canvas(source)

    tables = [item for item in imported.objects if item.kind == "table"]
    assert len(tables) == 1
    imported_table = tables[0]
    assert imported_table.table_cells[0][0]["text"] == "En-tête fusionné"
    assert imported_table.table_cells[0][0]["horizontal_align"] == "center"
    assert imported_table.table_cells[0][0]["vertical_align"] == "middle"
    assert imported_table.table_cells[1][0]["text"] == "Valeur modifiable"
    assert imported_table.table_cells[0][1]["text"] == ""
    assert imported_table.table_merges == [[0, 0, 1, 2]]
    cell_image = Path(imported_table.table_cells[1][1]["image_path"])
    assert cell_image.is_file()
    assert Image.open(cell_image).size == (80, 40)


def test_docx_import_handles_highly_fragmented_word_text_without_runaway_cpu(
    tmp_path: Path,
) -> None:
    source = tmp_path / "fragmented.docx"
    document = Document()
    paragraph = document.add_paragraph()
    expected = []
    for index in range(1200):
        value = chr(ord("a") + index % 26)
        expected.append(value)
        run = paragraph.add_run(value)
        run.bold = index % 2 == 0
        run.italic = index % 3 == 0
        run.font.size = Pt(8.5)
    document.save(source)

    started = monotonic()
    imported = import_docx_as_canvas(source)
    elapsed = monotonic() - started

    assert imported.objects[0].text == "".join(expected)
    assert len(imported.objects[0].text_styles) == 1200
    assert elapsed < 5.0


def test_docx_import_avoids_a_third_page_for_tiny_metric_overflow() -> None:
    frame = PageObject("text", 0, 0, 0, 500, 789, font_size=8.5)

    capacity, page_count = _fit_nearly_empty_last_page(frame, 138)

    assert capacity >= 69
    assert page_count == 2
    assert frame.font_size < 8.5
