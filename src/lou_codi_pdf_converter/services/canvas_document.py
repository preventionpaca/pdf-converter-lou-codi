from __future__ import annotations

import json
import math
import os
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

import pymupdf

from .table_formulas import evaluate_table

A4_WIDTH = 595.28
A4_HEIGHT = 841.89


@dataclass
class PageObject:
    kind: str
    page: int
    x: float
    y: float
    width: float
    height: float
    text: str = ""
    image_path: str = ""
    font_size: float = 12
    bold: bool = False
    italic: bool = False
    align: str = "left"
    color: str = "#000000"
    fill: str = "#FFFFFF"
    pages: str = ""
    group: str = ""
    font_family: str = "Sans-serif"
    object_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    source_id: str = ""


@dataclass
class CanvasDocument:
    source_pdf: str = ""
    page_count: int = 1
    objects: list[PageObject] = field(default_factory=list)
    page_width: float = A4_WIDTH
    page_height: float = A4_HEIGHT

    def save(self, path: Path) -> None:
        path.write_text(
            json.dumps(
                {
                    "format": 2,
                    "source_pdf": self.source_pdf,
                    "page_count": self.page_count,
                    "page_width": self.page_width,
                    "page_height": self.page_height,
                    "objects": [asdict(item) for item in self.objects],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> CanvasDocument:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("format") != 2:
            raise ValueError("Ce projet utilise un ancien format de document.")
        return cls(
            source_pdf=str(data.get("source_pdf", "")),
            page_count=max(1, int(data.get("page_count", 1))),
            page_width=float(data.get("page_width", A4_WIDTH)),
            page_height=float(data.get("page_height", A4_HEIGHT)),
            objects=[PageObject(**item) for item in data.get("objects", [])],
        )


def export_canvas_pdf(document: CanvasDocument, target: Path) -> None:
    source = Path(document.source_pdf) if document.source_pdf else None
    if source and source.is_file():
        pdf = pymupdf.open(source)
    else:
        pdf = pymupdf.open()

    while pdf.page_count < document.page_count:
        pdf.new_page(width=document.page_width, height=document.page_height)
    if pdf.page_count == 0:
        pdf.new_page(width=A4_WIDTH, height=A4_HEIGHT)

    for item in document.objects:
        for page_number in pages_for_object(item, pdf.page_count):
            page = pdf[page_number]
            _draw_object(
                page,
                item,
                page_number,
                pdf.page_count,
                source.stem if source else target.stem,
                document.objects,
            )
    target.parent.mkdir(parents=True, exist_ok=True)
    pdf.save(target, garbage=4, deflate=True)
    pdf.close()


def _draw_object(
    page: pymupdf.Page,
    item: PageObject,
    page_number: int,
    page_count: int,
    document_name: str,
    objects: list[PageObject],
) -> None:
    rectangle = pymupdf.Rect(item.x, item.y, item.x + item.width, item.y + item.height)
    if item.kind == "mask":
        page.draw_rect(rectangle, color=_rgb(item.fill), fill=_rgb(item.fill), overlay=True)
    elif item.kind == "line":
        page.draw_line(rectangle.top_left, rectangle.bottom_right, color=_rgb(item.color), width=max(0.5, item.font_size / 6), overlay=True)
    elif item.kind == "chart":
        source = next((candidate for candidate in objects if candidate.object_id == item.source_id), None)
        if source is not None:
            _draw_chart(page, rectangle, source, item.fill)
    elif item.kind == "image" and Path(item.image_path).is_file():
        page.insert_image(rectangle, filename=item.image_path, keep_proportion=True, overlay=True)
    elif item.kind in {"text", "table"}:
        rendered_text = resolve_dynamic_text(item.text, page_number, page_count, document_name)
        if item.kind == "table":
            _draw_table(page, rectangle, item, rendered_text)
        else:
            font_file = _font_file(item.font_family, item.bold, item.italic)
            if font_file:
                font_name = f"lc{item.font_family.replace('-', '')}{'b' if item.bold else ''}{'i' if item.italic else ''}"
            else:
                family = {"Serif": "tiro", "Monospace": "cour"}.get(item.font_family, "helv")
                font_name = "hebi" if item.bold and item.italic else "hebo" if item.bold else "heit" if item.italic else family
            page.insert_textbox(
                rectangle,
                rendered_text,
                fontsize=max(6, item.font_size),
                fontname=font_name,
                fontfile=font_file,
                color=_rgb(item.color),
                align={"left": 0, "center": 1, "right": 2, "justify": 3}.get(item.align, 0),
                overlay=True,
            )


def pages_for_object(item: PageObject, page_count: int) -> list[int]:
    """Resolve `all` or a human page selection such as `1,3-5`."""
    if item.pages == "all":
        return list(range(page_count))
    if not item.pages:
        return [item.page] if 0 <= item.page < page_count else []
    selected: set[int] = set()
    for part in item.pages.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                start, end = (int(value) for value in part.split("-", 1))
                selected.update(range(min(start, end) - 1, max(start, end)))
            else:
                selected.add(int(part) - 1)
        except ValueError:
            continue
    return sorted(page for page in selected if 0 <= page < page_count)


def resolve_dynamic_text(text: str, page_number: int, page_count: int, document_name: str = "") -> str:
    return (
        text.replace("{{PAGE}}", str(page_number + 1))
        .replace("{{PAGES}}", str(page_count))
        .replace("{{DATE}}", date.today().strftime("%d/%m/%Y"))
        .replace("{{DOCUMENT}}", document_name)
    )


def _draw_table(page: pymupdf.Page, rectangle: pymupdf.Rect, item: PageObject, text: str) -> None:
    rows = evaluate_table(text)
    if not rows:
        return
    columns = max(len(row) for row in rows)
    row_height = rectangle.height / len(rows)
    column_width = rectangle.width / columns
    for row_index, row in enumerate(rows):
        for column_index in range(columns):
            cell = pymupdf.Rect(
                rectangle.x0 + column_index * column_width,
                rectangle.y0 + row_index * row_height,
                rectangle.x0 + (column_index + 1) * column_width,
                rectangle.y0 + (row_index + 1) * row_height,
            )
            page.draw_rect(cell, color=(0.35, 0.35, 0.35), width=0.6, overlay=True)
            value = row[column_index] if column_index < len(row) else ""
            page.insert_textbox(cell + (3, 2, -3, -2), value, fontsize=item.font_size, overlay=True)


def _draw_chart(page: pymupdf.Page, rectangle: pymupdf.Rect, source: PageObject, chart_type: str) -> None:
    rows = evaluate_table(source.text)
    labels: list[str] = []
    values: list[float] = []
    for index, row in enumerate(rows):
        if not row:
            continue
        try:
            value = float(row[-1].replace(",", "."))
        except ValueError:
            continue
        labels.append(row[0] or str(index + 1))
        values.append(value)
    if not values:
        page.insert_textbox(rectangle, "Aucune donnée numérique", fontsize=10, align=1, overlay=True)
        return
    colors = ((0.14, 0.41, 0.69), (0.91, 0.39, 0.18), (0.27, 0.64, 0.49), (0.94, 0.72, 0.22), (0.53, 0.36, 0.71))
    if chart_type == "pie":
        total = sum(abs(value) for value in values) or 1
        center = rectangle.tl + (rectangle.width / 2, rectangle.height / 2)
        radius = min(rectangle.width, rectangle.height) * 0.38
        angle = 0.0
        for index, value in enumerate(values):
            sweep = 360 * abs(value) / total
            points = [center]
            for degree in range(round(angle), round(angle + sweep) + 1, max(1, round(sweep / 20))):
                radians = math.radians(degree)
                points.append(center + (math.cos(radians) * radius, math.sin(radians) * radius))
            points.append(center)
            shape = page.new_shape()
            shape.draw_polyline(points)
            shape.finish(color=colors[index % len(colors)], fill=colors[index % len(colors)])
            shape.commit(overlay=True)
            angle += sweep
    else:
        maximum = max(abs(value) for value in values) or 1
        gap = rectangle.width / max(1, len(values))
        baseline = rectangle.y1 - 18
        for index, (label, value) in enumerate(zip(labels, values)):
            bar_height = (rectangle.height - 35) * abs(value) / maximum
            bar = pymupdf.Rect(rectangle.x0 + index * gap + 5, baseline - bar_height, rectangle.x0 + (index + 1) * gap - 5, baseline)
            page.draw_rect(bar, color=colors[index % len(colors)], fill=colors[index % len(colors)], overlay=True)
            page.insert_textbox(pymupdf.Rect(bar.x0, baseline + 2, bar.x1, rectangle.y1), label[:12], fontsize=7, align=1, overlay=True)


def _rgb(value: str) -> tuple[float, float, float]:
    clean = value.lstrip("#")
    if len(clean) != 6:
        return (0, 0, 0)
    try:
        return tuple(int(clean[index : index + 2], 16) / 255 for index in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return (0, 0, 0)


@lru_cache(maxsize=32)
def _font_file(family: str, bold: bool, italic: bool) -> str | None:
    style = "BoldItalic" if bold and italic else "Bold" if bold else "Italic" if italic else "Regular"
    if sys.platform == "win32":
        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        names = {
            "Sans-serif": "arial.ttf",
            "Serif": "times.ttf",
            "Monospace": "cour.ttf",
            "Cursive": "comic.ttf",
            "Symboles": "seguisym.ttf",
            "Flèches": "seguisym.ttf",
        }
        candidate = fonts / names.get(family, "arial.ttf")
        return str(candidate) if candidate.is_file() else None
    if sys.platform == "darwin":
        names = {
            "Sans-serif": "Arial Unicode.ttf",
            "Serif": "Times New Roman.ttf",
            "Monospace": "Courier New.ttf",
            "Cursive": "Apple Chancery.ttf",
            "Symboles": "Apple Symbols.ttf",
            "Flèches": "Apple Symbols.ttf",
        }
        for root in (Path("/Library/Fonts"), Path("/System/Library/Fonts")):
            candidate = root / names.get(family, "Arial Unicode.ttf")
            if candidate.is_file():
                return str(candidate)
        return None
    linux_names = {
        "Sans-serif": f"NotoSans-{style}.ttf",
        "Serif": f"NotoSerif-{style}.ttf",
        "Monospace": f"LiberationMono-{style}.ttf",
        "Cursive": "ComicRelief-Regular.ttf",
        "Symboles": "NotoSansSymbols2-Regular.ttf",
        "Flèches": "NotoSansSymbols-Regular.ttf",
    }
    filename = linux_names.get(family, linux_names["Sans-serif"])
    roots = (
        Path("/usr/share/fonts/truetype/noto"),
        Path("/usr/share/fonts/truetype/liberation"),
        Path("/usr/share/fonts/truetype/comic-relief-zorin-os"),
    )
    for root in roots:
        candidate = root / filename
        if candidate.is_file():
            return str(candidate)
    regular = roots[0] / "NotoSans-Regular.ttf"
    return str(regular) if regular.is_file() else None
