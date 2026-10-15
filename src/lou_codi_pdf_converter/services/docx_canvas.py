from __future__ import annotations

import copy
import tempfile
from html import escape
from pathlib import Path

import pymupdf
from docx import Document
from docx.enum.text import WD_BREAK
from docx.shared import Inches, Pt

from .canvas_document import (
    CanvasDocument,
    PageObject,
    export_canvas_pdf,
    pages_for_object,
    resolve_dynamic_text,
)

VML = "urn:schemas-microsoft-com:vml"
WORD = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def export_editable_docx(canvas_document: CanvasDocument, target: Path) -> None:
    """Export faithful page backgrounds with editable, positioned Word text boxes."""
    background = copy.deepcopy(canvas_document)
    background.objects = [item for item in background.objects if item.kind != "text"]
    with tempfile.TemporaryDirectory(prefix="lou-codi-docx-") as directory:
        temporary = Path(directory)
        pdf_path = temporary / "background.pdf"
        export_canvas_pdf(background, pdf_path)
        document = Document()
        section = document.sections[0]
        section.page_width = Inches(canvas_document.page_width / 72)
        section.page_height = Inches(canvas_document.page_height / 72)
        section.left_margin = section.right_margin = Inches(0)
        section.top_margin = section.bottom_margin = Inches(0)
        with pymupdf.open(pdf_path) as pdf:
            for page_number, page in enumerate(pdf):
                paragraph = document.add_paragraph()
                paragraph.paragraph_format.space_before = Pt(0)
                paragraph.paragraph_format.space_after = Pt(0)
                image_path = temporary / f"page-{page_number + 1}.png"
                page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False).save(image_path)
                paragraph.add_run().add_picture(str(image_path), width=Inches((canvas_document.page_width - 5) / 72))
                for index, item in enumerate(canvas_document.objects):
                    if item.kind == "text" and page_number in pages_for_object(item, canvas_document.page_count):
                        document_name = Path(canvas_document.source_pdf).stem if canvas_document.source_pdf else target.stem
                        paragraph._p.append(
                            _textbox_xml(item, page_number, index, canvas_document.page_count, document_name)
                        )
                if page_number < pdf.page_count - 1:
                    paragraph.add_run().add_break(WD_BREAK.PAGE)
        target.parent.mkdir(parents=True, exist_ok=True)
        document.save(target)


def _textbox_xml(
    item: PageObject,
    page_number: int,
    index: int,
    page_count: int,
    document_name: str,
):
    text = resolve_dynamic_text(item.text, page_number, page_count, document_name)
    fragments = "<w:br/>".join(f'<w:t xml:space="preserve">{escape(line)}</w:t>' for line in text.splitlines())
    bold = "<w:b/>" if item.bold else ""
    italic = "<w:i/>" if item.italic else ""
    font_size = round(item.font_size * 2)
    color = item.color.lstrip("#")
    family = {"Serif": "Liberation Serif", "Monospace": "Liberation Mono", "Cursive": "URW Chancery L", "Symboles": "Noto Sans Symbols 2", "Flèches": "Noto Sans Symbols"}.get(item.font_family, "Liberation Sans")
    alignment = {"left": "left", "center": "center", "right": "right", "justify": "both"}.get(item.align, "left")
    xml = f"""
    <w:r xmlns:w="{WORD}" xmlns:v="{VML}">
      <w:pict>
        <v:shape id="LouCodiTextBox{page_number}_{index}"
          style="position:absolute;margin-left:{item.x:.2f}pt;margin-top:{item.y:.2f}pt;width:{item.width:.2f}pt;height:{item.height:.2f}pt;z-index:5;mso-position-horizontal-relative:page;mso-position-vertical-relative:page"
          strokecolor="#72879C" fillcolor="#FFFFFF">
          <v:textbox inset="3pt,2pt,3pt,2pt">
            <w:txbxContent>
              <w:p>
                <w:pPr><w:jc w:val="{alignment}"/></w:pPr>
                <w:r><w:rPr>{bold}{italic}<w:rFonts w:ascii="{family}" w:hAnsi="{family}"/><w:sz w:val="{font_size}"/><w:color w:val="{color}"/></w:rPr>{fragments}</w:r>
              </w:p>
            </w:txbxContent>
          </v:textbox>
        </v:shape>
      </w:pict>
    </w:r>
    """
    from docx.oxml import parse_xml

    return parse_xml(xml)
