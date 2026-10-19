from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from PIL import Image, ImageChops

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
        background = Image.open(BytesIO(archive.read("word/media/image1.png"))).convert("RGB")
    assert "v:textbox" in xml
    assert "Texte modifiable" in xml
    assert ImageChops.difference(
        background, Image.new("RGB", background.size, "white")
    ).getbbox() is None


def test_docx_keeps_rotated_textbox_appearance_and_character_styles(tmp_path: Path) -> None:
    target = tmp_path / "zone-stylee.docx"
    document = CanvasDocument(objects=[PageObject(
        "text", 0, 50, 70, 250, 80,
        text="Texte rouge", rotation=30,
        fill="#DCEBFA", border_color="#2368AF",
        border_width=3, border_style="dotted",
        text_styles=[{
            "start": 6, "end": 11, "bold": True,
            "color": "#CC0000", "highlight": "#FFF176",
        }],
    )])

    export_editable_docx(document, target)

    with ZipFile(target) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    assert "Texte " in xml
    assert "rouge" in xml
    assert "rotation:30" in xml
    assert 'strokeweight="3pt"' in xml
    assert 'dashstyle="dot"' in xml
    assert 'fillcolor="#DCEBFA"' in xml
    assert '<w:b/>' in xml
    assert 'w:val="CC0000"' in xml
    assert 'w:fill="FFF176"' in xml


def test_compatible_docx_renders_text_once_without_vml_overlay(tmp_path: Path) -> None:
    target = tmp_path / "compatible.docx"
    document = CanvasDocument(
        objects=[PageObject("text", 0, 50, 70, 250, 60, text="Texte universel")]
    )

    export_editable_docx(document, target, compatibility_mode=True)

    with ZipFile(target) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
        image = Image.open(BytesIO(archive.read("word/media/image1.png"))).convert("RGB")
    assert "v:textbox" not in xml
    assert ImageChops.difference(
        image, Image.new("RGB", image.size, "white")
    ).getbbox() is not None


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


def test_docx_keeps_hyperlinks_attached_to_selected_words(tmp_path: Path) -> None:
    target = tmp_path / "liens.docx"
    document = CanvasDocument(
        objects=[PageObject(
            "text", 0, 50, 70, 300, 60, text="Consulter le site",
            text_links=[{"start": 10, "end": 17, "hyperlink": "https://example.com"}],
        )]
    )

    export_editable_docx(document, target)

    with ZipFile(target) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
        relationships = archive.read("word/_rels/document.xml.rels").decode("utf-8")
    assert "w:hyperlink" in xml
    assert "site" in xml
    assert "https://example.com" in relationships


def test_docx_exports_simple_drawings_as_separate_positioned_objects(tmp_path: Path) -> None:
    target = tmp_path / "dessins.docx"
    document = CanvasDocument(objects=[
        PageObject("shape", 0, 40, 50, 100, 60, shape="rectangle", hyperlink="https://example.com"),
        PageObject("line", 0, 180, 90, 120, 30, border_width=2),
    ])

    export_editable_docx(document, target)

    with ZipFile(target) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
        relationships = archive.read("word/_rels/document.xml.rels").decode("utf-8")
        media = [name for name in archive.namelist() if name.startswith("word/media/")]
    assert "LouCodiDrawing0_0" in xml
    assert "LouCodiDrawing0_1" in xml
    assert "wp:anchor" in xml
    assert "a:hlinkClick" in xml
    assert "https://example.com" in relationships
    assert len(media) == 3  # page background plus two independently positioned drawings


def test_docx_exports_table_at_its_own_dimensions_instead_of_page_background(tmp_path: Path) -> None:
    target = tmp_path / "tableau-separe.docx"
    table = PageObject(
        "table", 0, 90, 520, 260, 110,
        table_cells=[
            [{"text": "55"}, {"text": "45"}],
            [{"text": ""}, {"text": "10"}],
        ],
        table_border_ranges=[
            {"top": 0.0, "left": 0.0, "bottom": 0.0, "right": 1.0, "width": 3.0}
        ],
    )

    export_editable_docx(CanvasDocument(objects=[table]), target)

    with ZipFile(target) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
        media = [name for name in archive.namelist() if name.startswith("word/media/")]
        background = Image.open(BytesIO(archive.read("word/media/image1.png"))).convert("RGB")

    assert "wp:anchor" in xml
    assert 'name="LouCodiDrawing0_0"' in xml
    assert len(media) == 2  # fond de page vierge + tableau à ses dimensions propres
    assert ImageChops.difference(
        background, Image.new("RGB", background.size, "white")
    ).getbbox() is None
