from __future__ import annotations

import json
import math
import os
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
    table_cells: list[list[dict[str, str]]] = field(default_factory=list)
    table_outer_border_width: float = 1.5
    table_inner_border_width: float = 0.6
    table_row_border_widths: dict[str, float] = field(default_factory=dict)
    table_merges: list[list[int]] = field(default_factory=list)
    table_border_ranges: list[dict[str, float]] = field(default_factory=list)
    points: list[list[float]] = field(default_factory=list)


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
        page.draw_rect(rectangle, color=_rgb(item.fill), fill=_rgb(item.fill), overlay=True)
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
        compact = length < 55
        label_position = pymupdf.Point(
            item.x + item.width + (item.width / length * 8 if compact and length else 0)
            if compact
            else item.x + item.width / 2 + 3,
            item.y + item.height + (item.height / length * 8 if compact and length else 0)
            if compact
            else item.y + item.height / 2 - 3,
        )
        page.insert_text(
            label_position,
            f"{item.text} mm",
            fontsize=8,
            color=_rgb(item.border_color),
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
            if item.underline or item.strikethrough:
                for text_line in (line.strip() for line in rendered_text.splitlines()):
                    if not text_line:
                        continue
                    for text_rectangle in page.search_for(text_line, clip=rectangle):
                        if item.underline:
                            page.draw_line(
                                text_rectangle.bottom_left,
                                text_rectangle.bottom_right,
                                color=_rgb(item.color), width=0.8, overlay=True,
                            )
                        if item.strikethrough:
                            middle_y = (text_rectangle.y0 + text_rectangle.y1) / 2
                            page.draw_line(
                                pymupdf.Point(text_rectangle.x0, middle_y),
                                pymupdf.Point(text_rectangle.x1, middle_y),
                                color=_rgb(item.color), width=0.8, overlay=True,
                            )
            for link in item.text_links:
                start = max(0, int(link.get("start", 0)))
                end = min(len(rendered_text), int(link.get("end", 0)))
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
    if item.hyperlink.strip():
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
    return len(wrapped_text_lines(text, frame)) <= text_frame_line_capacity(frame)


def text_frame_line_height(frame: PageObject) -> float:
    """Return the text leading used consistently by flow and canvas preview."""
    return max(7.0, frame.font_size * 1.35)


def text_frame_line_capacity(frame: PageObject) -> int:
    """Return how many complete lines are visible inside a text frame."""
    return max(1, int((abs(frame.height) - 8) / text_frame_line_height(frame)))


def wrapped_text_lines(text: str, frame: PageObject) -> list[str]:
    """Wrap text in page units so flow and on-screen rendering cannot diverge."""
    available_width = max(4.0, abs(frame.width) - 2 * TEXT_FRAME_HORIZONTAL_PADDING)
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current_words: list[str] = []
        current_width = 0.0
        space_width = _text_flow_character_width(
            frame.font_family, frame.font_size, frame.bold, frame.italic, " "
        )
        for word in words:
            word_width = _text_flow_text_width(
                frame.font_family, frame.font_size, frame.bold, frame.italic, word
            )
            candidate_width = current_width + (space_width if current_words else 0) + word_width
            if current_words and candidate_width > available_width:
                lines.append(" ".join(current_words))
                current_words = []
                current_width = 0.0
            if word_width <= available_width:
                current_words.append(word)
                current_width = word_width if len(current_words) == 1 else candidate_width
                continue
            if current_words:
                lines.append(" ".join(current_words))
                current_words = []
                current_width = 0.0
            fragment = ""
            fragment_width = 0.0
            for character in word:
                character_width = _text_flow_character_width(
                    frame.font_family,
                    frame.font_size,
                    frame.bold,
                    frame.italic,
                    character,
                )
                if fragment and fragment_width + character_width > available_width:
                    lines.append(fragment)
                    fragment = character
                    fragment_width = character_width
                else:
                    fragment += character
                    fragment_width += character_width
            if fragment:
                current_words = [fragment]
                current_width = fragment_width
        if current_words:
            lines.append(" ".join(current_words))
    return lines


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
    row_height = rectangle.height / len(rows)
    column_width = rectangle.width / columns
    for row_index, row in enumerate(rows):
        for column_index in range(columns):
            merge = _table_merge_for_cell(item, row_index, column_index)
            if merge and (row_index, column_index) != (merge[0], merge[1]):
                continue
            row_span, column_span = (merge[2], merge[3]) if merge else (1, 1)
            cell = pymupdf.Rect(
                rectangle.x0 + column_index * column_width,
                rectangle.y0 + row_index * row_height,
                rectangle.x0 + (column_index + column_span) * column_width,
                rectangle.y0 + (row_index + row_span) * row_height,
            )
            value = row[column_index] if column_index < len(row) else ""
            metadata = (
                item.table_cells[row_index][column_index]
                if item.table_cells and row_index < len(item.table_cells)
                and column_index < len(item.table_cells[row_index])
                else {}
            )
            image_path = metadata.get("image_path", "")
            horizontal_align = metadata.get("horizontal_align", "left")
            vertical_align = metadata.get("vertical_align", "top")
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
            line_count = max(1, value.count("\n") + 1)
            estimated_height = line_count * item.font_size * 1.2
            if vertical_align == "middle":
                text_cell.y0 += max(0, (text_cell.height - estimated_height) / 2)
            elif vertical_align == "bottom":
                text_cell.y0 += max(0, text_cell.height - estimated_height)
            page.insert_textbox(
                text_cell, value, fontsize=item.font_size,
                align={"left": 0, "center": 1, "right": 2}.get(horizontal_align, 0),
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
            x = rectangle.x0 + column * column_width
            for row in range(len(rows)):
                if not _table_grid_hidden(item, row, column - 1, row, column):
                    page.draw_line(
                        pymupdf.Point(x, rectangle.y0 + row * row_height),
                        pymupdf.Point(x, rectangle.y0 + (row + 1) * row_height),
                        color=border_color, width=item.table_inner_border_width, overlay=True,
                    )
        for row in range(1, len(rows)):
            y = rectangle.y0 + row * row_height
            width = item.table_row_border_widths.get(str(row - 1), item.table_inner_border_width)
            for column in range(columns):
                if not _table_grid_hidden(item, row - 1, column, row, column):
                    page.draw_line(
                        pymupdf.Point(rectangle.x0 + column * column_width, y),
                        pymupdf.Point(rectangle.x0 + (column + 1) * column_width, y),
                        color=border_color, width=width, overlay=True,
                    )
    for row_text, width in item.table_row_border_widths.items():
        row = int(row_text)
        if 0 <= row < len(rows):
            for y in (rectangle.y0 + row * row_height, rectangle.y0 + (row + 1) * row_height):
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
                rectangle.x0 + left * column_width,
                rectangle.y0 + top * row_height,
                rectangle.x0 + (right + 1) * column_width,
                rectangle.y0 + (bottom + 1) * row_height,
            ),
            color=border_color,
            width=float(border_range.get("width", 1.5)),
            overlay=True,
        )
    if item.table_outer_border_width > 0:
        page.draw_rect(
            rectangle, color=border_color, width=item.table_outer_border_width, overlay=True
        )


def _draw_chart(page: pymupdf.Page, rectangle: pymupdf.Rect, source: PageObject, chart_type: str) -> None:
    rows = evaluate_table_cells(source.table_cells) if source.table_cells else evaluate_table(source.text)
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
