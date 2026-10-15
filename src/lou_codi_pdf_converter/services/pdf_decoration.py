from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import Color, HexColor, white
from reportlab.pdfgen import canvas

MM = 72 / 25.4


@dataclass(frozen=True)
class DecorationSettings:
    selected_pages: frozenset[int] | None = None
    watermark_text: str = ""
    watermark_image: Path | None = None
    watermark_x_mm: float | None = None
    watermark_y_mm: float | None = None
    watermark_size: float = 52
    watermark_rotation: float = 35
    watermark_opacity: float = 0.18
    watermark_color: str = "#7A8795"
    watermark_front: bool = True
    header_text: str = ""
    header_position: str = "center"
    header_y_mm: float = 12
    footer_text: str = ""
    footer_position: str = "center"
    footer_y_mm: float = 10
    text_size: float = 9
    text_color: str = "#193B66"
    footer_line: bool = False
    mask_original_footer: bool = False
    footer_mask_height_mm: float = 18


def parse_page_selection(expression: str, page_count: int) -> frozenset[int] | None:
    """Parse French-friendly 1-based page ranges; an empty value means all pages."""
    value = expression.strip().lower()
    if not value or value in {"toutes", "tout", "all"}:
        return None
    selected: set[int] = set()
    for raw_part in value.replace(";", ",").split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start, end = int(start_text), int(end_text)
            if start > end:
                start, end = end, start
            numbers = range(start, end + 1)
        else:
            numbers = (int(part),)
        for number in numbers:
            if number < 1 or number > page_count:
                raise ValueError(f"La page {number} n’existe pas dans ce document.")
            selected.add(number - 1)
    if not selected:
        raise ValueError("Indiquez au moins une page valide.")
    return frozenset(selected)


def apply_pdf_decorations(
    source: Path,
    target: Path,
    settings: DecorationSettings,
) -> None:
    reader = PdfReader(source)
    writer = PdfWriter()
    total = len(reader.pages)
    document_name = source.stem

    for page_index, page in enumerate(reader.pages):
        if settings.selected_pages is None or page_index in settings.selected_pages:
            width = float(page.mediabox.width)
            height = float(page.mediabox.height)
            has_watermark = bool(settings.watermark_text or settings.watermark_image)
            if has_watermark and not settings.watermark_front:
                background = _make_overlay(
                    width,
                    height,
                    page_index + 1,
                    total,
                    document_name,
                    settings,
                    draw_watermark=True,
                    draw_layout=False,
                )
                writer.add_page(background)
                output_page = writer.pages[-1]
                output_page.merge_page(page, over=True)
            else:
                writer.add_page(page)
                output_page = writer.pages[-1]
            foreground = _make_overlay(
                width,
                height,
                page_index + 1,
                total,
                document_name,
                settings,
                draw_watermark=settings.watermark_front,
                draw_layout=True,
            )
            output_page.merge_page(foreground, over=True)
        else:
            writer.add_page(page)

    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as stream:
        writer.write(stream)


def _make_overlay(
    width: float,
    height: float,
    page_number: int,
    total: int,
    document_name: str,
    settings: DecorationSettings,
    *,
    draw_watermark: bool,
    draw_layout: bool,
):
    stream = io.BytesIO()
    drawing = canvas.Canvas(stream, pagesize=(width, height))

    if draw_layout and settings.mask_original_footer:
        drawing.setFillColor(white)
        drawing.rect(
            0,
            0,
            width,
            max(0, settings.footer_mask_height_mm) * MM,
            fill=1,
            stroke=0,
        )

    if draw_watermark and settings.watermark_text:
        drawing.saveState()
        _set_alpha(drawing, settings.watermark_opacity)
        drawing.setFillColor(_color(settings.watermark_color))
        drawing.setFont("Helvetica-Bold", max(4, settings.watermark_size))
        x = settings.watermark_x_mm * MM if settings.watermark_x_mm is not None else width / 2
        y = settings.watermark_y_mm * MM if settings.watermark_y_mm is not None else height / 2
        drawing.translate(x, y)
        drawing.rotate(settings.watermark_rotation)
        drawing.drawCentredString(0, 0, settings.watermark_text)
        drawing.restoreState()

    if draw_watermark and settings.watermark_image and settings.watermark_image.is_file():
        drawing.saveState()
        _set_alpha(drawing, settings.watermark_opacity)
        image_width = max(10, settings.watermark_size * 2.4)
        x = settings.watermark_x_mm * MM if settings.watermark_x_mm is not None else width / 2
        y = settings.watermark_y_mm * MM if settings.watermark_y_mm is not None else height / 2
        drawing.translate(x, y)
        drawing.rotate(settings.watermark_rotation)
        drawing.drawImage(
            str(settings.watermark_image),
            -image_width / 2,
            -image_width / 2,
            width=image_width,
            height=image_width,
            preserveAspectRatio=True,
            anchor="c",
            mask="auto",
        )
        drawing.restoreState()

    if draw_layout:
        drawing.setFillColor(_color(settings.text_color))
        drawing.setStrokeColor(_color(settings.text_color))
        drawing.setFont("Helvetica", max(4, settings.text_size))
        if settings.header_text:
            text = _expand(settings.header_text, page_number, total, document_name)
            _draw_aligned(
                drawing,
                text,
                settings.header_position,
                width,
                height - settings.header_y_mm * MM,
            )
        if settings.footer_line:
            y = max(4, settings.footer_mask_height_mm * MM)
            drawing.setLineWidth(0.6)
            drawing.line(15 * MM, y, width - 15 * MM, y)
        if settings.footer_text:
            text = _expand(settings.footer_text, page_number, total, document_name)
            _draw_aligned(
                drawing,
                text,
                settings.footer_position,
                width,
                settings.footer_y_mm * MM,
            )

    drawing.save()
    stream.seek(0)
    return PdfReader(stream).pages[0]


def _draw_aligned(drawing: canvas.Canvas, text: str, position: str, width: float, y: float) -> None:
    margin = 15 * MM
    if position == "left":
        drawing.drawString(margin, y, text)
    elif position == "right":
        drawing.drawRightString(width - margin, y, text)
    else:
        drawing.drawCentredString(width / 2, y, text)


def _expand(template: str, page: int, total: int, document: str) -> str:
    return (
        template.replace("{page}", str(page))
        .replace("{pages}", str(total))
        .replace("{document}", document)
        .replace("{date}", date.today().strftime("%d/%m/%Y"))
    )


def _set_alpha(drawing: canvas.Canvas, opacity: float) -> None:
    if hasattr(drawing, "setFillAlpha"):
        drawing.setFillAlpha(min(1, max(0, opacity)))


def _color(value: str) -> Color:
    try:
        return HexColor(value)
    except (TypeError, ValueError):
        return HexColor("#193B66")
