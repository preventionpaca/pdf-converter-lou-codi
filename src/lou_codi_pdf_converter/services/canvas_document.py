from __future__ import annotations

import json
import math
import os
import re
import sys
import tempfile
import uuid
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

import pymupdf
from PIL import ImageFont

from .table_formulas import evaluate_table, evaluate_table_cells

A4_WIDTH = 595.28
A4_HEIGHT = 841.89
FLOW_BREAK_TOKEN = "{{CADRE_SUIVANT}}"
TEXT_FRAME_HORIZONTAL_PADDING = 8.0

TABLE_STYLE_PALETTES: dict[str, tuple[str, str, str, str]] = {
    "blue": ("#193F6A", "#FFFFFF", "#EAF3FC", "#D5E7F7"),
    "green": ("#087F6A", "#FFFFFF", "#E9F7F2", "#D2EEE5"),
}


def table_cell_colors(style: str, row: int) -> tuple[str, str]:
    """Return the background and text colours for a table row preset."""
    palette = TABLE_STYLE_PALETTES.get(style)
    if palette is None:
        return "#FFFFFF", "#000000"
    header_fill, header_text, odd_fill, even_fill = palette
    if row == 0:
        return header_fill, header_text
    return (odd_fill if row % 2 else even_fill), "#000000"


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
    underline: bool = False
    strikethrough: bool = False
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
    locked: bool = False
    level: int = 0
    hyperlink: str = ""
    text_links: list[dict[str, object]] = field(default_factory=list)
    text_styles: list[dict[str, object]] = field(default_factory=list)
    paragraph_alignments: list[dict[str, object]] = field(default_factory=list)
    text_line_height: float = 0.0
    table_cells: list[list[dict[str, object]]] = field(default_factory=list)
    table_column_widths: list[float] = field(default_factory=list)
    table_row_heights: list[float] = field(default_factory=list)
    table_style: str = "plain"
    table_outer_border_width: float = 1.5
    table_inner_border_width: float = 0.6
    table_row_border_widths: dict[str, float] = field(default_factory=dict)
    table_merges: list[list[int]] = field(default_factory=list)
    table_border_ranges: list[dict[str, float]] = field(default_factory=list)
    points: list[list[float]] = field(default_factory=list)
    dimension_refs: list[dict[str, object]] = field(default_factory=list)
    chart_title: str = ""
    chart_series_index: int = 1
    chart_series_indices: list[int] = field(default_factory=list)
    chart_data_orientation: str = "columns"
    chart_show_legend: bool = True
    chart_show_values: bool = True


