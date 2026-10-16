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
FLOW_BREAK_TOKEN = "{{CADRE_SUIVANT}}"


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
    flow_next_id: str = ""
    shape: str = ""
    border_color: str = "#72879C"
    border_width: float = 0.0
    border_style: str = "solid"
    rotation: int = 0
    flip_horizontal: bool = False
    flip_vertical: bool = False


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
        page.draw_line(
            rectangle.top_left,
            rectangle.bottom_right,
            color=_rgb(item.border_color),
            width=max(0.5, item.border_width),
            dashes="[8 3 2 3]" if item.shape == "axis" else "[5 3]" if item.border_style == "dashed" else "[1 3]" if item.border_style == "dotted" else None,
            overlay=True,
        )
    elif item.kind == "shape":
        _draw_shape(page, rectangle, item)
    elif item.kind == "chart":
        source = next((candidate for candidate in objects if candidate.object_id == item.source_id), None)
        if source is not None:
            _draw_chart(page, rectangle, source, item.fill)
    elif item.kind == "image" and Path(item.image_path).is_file():
        page.insert_image(rectangle, filename=item.image_path, keep_proportion=True, overlay=True)
    elif item.kind in {"text", "table"}:
        content = flowed_text_for_object(item, objects) if item.kind == "text" else item.text
        rendered_text = resolve_dynamic_text(content, page_number, page_count, document_name)
        if item.kind == "table":
            _draw_table(page, rectangle, item, rendered_text)
        else:
            if item.fill.upper() != "#FFFFFF" or item.border_width > 0:
                page.draw_rect(
                    rectangle,
                    color=_rgb(item.border_color) if item.border_width > 0 else _rgb(item.fill),
                    fill=_rgb(item.fill) if item.fill.lower() not in {"", "none", "transparent"} else None,
                    width=max(0.5, item.border_width),
                    dashes="[5 3]" if item.border_style == "dashed" else "[1 3]" if item.border_style == "dotted" else None,
                    overlay=True,
                )
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


def _draw_shape(page: pymupdf.Page, rectangle: pymupdf.Rect, item: PageObject) -> None:
    shape = page.new_shape()
    x0, y0, x1, y1 = rectangle.x0, rectangle.y0, rectangle.x1, rectangle.y1
    if item.shape == "ellipse":
        shape.draw_oval(rectangle)
    elif item.shape == "triangle":
        shape.draw_polyline([(x0 + rectangle.width / 2, y0), (x1, y1), (x0, y1), (x0 + rectangle.width / 2, y0)])
    elif item.shape == "trapezoid":
        inset = rectangle.width * 0.2
        shape.draw_polyline([(x0 + inset, y0), (x1 - inset, y0), (x1, y1), (x0, y1), (x0 + inset, y0)])
    elif item.shape == "arrow":
        if item.rotation % 180 == 90:
            middle, head, thickness = x0 + rectangle.width / 2, rectangle.height * 0.28, rectangle.width * 0.28
            points = [
                (middle - thickness, y0), (middle - thickness, y1 - head),
                (x0, y1 - head), (middle, y1), (x1, y1 - head),
                (middle + thickness, y1 - head), (middle + thickness, y0),
            ]
            if item.flip_vertical:
                points = [(x, y0 + y1 - y) for x, y in points]
        else:
            middle, head, thickness = y0 + rectangle.height / 2, rectangle.width * 0.28, rectangle.height * 0.28
            points = [
                (x0, middle - thickness), (x1 - head, middle - thickness),
                (x1 - head, y0), (x1, middle), (x1 - head, y1),
                (x1 - head, middle + thickness), (x0, middle + thickness),
            ]
            if item.flip_horizontal:
                points = [(x0 + x1 - x, y) for x, y in points]
        shape.draw_polyline(points)
    else:
        shape.draw_rect(rectangle)
    dashes = "[5 3]" if item.border_style == "dashed" else "[1 3]" if item.border_style == "dotted" else None
    fill = None if item.fill.lower() in {"", "none", "transparent"} else _rgb(item.fill)
    shape.finish(color=_rgb(item.border_color), fill=fill, width=max(0.5, item.border_width), dashes=dashes, closePath=True)
    shape.commit(overlay=True)


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


def flowed_text_for_object(item: PageObject, objects: list[PageObject]) -> str:
    """Return the portion of a linked text flow displayed by ``item``."""
    if item.kind != "text":
        return item.text
    by_id = {candidate.object_id: candidate for candidate in objects}
    previous = {
        candidate.flow_next_id: candidate
        for candidate in objects
        if candidate.kind == "text" and candidate.flow_next_id
    }
    root = item
    visited: set[str] = set()
    while root.object_id in previous and root.object_id not in visited:
        visited.add(root.object_id)
        root = previous[root.object_id]
    chain: list[PageObject] = []
    current = root
    visited.clear()
    while current.object_id not in visited:
        visited.add(current.object_id)
        chain.append(current)
        if not current.flow_next_id or current.flow_next_id not in by_id:
            break
        current = by_id[current.flow_next_id]
    segments = _flow_segments(root.text, chain)
    try:
        return segments[chain.index(item)]
    except ValueError:
        return item.text


def _flow_segments(text: str, frames: list[PageObject]) -> list[str]:
    remaining = text
    segments: list[str] = []
    for frame in frames:
        if not remaining:
            segments.append("")
            continue
        break_at = remaining.find(FLOW_BREAK_TOKEN)
        candidate = remaining[:break_at] if break_at >= 0 else remaining
        if _text_fits(candidate, frame):
            segments.append(candidate.rstrip())
            remaining = (
                remaining[break_at + len(FLOW_BREAK_TOKEN) :].lstrip("\n ")
                if break_at >= 0
                else ""
            )
            continue
        low, high = 1, len(candidate)
        while low < high:
            middle = (low + high + 1) // 2
            if _text_fits(candidate[:middle], frame):
                low = middle
            else:
                high = middle - 1
        cut = max(1, low)
        if cut >= len(candidate) or not candidate[cut].isspace():
            word_boundary = max(
                candidate.rfind(" ", int(cut * 0.6), cut),
                candidate.rfind("\n", 0, cut),
            )
            if word_boundary > 0:
                cut = word_boundary
        segment = candidate[:cut].rstrip()
        segments.append(segment)
        remaining = remaining[cut:].lstrip("\n ")
    return segments


def _text_fits(text: str, frame: PageObject) -> bool:
    font_name = {"Serif": "tiro", "Monospace": "cour"}.get(frame.font_family, "helv")
    font = pymupdf.Font(font_name)
    available_width = max(4.0, frame.width - 12)
    line_height = max(7.0, frame.font_size * 1.35)
    maximum_lines = max(1, int((frame.height - 8) / line_height))
    lines = 0
    for paragraph in text.split("\n"):
        if not paragraph:
            lines += 1
            continue
        current = ""
        for character in paragraph:
            candidate = current + character
            if current and font.text_length(candidate, fontsize=frame.font_size) > available_width:
                lines += 1
                current = character.lstrip() if character.isspace() else character
            else:
                current = candidate
        lines += 1
        if lines > maximum_lines:
            return False
    return lines <= maximum_lines


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