@dataclass
class CanvasDocument:
    source_pdf: str = ""
    page_count: int = 1
    objects: list[PageObject] = field(default_factory=list)
    page_width: float = A4_WIDTH
    page_height: float = A4_HEIGHT
    measurement_scale: float = 1.0
    is_template: bool = False

    def save(self, path: Path) -> None:
        """Save one self-contained .cod archive, including every external asset."""
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        archived_paths: dict[Path, str] = {}
        try:
            with zipfile.ZipFile(
                temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
            ) as archive:
                def add_asset(raw_path: str, category: str) -> str:
                    if not raw_path:
                        return ""
                    source = Path(raw_path).expanduser()
                    if not source.is_file():
                        return ""
                    resolved = source.resolve()
                    if resolved in archived_paths:
                        return archived_paths[resolved]
                    suffix = source.suffix.lower() or ".bin"
                    member = f"assets/{category}/{uuid.uuid4().hex}{suffix}"
                    archive.write(source, member)
                    archived_paths[resolved] = member
                    return member

                objects: list[dict[str, object]] = []
                for item in self.objects:
                    data = asdict(item)
                    data["image_path"] = add_asset(item.image_path, "images")
                    cells = data.get("table_cells", [])
                    if isinstance(cells, list):
                        for row in cells:
                            if not isinstance(row, list):
                                continue
                            for cell in row:
                                if isinstance(cell, dict):
                                    cell["image_path"] = add_asset(
                                        str(cell.get("image_path", "")), "images"
                                    )
                    objects.append(data)
                manifest = {
                    "format": 3,
                    "source_pdf": add_asset(self.source_pdf, "backgrounds"),
                    "page_count": self.page_count,
                    "page_width": self.page_width,
                    "page_height": self.page_height,
                    "measurement_scale": self.measurement_scale,
                    "is_template": self.is_template,
                    "objects": objects,
                }
                archive.writestr(
                    "document.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2),
                )
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def load(cls, path: Path) -> CanvasDocument:
        if not zipfile.is_zipfile(path):
            raise ValueError("Ce fichier n’est pas un document Lou Còdi autonome.")
        asset_directory = Path(tempfile.mkdtemp(prefix="lou-codi-document-"))
        with zipfile.ZipFile(path) as archive:
            try:
                data = json.loads(archive.read("document.json").decode("utf-8"))
            except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("Le document Lou Còdi est incomplet ou endommagé.") from exc
            if data.get("format") != 3:
                raise ValueError("Ce document utilise un format Lou Còdi non pris en charge.")

            extracted: dict[str, str] = {}

            def materialize(member: object) -> str:
                name = str(member or "")
                if not name:
                    return ""
                if name in extracted:
                    return extracted[name]
                if not name.startswith("assets/") or name not in archive.namelist():
                    raise ValueError("Une ressource incorporée au document est manquante.")
                target = asset_directory / f"{uuid.uuid4().hex}{Path(name).suffix}"
                target.write_bytes(archive.read(name))
                extracted[name] = str(target)
                return str(target)

            object_values = data.get("objects", [])
            if not isinstance(object_values, list):
                raise ValueError("La liste des objets du document est incorrecte.")
            for item in object_values:
                if not isinstance(item, dict):
                    raise ValueError("Un objet du document est incorrect.")
                item["image_path"] = materialize(item.get("image_path", ""))
                for row in item.get("table_cells", []):
                    for cell in row:
                        if isinstance(cell, dict):
                            cell["image_path"] = materialize(cell.get("image_path", ""))
        return cls(
            source_pdf=materialize(data.get("source_pdf", "")),
            page_count=max(1, int(data.get("page_count", 1))),
            page_width=float(data.get("page_width", A4_WIDTH)),
            page_height=float(data.get("page_height", A4_HEIGHT)),
            measurement_scale=max(1e-9, float(data.get("measurement_scale", 1.0))),
            is_template=bool(data.get("is_template", False)),
            objects=[PageObject(**item) for item in object_values],
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

    for _index, item in sorted(
        enumerate(document.objects), key=lambda indexed: (indexed[1].level, indexed[0])
    ):
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
        fill = "#FFFFFF" if item.fill.lower() in {"", "none", "transparent"} else item.fill
        page.draw_rect(
            rectangle,
            color=_rgb(item.border_color) if item.border_width > 0 else _rgb(fill),
            fill=_rgb(fill),
            width=max(0.5, item.border_width) if item.border_width > 0 else 0.5,
            overlay=True,
        )
    elif item.kind == "origin":
        color = (0.78, 0.12, 0.12)
        page.draw_line(
            pymupdf.Point(item.x - 12, item.y),
            pymupdf.Point(item.x + 12, item.y),
            color=color,
            width=1.5,
            overlay=True,
        )
        page.draw_line(
            pymupdf.Point(item.x, item.y + 12),
            pymupdf.Point(item.x, item.y - 12),
            color=color,
            width=1.5,
            overlay=True,
        )
        page.insert_text(
            pymupdf.Point(item.x + 5, item.y - 5),
            "X0 / Z0",
            fontsize=7,
            color=color,
            overlay=True,
        )
    elif item.kind == "line":
        page.draw_line(
            rectangle.top_left,
            rectangle.bottom_right,
            color=_rgb(item.border_color),
            width=max(0.5, item.border_width),
            dashes="[8 3 2 3]" if item.shape == "axis" else "[5 3]" if item.border_style == "dashed" else "[1 3]" if item.border_style == "dotted" else None,
            overlay=True,
        )
    elif item.kind == "dimension":
        start = pymupdf.Point(item.x, item.y)
        end = pymupdf.Point(item.x + item.width, item.y + item.height)
        anchors = item.points if len(item.points) == 2 else [[start.x, start.y], [end.x, end.y]]
        for anchor, endpoint in zip(anchors, (start, end), strict=True):
            page.draw_line(
                pymupdf.Point(float(anchor[0]), float(anchor[1])),
                endpoint,
                color=_rgb(item.border_color),
                width=max(0.5, item.border_width),
                overlay=True,
            )
        page.draw_line(
            start,
            end,
            color=_rgb(item.border_color),
            width=max(0.5, item.border_width),
            overlay=True,
        )
        length = math.hypot(item.width, item.height)
        if length > 1e-8:
            normal_x = -item.height / length * 5
            normal_y = item.width / length * 5
            for point in (start, end):
                page.draw_line(
                    pymupdf.Point(point.x - normal_x, point.y - normal_y),
                    pymupdf.Point(point.x + normal_x, point.y + normal_y),
                    color=_rgb(item.border_color),
                    width=max(0.5, item.border_width),
                    overlay=True,
                )
        text = f"{item.text} mm"
        unit_x, unit_y = (item.width / length, item.height / length) if length else (1.0, 0.0)
        normal_x, normal_y = -unit_y, unit_x
        if normal_y > 0:
            normal_x, normal_y = -normal_x, -normal_y
        angle = -math.degrees(math.atan2(item.height, item.width)) if length else 0.0
        reversed_text = False
        if angle > 90:
            angle -= 180
            reversed_text = True
        elif angle < -90:
            angle += 180
            reversed_text = True
        if reversed_text:
            unit_x, unit_y = -unit_x, -unit_y
        center_x = item.x + item.width / 2 + normal_x * 11
        center_y = item.y + item.height / 2 + normal_y * 11
        text_width = pymupdf.get_text_length(text, fontsize=8)
        label_position = pymupdf.Point(
            center_x - unit_x * text_width / 2,
            center_y - unit_y * text_width / 2,
        )
        page.insert_text(
            label_position,
            text,
            fontsize=8,
            color=_rgb(item.border_color),
            morph=(label_position, pymupdf.Matrix(angle)),
            overlay=True,
        )
    elif item.kind == "polyline" and len(item.points) >= 2:
        points = [(item.x + point[0], item.y + point[1]) for point in item.points]
        closed = len(points) >= 3 and math.dist(points[0], points[-1]) <= 1e-6
        shape = page.new_shape()
        shape.draw_polyline(points)
        shape.finish(
            color=_rgb(item.border_color),
            fill=(
                None
                if not closed or item.fill.lower() in {"", "none", "transparent"}
                else _rgb(item.fill)
            ),
            width=max(0.5, item.border_width),
            dashes="[5 3]" if item.border_style == "dashed" else "[1 3]" if item.border_style == "dotted" else None,
            closePath=closed,
        )
        shape.commit(overlay=True)
    elif item.kind == "shape":
        _draw_shape(page, rectangle, item)
    elif item.kind == "chart":
        source = next((candidate for candidate in objects if candidate.object_id == item.source_id), None)
        if source is not None:
            _draw_chart(page, rectangle, source, item)
    elif item.kind == "image" and Path(item.image_path).is_file():
        page.insert_image(rectangle, filename=item.image_path, keep_proportion=True, overlay=True)
        if item.border_width > 0:
            page.draw_rect(
                rectangle,
                color=_rgb(item.border_color),
                width=max(0.5, item.border_width),
                dashes="[5 3]" if item.border_style == "dashed" else "[1 3]" if item.border_style == "dotted" else None,
                overlay=True,
            )
    elif item.kind in {"text", "table"}:
        if item.kind == "text":
            content, style_source, flow_offset = flowed_text_context(item, objects)
        else:
            content, style_source, flow_offset = item.text, item, 0
        rendered_text = resolve_dynamic_text(content, page_number, page_count, document_name)
        if item.kind == "table":
            _draw_table(page, rectangle, item, rendered_text)
        else:
            rotation = float(item.rotation) % 360
            centre = pymupdf.Point(
                (rectangle.x0 + rectangle.x1) / 2,
                (rectangle.y0 + rectangle.y1) / 2,
            )
            # Canvas/Pillow use screen coordinates (positive angles clockwise).
            # PyMuPDF uses the opposite sign, so mirror the angle, not the page.
            morph = (centre, pymupdf.Matrix(-rotation)) if rotation else None
            if item.fill.upper() != "#FFFFFF" or item.border_width > 0:
                page.draw_rect(
                    rectangle,
                    color=_rgb(item.border_color) if item.border_width > 0 else _rgb(item.fill),
                    fill=_rgb(item.fill) if item.fill.lower() not in {"", "none", "transparent"} else None,
                    width=max(0.5, item.border_width),
                    dashes="[5 3]" if item.border_style == "dashed" else "[1 3]" if item.border_style == "dotted" else None,
                    morph=morph,
                    overlay=True,
                )
            font_file = _font_file(style_source.font_family, style_source.bold, style_source.italic)
            if font_file:
                font_name = f"lc{style_source.font_family.replace('-', '')}{'b' if style_source.bold else ''}{'i' if style_source.italic else ''}"
            else:
                family = {"Serif": "tiro", "Monospace": "cour"}.get(style_source.font_family, "helv")
                font_name = "hebi" if style_source.bold and style_source.italic else "hebo" if style_source.bold else "heit" if style_source.italic else family
            # PyMuPDF's built-in font metrics are slightly taller than the
            # exact line spacing used by Word / TextMaker.  A textbox that is
            # only a fraction of a point too short is otherwise rejected in
            # full, leaving a completely blank legal-text frame.  Retry with
            # the smallest necessary reduction instead of losing its content.
            text_font_size = max(6.0, style_source.font_size)
            while text_font_size >= 4.0:
                spare_height = page.insert_textbox(
                    rectangle,
                    rendered_text,
                    fontsize=text_font_size,
                    fontname=font_name,
                    fontfile=font_file,
                    color=_rgb(style_source.color),
                    align={"left": 0, "center": 1, "right": 2, "justify": 3}.get(style_source.align, 0),
                    rotate=0,
                    morph=morph,
                    overlay=True,
                )
                if spare_height >= 0:
                    break
                text_font_size -= 0.25
            if style_source.underline or style_source.strikethrough:
                for text_line in (line.strip() for line in rendered_text.splitlines()):
                    if not text_line:
                        continue
                    for text_rectangle in page.search_for(text_line, clip=rectangle):
                        if style_source.underline:
                            page.draw_line(
                                text_rectangle.bottom_left,
                                text_rectangle.bottom_right,
                                color=_rgb(style_source.color), width=0.8, overlay=True,
                            )
                        if style_source.strikethrough:
                            middle_y = (text_rectangle.y0 + text_rectangle.y1) / 2
                            page.draw_line(
                                pymupdf.Point(text_rectangle.x0, middle_y),
                                pymupdf.Point(text_rectangle.x1, middle_y),
                                color=_rgb(style_source.color), width=0.8, overlay=True,
                            )
            for link in style_source.text_links:
                start = max(0, int(link.get("start", 0)) - flow_offset)
                end = min(len(rendered_text), int(link.get("end", 0)) - flow_offset)
                uri = str(link.get("hyperlink", "")).strip()
                linked_text = rendered_text[start:end].strip()
                if not linked_text or not uri:
                    continue
                for linked_rectangle in page.search_for(linked_text, clip=rectangle):
                    page.draw_line(
                        linked_rectangle.bottom_left,
                        linked_rectangle.bottom_right,
                        color=(0.09, 0.41, 0.69), width=0.8, overlay=True,
                    )
                    page.insert_link(
                        {"kind": pymupdf.LINK_URI, "from": linked_rectangle, "uri": uri}
                    )
    # Text frames only carry links on explicit character ranges.  A frame-wide
    # link makes editing ambiguous and used to destabilise the inline editor.
    if item.kind != "text" and item.hyperlink.strip():
        page.draw_line(
            pymupdf.Point(min(rectangle.x0, rectangle.x1), max(rectangle.y0, rectangle.y1) - 1),
            pymupdf.Point(max(rectangle.x0, rectangle.x1), max(rectangle.y0, rectangle.y1) - 1),
            color=(0.09, 0.41, 0.69), width=1.0, overlay=True,
        )
        link_rectangle = pymupdf.Rect(
            min(rectangle.x0, rectangle.x1), min(rectangle.y0, rectangle.y1),
            max(rectangle.x0, rectangle.x1), max(rectangle.y0, rectangle.y1),
        )
        page.insert_link(
            {"kind": pymupdf.LINK_URI, "from": link_rectangle, "uri": item.hyperlink.strip()}
        )


def _draw_shape(page: pymupdf.Page, rectangle: pymupdf.Rect, item: PageObject) -> None:
    shape = page.new_shape()
    x0, y0, x1, y1 = rectangle.x0, rectangle.y0, rectangle.x1, rectangle.y1
    if item.shape in {"ellipse", "circle"}:
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
    return flowed_text_context(item, objects)[0]


def flowed_text_context(
    item: PageObject, objects: list[PageObject]
) -> tuple[str, PageObject, int]:
    """Return displayed text, its root style source and its offset in that source."""
    if item.kind != "text":
        return item.text, item, 0
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
        target_index = chain.index(item)
    except ValueError:
        return item.text, item, 0
    cursor = 0
    offsets: list[int] = []
    for segment in segments:
        offset = root.text.find(segment, cursor) if segment else cursor
        if offset < 0:
            offset = cursor
        offsets.append(offset)
        cursor = offset + len(segment)
    return segments[target_index], root, offsets[target_index]


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
    return len(wrapped_text_lines(text, frame)) <= text_frame_line_capacity(frame)


def text_frame_line_height(frame: PageObject) -> float:
    """Return the text leading used consistently by flow and canvas preview."""
    return max(1.0, frame.text_line_height or frame.font_size * 1.35)


def table_grid_offsets(values: list[float], count: int, total: float) -> list[float]:
    """Return normalized grid boundaries, preserving imported Word dimensions."""
    usable = [max(0.0, float(value)) for value in values[:count]]
    if len(usable) != count or sum(usable) <= 0:
        usable = [1.0] * max(1, count)
    scale = total / sum(usable)
    offsets = [0.0]
    for value in usable:
        offsets.append(offsets[-1] + value * scale)
    offsets[-1] = total
    return offsets


def fitted_table_cell_text(
    value: str,
    width: float,
    height: float,
    font_size: float,
    *,
    bold: bool = False,
    italic: bool = False,
) -> tuple[str, float]:
    """Fit an editable cell value without allowing it to paint over neighbours."""
    available_width = max(4.0, width - 6.0)
    available_height = max(4.0, height - 4.0)
    requested = max(4.0, float(font_size))

    def wrap(size: float) -> list[str]:
        font = _text_flow_font("Sans-serif", size, bold, italic)
        lines: list[str] = []
        for paragraph in value.replace("\t", " ").split("\n"):
            if not paragraph:
                lines.append("")
                continue
            current = ""
            for word in paragraph.split(" "):
                candidate = word if not current else f"{current} {word}"
                if font.getlength(candidate) <= available_width:
                    current = candidate
                elif not current:
                    fragment = ""
                    for character in word:
                        if fragment and font.getlength(fragment + character) > available_width:
                            lines.append(fragment)
                            fragment = character
                        else:
                            fragment += character
                    current = fragment
                else:
                    lines.append(current)
                    current = word
            lines.append(current)
        return lines or [""]

    size = requested
    lines = wrap(size)
    while size > 4.0 and len(lines) * size * 1.2 > available_height:
        size = max(4.0, size - 0.5)
        lines = wrap(size)
    capacity = max(1, int(available_height / max(1.0, size * 1.2)))
    if len(lines) > capacity:
        lines = lines[:capacity]
        last = lines[-1].rstrip()
        while last and _text_flow_font("Sans-serif", size, bold, italic).getlength(f"{last}…") > available_width:
            last = last[:-1]
        lines[-1] = f"{last.rstrip()}…"
    return "\n".join(lines), size


def text_frame_line_capacity(frame: PageObject) -> int:
    """Return how many complete lines are visible inside a text frame."""
    return max(1, int((abs(frame.height) - 8) / text_frame_line_height(frame)))


def wrapped_text_lines(text: str, frame: PageObject) -> list[str]:
    """Wrap text in page units so flow and on-screen rendering cannot diverge."""
    return [line for line, _start, _end in wrapped_text_ranges(text, frame)]


def wrapped_text_ranges(
    text: str, frame: PageObject
) -> list[tuple[str, int, int]]:
    """Return wrapped lines with their exact offsets in the rich source text."""
    available_width = max(4.0, abs(frame.width) - 2 * TEXT_FRAME_HORIZONTAL_PADDING)
    style_lookup = _text_flow_style_lookup(frame, len(text))

    def styled_width(value: str, start: int) -> float:
        return _styled_text_flow_width(frame, value, start, style_lookup)

    lines: list[tuple[str, int, int]] = []
    paragraph_start = 0
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append(("", paragraph_start, paragraph_start))
            paragraph_start += 1
            continue
        matches = list(re.finditer(r"\S+", paragraph))
        if not matches:
            lines.append(("", paragraph_start, paragraph_start))
            paragraph_start += len(paragraph) + 1
            continue
        line_start: int | None = None
        line_end = paragraph_start
        current_width = 0.0
        previous_end = 0
        for match in matches:
            word = match.group(0)
            word_start = paragraph_start + match.start()
            word_end = paragraph_start + match.end()
            word_width = styled_width(word, word_start)
            separator = paragraph[previous_end : match.start()] if line_start is not None else ""
            separator_width = styled_width(separator, paragraph_start + previous_end)
            previous_end = match.end()
            candidate_width = current_width + separator_width + word_width
            if line_start is not None and candidate_width > available_width:
                lines.append((text[line_start:line_end], line_start, line_end))
                line_start = None
                current_width = 0.0
            if word_width <= available_width:
                if line_start is None:
                    line_start = word_start
                    current_width = word_width
                else:
                    current_width = candidate_width
                line_end = word_end
                continue
            if line_start is not None:
                lines.append((text[line_start:line_end], line_start, line_end))
                line_start = None
                current_width = 0.0
            fragment_start = word_start
            fragment_width = 0.0
            for character_index, character in enumerate(word):
                character_width = styled_width(character, word_start + character_index)
                character_position = word_start + character_index
                if character_position > fragment_start and fragment_width + character_width > available_width:
                    lines.append((text[fragment_start:character_position], fragment_start, character_position))
                    fragment_start = character_position
                    fragment_width = character_width
                else:
                    fragment_width += character_width
            if fragment_start < word_end:
                line_start = fragment_start
                line_end = word_end
                current_width = fragment_width
        if line_start is not None:
            lines.append((text[line_start:line_end], line_start, line_end))
        paragraph_start += len(paragraph) + 1
    return lines


def _text_flow_style_lookup(
    frame: PageObject, text_length: int
) -> list[tuple[str, float, bool, bool]]:
    """Resolve rich-text metrics once instead of scanning every run per glyph."""
    default = (frame.font_family, frame.font_size, frame.bold, frame.italic)
    lookup = [default] * max(0, text_length)
    for run in frame.text_styles:
        try:
            run_start = max(0, min(text_length, int(run.get("start", 0))))
            run_end = max(run_start, min(text_length, int(run.get("end", 0))))
            family = str(run.get("font_family", frame.font_family))
            size = float(run.get("font_size", frame.font_size))
        except (TypeError, ValueError):
            continue
        for position in range(run_start, run_end):
            previous = lookup[position]
            lookup[position] = (
                family if "font_family" in run else previous[0],
                size if "font_size" in run else previous[1],
                bool(run["bold"]) if "bold" in run else previous[2],
                bool(run["italic"]) if "italic" in run else previous[3],
            )
    return lookup


def _styled_text_flow_width(
    frame: PageObject,
    text: str,
    start: int,
    style_lookup: list[tuple[str, float, bool, bool]] | None = None,
) -> float:
    """Measure text with the effective rich style of every character."""
    width = 0.0
    for offset, character in enumerate(text):
        position = start + offset
        if style_lookup is not None and 0 <= position < len(style_lookup):
            family, size, bold, italic = style_lookup[position]
        else:
            family, size, bold, italic = frame.font_family, frame.font_size, frame.bold, frame.italic
        width += _text_flow_character_width(family, size, bold, italic, character)
    return width


@lru_cache(maxsize=48)
def _text_flow_font(
    font_family: str, font_size: float, bold: bool, italic: bool
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load the exact font used by the canvas preview for reliable wrapping."""
    suffix = (
        "-BoldOblique"
        if bold and italic
        else "-Bold"
        if bold
        else "-Oblique"
        if italic
        else ""
    )
    family = (
        "DejaVuSansMono"
        if font_family == "Monospace"
        else "DejaVuSerif"
        if font_family == "Serif"
        else "DejaVuSans"
    )
    try:
        return ImageFont.truetype(f"{family}{suffix}.ttf", max(7, round(font_size)))
    except OSError:
        return ImageFont.load_default()


@lru_cache(maxsize=4096)
def _text_flow_character_width(
    font_family: str,
    font_size: float,
    bold: bool,
    italic: bool,
    character: str,
) -> float:
    return _text_flow_font(font_family, font_size, bold, italic).getlength(character)


def _text_flow_text_width(
    font_family: str, font_size: float, bold: bool, italic: bool, text: str
) -> float:
    return sum(
        _text_flow_character_width(
            font_family, font_size, bold, italic, character
        )
        for character in text
    )


def _table_merge_for_cell(item: PageObject, row: int, column: int) -> list[int] | None:
    for merge in item.table_merges:
        if len(merge) == 4:
            top, left, row_span, column_span = merge
            if top <= row < top + row_span and left <= column < left + column_span:
                return merge
    return None


def _table_grid_hidden(
    item: PageObject, row_a: int, column_a: int, row_b: int, column_b: int
) -> bool:
    merge = _table_merge_for_cell(item, row_a, column_a)
    return merge is not None and merge == _table_merge_for_cell(item, row_b, column_b)


def _draw_table(page: pymupdf.Page, rectangle: pymupdf.Rect, item: PageObject, text: str) -> None:
    rows = evaluate_table_cells(item.table_cells) if item.table_cells else evaluate_table(text)
    if not rows:
        return
    columns = max(len(row) for row in rows)
    row_offsets = table_grid_offsets(item.table_row_heights, len(rows), rectangle.height)
    column_offsets = table_grid_offsets(item.table_column_widths, columns, rectangle.width)
    for row_index, row in enumerate(rows):
        for column_index in range(columns):
            merge = _table_merge_for_cell(item, row_index, column_index)
            if merge and (row_index, column_index) != (merge[0], merge[1]):
                continue
            row_span, column_span = (merge[2], merge[3]) if merge else (1, 1)
            cell = pymupdf.Rect(
                rectangle.x0 + column_offsets[column_index],
                rectangle.y0 + row_offsets[row_index],
                rectangle.x0 + column_offsets[column_index + column_span],
                rectangle.y0 + row_offsets[row_index + row_span],
            )
            default_fill, text_color = table_cell_colors(item.table_style, row_index)
            value = row[column_index] if column_index < len(row) else ""
            metadata = (
                item.table_cells[row_index][column_index]
                if item.table_cells and row_index < len(item.table_cells)
                and column_index < len(item.table_cells[row_index])
                else {}
            )
            cell_fill = str(metadata.get("fill", default_fill))
            cell_border_width = float(metadata.get("border_width", 0) or 0)
            cell_border_color = str(metadata.get("border_color", item.border_color))
            page.draw_rect(
                cell,
                color=_rgb(cell_border_color) if cell_border_width else None,
                fill=_rgb(cell_fill),
                width=max(0.1, cell_border_width),
                overlay=True,
            )
            image_path = metadata.get("image_path", "")
            horizontal_align = metadata.get("horizontal_align", "left")
            vertical_align = metadata.get("vertical_align", "top")
            cell_font_size = float(metadata.get("font_size", item.font_size) or item.font_size)
            cell_color = str(metadata.get("color", text_color) or text_color)
            cell_bold = bool(metadata.get("bold", False))
            cell_italic = bool(metadata.get("italic", False))
            value, cell_font_size = fitted_table_cell_text(
                value,
                cell.width,
                cell.height,
                cell_font_size,
                bold=cell_bold,
                italic=cell_italic,
            )
            text_cell = cell + (3, 2, -3, -2)
            if image_path and Path(image_path).is_file():
                image_bottom = cell.y0 + cell.height * (0.62 if value else 0.92)
                page.insert_image(
                    pymupdf.Rect(cell.x0 + 3, cell.y0 + 3, cell.x1 - 3, image_bottom),
                    filename=image_path,
                    keep_proportion=True,
                    overlay=True,
                )
                text_cell = pymupdf.Rect(cell.x0 + 3, image_bottom + 1, cell.x1 - 3, cell.y1 - 2)
            font_name = (
                "hebi" if cell_bold and cell_italic else
                "hebo" if cell_bold else
                "heit" if cell_italic else
                "helv"
            )
            lines = value.split("\n")
            line_height = cell_font_size * 1.2
            block_height = len(lines) * line_height
            start_y = text_cell.y0 + cell_font_size
            if vertical_align == "middle":
                start_y += max(0.0, (text_cell.height - block_height) / 2)
            elif vertical_align == "bottom":
                start_y += max(0.0, text_cell.height - block_height)
            for line_number, line in enumerate(lines):
                line_width = pymupdf.get_text_length(
                    line, fontname=font_name, fontsize=cell_font_size
                )
                line_x = text_cell.x0
                if horizontal_align == "center":
                    line_x += max(0.0, (text_cell.width - line_width) / 2)
                elif horizontal_align == "right":
                    line_x += max(0.0, text_cell.width - line_width)
                page.insert_text(
                    pymupdf.Point(line_x, start_y + line_number * line_height),
                    line,
                    fontsize=cell_font_size,
                    fontname=font_name,
                    color=_rgb(cell_color),
                    overlay=True,
                )
            hyperlink = metadata.get("hyperlink", "").strip()
            if hyperlink:
                page.draw_line(
                    pymupdf.Point(cell.x0 + 2, cell.y1 - 2),
                    pymupdf.Point(cell.x1 - 2, cell.y1 - 2),
                    color=(0.09, 0.41, 0.69), width=0.8, overlay=True,
                )
                page.insert_link({"kind": pymupdf.LINK_URI, "from": cell, "uri": hyperlink})
    border_color = _rgb(item.border_color)
    if item.table_inner_border_width > 0:
        for column in range(1, columns):
            x = rectangle.x0 + column_offsets[column]
            for row in range(len(rows)):
                if not _table_grid_hidden(item, row, column - 1, row, column):
                    page.draw_line(
                        pymupdf.Point(x, rectangle.y0 + row_offsets[row]),
                        pymupdf.Point(x, rectangle.y0 + row_offsets[row + 1]),
                        color=border_color, width=item.table_inner_border_width, overlay=True,
                    )
        for row in range(1, len(rows)):
            y = rectangle.y0 + row_offsets[row]
            width = item.table_row_border_widths.get(str(row - 1), item.table_inner_border_width)
            for column in range(columns):
                if not _table_grid_hidden(item, row - 1, column, row, column):
                    page.draw_line(
                        pymupdf.Point(rectangle.x0 + column_offsets[column], y),
                        pymupdf.Point(rectangle.x0 + column_offsets[column + 1], y),
                        color=border_color, width=width, overlay=True,
                    )
    for row_text, width in item.table_row_border_widths.items():
        row = int(row_text)
        if 0 <= row < len(rows):
            for y in (rectangle.y0 + row_offsets[row], rectangle.y0 + row_offsets[row + 1]):
                page.draw_line(
                    pymupdf.Point(rectangle.x0, y), pymupdf.Point(rectangle.x1, y),
                    color=border_color, width=width, overlay=True,
                )
    for border_range in item.table_border_ranges:
        left = int(border_range.get("left", 0))
        top = int(border_range.get("top", 0))
        right = int(border_range.get("right", left))
        bottom = int(border_range.get("bottom", top))
        page.draw_rect(
            pymupdf.Rect(
                rectangle.x0 + column_offsets[left],
                rectangle.y0 + row_offsets[top],
                rectangle.x0 + column_offsets[right + 1],
                rectangle.y0 + row_offsets[bottom + 1],
            ),
            color=border_color,
            width=float(border_range.get("width", 1.5)),
            overlay=True,
        )
    if item.table_outer_border_width > 0:
        page.draw_rect(
            rectangle, color=border_color, width=item.table_outer_border_width, overlay=True
        )


def _draw_chart(page: pymupdf.Page, rectangle: pymupdf.Rect, source: PageObject, chart: PageObject) -> None:
    rows = evaluate_table_cells(source.table_cells) if source.table_cells else evaluate_table(source.text)
    if chart.chart_data_orientation == "rows" and rows:
        width = max(len(row) for row in rows)
        padded = [row + [""] * (width - len(row)) for row in rows]
        rows = [list(column) for column in zip(*padded)]
    columns = max((len(row) for row in rows), default=1)
    first_is_header = bool(rows and any(
        value and not value.replace(",", ".").replace("-", "", 1).isdigit()
        for value in rows[0]
    ))
    selected_indices = chart.chart_series_indices or [chart.chart_series_index]
    selected_indices = list(dict.fromkeys(
        min(max(0, index), columns - 1) for index in selected_indices
    ))
    if chart.fill == "pie":
        selected_indices = selected_indices[:1]
    series: list[tuple[str, list[tuple[str, float]]]] = []
    data_rows = rows[1:] if first_is_header else rows
    for series_index in selected_indices:
        header = rows[0][series_index] if first_is_header and series_index < len(rows[0]) else ""
        entries: list[tuple[str, float]] = []
        for index, row in enumerate(data_rows):
            if not row:
                continue
            try:
                value = float(row[series_index].replace(",", "."))
            except (ValueError, IndexError):
                continue
            label = (row[0] if series_index != 0 else "") or str(index + 1)
            entries.append((label, value))
        if entries:
            series.append((header, entries))
    if not series:
        page.insert_textbox(rectangle, "Aucune donnée numérique", fontsize=10, align=1, overlay=True)
        return
    colors = ((0.14, 0.41, 0.69), (0.91, 0.39, 0.18), (0.27, 0.64, 0.49), (0.94, 0.72, 0.22), (0.53, 0.36, 0.71))
    top = rectangle.y0
    if chart.chart_title:
        page.insert_textbox(
            pymupdf.Rect(rectangle.x0, top, rectangle.x1, top + 18),
            chart.chart_title, fontsize=10, align=1, overlay=True,
        )
        top += 18
    if chart.fill == "pie":
        _series_name, entries = series[0]
        labels = [label for label, _value in entries]
        values = [value for _label, value in entries]
        total = sum(abs(value) for value in values) or 1
        legend_width = rectangle.width * 0.32 if chart.chart_show_legend else 0
        center = pymupdf.Point(
            rectangle.x0 + (rectangle.width - legend_width) / 2,
            top + (rectangle.y1 - top) / 2,
        )
        radius = min(rectangle.width - legend_width, rectangle.y1 - top) * 0.36
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
            if chart.chart_show_legend:
                legend = labels[index]
                if chart.chart_show_values:
                    legend += f" — {value:g}"
                page.insert_text(
                    pymupdf.Point(rectangle.x1 - legend_width + 6, top + 12 + index * 14),
                    legend, fontsize=7, overlay=True,
                )
            angle += sweep
    elif chart.fill == "line":
        categories = series[0][1]
        maximum = max(
            (abs(value) for _name, entries in series for _label, value in entries),
            default=1,
        ) or 1
        plot_top = top + (14 if chart.chart_show_legend else 0)
        baseline = rectangle.y1 - 18
        step = (rectangle.width - 20) / max(1, len(categories) - 1)
        for series_index, (_name, entries) in enumerate(series):
            points: list[pymupdf.Point] = []
            color = colors[series_index % len(colors)]
            for index, (_label, value) in enumerate(entries):
                point = pymupdf.Point(
                    rectangle.x0 + 10 + index * step,
                    baseline - (baseline - plot_top) * abs(value) / maximum,
                )
                points.append(point)
                page.draw_circle(point, 2.2, color=color, fill=color, overlay=True)
                if chart.chart_show_values:
                    page.insert_text(pymupdf.Point(point.x - 4, point.y - 4), f"{value:g}", fontsize=6, overlay=True)
            if len(points) >= 2:
                shape = page.new_shape()
                shape.draw_polyline(points)
                shape.finish(color=color, width=1.5)
                shape.commit(overlay=True)
        for index, (label, _value) in enumerate(categories):
            center_x = rectangle.x0 + 10 + index * step
            page.insert_textbox(
                pymupdf.Rect(center_x - 24, baseline + 2, center_x + 24, rectangle.y1),
                label[:12], fontsize=7, align=1, overlay=True,
            )
        if chart.chart_show_legend:
            _draw_chart_series_legend(page, rectangle, top, series, colors)
    elif chart.fill == "hbar":
        categories = series[0][1]
        maximum = max(
            (abs(value) for _name, entries in series for _label, value in entries),
            default=1,
        ) or 1
        plot_top = top + (14 if chart.chart_show_legend else 0)
        category_gap = max(10.0, (rectangle.y1 - plot_top - 4) / max(1, len(categories)))
        series_count = max(1, len(series))
        bar_height = max(2.5, category_gap - 4) / series_count
        plot_left = rectangle.x0 + min(60, rectangle.width * 0.24)
        for category_index, (label, _value) in enumerate(categories):
            center_y = plot_top + (category_index + 0.5) * category_gap
            page.insert_textbox(
                pymupdf.Rect(rectangle.x0, center_y - 5, plot_left - 4, center_y + 5),
                label[:12], fontsize=7, align=2, overlay=True,
            )
            for series_index, (_name, entries) in enumerate(series):
                if category_index >= len(entries):
                    continue
                value = entries[category_index][1]
                y0 = center_y - series_count * bar_height / 2 + series_index * bar_height
                x1 = plot_left + (rectangle.x1 - plot_left - 8) * abs(value) / maximum
                color = colors[series_index % len(colors)]
                page.draw_rect(
                    pymupdf.Rect(plot_left, y0, x1, y0 + max(2, bar_height - 1.5)),
                    color=color, fill=color, overlay=True,
                )
                if chart.chart_show_values:
                    page.insert_text(pymupdf.Point(x1 + 2, y0 + 6), f"{value:g}", fontsize=6, overlay=True)
        if chart.chart_show_legend:
            _draw_chart_series_legend(page, rectangle, top, series, colors)
    else:
        categories = series[0][1]
        maximum = max(
            (abs(value) for _name, entries in series for _label, value in entries),
            default=1,
        ) or 1
        gap = rectangle.width / max(1, len(categories))
        series_count = max(1, len(series))
        bar_gap = max(4.0, gap - 10) / series_count
        baseline = rectangle.y1 - 18
        for category_index, (label, _value) in enumerate(categories):
            for series_index, (_name, entries) in enumerate(series):
                if category_index >= len(entries):
                    continue
                value = entries[category_index][1]
                bar_height = (rectangle.y1 - top - 35) * abs(value) / maximum
                left = rectangle.x0 + category_index * gap + 5 + series_index * bar_gap
                bar = pymupdf.Rect(left, baseline - bar_height, left + max(2, bar_gap - 3), baseline)
                color = colors[series_index % len(colors)]
                page.draw_rect(bar, color=color, fill=color, overlay=True)
                if chart.chart_show_values:
                    page.insert_textbox(
                        pymupdf.Rect(bar.x0, bar.y0 - 12, bar.x1, bar.y0),
                        f"{value:g}", fontsize=7, align=1, overlay=True,
                    )
            page.insert_textbox(
                pymupdf.Rect(
                    rectangle.x0 + category_index * gap,
                    baseline + 2,
                    rectangle.x0 + (category_index + 1) * gap,
                    rectangle.y1,
                ),
                label[:12], fontsize=7, align=1, overlay=True,
            )
        if chart.chart_show_legend:
            _draw_chart_series_legend(page, rectangle, top, series, colors)


def _draw_chart_series_legend(
    page: pymupdf.Page,
    rectangle: pymupdf.Rect,
    top: float,
    series: list[tuple[str, list[tuple[str, float]]]],
    colors: tuple[tuple[float, float, float], ...],
) -> None:
    legend_x = rectangle.x0 + 6
    for series_index, (name, _entries) in enumerate(series):
        color = colors[series_index % len(colors)]
        page.draw_rect(
            pymupdf.Rect(legend_x, top + 2, legend_x + 8, top + 10),
            color=color, fill=color, overlay=True,
        )
        label = name or f"Série {series_index + 1}"
        page.insert_text(pymupdf.Point(legend_x + 11, top + 9), label, fontsize=7, overlay=True)
        legend_x += max(50, len(label) * 4 + 22)


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
    bundled_names = {
        "Sans-serif": {"Regular": "DejaVuSans.ttf", "Bold": "DejaVuSans-Bold.ttf", "Italic": "DejaVuSans-Oblique.ttf", "BoldItalic": "DejaVuSans-BoldOblique.ttf"},
        "Serif": {"Regular": "DejaVuSerif.ttf", "Bold": "DejaVuSerif-Bold.ttf", "Italic": "DejaVuSerif-Italic.ttf", "BoldItalic": "DejaVuSerif-BoldItalic.ttf"},
        "Monospace": {"Regular": "DejaVuSansMono.ttf", "Bold": "DejaVuSansMono-Bold.ttf", "Italic": "DejaVuSansMono-Oblique.ttf", "BoldItalic": "DejaVuSansMono-BoldOblique.ttf"},
        "Cursive": {"Regular": "ComicRelief-Regular.ttf", "Bold": "ComicRelief-Bold.ttf", "Italic": "ComicRelief-Regular.ttf", "BoldItalic": "ComicRelief-Bold.ttf"},
        "Manuscrite ancienne": {"Regular": "Z003-MediumItalic.otf", "Bold": "Z003-MediumItalic.otf", "Italic": "Z003-MediumItalic.otf", "BoldItalic": "Z003-MediumItalic.otf"},
        "Inter": {"Regular": "Inter-Regular.ttf", "Bold": "Inter-Bold.ttf", "Italic": "Inter-Italic.ttf", "BoldItalic": "Inter-BoldItalic.ttf"},
        "JetBrains Mono": {"Regular": "JetBrainsMono-Regular.ttf", "Bold": "JetBrainsMono-Bold.ttf", "Italic": "JetBrainsMono-Italic.ttf", "BoldItalic": "JetBrainsMono-BoldItalic.ttf"},
        "Symboles": {"Regular": "DejaVuSans.ttf", "Bold": "DejaVuSans-Bold.ttf", "Italic": "DejaVuSans-Oblique.ttf", "BoldItalic": "DejaVuSans-BoldOblique.ttf"},
        "Flèches": {"Regular": "DejaVuSans.ttf", "Bold": "DejaVuSans-Bold.ttf", "Italic": "DejaVuSans-Oblique.ttf", "BoldItalic": "DejaVuSans-BoldOblique.ttf"},
    }
    bundled_root = Path(__file__).resolve().parents[1] / "assets" / "fonts"
    bundled = bundled_root / bundled_names.get(family, bundled_names["Sans-serif"])[style]
    if bundled.is_file():
        return str(bundled)
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
