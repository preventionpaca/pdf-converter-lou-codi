from __future__ import annotations

import copy
import difflib
import io
import math
import re
import shutil
import subprocess
import sys
import tempfile
import tkinter as tk
import unicodedata
import uuid
import webbrowser
from html.parser import HTMLParser
from itertools import pairwise
from pathlib import Path
from tkinter import messagebox, ttk
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

import pymupdf
from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageGrab, ImageOps, ImageTk

from ..i18n import settings_path, translate_widget_tree
from ..paths import downloads_directory, module_output_directory
from ..services.canvas_document import (
    A4_HEIGHT,
    A4_WIDTH,
    FLOW_BREAK_TOKEN,
    TEXT_FRAME_HORIZONTAL_PADDING,
    TEXT_FRAME_VERTICAL_PADDING,
    CanvasDocument,
    PageObject,
    append_canvas_document,
    export_canvas_pdf,
    flowed_text_context,
    fitted_table_cell_text,
    flowed_text_for_object,
    pages_for_object,
    resolve_dynamic_text,
    table_cell_colors,
    table_grid_offsets,
    text_frame_line_capacity,
    text_frame_line_height,
    text_frame_horizontal_inset,
    text_frame_vertical_inset,
    wrapped_text_lines,
    wrapped_text_ranges,
    _font_file,
)
from ..services.font_catalog import (
    bundled_fonts,
    closest_family,
    install_user_fonts,
    installed_families,
    normalize_font_name,
    refresh_font_catalog,
)
from ..services.docx_canvas import export_editable_docx
from ..services.docx_import import import_docx_as_canvas
from ..services.destinations import (
    document_destination,
    favorite_destinations,
    set_toolbar_size,
    toolbar_size,
)
from ..services.geometry import (
    Segment,
    angle_at_vertex,
    angle_between_segments,
    chamfer_segments,
    closest_point_on_segment,
    hatch_segments,
    join_segments,
    line_intersection,
    point_to_segment_distance,
    project_point_onto_line,
    reflect_point_across_line,
    segment_intersection,
    split_at_intersection,
    split_closed_polyline_by_polyline,
    split_closed_polyline_by_segment,
    split_segment_by_closed_polyline,
)
from ..services.table_formulas import evaluate_table, evaluate_table_cells
from ..system import open_path
from .input_dialogs import ask_number, ask_table_size, ask_text, choose_color, pick_symbol
from .destination_settings import configure_document_destinations
from .directory_picker import choose_save_path
from .pdf_picker import choose_documents
from .windowing import center_window, make_modal, maximize_window

NAVY = "#193B66"
BACKGROUND = "#F0F4F9"
BUILTIN_FONT_FAMILIES = (
    "Sans-serif", "Serif", "Monospace", "Cursive", "Manuscrite ancienne",
    "Inter", "JetBrains Mono", "Symboles",
)


def available_font_families() -> tuple[str, ...]:
    """Return one alphabetic list combining aliases and actual local fonts."""
    names = {name.casefold(): name for name in installed_families()}
    for name in BUILTIN_FONT_FAMILIES:
        names.setdefault(name.casefold(), name)
    return tuple(sorted(names.values(), key=str.casefold))


def safe_pillow_color(value: object, fallback: str, *, allow_transparent: bool = False) -> str:
    """Return a Pillow-compatible colour without trusting imported rich-text data."""
    candidate = str(value or "").strip()
    if allow_transparent and candidate.lower() in {"", "none", "transparent"}:
        return ""
    try:
        ImageColor.getrgb(candidate)
    except (TypeError, ValueError):
        return fallback
    return candidate


def safe_number(value: object, fallback: float, *, minimum: float | None = None) -> float:
    """Coerce values loaded from old/imported documents to a finite number."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = fallback
    if not math.isfinite(number):
        number = fallback
    return max(minimum, number) if minimum is not None else number


def safe_text_offset(value: object, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def inline_editor_font_size(font_size: object, zoom: float) -> int:
    """Return a Tk pixel size matching the Pillow canvas preview."""
    pixels = max(7, round(safe_number(font_size, 12.0, minimum=1.0) * zoom))
    # Tk interprets positive sizes as typographic points and negative sizes as
    # pixels.  The final canvas preview already renders in pixels.
    return -pixels


def inline_editor_padding(zoom: float) -> tuple[int, int]:
    """Return the same horizontal and vertical insets as the final preview."""
    return (
        max(0, round(TEXT_FRAME_HORIZONTAL_PADDING * zoom)),
        max(0, round(TEXT_FRAME_VERTICAL_PADDING * zoom)),
    )


def _slice_text_ranges(
    ranges: list[dict[str, object]], start: int, length: int
) -> list[dict[str, object]]:
    """Return text metadata overlapping a displayed linked-frame segment."""
    end = start + length
    sliced: list[dict[str, object]] = []
    for run in ranges:
        run_start = safe_text_offset(run.get("start"))
        run_end = safe_text_offset(run.get("end"))
        overlap_start = max(start, run_start)
        overlap_end = min(end, run_end)
        if overlap_end > overlap_start:
            sliced.append(
                {**run, "start": overlap_start - start, "end": overlap_end - start}
            )
    return sliced


def _replace_text_ranges(
    ranges: list[dict[str, object]],
    start: int,
    old_length: int,
    replacement: list[dict[str, object]],
    new_length: int,
) -> list[dict[str, object]]:
    """Replace metadata for one linked-frame segment and rebase later ranges."""
    end = start + old_length
    delta = new_length - old_length
    result: list[dict[str, object]] = []
    for run in ranges:
        run_start = safe_text_offset(run.get("start"))
        run_end = safe_text_offset(run.get("end"))
        if run_end <= start:
            result.append(copy.deepcopy(run))
        elif run_start >= end:
            result.append({**run, "start": run_start + delta, "end": run_end + delta})
        else:
            if run_start < start:
                result.append({**run, "end": start})
            if run_end > end:
                result.append(
                    {**run, "start": start + new_length, "end": run_end + delta}
                )
    result.extend(
        {
            **run,
            "start": start + safe_text_offset(run.get("start")),
            "end": start + safe_text_offset(run.get("end")),
        }
        for run in replacement
        if safe_text_offset(run.get("end")) > safe_text_offset(run.get("start"))
    )
    return sorted(
        result,
        key=lambda run: (
            safe_text_offset(run.get("start")),
            safe_text_offset(run.get("end")),
        ),
    )


def proportional_resize(
    old_width: float,
    old_height: float,
    proposed_width: float,
    proposed_height: float,
    *,
    minimum: float = 20.0,
) -> tuple[float, float]:
    """Constrain a diagonal resize to the object's original proportions."""
    if old_width <= 0 or old_height <= 0:
        return max(minimum, proposed_width), max(minimum, proposed_height)
    width_scale = proposed_width / old_width
    height_scale = proposed_height / old_height
    scale = width_scale if abs(width_scale - 1.0) >= abs(height_scale - 1.0) else height_scale
    scale = max(minimum / old_width, minimum / old_height, scale)
    return old_width * scale, old_height * scale


def table_cell_editor_size(
    cell_width: float,
    cell_height: float,
    page_width: float,
    page_height: float,
) -> tuple[float, float]:
    """Keep cell wrapping stable between preview and editing."""
    return (
        min(max(60.0, cell_width), page_width),
        min(max(35.0, cell_height), page_height * 0.45),
    )


def stable_table_height_after_cell_edit(
    current_height: float, row_count: int
) -> float:
    """Keep one verbose cell from expanding every row in an imported table."""
    return max(current_height, max(1, row_count) * 24.0)


class RichClipboardHTMLParser(HTMLParser):
    """Extract editable text and character styles from office HTML clipboard data."""

    _blocks = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.styles: list[dict[str, object]] = []
        self._length = 0
        self._stack: list[dict[str, object]] = [{}]
        self._class_styles: dict[str, dict[str, object]] = {}
        self._inside_style = False
        self._style_source: list[str] = []
        self._ignored_depth = 0

    @staticmethod
    def _css_style(css: str) -> dict[str, object]:
        declarations = {
            name.strip().lower(): value.strip()
            for declaration in css.split(";")
            if ":" in declaration
            for name, value in [declaration.split(":", 1)]
        }
        style: dict[str, object] = {}
        weight = declarations.get("font-weight", "").lower()
        if weight == "bold" or (weight.isdigit() and int(weight) >= 600):
            style["bold"] = True
        if declarations.get("font-style", "").lower() in {"italic", "oblique"}:
            style["italic"] = True
        decoration = declarations.get("text-decoration", "").lower()
        if "underline" in decoration:
            style["underline"] = True
        if "line-through" in decoration:
            style["strikethrough"] = True
        family = declarations.get("font-family", "").strip(" '\"").split(",", 1)[0]
        if family:
            style["font_family"] = (
                "Monospace" if "courier" in family.lower() or "mono" in family.lower()
                else "Serif" if "times" in family.lower() or "serif" in family.lower()
                else "Sans-serif"
            )
        size_match = re.match(r"([0-9.]+)\s*pt", declarations.get("font-size", ""))
        if size_match:
            style["font_size"] = max(1.0, float(size_match.group(1)))
        if declarations.get("color"):
            style["color"] = safe_pillow_color(declarations["color"], "#000000")
        background = declarations.get("background-color") or declarations.get("background")
        if background:
            style["highlight"] = safe_pillow_color(background, "", allow_transparent=True)
        return style

    def _read_stylesheet(self) -> None:
        source = "".join(self._style_source)
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", source):
            style = self._css_style(body)
            if not style:
                continue
            for class_name in re.findall(r"\.([A-Za-z_][\w-]*)", selector):
                self._class_styles.setdefault(class_name, {}).update(style)

    def _newline(self) -> None:
        if self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append("\n")
            self._length += 1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "style":
            self._inside_style = True
            self._style_source = []
            return
        if tag in {"title", "script"}:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            self._ignored_depth += 1
            return
        if tag in self._blocks:
            self._newline()
        if tag == "li":
            self.parts.append("• ")
            self._length += 2
        if tag == "br":
            self._newline()
        style = dict(self._stack[-1])
        if tag in {"b", "strong"}:
            style["bold"] = True
        if tag in {"i", "em"}:
            style["italic"] = True
        if tag == "u":
            style["underline"] = True
        if tag in {"s", "strike", "del"}:
            style["strikethrough"] = True
        attributes = {name.lower(): value or "" for name, value in attrs}
        css = attributes.get("style", "")
        if "mso-list:ignore" in css.replace(" ", "").lower():
            self._ignored_depth = 1
            return
        for class_name in attributes.get("class", "").split():
            style.update(self._class_styles.get(class_name, {}))
        style.update(self._css_style(css))
        self._stack.append(style)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "style":
            self._inside_style = False
            self._read_stylesheet()
            return
        if self._ignored_depth:
            self._ignored_depth -= 1
            return
        if len(self._stack) > 1:
            self._stack.pop()
        if tag in self._blocks:
            self._newline()

    def handle_data(self, data: str) -> None:
        if self._inside_style:
            self._style_source.append(data)
            return
        if self._ignored_depth:
            return
        if not data.strip() and ("\n" in data or "\r" in data):
            return
        value = normalize_external_text(data)
        if not value:
            return
        start = self._length
        self.parts.append(value)
        self._length += len(value)
        style = self._stack[-1]
        if style:
            run = {"start": start, "end": self._length, **style}
            if self.styles and self.styles[-1]["end"] == start and {
                key: value for key, value in self.styles[-1].items() if key not in {"start", "end"}
            } == style:
                self.styles[-1]["end"] = self._length
            else:
                self.styles.append(run)


def parse_rich_clipboard_html(value: str) -> tuple[str, list[dict[str, object]]]:
    value = extract_clipboard_html(value)
    parser = RichClipboardHTMLParser()
    parser.feed(value)
    text = "".join(parser.parts)
    leading = len(text) - len(text.lstrip("\n"))
    text = text.strip("\n")
    styles = [
        {
            **run,
            "start": max(0, int(run["start"]) - leading),
            "end": min(len(text), int(run["end"]) - leading),
        }
        for run in parser.styles
        if int(run["end"]) - leading > 0 and int(run["start"]) - leading < len(text)
    ]
    return text, [run for run in styles if run["end"] > run["start"]]


def extract_clipboard_html(value: str) -> str:
    """Remove the CF_HTML transport header used by Word and some Office ports."""
    match_start = re.search(r"(?im)^StartHTML:\s*(\d+)", value)
    match_end = re.search(r"(?im)^EndHTML:\s*(\d+)", value)
    if match_start:
        start = int(match_start.group(1))
        end = int(match_end.group(1)) if match_end else len(value)
        if 0 <= start < end <= len(value):
            return value[start:end]
    fragment_start = value.find("<!--StartFragment-->")
    fragment_end = value.find("<!--EndFragment-->")
    if fragment_start >= 0 and fragment_end > fragment_start:
        return value[
            fragment_start + len("<!--StartFragment-->") : fragment_end
        ]
    html_start = value.lower().find("<html")
    return value[html_start:] if html_start >= 0 else value


def rich_clipboard_matches_plain(rich_text: str, plain_text: str) -> bool:
    """Ensure HTML and plain clipboard targets describe the same document."""
    compact = lambda text: re.sub(r"[\W_]+", "", text, flags=re.UNICODE).casefold()
    rich_compact = compact(rich_text)
    plain_compact = compact(plain_text)
    if not rich_compact or not plain_compact:
        return False
    if rich_compact == plain_compact:
        return True
    # Office suites encode bullets and paragraph separators differently in
    # text/plain and text/html.  Keep the rich target when their actual words
    # still describe the same clipboard content.
    shorter, longer = sorted((rich_compact, plain_compact), key=len)
    if len(shorter) >= 12 and shorter in longer and len(shorter) / len(longer) >= 0.85:
        return True
    return difflib.SequenceMatcher(None, rich_compact, plain_compact).ratio() >= 0.9


def normalize_external_text(value: str) -> str:
    """Turn office/PDF clipboard separators into ordinary editable text."""
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("\v", "\n").replace("\f", "\n")
    value = value.replace("\u2028", "\n").replace("\u2029", "\n")
    value = value.replace("\u00a0", " ")
    value = value.translate(
        {
            ord("\uf0b7"): "•",
            ord("\uf0a7"): "▪",
            ord("\uf0d8"): "➢",
        }
    )
    value = unicodedata.normalize("NFC", value)
    return "".join(
        character
        for character in value
        if character in "\n\t" or not unicodedata.category(character).startswith("C")
    )


def normalize_rich_plain_fallback(value: str) -> str:
    """Keep lists readable when an Office clipboard exposes no usable HTML."""
    cleaned: list[str] = []
    marker = re.compile(r"^([\t ]*)[·•▪◦‣⁃●○■□◆◇➢➤]+[\t ]*")
    for line in normalize_external_text(value).split("\n"):
        match = marker.match(line)
        if match:
            line = f"{match.group(1)}• {line[match.end():]}"
        cleaned.append(line)
    return "\n".join(cleaned)


def normalize_plain_paste(value: str) -> str:
    """Produce genuinely unformatted text, without office list indentation."""
    value = normalize_external_text(value)
    cleaned: list[str] = []
    for line in value.split("\n"):
        line = line.replace("\uf0b7", "").replace("\uf0a7", "")
        line = re.sub(r"^[\t ]*[•·▪◦‣⁃●○■□◆◇➢➤]+[\t ]*", "", line)
        cleaned.append(line.lstrip("\t "))
    return "\n".join(cleaned)


def draw_styled_rectangle(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    color: str,
    width: int,
    style: str,
) -> None:
    """Draw a solid, dashed or dotted rectangular border on a Pillow canvas."""
    if style == "solid":
        draw.rectangle(box, outline=color, width=width)
        return
    left, top, right, bottom = box
    dash = max(width, width * (1 if style == "dotted" else 4))
    gap = max(width * 2, dash)
    for start, end in (
        ((left, top), (right, top)),
        ((right, top), (right, bottom)),
        ((right, bottom), (left, bottom)),
        ((left, bottom), (left, top)),
    ):
        length = math.hypot(end[0] - start[0], end[1] - start[1])
        if length <= 0:
            continue
        unit_x = (end[0] - start[0]) / length
        unit_y = (end[1] - start[1]) / length
        position = 0.0
        while position < length:
            segment_end = min(length, position + dash)
            draw.line(
                (
                    start[0] + unit_x * position,
                    start[1] + unit_y * position,
                    start[0] + unit_x * segment_end,
                    start[1] + unit_y * segment_end,
                ),
                fill=color,
                width=width,
            )
            position += dash + gap


def parse_tabular_clipboard(value: str) -> list[list[dict[str, str]]]:
    """Recognise a spreadsheet clipboard as editable Lou Còdi cells."""
    normalized = normalize_external_text(value).strip("\n")
    if not normalized or "\t" not in normalized:
        return []
    rows = [line.split("\t") for line in normalized.split("\n")]
    columns = max((len(row) for row in rows), default=0)
    if columns < 2:
        return []
    return [
        [{"text": row[column] if column < len(row) else ""} for column in range(columns)]
        for row in rows
    ]


class SpreadsheetClipboardHTMLParser(HTMLParser):
    """Read the editable grid and common Office styles from clipboard HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[dict[str, object]]] = []
        self.column_widths: list[float] = []
        self.row_heights: list[float] = []
        self._row: list[dict[str, object]] | None = None
        self._cell: dict[str, object] | None = None
        self._parts: list[str] = []
        self._cell_width = 0.0
        self._row_height = 0.0
        self._in_style = False
        self._style_parts: list[str] = []
        self._class_styles: dict[str, str] = {}

    def _register_stylesheet(self) -> None:
        css = "".join(self._style_parts)
        for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            for selector in selectors.split(","):
                match = re.search(r"\.([\w-]+)\s*$", selector.strip())
                if match:
                    self._class_styles[match.group(1)] = body

    @staticmethod
    def _length(value: str) -> float:
        match = re.search(r"([0-9.]+)\s*(px|pt)?", value, re.I)
        if not match:
            return 0.0
        number = float(match.group(1))
        return number * 0.75 if (match.group(2) or "px").lower() == "px" else number

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name.lower(): value or "" for name, value in attrs}
        if tag.lower() == "style":
            self._in_style = True
            self._style_parts = []
            return
        class_style = ";".join(
            self._class_styles.get(name, "")
            for name in attributes.get("class", "").split()
        )
        style_source = f"{class_style};{attributes.get('style', '')}"
        declarations = {
            name.strip().lower(): value.strip()
            for declaration in style_source.split(";") if ":" in declaration
            for name, value in [declaration.split(":", 1)]
        }
        if tag.lower() == "tr":
            self._row = []
            self._row_height = self._length(declarations.get("height", attributes.get("height", "")))
        elif tag.lower() in {"td", "th"} and self._row is not None:
            self._parts = []
            self._cell_width = self._length(declarations.get("width", attributes.get("width", "")))
            formula = next((attributes.get(name, "") for name in (
                "data-formula", "data-sheets-formula", "formula", "x:fmla",
                "data-fmla", "data-cell-formula",
            ) if attributes.get(name)), "")
            formula = formula or declarations.get("mso-formula", "")
            if formula.startswith("of:="):
                formula = formula[3:]
            cell: dict[str, object] = {"text": formula}
            rich = RichClipboardHTMLParser._css_style(style_source)
            cell.update({key: value for key, value in rich.items() if key != "highlight"})
            background = declarations.get("background-color") or declarations.get("background")
            if background:
                cell["fill"] = safe_pillow_color(background, "#FFFFFF")
            align = declarations.get("text-align", attributes.get("align", "")).lower()
            if align in {"left", "center", "right"}:
                cell["horizontal_align"] = align
            vertical = declarations.get("vertical-align", attributes.get("valign", "")).lower()
            if vertical in {"top", "middle", "bottom"}:
                cell["vertical_align"] = vertical
            border = declarations.get("border", "") or " ".join(
                declarations.get(side, "")
                for side in ("border-top", "border-right", "border-bottom", "border-left")
            )
            border_width = self._length(border)
            if border_width:
                cell["border_width"] = border_width
            color_match = re.search(r"(#[0-9a-f]{3,8}|rgb\([^)]*\))", border, re.I)
            if color_match:
                cell["border_color"] = safe_pillow_color(color_match.group(1), "#72879C")
            self._cell = cell
        elif tag.lower() == "br" and self._cell is not None:
            self._parts.append("\n")
        elif self._cell is not None and tag.lower() in {"b", "strong"}:
            self._cell["bold"] = True
        elif self._cell is not None and tag.lower() in {"i", "em"}:
            self._cell["italic"] = True
        elif self._cell is not None and tag.lower() == "u":
            self._cell["underline"] = True
        elif self._cell is not None and tag.lower() == "font" and attributes.get("color"):
            self._cell["color"] = safe_pillow_color(attributes["color"], "#000000")

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self._style_parts.append(data)
        elif self._cell is not None:
            self._parts.append(normalize_external_text(data))

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "style":
            self._in_style = False
            self._register_stylesheet()
        elif tag.lower() in {"td", "th"} and self._cell is not None and self._row is not None:
            if not str(self._cell.get("text", "")).startswith("="):
                self._cell["text"] = "".join(self._parts).strip()
            self._row.append(self._cell)
            column = len(self._row) - 1
            while len(self.column_widths) <= column:
                self.column_widths.append(0.0)
            self.column_widths[column] = max(self.column_widths[column], self._cell_width)
            self._cell = None
        elif tag.lower() == "tr" and self._row is not None:
            self.rows.append(self._row)
            self.row_heights.append(self._row_height)
            self._row = None


def parse_tabular_clipboard_html(
    value: str,
) -> tuple[list[list[dict[str, object]]], list[float], list[float]]:
    parser = SpreadsheetClipboardHTMLParser()
    parser.feed(extract_clipboard_html(value))
    columns = max((len(row) for row in parser.rows), default=0)
    if not parser.rows or columns < 2:
        return [], [], []
    for row in parser.rows:
        row.extend({"text": ""} for _ in range(columns - len(row)))
    return parser.rows, parser.column_widths, parser.row_heights


def objects_bounds(objects: list[PageObject]) -> tuple[float, float, float, float]:
    """Return the left, top, width and height of an object assembly."""
    if not objects:
        return 0.0, 0.0, 0.0, 0.0
    left = min(min(item.x, item.x + item.width) for item in objects)
    top = min(min(item.y, item.y + item.height) for item in objects)
    right = max(max(item.x, item.x + item.width) for item in objects)
    bottom = max(max(item.y, item.y + item.height) for item in objects)
    return left, top, right - left, bottom - top


def rotated_rectangle_points(item: PageObject) -> list[tuple[float, float]]:
    """Return an object's four corners after rotation around its centre."""
    center_x = item.x + item.width / 2
    center_y = item.y + item.height / 2
    angle = math.radians(float(item.rotation) % 360)
    cosine, sine = math.cos(angle), math.sin(angle)
    points: list[tuple[float, float]] = []
    for x, y in (
        (item.x, item.y),
        (item.x + item.width, item.y),
        (item.x + item.width, item.y + item.height),
        (item.x, item.y + item.height),
    ):
        offset_x, offset_y = x - center_x, y - center_y
        points.append((
            center_x + offset_x * cosine - offset_y * sine,
            center_y + offset_x * sine + offset_y * cosine,
        ))
    return points


def snapped_rotation_delta(start_angle: float, current_angle: float, step: float) -> float:
    """Return the shortest signed rotation, snapped to the configured angular step."""
    delta = (current_angle - start_angle + 180.0) % 360.0 - 180.0
    increment = max(0.1, abs(step))
    return round(delta / increment) * increment


def rotation_step_for_objects(objects: list[PageObject], configured_step: float) -> float:
    """Keep layout-rich objects on quarter turns while geometry remains freely stepped."""
    if any(item.kind in {"table", "chart", "mask"} for item in objects):
        return 90.0
    return max(0.1, abs(configured_step))


TEXT_STYLE_KEYS = {"bold", "italic", "underline", "strikethrough", "color", "highlight", "font_family", "font_size"}


def text_style_at(item: PageObject, position: int) -> dict[str, object]:
    style: dict[str, object] = {
        "bold": item.bold,
        "italic": item.italic,
        "underline": item.underline,
        "strikethrough": item.strikethrough,
        "color": item.color,
        "highlight": "",
        "font_family": item.font_family,
        "font_size": item.font_size,
    }
    for run in item.text_styles:
        if int(run.get("start", 0)) <= position < int(run.get("end", 0)):
            for key in TEXT_STYLE_KEYS:
                if key in run:
                    style[key] = run[key]
    return style


def resolved_text_styles(item: PageObject, text_length: int) -> list[dict[str, object]]:
    """Resolve overlapping rich styles once for a complete preview pass."""
    base = text_style_at(item, -1)
    lookup = [base] * max(0, text_length)
    for run in item.text_styles:
        try:
            start = max(0, min(text_length, int(run.get("start", 0))))
            end = max(start, min(text_length, int(run.get("end", 0))))
        except (TypeError, ValueError):
            continue
        update = {key: value for key, value in run.items() if key in TEXT_STYLE_KEYS}
        for position in range(start, end):
            merged = dict(lookup[position])
            merged.update(update)
            lookup[position] = merged
    return lookup


def paragraph_alignment_at(item: PageObject, position: int) -> str:
    """Return the alignment applied to the paragraph containing a character."""
    for run in reversed(item.paragraph_alignments):
        if int(run.get("start", 0)) <= position < int(run.get("end", 0)):
            value = str(run.get("align", item.align))
            if value in {"left", "center", "right", "justify"}:
                return value
    return item.align


def aligned_text_x(frame_width: float, text_width: float, padding: float, align: str) -> float:
    """Place a rendered line using its real glyph width, not an approximate font."""
    if align in {"left", "justify"}:
        return padding
    if align == "center":
        return (frame_width - text_width) / 2
    return frame_width - text_width - padding


def polygon_area(points: list[tuple[float, float]]) -> float:
    """Return the unsigned area of a closed or open polygon point sequence."""
    if len(points) < 3:
        return 0.0
    closed = points if points[0] == points[-1] else [*points, points[0]]
    return abs(sum(
        first[0] * second[1] - second[0] * first[1]
        for first, second in pairwise(closed)
    )) / 2


def dimension_line_geometry(
    first: tuple[float, float],
    second: tuple[float, float],
    placement: tuple[float, float],
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Project a parallel dimension line through the requested placement point."""
    dx, dy = second[0] - first[0], second[1] - first[1]
    length = math.hypot(dx, dy)
    if length <= 1e-9:
        return None
    normal_x, normal_y = -dy / length, dx / length
    offset = (
        (placement[0] - first[0]) * normal_x
        + (placement[1] - first[1]) * normal_y
    )
    return (
        (first[0] + normal_x * offset, first[1] + normal_y * offset),
        (second[0] + normal_x * offset, second[1] + normal_y * offset),
    )


def dimension_label_layout(
    start: tuple[float, float], end: tuple[float, float], gap: float = 12.0
) -> tuple[float, float, float]:
    """Return a readable label position and angle above a dimension line."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= 1e-9:
        return start[0], start[1] - gap, 0.0
    normal_x, normal_y = -dy / length, dx / length
    if normal_y > 0:
        normal_x, normal_y = -normal_x, -normal_y
    angle = -math.degrees(math.atan2(dy, dx))
    if angle > 90:
        angle -= 180
    elif angle < -90:
        angle += 180
    return (
        (start[0] + end[0]) / 2 + normal_x * gap,
        (start[1] + end[1]) / 2 + normal_y * gap,
        angle,
    )


def resized_circle_diameter(
    old_diameter: float, delta_x: float, delta_y: float
) -> float:
    """Resize a circle from the pointer axis carrying the clearest user intent."""
    delta = delta_x if abs(delta_x) >= abs(delta_y) else delta_y
    return max(20.0, old_diameter + delta)


def point_hits_rotation_handle(
    pointer: tuple[float, float], handle: tuple[float, float], radius: float = 15.0
) -> bool:
    """Use a generous hit area so the rotation handle remains easy to grab."""
    return math.dist(pointer, handle) <= radius


def spreadsheet_column_name(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def transform_object_assembly(
    objects: list[PageObject],
    target_x: float,
    target_y: float,
    target_width: float,
    target_height: float,
) -> None:
    """Move and resize objects while preserving their relative arrangement."""
    old_x, old_y, old_width, old_height = objects_bounds(objects)
    scale_x = target_width / old_width if old_width else 1.0
    scale_y = target_height / old_height if old_height else 1.0
    for item in objects:
        item.x = target_x + (item.x - old_x) * scale_x
        item.y = target_y + (item.y - old_y) * scale_y
        item.width *= scale_x
        item.height *= scale_y
        if item.kind == "polyline":
            item.points = [[point[0] * scale_x, point[1] * scale_y] for point in item.points]


def expanded_group_indices(objects: list[PageObject], selected: set[int]) -> set[int]:
    """Include every member of any assembly touched by the selection."""
    groups = {objects[index].group for index in selected if objects[index].group}
    if not groups:
        return set(selected)
    return set(selected) | {
        index for index, item in enumerate(objects) if item.group and item.group in groups
    }


def edge_coincidence_translation(
    fixed_edge: Segment, moving_edge: Segment
) -> tuple[float, float]:
    """Return the perpendicular translation that puts moving_edge on fixed_edge."""
    fixed_dx = fixed_edge.x2 - fixed_edge.x1
    fixed_dy = fixed_edge.y2 - fixed_edge.y1
    moving_dx = moving_edge.x2 - moving_edge.x1
    moving_dy = moving_edge.y2 - moving_edge.y1
    fixed_length = math.hypot(fixed_dx, fixed_dy)
    moving_length = math.hypot(moving_dx, moving_dy)
    if min(fixed_length, moving_length) <= 1e-8:
        raise ValueError("zero-length edge")
    parallel_error = abs(
        fixed_dx * moving_dy - fixed_dy * moving_dx
    ) / (fixed_length * moving_length)
    if parallel_error > 0.02:
        raise ValueError("edges are not parallel")
    middle = (
        (moving_edge.x1 + moving_edge.x2) / 2,
        (moving_edge.y1 + moving_edge.y2) / 2,
    )
    projection = project_point_onto_line(*middle, fixed_edge)
    return projection[0] - middle[0], projection[1] - middle[1]


def driving_dimension_translation(
    fixed_edge: Segment,
    moving_edge: Segment,
    moving_reference_point: tuple[float, float],
    distance: float,
) -> tuple[float, float, tuple[float, float], tuple[float, float]]:
    """Move a parallel edge to a distance while retaining its current side."""
    fixed_dx = fixed_edge.x2 - fixed_edge.x1
    fixed_dy = fixed_edge.y2 - fixed_edge.y1
    moving_dx = moving_edge.x2 - moving_edge.x1
    moving_dy = moving_edge.y2 - moving_edge.y1
    fixed_length = math.hypot(fixed_dx, fixed_dy)
    moving_length = math.hypot(moving_dx, moving_dy)
    if min(fixed_length, moving_length) <= 1e-8:
        raise ValueError("zero-length edge")
    parallel_error = abs(
        fixed_dx * moving_dy - fixed_dy * moving_dx
    ) / (fixed_length * moving_length)
    if parallel_error > 0.02:
        raise ValueError("edges are not parallel")
    normal_x, normal_y = -fixed_dy / fixed_length, fixed_dx / fixed_length
    origin = (fixed_edge.x1, fixed_edge.y1)
    side_value = (
        (moving_reference_point[0] - origin[0]) * normal_x
        + (moving_reference_point[1] - origin[1]) * normal_y
    )
    side = -1.0 if side_value < 0 else 1.0
    moving_middle = (
        (moving_edge.x1 + moving_edge.x2) / 2,
        (moving_edge.y1 + moving_edge.y2) / 2,
    )
    current_distance = (
        (moving_middle[0] - origin[0]) * normal_x
        + (moving_middle[1] - origin[1]) * normal_y
    )
    displacement = side * distance - current_distance
    delta_x, delta_y = normal_x * displacement, normal_y * displacement
    final_middle = (moving_middle[0] + delta_x, moving_middle[1] + delta_y)
    dimension_start = project_point_onto_line(*final_middle, fixed_edge)
    return delta_x, delta_y, dimension_start, final_middle


def union_axis_aligned_rectangles(
    rectangles: list[tuple[float, float, float, float]],
) -> list[tuple[float, float]]:
    """Return the outside contour of connected axis-aligned rectangles."""
    xs = sorted({coordinate for left, _, right, _ in rectangles for coordinate in (left, right)})
    ys = sorted({coordinate for _, top, _, bottom in rectangles for coordinate in (top, bottom)})
    occupied: set[tuple[int, int]] = set()
    for xi in range(len(xs) - 1):
        for yi in range(len(ys) - 1):
            middle_x = (xs[xi] + xs[xi + 1]) / 2
            middle_y = (ys[yi] + ys[yi + 1]) / 2
            if any(
                left < middle_x < right and top < middle_y < bottom
                for left, top, right, bottom in rectangles
            ):
                occupied.add((xi, yi))
    edges: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for xi, yi in occupied:
        left, right, top, bottom = xs[xi], xs[xi + 1], ys[yi], ys[yi + 1]
        if (xi, yi - 1) not in occupied:
            edges.append(((left, top), (right, top)))
        if (xi + 1, yi) not in occupied:
            edges.append(((right, top), (right, bottom)))
        if (xi, yi + 1) not in occupied:
            edges.append(((right, bottom), (left, bottom)))
        if (xi - 1, yi) not in occupied:
            edges.append(((left, bottom), (left, top)))
    by_start = {start: end for start, end in edges}
    if not by_start:
        raise ValueError("empty union")
    start = min(by_start, key=lambda point: (point[1], point[0]))
    contour = [start]
    cursor = start
    while True:
        cursor = by_start.get(cursor)
        if cursor is None:
            raise ValueError("rectangles are not connected")
        contour.append(cursor)
        if cursor == start:
            break
        if len(contour) > len(edges) + 1:
            raise ValueError("invalid rectangle union")
    if len(contour) != len(edges) + 1:
        raise ValueError("rectangles form more than one contour")
    simplified: list[tuple[float, float]] = []
    for point in contour[:-1]:
        while len(simplified) >= 2:
            a, b = simplified[-2:]
            if (a[0] == b[0] == point[0]) or (a[1] == b[1] == point[1]):
                simplified.pop()
            else:
                break
        simplified.append(point)
    simplified.append(simplified[0])
    return simplified


def revolution_stations(
    outlines: list[list[tuple[float, float]]] | list[tuple[float, float]], axis_y: float
) -> list[tuple[float, float]]:
    """Build ordered axial stations without losing vertical shoulders."""
    if outlines and isinstance(outlines[0], tuple):
        outlines = [outlines]  # type: ignore[list-item]
    fragments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for outline in outlines:  # type: ignore[assignment]
        for start, end in pairwise(outline):
            start_inside, end_inside = start[1] <= axis_y + 1e-6, end[1] <= axis_y + 1e-6
            if not start_inside and not end_inside:
                continue
            clipped_start, clipped_end = start, end
            if start_inside != end_inside:
                ratio = (axis_y - start[1]) / (end[1] - start[1])
                intersection = (
                    start[0] + (end[0] - start[0]) * ratio,
                    axis_y,
                )
                if start_inside:
                    clipped_end = intersection
                else:
                    clipped_start = intersection
            if abs(clipped_start[1] - axis_y) <= 1e-6 and abs(clipped_end[1] - axis_y) <= 1e-6:
                continue
            fragments.append((clipped_start, clipped_end))
    adjacency: dict[tuple[float, float], list[tuple[float, float]]] = {}
    for start, end in fragments:
        adjacency.setdefault(start, []).append(end)
        adjacency.setdefault(end, []).append(start)
    endpoints = [point for point, neighbours in adjacency.items() if len(neighbours) == 1]
    if len(endpoints) < 2:
        raise ValueError("profile has too few stations")
    start = min(endpoints, key=lambda point: point[0])
    path = [start]
    previous: tuple[float, float] | None = None
    current = start
    while True:
        candidates = [point for point in adjacency[current] if point != previous]
        if not candidates:
            break
        following = candidates[0]
        path.append(following)
        previous, current = current, following
    stations = [(x, max(0.0, axis_y - y)) for x, y in path]
    if len(stations) < 2 or max(radius for _x, radius in stations) <= 1e-6:
        raise ValueError("profile has too few stations")
    return stations


def revolution_axis_target(
    outlines: list[list[tuple[float, float]]],
    *,
    full_profile: bool,
    current_axis_y: float,
) -> tuple[float, str]:
    """Return the only safe axis position for a full or half revolution profile."""
    minimum_y = min(y for outline in outlines for _x, y in outline)
    maximum_y = max(y for outline in outlines for _x, y in outline)
    if full_profile:
        return (minimum_y + maximum_y) / 2, "plan de symétrie"
    nearest_boundary = min((minimum_y, maximum_y), key=lambda y: abs(y - current_axis_y))
    return nearest_boundary, "bord de fermeture"


def merge_mirrored_outlines(
    outlines: list[list[tuple[float, float]]], axis_y: float
) -> list[tuple[float, float]]:
    """Join mirrored half profiles while removing their closure lines on the axis."""
    paths: list[list[tuple[float, float]]] = []
    for outline in outlines:
        edges: list[tuple[tuple[float, float], tuple[float, float]]] = []
        for start, end in pairwise(outline):
            if abs(start[1] - axis_y) <= 1e-4 and abs(end[1] - axis_y) <= 1e-4:
                continue
            edges.append((start, end))
        coordinates: dict[tuple[float, float], tuple[float, float]] = {}
        adjacency: dict[tuple[float, float], set[tuple[float, float]]] = {}
        for start, end in edges:
            start_key = (round(start[0], 4), round(start[1], 4))
            end_key = (round(end[0], 4), round(end[1], 4))
            if start_key == end_key:
                continue
            coordinates.setdefault(start_key, start)
            coordinates.setdefault(end_key, end)
            adjacency.setdefault(start_key, set()).add(end_key)
            adjacency.setdefault(end_key, set()).add(start_key)
        endpoints = [key for key, neighbours in adjacency.items() if len(neighbours) == 1]
        if len(endpoints) != 2:
            raise ValueError("a half profile is not an open outside path")
        current = min(endpoints, key=lambda key: coordinates[key][0])
        previous: tuple[float, float] | None = None
        path = [coordinates[current]]
        while True:
            candidates = [key for key in adjacency[current] if key != previous]
            if not candidates:
                break
            following = candidates[0]
            path.append(coordinates[following])
            previous, current = current, following
        if path[0][0] > path[-1][0]:
            path.reverse()
        paths.append(path)
    if len(paths) != 2:
        raise ValueError("two half profiles are required")
    upper, lower = sorted(
        paths,
        key=lambda path: sum(point[1] for point in path) / len(path),
    )
    left_x = (upper[0][0] + lower[0][0]) / 2
    right_x = (upper[-1][0] + lower[-1][0]) / 2
    upper[0] = lower[0] = (left_x, axis_y)
    upper[-1] = lower[-1] = (right_x, axis_y)
    lower_return = list(reversed(lower))
    if math.dist(upper[-1], lower_return[0]) <= 1e-3:
        lower_return.pop(0)
    contour = upper + lower_return
    if math.dist(contour[-1], contour[0]) <= 1e-3:
        contour[-1] = contour[0]
    else:
        contour.append(contour[0])
    return contour


class DocumentEditorWindow(tk.Toplevel):
    """Editeur de pages : PDF original ou A4 blanc, avec objets indépendants."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        template_mode: bool = False,
        project_path: Path | None = None,
    ) -> None:
        super().__init__(parent, class_="Loucodiworkshop")
        self.template_mode = template_mode
        self.title(("Créer un modèle" if template_mode else "Créer un document") + " — Lou Còdi Workshop")
        self.configure(bg=BACKGROUND)
        self.document = CanvasDocument()
        self._saved_document = copy.deepcopy(self.document)
        self._document_tabs: list[dict[str, object]] = []
        self._active_document_tab = 0
        self.project_path: Path | None = None
        self.last_export: Path | None = None
        self.current_page = 0
        self.selected: int | None = None
        self.selected_indices: set[int] = set()
        self.zoom = 1.15
        self.undo_stack: list[CanvasDocument] = []
        self.redo_stack: list[CanvasDocument] = []
        self._background_image: ImageTk.PhotoImage | None = None
        self._overlay_images: list[ImageTk.PhotoImage] = []
        self._text_preview_cache: dict[tuple[object, ...], ImageTk.PhotoImage] = {}
        self._zoom_render_after_id: str | None = None
        self._page_edge_wheel: tuple[int, int, int] | None = None
        self._rendering = False
        self._drag_origin: tuple[float, float, float, float] | None = None
        self._resize_origin: tuple[str, float, float, float, float, float, float] | None = None
        self._assembly_resize_origin: tuple[float, float, float, float, float, float] | None = None
        self._rotation_drag_origin: tuple[float, float, float] | None = None
        self._rotation_drag_delta = 0.0
        self._rotation_drag_before: CanvasDocument | None = None
        self._rotation_preview_applied = False
        self._crop_mode_index: int | None = None
        self._crop_box: list[float] | None = None
        self._crop_drag_edge: str | None = None
        self._vertex_drag_origin: tuple[int, int, list[list[float]]] | None = None
        self._selected_vertex: tuple[int, int] | None = None
        self._marquee_origin: tuple[float, float] | None = None
        self._marquee_initial_selection: set[int] = set()
        self._drag_positions: dict[int, tuple[float, float]] = {}
        self._drag_before: CanvasDocument | None = None
        self._editing_widget: tk.Text | None = None
        self._editing_dialog: tk.Toplevel | None = None
        self._editing_object_id = ""
        self._editing_original_text = ""
        self._editing_style_tags: dict[str, dict[str, object]] = {}
        self._editing_original_styles: list[dict[str, object]] = []
        self._editing_original_align = "left"
        self._editing_original_fill = "#FFFFFF"
        self._editing_original_border_color = "#000000"
        self._editing_original_border_width = 1.0
        self._editing_original_border_style = "solid"
        self._editing_original_paragraph_alignments: list[dict[str, object]] = []
        self._editing_flow_root_id = ""
        self._editing_flow_offset = 0
        self._editing_flow_original_segment = ""
        self._editing_flow_original_links: list[dict[str, object]] = []
        self._editing_flow_local_links: list[dict[str, object]] = []
        self._editing_alignment_tags: dict[str, str] = {}
        self._editing_selection_range: tuple[int, int] | None = None
        self._editing_drag_anchor: str | None = None
        self._editing_text_context_menu: tk.Menu | None = None
        self._inline_font_family_combo: ttk.Combobox | None = None
        self._inline_font_menu: tk.Menu | None = None
        self._editing_table_cell: tuple[int, int] | None = None
        self._editing_table_original: dict[str, str] | None = None
        self._active_table_cell: tuple[str, int, int] | None = None
        self._table_border_range_start: tuple[str, int, int] | None = None
        self._format_clipboard: dict[str, object] | None = None
        self._object_clipboard: list[PageObject] = []
        self.properties_visible = tk.BooleanVar(value=False)
        self.ribbon_visible = tk.BooleanVar(value=True)
        self._pending_text_link_id = ""
        self._last_clicked_index: int | None = None
        self._polyline_points: list[tuple[float, float]] = []
        self._drawing_polyline = False
        self._polyline_raw_cursor: tuple[float, float] | None = None
        self._polyline_axis_index: int | None = None
        self._drawing_line = False
        self._line_points: list[tuple[float, float]] = []
        self._line_raw_cursor: tuple[float, float] | None = None
        self._drawing_triangle = False
        self._triangle_points: list[tuple[float, float]] = []
        self._triangle_right = False
        self._drawing_rectangle = False
        self._rectangle_points: list[tuple[float, float]] = []
        self._rectangle_square = False
        self._drawing_text = False
        self._text_draw_start: tuple[float, float] | None = None
        self._modifier_keys: set[str] = set()
        self._context_menu_visible = False
        self._pdf_font_pick_mode = False
        self._pending_corner_treatment: tuple[int, str, float] | None = None
        self._pending_edge_snap: dict[str, object] | None = None
        self._pending_driving_dimension: dict[str, object] | None = None
        self._placing_work_origin = False
        self._coincident_edge_highlight: Segment | None = None
        self._tool_buttons: list[tk.Widget] = []
        self._last_context_kind: str | None = None
        self.toolbar_size_var = tk.StringVar(value=toolbar_size())
        self._measurement_mode = ""
        self._measurement_points: list[tuple[float, float]] = []
        self._measurement_refs: list[dict[str, object]] = []
        self.write_measurement_var = tk.BooleanVar(value=False)
        self.show_measurement_length_var = tk.BooleanVar(value=False)
        self.measurement_label_vars = {
            "distance": tk.BooleanVar(value=True),
            "angle": tk.BooleanVar(value=False),
            "perimeter": tk.BooleanVar(value=False),
            "area": tk.BooleanVar(value=False),
            "segments": tk.BooleanVar(value=False),
        }
        self.palette_visible_vars = {
            key: tk.BooleanVar(value=key in {"shapes", "measurements", "table", "media"})
            for key in ("shapes", "measurements", "table", "media", "shape_style", "technical", "text_zone_style")
        }
        self.tool_palettes: dict[str, tk.Widget] = {}
        self.palette_positions = {
            "shapes": (10, 10), "measurements": (10, 440),
            "table": (108, 10), "media": (108, 530),
            "shape_style": (454, 10), "technical": (602, 10),
            "text_zone_style": (454, 10),
        }
        self._palette_drag: tuple[str, int, int, int, int] | None = None
        self._last_palette_context: str | None = None
        self._pending_right_triangle: tuple[int, int] | None = None
        self._triangle_property_originals: dict[str, float] = {}
        self._circle_property_originals: dict[str, float] = {}
        icon = getattr(self._root(), "app_icon", None)
        if icon is not None:
            self.iconphoto(False, icon)
        self._build()
        self._document_tabs.append({})
        self._store_active_document_tab("Nouveau document")
        self._refresh_document_tabs()
        self._apply_toolbar_size()
        if project_path is not None:
            loaded = CanvasDocument.load(project_path)
            opened_from_template = loaded.is_template
            loaded.is_template = False
            self.document = loaded
            self._saved_document = copy.deepcopy(loaded)
            self.project_path = None if opened_from_template else project_path
            self.status.configure(
                text=(
                    f"Nouveau document créé depuis le modèle {project_path.name}. Enregistrer demandera un nouveau nom."
                    if opened_from_template
                    else f"Projet ouvert : {project_path.name}"
                )
            )
            self._store_active_document_tab(project_path.name)
            self._refresh_document_tabs()
        self.protocol("WM_DELETE_WINDOW", self._request_close)
        self._toggle_properties_panel()
        translate_widget_tree(self)
        maximize_window(self)
        # Flush geometry and palette widgets before handing the window to the user.
        self.update_idletasks()
        make_modal(self, parent)
        self.after_idle(self._render)

    def _build(self) -> None:
        self._build_menu()
        ttk.Style(self).configure("EditorTool.TButton", padding=(3, 2), font=("Sans", 10))
        ttk.Style(self).configure("PaletteTool.TButton", padding=(5, 5), font=("Sans", 14, "bold"))
        header = tk.Frame(self, bg=NAVY, padx=22, pady=10)
        header.pack(fill="x")
        tk.Label(header, text="Créer un modèle" if self.template_mode else "Créer un document", bg=NAVY, fg="white", font=("Sans", 19, "bold")).pack(side="left")
        tk.Button(
            header,
            text="⚙  Propriétés  F4",
            command=self._toggle_properties_panel,
            bg="#285886",
            fg="white",
            activebackground="#3474AD",
            activeforeground="white",
            relief="flat",
            padx=12,
            pady=4,
        ).pack(side="right")
        tk.Button(
            header,
            text="▤  Panneaux",
            command=self._toggle_default_palettes,
            bg="#285886",
            fg="white",
            activebackground="#3474AD",
            activeforeground="white",
            relief="flat",
            padx=12,
            pady=4,
        ).pack(side="right", padx=(0, 8))

        self.document_tab_bar = tk.Frame(self, bg="#D5DFEA", padx=8, pady=3)
        self.document_tab_bar.pack(fill="x")
        tk.Button(
            header,
            text="▦  Ruban",
            command=self._toggle_ribbon,
            bg="#285886",
            fg="white",
            activebackground="#3474AD",
            activeforeground="white",
            relief="flat",
            padx=12,
            pady=4,
        ).pack(side="right", padx=(0, 8))

        self.ribbon = ttk.Notebook(self)
        self.ribbon.pack(fill="x", padx=8, pady=(4, 2))
        insertion = ttk.Frame(self.ribbon, style="App.TFrame", padding=(12, 7))
        formatting = ttk.Frame(self.ribbon, style="App.TFrame", padding=(12, 7))
        table_tools = ttk.Frame(self.ribbon, style="App.TFrame", padding=(12, 7))
        tools = ttk.Frame(self.ribbon, style="App.TFrame", padding=(12, 7))
        layout = ttk.Frame(self.ribbon, style="App.TFrame", padding=(12, 7))
        diagrams = ttk.Frame(self.ribbon, style="App.TFrame", padding=(12, 7))
        technical = ttk.Frame(self.ribbon, style="App.TFrame", padding=(12, 7))
        self.ribbon.add(insertion, text="Insérer")
        self.ribbon.add(formatting, text="Texte")
        self.ribbon.add(table_tools, text="Tableau")
        self.ribbon.add(tools, text="Outils")
        self.ribbon.add(layout, text="Mise en page")
        self.ribbon.add(technical, text="Technique")
        self._contextual_ribbon_tabs = {
            "table": table_tools,
            "technical": technical,
        }
        self._buttons(formatting, (
            ("↶", self._undo, "Annuler"), ("↷", self._redo, "Rétablir"),
            ("⧉", self._copy_objects, "Copier les objets sélectionnés"),
            ("▣", self._paste_objects, "Coller une copie indépendante sur cette page"),
            ("🖌", self._copy_format, "Copier la mise en forme"),
            ("🖌✓", self._apply_format, "Appliquer la mise en forme copiée"),
            ("G", lambda: self._toggle("bold"), "Gras"),
            ("I", lambda: self._toggle("italic"), "Italique"),
            ("S̲", lambda: self._toggle("underline"), "Souligné"),
            ("B̶", lambda: self._toggle("strikethrough"), "Barré"),
            ("≡  ←", lambda: self._align("left"), "Aligner à gauche"),
            ("← ≡ →", lambda: self._align("center"), "Centrer"),
            ("→  ≡", lambda: self._align("right"), "Aligner à droite"),
            ("≡", lambda: self._align("justify"), "Justifier"),
            ("A−", lambda: self._change_font(-1), "Réduire la taille du texte"),
            ("A+", lambda: self._change_font(1), "Agrandir la taille du texte"),
        ), color="#DCEBFA")
        ttk.Label(formatting, text="Police", style="Body.TLabel").pack(side="left", padx=(10, 3))
        self.font_family_var = tk.StringVar(value="Sans-serif")
        self.font_family_combo = ttk.Combobox(
            formatting,
            textvariable=self.font_family_var,
            values=available_font_families(),
            width=14,
        )
        self.font_family_combo.pack(side="left", padx=2)
        self.font_family_combo.bind("<<ComboboxSelected>>", lambda _event: self._apply_font_family())
        self.font_family_combo.bind("<Return>", lambda _event: self._apply_font_family())
        ttk.Button(
            formatting,
            text="Polices…",
            command=self._show_font_catalog,
            style="EditorTool.TButton",
        ).pack(side="left", padx=(3, 6))
        self.font_sample = ttk.Label(formatting, style="Body.TLabel")
        self.font_sample.pack(side="left", padx=(3, 5))
        self.font_family_combo.bind("<<ComboboxSelected>>", lambda _event: self._update_font_sample(), add="+")
        self._font_sample_image: ImageTk.PhotoImage | None = None
        self._update_font_sample()
        ttk.Label(formatting, text="Taille", style="Body.TLabel").pack(side="left", padx=(10, 3))
        self.font_size_var = tk.StringVar(value="12")
        font_size = ttk.Combobox(
            formatting,
            textvariable=self.font_size_var,
            values=("8", "9", "10", "11", "12", "14", "16", "18", "20", "24", "28", "32", "36", "48", "60", "72"),
            width=5,
        )
        font_size.pack(side="left", padx=2)
        font_size.bind("<<ComboboxSelected>>", lambda _event: self._apply_font_size())
        font_size.bind("<Return>", lambda _event: self._apply_font_size())
        self._color_menu_button(formatting, "A▾", "color", "Couleur du texte")
        self._color_menu_button(formatting, "Fond▾", "fill", "Couleur de fond de la zone")
        self._color_menu_button(formatting, "Bord▾", "border_color", "Couleur de la bordure")
        self.border_style_var = tk.StringVar(value="Continu")
        border_style = ttk.Combobox(
            formatting, textvariable=self.border_style_var,
            values=("Continu", "Pointillé", "Tirets"), state="readonly", width=8,
        )
        border_style.pack(side="left", padx=2)
        border_style.bind("<<ComboboxSelected>>", lambda _event: self._apply_border_style())
        self.border_width_var = tk.StringVar(value="1.5")
        border_width = ttk.Combobox(
            formatting, textvariable=self.border_width_var,
            values=("0", "0.5", "1", "1.5", "2", "3", "4", "6"), width=4,
        )
        border_width.pack(side="left", padx=2)
        border_width.bind("<<ComboboxSelected>>", lambda _event: self._apply_border_width())
        border_width.bind("<Return>", lambda _event: self._apply_border_width())
        table_borders = ttk.Menubutton(table_tools, text="Quadrillage ▾")
        table_border_menu = tk.Menu(table_borders, tearoff=False)
        table_border_menu.add_command(label="Quadrillage standard", command=lambda: self._set_table_border_preset("standard"))
        table_border_menu.add_command(label="Bordure extérieure épaisse", command=lambda: self._set_table_border_preset("outer"))
        table_border_menu.add_command(label="Toutes les bordures fines", command=lambda: self._set_table_border_preset("thin"))
        table_border_menu.add_command(label="Quadrillage intérieur plus fin", command=lambda: self._change_table_inner_border(-0.25))
        table_border_menu.add_command(label="Quadrillage intérieur plus épais", command=lambda: self._change_table_inner_border(0.25))
        table_border_menu.add_command(label="Masquer le quadrillage intérieur", command=lambda: self._set_table_inner_border(0.0))
        table_border_menu.add_command(label="Aucune bordure", command=lambda: self._set_table_border_preset("none"))
        table_border_menu.add_separator()
        table_border_menu.add_command(label="Épaissir la ligne active", command=self._emphasize_active_table_row)
        table_border_menu.add_command(label="Rétablir la ligne active", command=self._reset_active_table_row)
        table_border_menu.add_separator()
        table_border_menu.add_command(label="Contour fin de la cellule active", command=lambda: self._outline_active_table_cell(0.6))
        table_border_menu.add_command(label="Contour épais de la cellule active", command=lambda: self._outline_active_table_cell(3.0))
        table_border_menu.add_command(label="Contour épais de la ligne active", command=lambda: self._outline_active_table_row_or_column("row", 3.0))
        table_border_menu.add_command(label="Contour épais de la colonne active", command=lambda: self._outline_active_table_row_or_column("column", 3.0))
        table_border_menu.add_separator()
        table_border_menu.add_command(label="Définir le premier coin d’une plage", command=self._start_table_border_range)
        table_border_menu.add_command(label="Appliquer le contour jusqu’à la cellule active", command=lambda: self._finish_table_border_range(3.0))
        table_border_menu.add_command(label="Effacer les contours personnalisés", command=self._clear_table_border_ranges)
        table_borders.configure(menu=table_border_menu)
        table_borders.pack(side="left", padx=2, pady=3)
        self._buttons(insertion, (
            ("T  Texte", self._add_text, "Insérer une zone de texte"),
            ("🖼  Image", self._add_image, "Insérer une image"),
            ("🔗  Lien", self._set_selected_hyperlink, "Ajouter ou modifier un lien Internet sur l’objet sélectionné"),
            ("▦  Tableau", self._add_table, "Insérer un tableau"),
            ("▒  Masque", self._add_mask, "Insérer un masque blanc"),
        ), color="#DDF3E7")
        shapes_button = tk.Menubutton(
            insertion,
            text="◯  Formes ▾",
            bg="#DDF3E7",
            activebackground="#B8DFC9",
            relief="flat",
            padx=10,
            pady=5,
        )
        shapes_menu = tk.Menu(shapes_button, tearoff=False)
        for label, command in (
            ("Rectangle orienté", lambda: self._start_rectangle(False)),
            ("Carré orienté", lambda: self._start_rectangle(True)),
            ("Cercle paramétrique", lambda: self._add_shape("circle")),
            ("Ellipse", lambda: self._add_shape("ellipse")),
            ("Triangle quelconque", lambda: self._start_triangle(False)),
            ("Triangle rectangle", lambda: self._start_triangle(True)),
            ("Trapèze", lambda: self._add_shape("trapezoid")),
            ("Flèche", lambda: self._add_shape("arrow")),
            ("Trait libre", self._add_line),
            ("Polyligne / profil", self._start_polyline),
            ("Trait d’axe", self._add_axis),
        ):
            shapes_menu.add_command(label=label, command=command)
        shapes_button.configure(menu=shapes_menu)
        shapes_button.pack(side="left", padx=4)
        self._tool_buttons.append(shapes_button)
        panels_button = tk.Menubutton(
            insertion,
            text="▤  Panneaux ▾",
            bg="#DDF3E7",
            activebackground="#B8DFC9",
            relief="flat",
            padx=10,
            pady=5,
        )
        panels_menu = tk.Menu(panels_button, tearoff=False)
        self._populate_panels_menu(panels_menu)
        panels_button.configure(menu=panels_menu)
        panels_button.pack(side="left", padx=4)
        self._tool_buttons.append(panels_button)
        self._buttons(formatting, (
            ("🤖", self._open_chatgpt_for_selected, "Ouvrir ChatGPT pour dicter, corriger ou reformuler le texte"),
            ("📋", self._paste_chatgpt_result, "Coller le résultat de ChatGPT dans la zone de texte"),
            ("✓", self._review_selected, "Relire et corriger manuellement la zone de texte"),
            ("Ω", self._insert_symbol, "Insérer un caractère spécial"),
            ("•", lambda: self._make_list(False), "Liste à puces"),
            ("1.", lambda: self._make_list(True), "Liste numérotée"),
        ), color="#DCEBFA")
        self._buttons(table_tools, (
            ("▥", lambda: self._add_chart("bar"), "Graphique en barres lié au tableau"),
            ("◔", lambda: self._add_chart("pie"), "Camembert lié au tableau"),
        ), color="#DDF3E7")
        structure_button = ttk.Menubutton(table_tools, text="Lignes / colonnes ▾")
        structure_menu = tk.Menu(structure_button, tearoff=False)
        structure_menu.add_command(label="Insérer une ligne au-dessus", command=lambda: self._change_table_structure("insert_row_before"))
        structure_menu.add_command(label="Insérer une ligne en dessous", command=lambda: self._change_table_structure("insert_row_after"))
        structure_menu.add_command(label="Supprimer la ligne active", command=lambda: self._change_table_structure("delete_row"))
        structure_menu.add_separator()
        structure_menu.add_command(label="Insérer une colonne à gauche", command=lambda: self._change_table_structure("insert_column_before"))
        structure_menu.add_command(label="Insérer une colonne à droite", command=lambda: self._change_table_structure("insert_column_after"))
        structure_menu.add_command(label="Supprimer la colonne active", command=lambda: self._change_table_structure("delete_column"))
        structure_button.configure(menu=structure_menu)
        structure_button.pack(side="left", padx=4, pady=3)
        self._buttons(tools, (
            ("📏", self._start_measurement, "Mesurer librement deux points"),
            ("┊↔┊", self._start_dimension_measurement, "Créer une cote avec lignes de rappel"),
            ("∠", self._start_angle_measurement, "Mesurer un angle intérieur avec trois points"),
            ("🔎 Police PDF", self._start_pdf_font_picker, "Détecter la police, la taille et la couleur dans le PDF"),
            ("Aa Polices", self._show_font_catalog, "Afficher les polices installées et leurs équivalences"),
            ("📦 Polices", self._show_bundled_fonts, "Voir les polices réellement livrées avec Lou Còdi"),
            ("OCR", self._ocr_pdf_page, "Reconnaître le texte de la page PDF scannée"),
        ), color="#DDF3E7")
        self._buttons(layout, (
            ("▯", lambda: self._set_orientation("portrait"), "Page en orientation portrait"),
            ("▭", lambda: self._set_orientation("landscape"), "Page en orientation paysage"),
            ("▔ H", lambda: self._add_preset("header"), "Ajouter un en-tête répété"),
            ("▁ P", lambda: self._add_preset("footer"), "Ajouter un pied de page répété"),
            ("║", lambda: self._add_preset("left_margin"), "Ajouter une marge de notes"),
            ("🔗", self._link_text_frames, "Faire continuer le texte dans le cadre suivant"),
            ("⛓", self._unlink_text_frame, "Supprimer le chaînage du cadre"),
            ("№", lambda: self._insert_field("Page {{PAGE}} / {{PAGES}}"), "Numérotation automatique"),
            ("◷", lambda: self._insert_field("{{DATE}}"), "Insérer la date du jour"),
            ("▣", self._group_selected, "Assembler les objets sélectionnés pour les déplacer ensemble"),
            ("□", self._ungroup_selected, "Dissocier les objets"),
        ), color="#F9E8C8")
        ttk.Label(layout, text="Format", style="Body.TLabel").pack(side="left", padx=(10, 3))
        self.page_format_var = tk.StringVar(value="A4")
        page_format = ttk.Combobox(
            layout,
            textvariable=self.page_format_var,
            values=("A4", "A3"),
            state="readonly",
            width=4,
        )
        page_format.pack(side="left", padx=2)
        page_format.bind("<<ComboboxSelected>>", lambda _event: self._set_page_format())
        scale_button = ttk.Button(
            layout,
            text="Échelle…",
            command=self._start_scale_calibration,
            style="EditorTool.TButton",
        )
        scale_button.pack(side="left", padx=(6, 2))
        self._tool_buttons.append(scale_button)
        tk.Label(
            layout,
            text="Chaînage : 1  sélectionnez la première zone   →   2  cliquez sur Lier texte   →   3  cliquez sur la zone verte",
            bg="#FFF5DE",
            fg="#744500",
            font=("Sans", 9, "bold"),
            padx=10,
            pady=5,
        ).pack(side="right", padx=(12, 0))
        self._buttons(diagrams, (
            ("▭", lambda: self._start_rectangle(False), "Dessiner un rectangle orienté"),
            ("□", lambda: self._start_rectangle(True), "Dessiner un carré orienté"),
            ("◯", lambda: self._add_shape("ellipse"), "Insérer une ellipse"),
            ("△", lambda: self._start_triangle(False), "Dessiner un triangle quelconque orienté"),
            ("◿", lambda: self._start_triangle(True), "Dessiner un triangle rectangle orienté"),
            ("⌔", lambda: self._add_shape("trapezoid"), "Insérer un trapèze"),
            ("➜", lambda: self._add_shape("arrow"), "Insérer une flèche"),
            ("／", self._add_line, "Tracer un trait"),
            ("⌁", self._start_polyline, "Tracer un profil point par point"),
            ("┄", self._add_axis, "Insérer un trait d’axe"),
            ("↺", lambda: self._rotate_selected(-1), "Pivoter selon le pas vers la gauche"),
            ("↻", lambda: self._rotate_selected(1), "Pivoter selon le pas vers la droite"),
        ), color="#E8E0F5")

        profile_button = ttk.Menubutton(technical, text="Profil ▾")
        profile_menu = tk.Menu(profile_button, tearoff=False)
        profile_menu.add_command(label="Chanfrein entre deux traits…", command=self._chamfer_selected)
        profile_menu.add_command(label="Chanfrein ou arrondi sur des coins…", command=self._treat_shape_corner)
        profile_menu.add_command(label="Fusionner deux rectangles en profil", command=self._merge_rectangles_as_profile)
        profile_menu.add_separator()
        profile_menu.add_command(label="Contrôler le contour", command=self._check_contour)
        profile_menu.add_command(label="Fermer le contour", command=self._close_contour)
        profile_menu.add_command(label="Ajuster le profil à l’axe", command=self._snap_profile_to_axis)
        profile_menu.add_command(label="Poser l’axe sur le fond du profil", command=self._place_axis_on_profile_base)
        profile_menu.add_command(label="Recentrer l’axe dans le profil complet", command=self._center_revolution_axis)
        profile_menu.add_command(label="Valider et verrouiller l’axe 3D", command=self._validate_and_lock_revolution_axis)
        profile_menu.add_command(label="Déverrouiller l’axe", command=self._unlock_revolution_axis)
        profile_menu.add_command(label="Placer l’origine pièce", command=self._start_work_origin)
        profile_menu.add_command(label="Aperçu 3D de la révolution", command=self._show_revolution_preview)
        profile_menu.add_command(label="Symétrie autour de l’axe + copie", command=self._mirror_copy_about_axis)
        profile_menu.add_command(label="Fusionner les deux moitiés symétriques", command=self._merge_mirrored_profiles)
        profile_menu.add_command(label="Symétrie horizontale", command=lambda: self._mirror_selected("horizontal"))
        profile_menu.add_command(label="Symétrie verticale", command=lambda: self._mirror_selected("vertical"))
        profile_button.configure(menu=profile_menu)
        profile_button.pack(side="left", padx=2, pady=3)

        self._buttons(
            technical,
            (("✂", self._split_selection_automatically, "Découper automatiquement selon la sélection"),),
            color="#E8E0F5",
        )

        arrange_button = ttk.Menubutton(technical, text="Assembler ▾")
        arrange_menu = tk.Menu(arrange_button, tearoff=False)
        arrange_menu.add_command(label="Sélectionner par zone", command=self._explain_marquee_selection)
        arrange_menu.add_command(label="Bords confondus guidés…", command=self._snap_selected_edges)
        arrange_menu.add_command(label="Cote pilotante entre deux bords…", command=self._start_driving_dimension)
        arrange_menu.add_separator()
        arrange_menu.add_command(label="Assembler la sélection", command=self._group_selected)
        arrange_menu.add_command(label="Dissocier", command=self._ungroup_selected)
        arrange_menu.add_command(label="Réduire le groupe de 10 %", command=lambda: self._scale_selected_assembly(0.9))
        arrange_menu.add_command(label="Agrandir le groupe de 10 %", command=lambda: self._scale_selected_assembly(1.1))
        arrange_menu.add_separator()
        arrange_menu.add_command(label="Aligner à gauche", command=lambda: self._align_objects("left"))
        arrange_menu.add_command(label="Aligner verticalement", command=lambda: self._align_objects("middle"))
        arrange_button.configure(menu=arrange_menu)
        arrange_button.pack(side="left", padx=2, pady=3)

        hatch_button = ttk.Menubutton(technical, text="Hachures ▾")
        hatch_menu = tk.Menu(hatch_button, tearoff=False)
        hatch_menu.add_command(
            label="Enlever toutes les hachures",
            command=self._remove_selected_hatches,
        )
        hatch_menu.add_separator()
        for label, preset in (
            ("Acier — 45°, moyen", "steel"),
            ("Aluminium — 45°, traits doubles", "aluminium"),
            ("Fonte — 45°, large", "cast_iron"),
            ("Croisées — 45° / 135°", "cross"),
            ("Verticales — 90°", "vertical"),
            ("Personnalisées…", "custom"),
        ):
            hatch_menu.add_command(
                label=label,
                command=lambda selected=preset: self._hatch_selected(selected),
            )
        hatch_button.configure(menu=hatch_menu)
        hatch_button.pack(side="left", padx=2, pady=3)
        self._color_menu_button(technical, "Fond ▾", "fill", "Couleur de fond de la forme")
        self._color_menu_button(technical, "Bord ▾", "border_color", "Couleur de la bordure de la forme")
        technical_border_style = ttk.Combobox(
            technical,
            textvariable=self.border_style_var,
            values=("Continu", "Pointillé", "Tirets"),
            state="readonly",
            width=8,
        )
        technical_border_style.pack(side="left", padx=2)
        technical_border_style.bind("<<ComboboxSelected>>", lambda _event: self._apply_border_style())
        technical_border_width = ttk.Combobox(
            technical,
            textvariable=self.border_width_var,
            values=("0", "0.5", "1", "1.5", "2", "3", "4", "6"),
            width=4,
        )
        technical_border_width.pack(side="left", padx=2)
        technical_border_width.bind("<<ComboboxSelected>>", lambda _event: self._apply_border_width())
        technical_border_width.bind("<Return>", lambda _event: self._apply_border_width())
        ttk.Label(technical, text="Rotation", style="Body.TLabel").pack(side="left", padx=(10, 3))
        self.rotation_step_var = tk.StringVar(value="15")
        ttk.Combobox(
            technical,
            textvariable=self.rotation_step_var,
            values=("5", "10", "15", "30", "45", "60", "90"),
            width=4,
        ).pack(side="left", padx=2)
        self.angle_var = tk.StringVar(value="0")
        angle = ttk.Combobox(
            technical,
            textvariable=self.angle_var,
            values=("0", "15", "30", "45", "60", "90", "120", "135", "150"),
            width=5,
        )
        angle.pack(side="left", padx=2)
        angle.bind("<<ComboboxSelected>>", lambda _event: self._apply_absolute_angle())
        angle.bind("<Return>", lambda _event: self._apply_absolute_angle())
        ttk.Label(technical, text="Pas (mm)", style="Body.TLabel").pack(side="left", padx=(10, 3))
        self.nudge_var = tk.StringVar(value="1")
        ttk.Combobox(
            technical,
            textvariable=self.nudge_var,
            values=("10", "1", "0.1", "0.01"),
            state="readonly",
            width=5,
        ).pack(side="left", padx=2)

        self.body = ttk.Panedwindow(self, orient="horizontal")
        self.body.pack(fill="both", expand=True, padx=12, pady=(2, 0))
        canvas_frame = ttk.Frame(self.body, style="App.TFrame")
        self.body.add(canvas_frame, weight=5)
        self.canvas = tk.Canvas(canvas_frame, bg="#C8D0DA", highlightthickness=0)
        xbar = ttk.Scrollbar(canvas_frame, orient="horizontal", command=self.canvas.xview)
        ybar = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)
        self.palette_host = canvas_frame
        canvas_frame.bind(
            "<Configure>",
            lambda _event: self.after_idle(self._redock_visible_contextual_palettes),
            add="+",
        )
        palette_definitions = {
            "shapes": ("FORMES", (
                ("T", self._add_text, "Créer une zone de texte"),
                ("▭", lambda: self._start_rectangle(False), "Rectangle orienté"),
                ("□", lambda: self._start_rectangle(True), "Carré orienté"),
                ("○", lambda: self._add_shape("circle"), "Cercle paramétrique"),
                ("⬭", lambda: self._add_shape("ellipse"), "Ellipse"),
                ("△", lambda: self._start_triangle(False), "Triangle quelconque"),
                ("◿", lambda: self._start_triangle(True), "Triangle rectangle"),
                ("⌔", lambda: self._add_shape("trapezoid"), "Trapèze"),
                ("➜", lambda: self._add_shape("arrow"), "Flèche"),
                ("／", self._add_line, "Trait libre"),
                ("⌁", self._start_polyline, "Polyligne / profil"),
            )),
            "technical": ("TECHNIQUE", (
                ("╱", self._chamfer_selected, "Chanfrein entre deux traits"),
                ("⌒", self._treat_shape_corner, "Traiter les coins de la forme"),
                ("⌘", self._merge_rectangles_as_profile, "Fusionner deux rectangles"),
                ("┄", self._add_axis, "Ajouter un axe"),
                ("✂", self._split_selection_automatically, "Découper automatiquement"),
                ("▣", self._group_selected, "Assembler la sélection"),
                ("□", self._ungroup_selected, "Dissocier"),
                ("≋", self._snap_selected_edges, "Rendre deux bords confondus"),
                ("┊↔┊", self._start_driving_dimension, "Cote pilotante entre deux bords"),
                ("×", self._remove_selected_hatches, "Enlever toutes les hachures"),
                ("╱", lambda: self._hatch_selected("steel"), "Acier"),
                ("〽", lambda: self._hatch_selected("aluminium"), "Aluminium"),
                ("▦", lambda: self._hatch_selected("cross"), "Hachures croisées"),
            )),
            "measurements": ("MESURES", (
                ("📏", self._start_measurement, "Distance et orientation"),
                ("┊↔┊", self._start_dimension_measurement, "Cote avec lignes de rappel"),
                ("∠", self._start_angle_measurement, "Angle intérieur"),
                ("Ø", self._dimension_selected_circle, "Coter le cercle"),
                ("A", self._measure_selected_area, "Calculer l’aire"),
                ("Éch", self._start_scale_calibration, "Étalonner l’échelle"),
            )),
            "table": ("TABLEAU", (
                ("▦", self._add_table, "Insérer un tableau"),
                ("▂▅█", lambda: self._add_chart("bar"), "Graphique en barres / histogramme"),
                ("◔", lambda: self._add_chart("pie"), "Camembert"),
                ("R+", lambda: self._change_table_structure("insert_row_after"), "Ajouter une ligne"),
                ("R−", lambda: self._change_table_structure("delete_row"), "Supprimer la ligne"),
                ("C+", lambda: self._change_table_structure("insert_column_after"), "Ajouter une colonne"),
                ("C−", lambda: self._change_table_structure("delete_column"), "Supprimer la colonne"),
                ("▦", lambda: self._set_table_border_preset("standard"), "Quadrillage standard"),
                ("▣", lambda: self._set_table_border_preset("outer"), "Contour extérieur épais"),
                ("H▦", lambda: self._set_table_style("blue"), "En-tête bleu et lignes bleues alternées"),
                ("H▤", lambda: self._set_table_style("green"), "En-tête vert et lignes vertes alternées"),
                ("H×", lambda: self._set_table_style("plain"), "Retirer le style d’en-tête et les lignes alternées"),
            )),
            "text_zone_style": ("APPARENCE ZONE", (
                ("Fond", self._choose_inline_text_frame_fill, "Choisir la couleur de fond"),
                ("ØF", lambda: self._set_inline_text_frame_fill("transparent"), "Fond transparent"),
                ("Bord", lambda: self._choose_color("border_color"), "Choisir la couleur de bordure"),
                ("ØB", lambda: self._set_border_width_value(0), "Supprimer la bordure"),
                ("0.5", lambda: self._set_border_width_value(0.5), "Bordure fine"),
                ("1.5", lambda: self._set_border_width_value(1.5), "Bordure moyenne"),
                ("3", lambda: self._set_border_width_value(3), "Bordure épaisse"),
                ("5", lambda: self._set_border_width_value(5), "Bordure très épaisse"),
                ("—", lambda: self._set_border_style_value("solid"), "Bordure continue"),
                ("···", lambda: self._set_border_style_value("dotted"), "Bordure pointillée"),
                ("---", lambda: self._set_border_style_value("dashed"), "Bordure en tirets"),
                ("−1°", lambda: self._rotate_selected_degrees(-1), "Tourner d’un degré vers la gauche"),
                ("+1°", lambda: self._rotate_selected_degrees(1), "Tourner d’un degré vers la droite"),
                ("∠°", self._ask_absolute_angle, "Saisir un angle exact"),
            )),
            "media": ("IMAGE", (
                ("👤", self._add_image, "Insérer une image"),
                ("🔗", self._set_selected_hyperlink, "Ajouter ou modifier un hyperlien"),
                ("▱", self._add_mask, "Insérer un masque blanc"),
                ("┌┄", self._crop_selected_image, "Rogner l’image sélectionnée"),
                ("↻", lambda: self._rotate_selected(1), "Faire pivoter"),
            )),
            "shape_style": ("APPARENCE FORME", (
                ("Fond", lambda: self._choose_color("fill"), "Choisir la couleur de fond"),
                ("ØF", lambda: self._set_object_color("fill", "transparent"), "Fond transparent"),
                ("Bord", lambda: self._choose_color("border_color"), "Choisir la couleur de bordure"),
                ("ØB", lambda: self._set_border_width_value(0), "Supprimer la bordure"),
                ("0.5", lambda: self._set_border_width_value(0.5), "Bordure fine"),
                ("1.5", lambda: self._set_border_width_value(1.5), "Bordure moyenne"),
                ("3", lambda: self._set_border_width_value(3), "Bordure épaisse"),
                ("5", lambda: self._set_border_width_value(5), "Bordure très épaisse"),
                ("—", lambda: self._set_border_style_value("solid"), "Bordure continue"),
                ("···", lambda: self._set_border_style_value("dotted"), "Bordure pointillée"),
                ("---", lambda: self._set_border_style_value("dashed"), "Bordure en tirets"),
                ("−1°", lambda: self._rotate_selected_degrees(-1), "Tourner d’un degré vers la gauche"),
                ("+1°", lambda: self._rotate_selected_degrees(1), "Tourner d’un degré vers la droite"),
                ("∠°", self._ask_absolute_angle, "Saisir un angle exact"),
            )),
        }
        vertical_palettes = {"shapes", "media", "table", "measurements"}
        for key, (title, actions) in palette_definitions.items():
            self._create_tool_palette(key, title, actions, columns=1 if key in vertical_palettes else 2)
        self.canvas.bind("<Button-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Double-Button-1>", self._double_click)
        self.canvas.bind("<Button-3>", self._show_context_menu)
        self.canvas.bind("<Motion>", self._polyline_motion)
        self.canvas.bind("<Return>", self._finish_drawing)
        self.canvas.bind("<KP_Enter>", self._finish_drawing)
        self.canvas.bind("<Control-MouseWheel>", self._mouse_zoom)
        self.canvas.bind("<Control-Button-4>", lambda event: self._mouse_zoom(event, 1))
        self.canvas.bind("<Control-Button-5>", lambda event: self._mouse_zoom(event, -1))
        self.canvas.bind("<MouseWheel>", self._mouse_scroll)
        self.canvas.bind("<Button-4>", lambda event: self._mouse_scroll(event, 1))
        self.canvas.bind("<Button-5>", lambda event: self._mouse_scroll(event, -1))
        self.bind("<KeyPress>", self._modifier_key_event, add="+")
        self.bind("<KeyPress>", self._table_typing_event, add="+")
        self.bind("<KeyRelease>", self._modifier_key_event, add="+")
        # A palette keeps following the pointer even after it leaves its narrow title bar.
        self.bind("<B1-Motion>", self._drag_tool_palette, add="+")
        self.bind("<ButtonRelease-1>", self._finish_palette_drag, add="+")

        panel_container = ttk.Frame(self.body, style="Card.TFrame")
        self.properties_panel = panel_container
        self.body.add(panel_container, weight=1)
        properties_canvas = tk.Canvas(
            panel_container, bg="#FFFFFF", highlightthickness=0, borderwidth=0
        )
        properties_scrollbar = ttk.Scrollbar(
            panel_container, orient="vertical", command=properties_canvas.yview
        )
        properties_canvas.configure(yscrollcommand=properties_scrollbar.set)
        properties_canvas.pack(side="left", fill="both", expand=True)
        properties_scrollbar.pack(side="right", fill="y")
        panel = ttk.Frame(properties_canvas, style="Card.TFrame", padding=14)
        properties_window = properties_canvas.create_window((0, 0), window=panel, anchor="nw")
        panel.bind(
            "<Configure>",
            lambda _event: properties_canvas.configure(scrollregion=properties_canvas.bbox("all")),
        )
        properties_canvas.bind(
            "<Configure>",
            lambda event: properties_canvas.itemconfigure(properties_window, width=event.width),
        )
        for widget in (properties_canvas, panel):
            widget.bind(
                "<MouseWheel>",
                lambda event: properties_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units"),
            )
            widget.bind("<Button-4>", lambda _event: properties_canvas.yview_scroll(-1, "units"))
            widget.bind("<Button-5>", lambda _event: properties_canvas.yview_scroll(1, "units"))
        ttk.Label(panel, text="OBJET SÉLECTIONNÉ", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        self.kind_label = ttk.Label(panel, text="Aucun objet", style="Body.TLabel")
        self.kind_label.pack(anchor="w", pady=(0, 8))
        self.property_vars: dict[str, tk.StringVar] = {}
        geometry_grid = ttk.Frame(panel, style="Card.TFrame")
        geometry_grid.pack(fill="x", pady=(0, 5))
        property_layout = (
            ("x", "X (mm)", 0, 0, 1),
            ("y", "Y (mm)", 0, 1, 1),
            ("width", "Largeur (mm)", 0, 2, 1),
            ("height", "Hauteur (mm)", 0, 3, 1),
            ("font_size", "Taille texte (pt)", 1, 0, 2),
            ("level", "Niveau (plan)", 1, 2, 2),
        )
        for column in range(4):
            geometry_grid.columnconfigure(column, weight=1, uniform="properties")
        for key, label, row, column, span in property_layout:
            field = ttk.Frame(geometry_grid, style="Card.TFrame")
            field.grid(row=row, column=column, columnspan=span, sticky="ew", padx=2, pady=2)
            ttk.Label(field, text=label, style="Body.TLabel").pack(anchor="w")
            var = tk.StringVar()
            self.property_vars[key] = var
            entry = ttk.Entry(field, textvariable=var, width=7)
            entry.pack(fill="x")
            entry.bind("<Return>", lambda _event: self._apply_properties())
            entry.bind("<Tab>", lambda _event: self._apply_properties(silent=True), add="+")
        self.geometry_help = ttk.Label(panel, text="", style="Body.TLabel", wraplength=260)
        self.geometry_help.pack(fill="x", pady=(0, 4))
        self.shape_geometry_label = ttk.Label(
            panel, text="", style="Body.TLabel", wraplength=260, justify="left"
        )
        self.shape_geometry_label.pack(fill="x", pady=(0, 4))
        self.triangle_frame = ttk.LabelFrame(panel, text="TRIANGLE — CÔTÉS ET ANGLES", padding=6)
        self.triangle_vars: dict[str, tk.StringVar] = {}
        self.triangle_entries: dict[str, ttk.Entry] = {}
        for row, (key, label) in enumerate((
            ("ab", "Côté AB (mm)"), ("bc", "Côté BC (mm)"), ("ca", "Côté CA (mm)"),
            ("angle_a", "Angle A (°)"), ("angle_b", "Angle B (°)"), ("angle_c", "Angle C (°)"),
        )):
            ttk.Label(self.triangle_frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 5), pady=1)
            variable = tk.StringVar()
            self.triangle_vars[key] = variable
            entry = ttk.Entry(self.triangle_frame, textvariable=variable, width=10)
            self.triangle_entries[key] = entry
            entry.grid(row=row, column=1, sticky="ew", pady=1)
            entry.bind("<Return>", lambda _event: self._apply_triangle_properties())
        self.triangle_frame.columnconfigure(1, weight=1)
        ttk.Button(self.triangle_frame, text="Appliquer au triangle", command=self._apply_triangle_properties).grid(
            row=6, column=0, columnspan=2, sticky="ew", pady=(5, 0)
        )
        self.circle_frame = ttk.LabelFrame(panel, text="CERCLE PARAMÉTRIQUE", padding=6)
        self.circle_vars: dict[str, tk.StringVar] = {}
        for row, (key, label) in enumerate((
            ("diameter", "Diamètre (mm)"),
            ("radius", "Rayon (mm)"),
            ("perimeter", "Périmètre (mm)"),
            ("area", "Aire (mm²)"),
        )):
            ttk.Label(self.circle_frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 5), pady=1)
            variable = tk.StringVar()
            self.circle_vars[key] = variable
            entry = ttk.Entry(self.circle_frame, textvariable=variable, width=12)
            entry.grid(row=row, column=1, sticky="ew", pady=1)
            entry.bind("<Return>", lambda _event: self._apply_circle_properties())
        self.circle_frame.columnconfigure(1, weight=1)
        ttk.Button(
            self.circle_frame, text="Recalculer le cercle", command=self._apply_circle_properties
        ).grid(row=4, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        assembly_actions = ttk.Frame(panel, style="Card.TFrame")
        self.assembly_actions = assembly_actions
        assembly_actions.pack(fill="x", pady=(0, 4))
        ttk.Button(
            assembly_actions,
            text="Réduire −10 %",
            command=lambda: self._scale_selected_assembly(0.9),
        ).pack(side="left", fill="x", expand=True, padx=(0, 2))
        ttk.Button(
            assembly_actions,
            text="Agrandir +10 %",
            command=lambda: self._scale_selected_assembly(1.1),
        ).pack(side="left", fill="x", expand=True, padx=(2, 0))
        ttk.Button(panel, text="Appliquer les coordonnées", style="Primary.TButton", command=self._apply_properties).pack(fill="x", pady=4)
        ttk.Button(panel, text="Modifier le contenu", command=self._edit_selected).pack(fill="x", pady=4)
        ttk.Button(
            panel,
            text="🌐 Ajouter / modifier le lien hypertexte",
            command=self._set_selected_hyperlink,
        ).pack(fill="x", pady=4)
        self.hyperlink_status = ttk.Label(
            panel, text="Aucun lien", style="Body.TLabel", wraplength=260
        )
        self.hyperlink_status.pack(fill="x", pady=(1, 3))
        hyperlink_actions = ttk.Frame(panel, style="Card.TFrame")
        hyperlink_actions.pack(fill="x", pady=(0, 4))
        ttk.Button(
            hyperlink_actions, text="Ouvrir le lien", command=self._open_selected_hyperlink
        ).pack(side="left", fill="x", expand=True, padx=(0, 2))
        ttk.Button(
            hyperlink_actions, text="Supprimer le lien", command=self._remove_selected_hyperlink
        ).pack(side="left", fill="x", expand=True, padx=(2, 0))
        measurement_existing = set(panel.pack_slaves())
        ttk.Separator(panel).pack(fill="x", pady=8)
        ttk.Label(panel, text="MESURE", style="Section.TLabel").pack(anchor="w")
        self.measurement_result = ttk.Label(
            panel,
            text="Cliquez sur 📏 puis sur deux points.",
            style="Body.TLabel",
            wraplength=260,
        )
        self.measurement_result.pack(fill="x", pady=(4, 2))
        ttk.Checkbutton(
            panel,
            text="Inscrire la mesure sur le plan",
            variable=self.write_measurement_var,
        ).pack(anchor="w", pady=(0, 2))
        measurement_choices = ttk.LabelFrame(panel, text="Informations à inscrire", padding=5)
        measurement_choices.pack(fill="x", pady=(0, 5))
        for column, (key, label) in enumerate((
            ("distance", "Distance / longueur"),
            ("angle", "Angle"),
            ("perimeter", "Périmètre"),
            ("area", "Aire"),
            ("segments", "Nombre de segments"),
        )):
            ttk.Checkbutton(
                measurement_choices, text=label, variable=self.measurement_label_vars[key]
            ).grid(row=column // 2, column=column % 2, sticky="w", padx=(0, 8))
        ttk.Checkbutton(
            panel,
            text="Afficher aussi la longueur de prise de cote",
            variable=self.show_measurement_length_var,
        ).pack(anchor="w", pady=(0, 5))
        ttk.Button(panel, text="📏 Distance / orientation", command=self._start_measurement).pack(fill="x", pady=2)
        ttk.Button(panel, text="┊↔┊ Cote avec lignes de rappel", command=self._start_dimension_measurement).pack(fill="x", pady=2)
        ttk.Button(panel, text="◯ Coter le cercle sélectionné", command=self._dimension_selected_circle).pack(fill="x", pady=2)
        ttk.Button(panel, text="▧ Calculer l’aire du contour", command=self._measure_selected_area).pack(fill="x", pady=2)
        ttk.Button(panel, text="∠ Angle intérieur (3 points)", command=self._start_angle_measurement).pack(fill="x", pady=2)
        ttk.Button(panel, text="⊥ Construire un triangle rectangle", command=self._start_right_triangle).pack(fill="x", pady=2)
        ttk.Button(panel, text="Étalonner l’échelle du plan", command=self._start_scale_calibration).pack(fill="x", pady=2)
        self._measurement_property_layout = [
            (widget, widget.pack_info())
            for widget in panel.pack_slaves()
            if widget not in measurement_existing
        ]
        scope_existing = set(panel.pack_slaves())
        ttk.Label(panel, text="Appliquer sur", style="Body.TLabel").pack(anchor="w", pady=(10, 0))
        self.scope_var = tk.StringVar(value="Cette page")
        self.scope_box = ttk.Combobox(
            panel,
            textvariable=self.scope_var,
            values=("Cette page", "Toutes les pages", "Pages choisies"),
            state="readonly",
        )
        self.scope_box.pack(fill="x", pady=(0, 5))
        self.scope_box.bind("<<ComboboxSelected>>", lambda _event: self._apply_scope())
        scope_actions = tk.Frame(panel, bg="white")
        scope_actions.pack(fill="x", pady=(2, 6))
        self._scope_button(scope_actions, "▣ Page", "Cette page", "#DCEBFA")
        self._scope_button(scope_actions, "▦ Toutes", "Toutes les pages", "#DDF3E7")
        self._scope_button(scope_actions, "☗ Choisir", "Pages choisies", "#F9E8C8")
        ttk.Label(panel, text="Pages (ex. 1,3-5)", style="Body.TLabel").pack(anchor="w")
        self.pages_var = tk.StringVar()
        pages_entry = ttk.Entry(panel, textvariable=self.pages_var)
        pages_entry.pack(fill="x", pady=(0, 5))
        pages_entry.bind("<Return>", lambda _event: self._apply_scope())
        ttk.Button(panel, text="Appliquer aux pages", command=self._apply_scope).pack(fill="x", pady=4)
        self._scope_property_layout = [
            (widget, widget.pack_info())
            for widget in panel.pack_slaves()
            if widget not in scope_existing
        ]
        ttk.Label(panel, text="Glissez un objet pour le déplacer. Double-cliquez pour modifier son contenu.", style="Body.TLabel", wraplength=230, justify="left").pack(anchor="w", pady=14)
        self._properties_static_layout = [
            (widget, widget.pack_info())
            for widget in panel.pack_slaves()
            if widget not in {self.kind_label, self.triangle_frame, self.circle_frame}
        ]
        self._properties_details_visible = True

        self._build_context_menu()

        bottom = ttk.Frame(self, style="App.TFrame", padding=(14, 6))
        bottom.pack(fill="x")
        self._buttons(bottom, (("◀ Page précédente", lambda: self._change_page(-1)),))
        self.page_label = ttk.Label(bottom, text="Page 1 / 1", style="Body.TLabel")
        self.page_label.pack(side="left", padx=10)
        self._buttons(bottom, (("Page suivante ▶", lambda: self._change_page(1)), ("+ Page blanche", self._add_blank_page)))
        ttk.Button(bottom, text="−", command=lambda: self._set_zoom(-0.1)).pack(side="right")
        self.zoom_label = ttk.Label(bottom, text="115 %", style="Body.TLabel")
        self.zoom_label.pack(side="right", padx=7)
        ttk.Button(bottom, text="+", command=lambda: self._set_zoom(0.1)).pack(side="right")
        ttk.Button(bottom, text="Page entière", command=self._zoom_full_page).pack(side="right", padx=(8, 0))
        ttk.Button(bottom, text="Largeur de page", command=self._zoom_page_width).pack(side="right", padx=(8, 0))
        ttk.Label(bottom, text="Zoom", style="Body.TLabel").pack(side="right", padx=5)
        self.status = ttk.Label(self, text="Nouvelle page A4", background=BACKGROUND)
        self.status.pack(fill="x", padx=18, pady=(2, 7))

    def _build_menu(self) -> None:
        menu = tk.Menu(self)
        file_menu = tk.Menu(menu, tearoff=False)
        for label, command, accelerator in (
            ("Nouveau document", self._new, "Ctrl+N"),
            ("Ouvrir un projet…", self._load, "Ctrl+O"),
            ("Nouveau depuis un modèle…", self._load_template, ""),
            ("Importer un PDF…", self._import_pdf, ""),
            ("Importer un DOCX…", self._import_docx, ""),
            ("Insérer un DOCX à la suite…", self._append_docx, ""),
            ("Enregistrer", self._save, "Ctrl+S"),
            ("Enregistrer sous…", self._save_as, "Ctrl+Maj+S"),
            ("Enregistrer comme modèle…", self._save_as_template, ""),
        ):
            file_menu.add_command(label=label, command=command, accelerator=accelerator)
        file_menu.add_separator()
        destinations_menu = tk.Menu(file_menu, tearoff=False)
        self._destinations_menu = destinations_menu
        destinations_menu.configure(postcommand=self._refresh_destinations_menu)
        file_menu.add_cascade(label="Enregistrer directement dans", menu=destinations_menu)
        file_menu.add_command(
            label="Dossiers et favoris…",
            command=lambda: configure_document_destinations(self),
        )
        file_menu.add_separator()
        file_menu.add_command(label="Exporter en PDF…", command=self._export_pdf)
        file_menu.add_command(
            label="Exporter en DOCX modifiable…",
            command=self._export_docx,
        )
        file_menu.add_command(label="Imprimer…", command=self._print, accelerator="Ctrl+P")
        file_menu.add_separator()
        file_menu.add_command(label="Fermer", command=self._request_close)
        menu.add_cascade(label="Fichier", menu=file_menu)

        view_menu = tk.Menu(menu, tearoff=False)
        view_menu.add_checkbutton(
            label="Volet des propriétés",
            variable=self.properties_visible,
            command=self._toggle_properties_panel,
            accelerator="F4",
        )
        view_menu.add_checkbutton(
            label="Ruban d’outils",
            variable=self.ribbon_visible,
            command=self._toggle_ribbon,
        )
        view_menu.add_separator()
        palettes_menu = tk.Menu(view_menu, tearoff=False)
        self._populate_panels_menu(palettes_menu)
        view_menu.add_cascade(label="Panneaux d’outils", menu=palettes_menu)
        view_menu.add_separator()
        size_menu = tk.Menu(view_menu, tearoff=False)
        size_menu.add_radiobutton(
            label="Petites icônes",
            value="compact",
            variable=self.toolbar_size_var,
            command=self._apply_toolbar_size,
        )
        size_menu.add_radiobutton(
            label="Grandes icônes",
            value="large",
            variable=self.toolbar_size_var,
            command=self._apply_toolbar_size,
        )
        view_menu.add_cascade(label="Taille des outils", menu=size_menu)
        view_menu.add_separator()
        view_menu.add_command(label="Zoom avant", command=lambda: self._set_zoom(0.1), accelerator="Ctrl++")
        view_menu.add_command(label="Zoom arrière", command=lambda: self._set_zoom(-0.1), accelerator="Ctrl+-")
        menu.add_cascade(label="Affichage", menu=view_menu)
        tools_menu = tk.Menu(menu, tearoff=False)
        tools_menu.add_command(label="Pipette typographique PDF…", command=self._start_pdf_font_picker)
        tools_menu.add_command(label="Catalogue des polices…", command=self._show_font_catalog)
        tools_menu.add_command(label="Polices livrées avec Lou Còdi…", command=self._show_bundled_fonts)
        tools_menu.add_separator()
        tools_menu.add_command(label="Reconnaître le texte de la page PDF (OCR)…", command=self._ocr_pdf_page)
        menu.add_cascade(label="Outils", menu=tools_menu)
        self.configure(menu=menu)
        self.bind("<Control-n>", lambda _event: self._new())
        self.bind("<Control-o>", lambda _event: self._load())
        self.bind("<Control-s>", lambda _event: self._save())
        self.bind("<Control-Shift-s>", lambda _event: self._save_as())
        self.bind("<Control-Shift-S>", lambda _event: self._save_as())
        self.bind("<Control-z>", lambda _event: self._undo())
        self.bind("<Control-y>", lambda _event: self._redo())
        self.bind("<Control-c>", self._copy_shortcut)
        self.bind("<Control-v>", self._paste_shortcut)
        self.bind("<Control-p>", lambda _event: self._print())
        self.bind("<Delete>", lambda _event: self._delete_selected())
        self.bind("<F4>", lambda _event: self._toggle_properties_panel())
        self.bind("<Escape>", self._cancel_current_action)
        self.bind("<Return>", self._finish_drawing)
        self.bind("<Left>", lambda event: self._nudge_selected(event, -1, 0))
        self.bind("<Right>", lambda event: self._nudge_selected(event, 1, 0))
        self.bind("<Up>", lambda event: self._nudge_selected(event, 0, -1))
        self.bind("<Down>", lambda event: self._nudge_selected(event, 0, 1))

    def _refresh_destinations_menu(self) -> None:
        """Refresh shortcuts after the settings dialog without reopening the editor."""
        menu = self._destinations_menu
        menu.delete(0, "end")
        menu.add_command(
            label="LouCodi — Document Studio",
            command=lambda: self._save_as(initial_directory=module_output_directory("Document Studio")),
        )
        for label, directory in favorite_destinations():
            menu.add_command(
                label=label,
                command=lambda selected=directory: self._save_as(initial_directory=selected),
            )
        menu.add_separator()
        menu.add_command(
            label="Configurer les dossiers favoris…",
            command=lambda: configure_document_destinations(self),
        )

    def _buttons(
        self,
        parent: tk.Misc,
        items: tuple[tuple[str, object] | tuple[str, object, str], ...],
        *,
        color: str | None = None,
    ) -> None:
        for item in items:
            label, command = item[:2]
            tooltip = item[2] if len(item) == 3 else ""
            options = {"width": max(2, len(label))} if len(label) <= 4 else {}
            if color:
                button = tk.Button(
                    parent,
                    text=label,
                    command=command,
                    bg=color,
                    activebackground=self._darker(color),
                    relief="flat",
                    padx=7,
                    pady=3,
                    **options,
                )
            else:
                button = ttk.Button(
                    parent,
                    text=label,
                    command=command,
                    style="EditorTool.TButton",
                    **options,
                )
            button.pack(side="left", padx=1)
            self._tool_buttons.append(button)
            if tooltip:
                self._add_tooltip(button, tooltip)

    def _apply_toolbar_size(self) -> None:
        size = self.toolbar_size_var.get()
        set_toolbar_size(size)
        # Even the compact variant must remain legible on a high-density screen.
        font_size, padding = (16, 9) if size == "large" else (13, 7)
        ttk.Style(self).configure("EditorTool.TButton", padding=(padding, padding), font=("Sans", font_size))
        for button in self._tool_buttons:
            if isinstance(button, (tk.Button, tk.Menubutton)):
                button.configure(font=("Sans", font_size), padx=padding + 2, pady=padding)

    def _color_menu_button(self, parent: tk.Misc, label: str, attribute: str, tooltip: str) -> None:
        button = tk.Menubutton(
            parent,
            text=label,
            bg="#DCEBFA",
            activebackground="#B8D7F4",
            relief="flat",
            padx=7,
            pady=3,
        )
        menu = tk.Menu(button, tearoff=False)
        presets = (
            ("Noir", "#000000"),
            ("Bleu", "#2368AF"),
            ("Rouge", "#C83232"),
            ("Vert", "#258A55"),
            ("Orange", "#E87524"),
            ("Violet", "#7B4DB5"),
            ("Blanc", "#FFFFFF"),
        )
        for name, value in presets:
            menu.add_command(
                label=f"■  {name}   {value}",
                foreground=value,
                command=lambda color=value, key=attribute: self._set_object_color(key, color),
            )
        if attribute == "fill":
            menu.add_command(
                label="▧  Transparent",
                command=lambda: self._set_object_color("fill", "transparent"),
            )
        menu.add_separator()
        menu.add_command(
            label="Saisir un code hexadécimal…",
            command=lambda key=attribute: self._enter_hex_color(key),
        )
        menu.add_command(
            label="Sélecteur de couleur…",
            command=lambda key=attribute: self._choose_color(key),
        )
        button.configure(menu=menu)
        button.pack(side="left", padx=2)
        self._add_tooltip(button, tooltip)

    @staticmethod
    def _darker(color: str) -> str:
        red, green, blue = (int(color[index:index + 2], 16) for index in (1, 3, 5))
        return f"#{max(0, red - 24):02X}{max(0, green - 24):02X}{max(0, blue - 24):02X}"

    def _scope_button(self, parent: tk.Misc, label: str, scope: str, color: str) -> None:
        tk.Button(
            parent,
            text=label,
            command=lambda: self._set_scope(scope),
            bg=color,
            activebackground=self._darker(color),
            relief="flat",
            padx=5,
            pady=3,
        ).pack(side="left", fill="x", expand=True, padx=1)

    def _set_scope(self, scope: str) -> None:
        self.scope_var.set(scope)
        if scope != "Pages choisies":
            self._apply_scope()
        else:
            self.status.configure(text="Indiquez les pages souhaitées, par exemple 1,3-5, puis validez.")

    def _add_tooltip(self, widget: tk.Widget, text: str) -> None:
        popup: list[tk.Toplevel | None] = [None]
        timer: list[str | None] = [None]

        def show() -> None:
            timer[0] = None
            if popup[0] is not None:
                return
            tip = tk.Toplevel(self)
            tip.wm_overrideredirect(True)
            tip.configure(bg="#152E4D")
            x = widget.winfo_rootx()
            y = widget.winfo_rooty() + widget.winfo_height() + 5
            tip.geometry(f"+{x}+{y}")
            tk.Label(
                tip,
                text=text,
                bg="#152E4D",
                fg="white",
                padx=8,
                pady=4,
                font=("Sans", 9),
            ).pack()
            popup[0] = tip

        def enter(_event: object) -> None:
            timer[0] = self.after(450, show)

        def hide(_event: object) -> None:
            if timer[0] is not None:
                self.after_cancel(timer[0])
                timer[0] = None
            if popup[0] is not None:
                popup[0].destroy()
                popup[0] = None

        widget.bind("<Enter>", enter, add="+")
        widget.bind("<Leave>", hide, add="+")
        widget.bind("<ButtonPress>", hide, add="+")

    def _create_tool_palette(
        self,
        key: str,
        title: str,
        actions: tuple[tuple[str, object, str], ...],
        *,
        columns: int = 2,
    ) -> None:
        palette = tk.Frame(
            self.palette_host,
            bg="#EDF3F8",
            bd=1,
            relief="solid",
            padx=4,
            pady=3,
        )
        header = tk.Frame(palette, bg="#193F6A")
        header.pack(fill="x", pady=(0, 3))
        title_label = tk.Label(
            header, text=title, bg="#193F6A", fg="white",
            font=("Sans", 8, "bold"), padx=5, pady=2,
        )
        title_label.pack(side="left", fill="x", expand=True)
        tools = ttk.Frame(palette)
        tools.pack(fill="x")
        for index, (symbol, command, help_text) in enumerate(actions):
            button = ttk.Button(
                tools, text=symbol, command=command, width=4,
                style="PaletteTool.TButton",
            )
            button.grid(row=index // columns, column=index % columns, padx=1, pady=1, sticky="ew")
            self._add_tooltip(button, help_text)
        self.tool_palettes[key] = palette
        palette.bind("<B1-Motion>", self._drag_tool_palette)
        palette.bind("<ButtonRelease-1>", self._finish_palette_drag)
        for handle in (header, title_label):
            handle.bind("<ButtonPress-1>", lambda event, palette_key=key: self._start_palette_drag(event, palette_key))
            handle.bind("<B1-Motion>", self._drag_tool_palette)
            handle.bind("<ButtonRelease-1>", self._finish_palette_drag)
        self._set_palette_visibility(key)

    def _populate_panels_menu(self, menu: tk.Menu) -> None:
        menu.add_checkbutton(
            label="Ruban d’outils",
            variable=self.ribbon_visible,
            command=self._toggle_ribbon,
        )
        menu.add_checkbutton(
            label="Volet des propriétés",
            variable=self.properties_visible,
            command=self._toggle_properties_panel,
        )
        menu.add_separator()
        for key, label in (
            ("shapes", "Formes"),
            ("measurements", "Mesures et cotations"),
            ("table", "Tableau"),
            ("media", "Image, lien et masque"),
            ("shape_style", "Apparence des formes"),
            ("technical", "Technique"),
        ):
            menu.add_checkbutton(
                label=label,
                variable=self.palette_visible_vars[key],
                command=lambda palette_key=key: self._set_palette_visibility(palette_key),
            )

    def _start_palette_drag(self, event: tk.Event[tk.Widget], key: str) -> None:
        palette = self.tool_palettes[key]
        self._palette_drag = (key, event.x_root, event.y_root, palette.winfo_x(), palette.winfo_y())
        palette.grab_set()

    def _drag_tool_palette(self, event: tk.Event[tk.Widget]) -> None:
        if self._palette_drag is None:
            return
        key, start_x, start_y, origin_x, origin_y = self._palette_drag
        palette = self.tool_palettes[key]
        x = max(0, min(origin_x + event.x_root - start_x, self.palette_host.winfo_width() - palette.winfo_width()))
        y = max(0, min(origin_y + event.y_root - start_y, self.palette_host.winfo_height() - palette.winfo_height()))
        self.palette_positions[key] = (x, y)
        palette.place(x=x, y=y, anchor="nw")

    def _finish_palette_drag(self, _event: tk.Event[tk.Widget] | None = None) -> None:
        if self._palette_drag is None:
            return
        key = self._palette_drag[0]
        palette = self.tool_palettes.get(key)
        self._palette_drag = None
        if palette is not None and palette.grab_current() is palette:
            palette.grab_release()

    def _close_tool_palette(self, key: str) -> None:
        self.palette_visible_vars[key].set(False)
        self._set_palette_visibility(key)

    def _toggle_default_palettes(self) -> None:
        keys = ("shapes", "measurements", "table", "media")
        show = not any(self.palette_visible_vars[key].get() for key in keys)
        for key in keys:
            self.palette_visible_vars[key].set(show)
            self._set_palette_visibility(key)
        self.status.configure(
            text="Panneaux principaux affichés." if show else "Panneaux principaux masqués."
        )

    def _set_palette_visibility(self, key: str) -> None:
        palette = self.tool_palettes.get(key)
        if palette is None:
            return
        if self.palette_visible_vars[key].get():
            x, y = self.palette_positions.get(key, (10, 10))
            palette.place(x=x, y=y, anchor="nw")
            palette.lift()
        elif palette.winfo_manager():
            palette.place_forget()

    def _dock_contextual_palettes(self, visible: set[str]) -> None:
        """Stack contextual palettes against the right edge of the drawing area."""
        self.palette_host.update_idletasks()
        y = 10
        for key in ("text_zone_style", "shape_style", "technical"):
            if key not in visible:
                continue
            palette = self.tool_palettes[key]
            palette.update_idletasks()
            x = max(10, self.palette_host.winfo_width() - palette.winfo_reqwidth() - 18)
            self.palette_positions[key] = (x, y)
            palette.place(x=x, y=y, anchor="nw")
            palette.lift()
            y += palette.winfo_reqheight() + 8

    def _redock_visible_contextual_palettes(self) -> None:
        visible = {
            key
            for key in ("text_zone_style", "shape_style", "technical")
            if self.palette_visible_vars[key].get()
        }
        if visible:
            self._dock_contextual_palettes(visible)

    def _toggle_properties_panel(self) -> None:
        visible = self.properties_visible.get()
        panes = tuple(map(str, self.body.panes()))
        panel_name = str(self.properties_panel)
        currently_visible = panel_name in panes
        if visible == currently_visible:
            visible = not currently_visible
            self.properties_visible.set(visible)
        if visible and not currently_visible:
            self.body.add(self.properties_panel, weight=1)
        elif not visible and currently_visible:
            self.body.forget(self.properties_panel)

    def _toggle_ribbon(self) -> None:
        visible = self.ribbon_visible.get()
        managed = self.ribbon.winfo_manager() == "pack"
        if visible == managed:
            visible = not managed
            self.ribbon_visible.set(visible)
        if visible and not managed:
            self.ribbon.pack(fill="x", padx=8, pady=(4, 2), before=self.body)
        elif not visible and managed:
            self.ribbon.pack_forget()

    def _build_context_menu(self) -> None:
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="Modifier le contenu", command=self._edit_selected)
        menu.add_command(label="Copier", command=self._copy_objects)
        menu.add_command(label="Coller une copie indépendante", command=self._paste_objects)
        menu.add_command(label="Dupliquer ici", command=self._duplicate_objects)
        menu.add_command(label="Assembler les objets sélectionnés", command=self._group_selected)
        menu.add_command(label="Dissocier l’assemblage", command=self._ungroup_selected)
        menu.add_command(label="Agrandir l’assemblage de 10 %", command=lambda: self._scale_selected_assembly(1.1))
        menu.add_command(label="Réduire l’assemblage de 10 %", command=lambda: self._scale_selected_assembly(0.9))
        menu.add_separator()
        rotation_menu = tk.Menu(menu, tearoff=False)
        for degrees in (5, 10, 15, 30, 45, 60, 90, 180):
            rotation_menu.add_command(
                label=f"Tourner de {degrees}°",
                command=lambda value=degrees: self._rotate_selected_degrees(value),
            )
        rotation_menu.add_separator()
        rotation_menu.add_command(label="Angle libre…", command=self._rotate_free)
        rotation_menu.add_command(label="Tourner avec copie…", command=self._rotate_with_copy)
        rotation_menu.add_command(label="Répétition circulaire…", command=self._repeat_rotation)
        menu.add_cascade(label="Rotation", menu=rotation_menu)
        symmetry_menu = tk.Menu(menu, tearoff=False)
        symmetry_menu.add_command(label="Symétrie horizontale", command=lambda: self._mirror_selected("horizontal"))
        symmetry_menu.add_command(label="Symétrie verticale", command=lambda: self._mirror_selected("vertical"))
        menu.add_cascade(label="Symétrie", menu=symmetry_menu)
        level_menu = tk.Menu(menu, tearoff=False)
        level_menu.add_command(label="Monter d’un niveau", command=lambda: self._change_selected_level(1))
        level_menu.add_command(label="Descendre d’un niveau", command=lambda: self._change_selected_level(-1))
        level_menu.add_command(label="Placer au niveau 0", command=lambda: self._set_selected_level(0))
        menu.add_cascade(label="Niveau (plan)", menu=level_menu)
        appearance_menu = tk.Menu(menu, tearoff=False)
        fill_menu = tk.Menu(appearance_menu, tearoff=False)
        fill_menu.add_command(label="Transparent", command=lambda: self._set_object_color("fill", "transparent"))
        for name, color in (("Blanc", "#FFFFFF"), ("Bleu", "#DCEBFA"), ("Vert", "#DDF3E7"), ("Orange", "#F9E8C8"), ("Rouge", "#F7D8D8")):
            fill_menu.add_command(label=name, command=lambda value=color: self._set_object_color("fill", value))
        fill_menu.add_command(label="Autre couleur…", command=lambda: self._choose_color("fill"))
        appearance_menu.add_cascade(label="Fond", menu=fill_menu)
        border_menu = tk.Menu(appearance_menu, tearoff=False)
        border_menu.add_command(label="Sans bordure", command=lambda: self._set_border_width_value(0.0))
        border_menu.add_command(label="Fine", command=lambda: self._set_border_width_value(0.5))
        border_menu.add_command(label="Normale", command=lambda: self._set_border_width_value(1.5))
        border_menu.add_command(label="Épaisse", command=lambda: self._set_border_width_value(3.0))
        border_menu.add_command(label="Très épaisse", command=lambda: self._set_border_width_value(5.0))
        border_menu.add_separator()
        border_menu.add_command(label="Continue", command=lambda: self._set_border_style_value("solid"))
        border_menu.add_command(label="Tirets", command=lambda: self._set_border_style_value("dashed"))
        border_menu.add_command(label="Pointillée", command=lambda: self._set_border_style_value("dotted"))
        border_menu.add_separator()
        border_menu.add_command(label="Couleur…", command=lambda: self._choose_color("border_color"))
        appearance_menu.add_cascade(label="Bordure", menu=border_menu)
        menu.add_cascade(label="Apparence", menu=appearance_menu)
        menu.add_command(
            label="🌐 Lien hypertexte sur l’objet…",
            command=self._set_selected_hyperlink,
        )
        menu.add_command(label="↗ Ouvrir le lien hypertexte", command=self._open_selected_hyperlink)
        menu.add_command(label="✕ Supprimer le lien hypertexte", command=self._remove_selected_hyperlink)
        menu.add_separator()
        menu.add_command(label="Appliquer à cette page", command=lambda: self._set_scope("Cette page"))
        menu.add_command(label="Appliquer à toutes les pages", command=lambda: self._set_scope("Toutes les pages"))
        menu.add_command(label="Choisir les pages…", command=lambda: self._set_scope("Pages choisies"))
        menu.add_separator()
        menu.add_command(label="Chaîner vers une autre zone de texte…", command=self._link_text_frames)
        menu.add_command(label="Délier la zone de texte", command=self._unlink_text_frame)
        menu.add_separator()
        menu.add_command(label="Afficher / masquer les propriétés", command=self._toggle_properties_panel)
        menu.add_command(label="Supprimer", command=self._delete_selected)
        self.context_menu = menu
        self.bind("<FocusOut>", self._schedule_context_menu_focus_check, add="+")
        self.bind("<Unmap>", lambda _event: self._dismiss_context_menu(), add="+")
        self.bind("<Destroy>", lambda _event: self._dismiss_context_menu(), add="+")

    def _show_context_menu(self, event: tk.Event[tk.Misc]) -> None:
        clicked = self._object_at_event(event)
        if self._pending_text_link_id and clicked is not None:
            target = self.document.objects[clicked]
            source = next(
                (item for item in self.document.objects if item.object_id == self._pending_text_link_id),
                None,
            )
            if source is not None and target.kind == "text" and target.object_id != source.object_id:
                self._pending_text_link_id = ""
                self.canvas.configure(cursor="")
                self._connect_text_frames(source, target)
                return
            self.status.configure(text="Cliquez sur une autre zone de texte pour terminer le chaînage.")
            return
        if clicked is not None and clicked not in self.selected_indices:
            self.selected = clicked
            self.selected_indices = {clicked}
            self._render()
        elif clicked is None:
            self.selected = None
            self.selected_indices.clear()
            self._render()
        self._populate_context_menu()
        try:
            self._context_menu_visible = True
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()
        self.after(120, self._watch_context_menu_focus)

    def _populate_context_menu(self) -> None:
        """Build a short menu tailored to the current selection."""
        menu = self.context_menu
        menu.delete(0, "end")
        indices = sorted(self.selected_indices)
        if not indices and self.selected is not None:
            indices = [self.selected]
        objects = [self.document.objects[index] for index in indices]

        if not objects:
            menu.add_command(label="Coller depuis le presse-papiers", command=self._paste_from_system_clipboard)
            if self._object_clipboard:
                menu.add_command(label="Coller une copie Lou Còdi", command=self._paste_objects)
            menu.add_separator()
            menu.add_command(label="Insérer une zone de texte", command=self._add_text)
            menu.add_command(label="Insérer une image…", command=self._add_image)
            menu.add_command(label="Afficher / masquer les propriétés", command=self._toggle_properties_panel)
            return

        kinds = {item.kind for item in objects}
        one = objects[0] if len(objects) == 1 else None
        if one is not None and one.kind in {"text", "table"}:
            menu.add_command(label="Modifier le contenu", command=self._edit_selected)
        menu.add_command(label="Copier", command=self._copy_objects)
        menu.add_command(label="Dupliquer", command=self._duplicate_objects)

        if one is not None and one.kind == "text":
            menu.add_separator()
            menu.add_command(label="Ouvrir ChatGPT", command=self._open_chatgpt_for_selected)
            menu.add_command(label="Coller le résultat de ChatGPT", command=self._paste_chatgpt_result)
            menu.add_command(label="Hyperlien sur un mot ou une sélection…", command=self._set_selected_hyperlink)
            if one.hyperlink or one.text_links:
                menu.add_command(label="Ouvrir le lien hypertexte", command=self._open_selected_hyperlink)
                menu.add_command(label="Supprimer le lien hypertexte", command=self._remove_selected_hyperlink)
            menu.add_command(label="Chaîner vers une autre zone de texte…", command=self._link_text_frames)
            if any(
                candidate.kind == "text" and candidate.flow_next_id == one.object_id
                for candidate in self.document.objects
            ):
                menu.add_command(
                    label="Reprendre l’apparence du cadre précédent",
                    command=self._copy_previous_text_frame_appearance,
                )
            if one.flow_next_id:
                menu.add_command(label="Délier la zone de texte", command=self._unlink_text_frame)

        if one is not None and one.kind == "table":
            structure = tk.Menu(menu, tearoff=False)
            for label, action in (
                ("Insérer une ligne au-dessus", "insert_row_before"),
                ("Insérer une ligne en dessous", "insert_row_after"),
                ("Supprimer la ligne active", "delete_row"),
                ("Insérer une colonne à gauche", "insert_column_before"),
                ("Insérer une colonne à droite", "insert_column_after"),
                ("Supprimer la colonne active", "delete_column"),
            ):
                structure.add_command(label=label, command=lambda value=action: self._change_table_structure(value))
            menu.add_cascade(label="Lignes et colonnes", menu=structure)

        if one is not None and one.kind == "image":
            menu.add_command(label="Rogner l’image…", command=self._crop_selected_image)
            image_menu = tk.Menu(menu, tearoff=False)
            image_menu.add_command(
                label="Réduire la définition / le poids…",
                command=self._resize_selected_image_pixels,
            )
            image_menu.add_command(label="Exporter en PNG ou JPEG…", command=self._export_selected_image)
            menu.add_cascade(label="Image", menu=image_menu)

        technical_kinds = {"shape", "polyline", "line", "dimension", "origin"}
        if kinds & technical_kinds:
            has_hatches = any(item.shape == "hatch" for item in objects)
            groups = {item.group for item in objects if item.group}
            if not has_hatches and groups:
                has_hatches = any(
                    item.group in groups
                    and (item.shape == "hatch" or (item.kind == "line" and not item.shape))
                    for item in self.document.objects
                )
            hatch = tk.Menu(menu, tearoff=False)
            if has_hatches:
                hatch.add_command(label="Enlever toutes les hachures", command=self._remove_selected_hatches)
            if any(self._closed_outline(item) for item in objects):
                for label, preset in (
                    ("Hachures simples", "simple"),
                    ("Hachures croisées", "cross"),
                    ("Aluminium", "aluminium"),
                    ("Personnalisées…", "custom"),
                ):
                    hatch.add_command(label=label, command=lambda value=preset: self._hatch_selected(value))
            if hatch.index("end") is not None:
                menu.add_cascade(label="Hachures", menu=hatch)

        if len(objects) > 1:
            menu.add_command(label="Assembler la sélection", command=self._group_selected)
        if any(item.group for item in objects):
            menu.add_command(label="Dissocier l’assemblage", command=self._ungroup_selected)

        transformable = kinds - {"table"}
        if transformable:
            rotation = tk.Menu(menu, tearoff=False)
            for degrees in (15, 30, 45, 90, 180):
                rotation.add_command(label=f"Tourner de {degrees}°", command=lambda value=degrees: self._rotate_selected_degrees(value))
            rotation.add_separator()
            rotation.add_command(label="Angle libre…", command=self._rotate_free)
            rotation.add_command(label="Tourner avec copie…", command=self._rotate_with_copy)
            menu.add_cascade(label="Rotation", menu=rotation)
            symmetry = tk.Menu(menu, tearoff=False)
            symmetry.add_command(label="Horizontale", command=lambda: self._mirror_selected("horizontal"))
            symmetry.add_command(label="Verticale", command=lambda: self._mirror_selected("vertical"))
            menu.add_cascade(label="Symétrie", menu=symmetry)

        appearance = tk.Menu(menu, tearoff=False)
        if kinds != {"image"}:
            appearance.add_command(label="Fond transparent", command=lambda: self._set_object_color("fill", "transparent"))
            appearance.add_command(label="Couleur du fond…", command=lambda: self._choose_color("fill"))
            appearance.add_separator()
        border = tk.Menu(appearance, tearoff=False)
        for label, width in (("Aucune", 0.0), ("Fine", 0.5), ("Normale", 1.5), ("Épaisse", 3.0), ("Très épaisse", 5.0)):
            border.add_command(label=label, command=lambda value=width: self._set_border_width_value(value))
        border.add_separator()
        border.add_command(label="Continue", command=lambda: self._set_border_style_value("solid"))
        border.add_command(label="Tirets", command=lambda: self._set_border_style_value("dashed"))
        border.add_command(label="Pointillée", command=lambda: self._set_border_style_value("dotted"))
        border.add_separator()
        border.add_command(label="Couleur…", command=lambda: self._choose_color("border_color"))
        appearance.add_cascade(label="Bordure", menu=border)
        menu.add_cascade(label="Apparence", menu=appearance)
        level = tk.Menu(menu, tearoff=False)
        level.add_command(label="Monter d’un niveau", command=lambda: self._change_selected_level(1))
        level.add_command(label="Descendre d’un niveau", command=lambda: self._change_selected_level(-1))
        level.add_command(label="Placer au niveau 0", command=lambda: self._set_selected_level(0))
        menu.add_cascade(label="Niveau (plan)", menu=level)
        if one is not None and one.kind != "text":
            menu.add_command(label="Lien hypertexte sur l’objet…", command=self._set_selected_hyperlink)
            if one.hyperlink:
                menu.add_command(label="Ouvrir le lien hypertexte", command=self._open_selected_hyperlink)
                menu.add_command(label="Supprimer le lien hypertexte", command=self._remove_selected_hyperlink)
        menu.add_separator()
        menu.add_command(label="Propriétés", command=self._toggle_properties_panel)
        menu.add_command(label="Supprimer", command=self._delete_selected)

    def _schedule_context_menu_focus_check(self, _event: tk.Event[tk.Misc]) -> None:
        if self._context_menu_visible:
            self.after(40, self._watch_context_menu_focus)

    def _watch_context_menu_focus(self) -> None:
        if not self._context_menu_visible:
            return
        try:
            if not self.context_menu.winfo_ismapped():
                self._context_menu_visible = False
                return
            if not self.winfo_viewable() or self.focus_displayof() is None:
                self._dismiss_context_menu()
                return
        except tk.TclError:
            self._context_menu_visible = False
            return
        self.after(150, self._watch_context_menu_focus)

    def _dismiss_context_menu(self) -> None:
        if not getattr(self, "_context_menu_visible", False):
            return
        self._context_menu_visible = False
        try:
            self.context_menu.unpost()
            self.context_menu.grab_release()
        except tk.TclError:
            pass

    def _checkpoint(self) -> None:
        self.undo_stack.append(copy.deepcopy(self.document))
        self.undo_stack = self.undo_stack[-80:]
        self.redo_stack.clear()

    def _has_unsaved_changes(self) -> bool:
        if self.document != self._saved_document:
            return True
        if self._editing_widget is None or not self._editing_widget.winfo_exists():
            return False
        item = next(
            (
                candidate
                for candidate in self.document.objects
                if candidate.object_id == self._editing_object_id
            ),
            None,
        )
        return item is not None and self._editing_widget.get("1.0", "end-1c") != item.text

    def _request_close(self) -> None:
        """Protect an edited project from an accidental window close."""
        if not self._has_unsaved_changes():
            self.destroy()
            return
        choice = messagebox.askyesnocancel(
            "Document non enregistré",
            "Le document contient des modifications non enregistrées.\n\n"
            "Voulez-vous les enregistrer avant de fermer ?",
            parent=self,
        )
        if choice is None:
            return
        if choice and not self._save():
            return
        self.destroy()

    def _undo(self) -> None:
        if self.undo_stack:
            self.redo_stack.append(copy.deepcopy(self.document))
            self.document = self.undo_stack.pop()
            self._after_history()

    def _redo(self) -> None:
        if self.redo_stack:
            self.undo_stack.append(copy.deepcopy(self.document))
            self.document = self.redo_stack.pop()
            self._after_history()

    def _after_history(self) -> None:
        self.current_page = min(self.current_page, self.document.page_count - 1)
        self.selected = None
        self.selected_indices.clear()
        self._render()

    def _store_active_document_tab(self, title: str | None = None) -> None:
        if not getattr(self, "_document_tabs", None):
            return
        tab = self._document_tabs[self._active_document_tab]
        tab.update(
            document=self.document,
            saved_document=self._saved_document,
            project_path=self.project_path,
            last_export=self.last_export,
            current_page=self.current_page,
            zoom=self.zoom,
            undo_stack=self.undo_stack,
            redo_stack=self.redo_stack,
        )
        if title is not None:
            tab["title"] = title

    def _restore_document_tab(self, index: int) -> None:
        tab = self._document_tabs[index]
        self.document = tab["document"]  # type: ignore[assignment]
        self._saved_document = tab["saved_document"]  # type: ignore[assignment]
        self.project_path = tab.get("project_path")  # type: ignore[assignment]
        self.last_export = tab.get("last_export")  # type: ignore[assignment]
        self.current_page = int(tab.get("current_page", 0))
        self.zoom = float(tab.get("zoom", 1.15))
        self.undo_stack = tab["undo_stack"]  # type: ignore[assignment]
        self.redo_stack = tab["redo_stack"]  # type: ignore[assignment]
        self.selected = None
        self.selected_indices.clear()

    def _switch_document_tab(self, index: int) -> None:
        if index == self._active_document_tab or not 0 <= index < len(self._document_tabs):
            return
        self._commit_inline_editor(render=False)
        self._store_active_document_tab()
        self._active_document_tab = index
        self._restore_document_tab(index)
        self._refresh_document_tabs()
        self.status.configure(text=f"Document actif : {self._document_tabs[index].get('title', 'Document')}")
        self._render()

    def _open_document_tab(
        self,
        document: CanvasDocument,
        title: str,
        *,
        project_path: Path | None = None,
        saved_document: CanvasDocument | None = None,
    ) -> None:
        self._commit_inline_editor(render=False)
        self._store_active_document_tab()
        self.document = document
        self._saved_document = copy.deepcopy(saved_document if saved_document is not None else document)
        self.project_path = project_path
        self.last_export = None
        self.current_page = 0
        self.zoom = 1.15
        self.undo_stack = []
        self.redo_stack = []
        self.selected = None
        self.selected_indices.clear()
        self._document_tabs.append({})
        self._active_document_tab = len(self._document_tabs) - 1
        self._store_active_document_tab(title)
        self._refresh_document_tabs()
        self._render()

    def _refresh_document_tabs(self) -> None:
        if not hasattr(self, "document_tab_bar"):
            return
        for child in self.document_tab_bar.winfo_children():
            child.destroy()
        for index, tab in enumerate(self._document_tabs):
            active = index == self._active_document_tab
            tk.Button(
                self.document_tab_bar,
                text=str(tab.get("title", f"Document {index + 1}")),
                command=lambda selected=index: self._switch_document_tab(selected),
                bg="#FFFFFF" if active else "#BFCBDA",
                fg=NAVY,
                relief="sunken" if active else "raised",
                padx=12,
                pady=3,
            ).pack(side="left", padx=(0, 3))
        tk.Button(
            self.document_tab_bar,
            text="＋",
            command=self._new,
            bg="#E4ECF4",
            fg=NAVY,
            relief="flat",
            padx=10,
        ).pack(side="left", padx=2)
        tk.Button(
            self.document_tab_bar,
            text="× Fermer l’onglet",
            command=self._close_document_tab,
            bg="#E4ECF4",
            fg="#7A2730",
            relief="flat",
            padx=8,
        ).pack(side="right")

    def _close_document_tab(self) -> None:
        self._commit_inline_editor(render=False)
        if self._has_unsaved_changes():
            choice = messagebox.askyesnocancel(
                "Document non enregistré",
                "Enregistrer ce document avant de fermer son onglet ?",
                parent=self,
            )
            if choice is None or choice and not self._save():
                return
        if len(self._document_tabs) == 1:
            self.document = CanvasDocument()
            self._saved_document = copy.deepcopy(self.document)
            self.project_path = None
            self.current_page = 0
            self.undo_stack = []
            self.redo_stack = []
            self._store_active_document_tab("Nouveau document")
        else:
            del self._document_tabs[self._active_document_tab]
            self._active_document_tab = min(self._active_document_tab, len(self._document_tabs) - 1)
            self._restore_document_tab(self._active_document_tab)
        self._refresh_document_tabs()
        self._render()

    def _new(self) -> None:
        self._open_document_tab(CanvasDocument(), "Nouveau document")
        self.status.configure(text="Nouvelle page A4")

    def _import_pdf(self) -> None:
        files = choose_documents(self, {".pdf"})
        if not files:
            return
        try:
            with pymupdf.open(files[0]) as pdf:
                count = pdf.page_count
        except (OSError, RuntimeError, ValueError) as exc:
            messagebox.showerror("PDF illisible", str(exc), parent=self)
            return
        self._open_document_tab(
            CanvasDocument(source_pdf=str(files[0]), page_count=max(1, count)),
            files[0].name,
        )
        self.status.configure(text=f"PDF importé comme document complet : {files[0].name}")

    def _page_size(self) -> tuple[float, float]:
        if self.document.source_pdf and Path(self.document.source_pdf).is_file():
            try:
                with pymupdf.open(self.document.source_pdf) as pdf:
                    if self.current_page < pdf.page_count:
                        rect = pdf[self.current_page].rect
                        return rect.width, rect.height
            except (OSError, RuntimeError, ValueError):
                pass
        return self.document.page_width, self.document.page_height

    def _render(self) -> None:
        # Tk peut livrer un événement Configure pendant la création d'un grand
        # PhotoImage. Sans garde, un second rendu repartait au milieu du premier
        # et doublait brutalement CPU et mémoire, surtout au-delà de 200 %.
        if self._rendering:
            return
        self._rendering = True
        if self._zoom_render_after_id is not None:
            try:
                self.after_cancel(self._zoom_render_after_id)
            except tk.TclError:
                pass
            self._zoom_render_after_id = None
        if self._editing_widget is not None:
            self._commit_inline_editor(render=False)
        self._update_associative_dimensions()
        self.canvas.delete("all")
        self._overlay_images.clear()
        width, height = self._page_size()
        if not self.document.source_pdf:
            self.page_format_var.set("A3" if max(width, height) > A4_HEIGHT + 100 else "A4")
        dw, dh = width * self.zoom, height * self.zoom
        viewport = max(self.canvas.winfo_width(), 900)
        self.page_x, self.page_y = max(48.0, (viewport - dw) / 2), 48.0
        rendered = False
        if self.document.source_pdf and Path(self.document.source_pdf).is_file():
            try:
                with pymupdf.open(self.document.source_pdf) as pdf:
                    if self.current_page < pdf.page_count:
                        pix = pdf[self.current_page].get_pixmap(matrix=pymupdf.Matrix(self.zoom, self.zoom), alpha=False)
                        self._background_image = tk.PhotoImage(data=pix.tobytes("ppm"))
                        self.canvas.create_image(self.page_x, self.page_y, image=self._background_image, anchor="nw")
                        rendered = True
            except (OSError, RuntimeError, ValueError):
                pass
        if not rendered:
            self.canvas.create_rectangle(self.page_x, self.page_y, self.page_x + dw, self.page_y + dh, fill="white", outline="#9AA5B1")
        self._draw_rulers(width, height)
        render_order = sorted(
            enumerate(self.document.objects), key=lambda indexed: (indexed[1].level, indexed[0])
        )
        for index, item in render_order:
            if self.current_page in pages_for_object(item, self.document.page_count):
                self._draw_object(index, item)
        self._draw_crop_overlay()
        if self._coincident_edge_highlight is not None:
            edge = self._coincident_edge_highlight
            self.canvas.create_line(
                self.page_x + edge.x1 * self.zoom,
                self.page_y + edge.y1 * self.zoom,
                self.page_x + edge.x2 * self.zoom,
                self.page_y + edge.y2 * self.zoom,
                fill="#18A558",
                width=5,
                tags=("coincident-edge",),
            )
            self.canvas.create_text(
                self.page_x + (edge.x1 + edge.x2) / 2 * self.zoom,
                self.page_y + (edge.y1 + edge.y2) / 2 * self.zoom - 10,
                text="BIM — bords confondus",
                fill="#087A3D",
                font=("Sans", 9, "bold"),
                tags=("coincident-edge",),
            )
        pending_edge_operation = self._pending_edge_snap or self._pending_driving_dimension
        if pending_edge_operation is not None:
            fixed_edge = pending_edge_operation.get("fixed_edge")
            if isinstance(fixed_edge, Segment):
                self.canvas.create_line(
                    self.page_x + fixed_edge.x1 * self.zoom,
                    self.page_y + fixed_edge.y1 * self.zoom,
                    self.page_x + fixed_edge.x2 * self.zoom,
                    self.page_y + fixed_edge.y2 * self.zoom,
                    fill="#E67E22",
                    width=5,
                    tags=("pending-edge",),
                )
                self.canvas.create_text(
                    self.page_x + (fixed_edge.x1 + fixed_edge.x2) / 2 * self.zoom,
                    self.page_y + (fixed_edge.y1 + fixed_edge.y2) / 2 * self.zoom - 10,
                    text="bord fixe",
                    fill="#B75400",
                    font=("Sans", 9, "bold"),
                    tags=("pending-edge",),
                )
        if len(self.selected_indices) > 1:
            objects = [self.document.objects[index] for index in self.selected_indices]
            left, top, group_width, group_height = objects_bounds(objects)
            x1 = self.page_x + left * self.zoom
            y1 = self.page_y + top * self.zoom
            x2 = x1 + group_width * self.zoom
            y2 = y1 + group_height * self.zoom
            self.canvas.create_rectangle(
                x1,
                y1,
                x2,
                y2,
                outline="#E47D16",
                width=2,
                dash=(7, 3),
                tags=("assembly-bounds",),
            )
            self.canvas.create_text(
                x1,
                y1 - 5,
                text="Assemblage",
                anchor="sw",
                fill="#A34D00",
                font=("Sans", 9, "bold"),
                tags=("assembly-bounds",),
            )
            size = 14
            self.canvas.create_rectangle(
                x2 - size / 2,
                y2 - size / 2,
                x2 + size / 2,
                y2 + size / 2,
                fill="#E47D16",
                outline="white",
                tags=("assembly-resize", "resize"),
            )
        if self.selected_indices:
            rotation_objects = [
                self.document.objects[index]
                for index in expanded_group_indices(self.document.objects, self.selected_indices)
            ]
            left, top, rotation_width, rotation_height = objects_bounds(rotation_objects)
            center_x = self.page_x + (left + rotation_width / 2) * self.zoom
            top_y = self.page_y + top * self.zoom
            handle_x = center_x
            handle_y = top_y - 30
            connection_x = center_x
            connection_y = top_y
            if len(rotation_objects) == 1 and rotation_objects[0].kind == "text":
                item = rotation_objects[0]
                corners = rotated_rectangle_points(item)
                top_middle_x = (corners[0][0] + corners[1][0]) / 2
                top_middle_y = (corners[0][1] + corners[1][1]) / 2
                item_center_x = item.x + item.width / 2
                item_center_y = item.y + item.height / 2
                normal_x = top_middle_x - item_center_x
                normal_y = top_middle_y - item_center_y
                normal_length = max(1e-9, math.hypot(normal_x, normal_y))
                connection_x = self.page_x + top_middle_x * self.zoom
                connection_y = self.page_y + top_middle_y * self.zoom
                handle_x = connection_x + normal_x / normal_length * 30
                handle_y = connection_y + normal_y / normal_length * 30
            self.canvas.create_line(
                connection_x, connection_y, handle_x, handle_y,
                fill="#1769AA", width=2, tags=("rotation-decoration",),
            )
            self.canvas.create_oval(
                handle_x - 9, handle_y - 9, handle_x + 9, handle_y + 9,
                fill="#FFFFFF", outline="#1769AA", width=2,
                tags=("rotation-handle",),
            )
            self.canvas.create_text(
                handle_x, handle_y, text="↻", fill="#1769AA",
                font=("Sans", 11, "bold"), tags=("rotation-handle",),
            )
        if self._pending_text_link_id:
            self.canvas.create_rectangle(
                self.page_x,
                0,
                self.page_x + dw,
                28,
                fill="#1E7D55",
                outline="",
                tags=("link-help",),
            )
            self.canvas.create_text(
                self.page_x + dw / 2,
                14,
                text="CHAÎNAGE : cliquez sur le cadre vert qui doit recevoir la suite  •  Échap pour annuler",
                fill="white",
                font=("Sans", 10, "bold"),
                tags=("link-help",),
            )
        self.canvas.configure(scrollregion=(0, 0, max(viewport, self.page_x + dw + 40), self.page_y + dh + 35))
        self.page_label.configure(text=f"Page {self.current_page + 1} / {self.document.page_count}")
        self.zoom_label.configure(text=f"{round(self.zoom * 100)} %")
        self._show_properties()
        self._update_contextual_ribbon()
        self._rendering = False

    def _update_contextual_ribbon(self) -> None:
        """Only expose commands that apply to the selected object."""
        kind = None
        if self.selected is not None and self.selected < len(self.document.objects):
            kind = self.document.objects[self.selected].kind
        states = {
            "table": kind == "table",
            "technical": kind in {"line", "polyline", "shape", "dimension", "origin"}
            or len(self.selected_indices) > 1,
        }
        current = self.ribbon.select()
        for name, frame in self._contextual_ribbon_tabs.items():
            self.ribbon.tab(frame, state="normal" if states[name] else "hidden")
        contextual_name = "table" if kind == "table" else "technical" if states["technical"] else None
        if contextual_name is not None and contextual_name != self._last_context_kind:
            self.ribbon.select(self._contextual_ribbon_tabs[contextual_name])
        visible_frames = [
            str(frame) for name, frame in self._contextual_ribbon_tabs.items() if states[name]
        ]
        if current and current not in visible_frames:
            current_state = self.ribbon.tab(current, "state")
            if current_state == "hidden":
                self.ribbon.select(0)
        self._last_context_kind = contextual_name
        palette_context = (
            "table" if kind == "table" else
            "text" if kind == "text" else
            "media" if kind in {"image", "mask"} else
            "technical" if states["technical"] else
            "general"
        )
        if palette_context != self._last_palette_context:
            contextual = {
                "general": set(),
                "text": set(),
                "table": set(),
                "media": {"shape_style"},
                "technical": {"shape_style", "technical"},
            }[palette_context]
            for key in ("text_zone_style", "shape_style", "technical"):
                variable = self.palette_visible_vars[key]
                variable.set(key in contextual)
                self._set_palette_visibility(key)
            self._dock_contextual_palettes(contextual)
            self._last_palette_context = palette_context

    def _draw_rulers(self, width: float, height: float) -> None:
        """Draw page rulers in millimetres around the current sheet."""
        points_per_mm = 72 / 25.4
        page_right = self.page_x + width * self.zoom
        page_bottom = self.page_y + height * self.zoom
        self.canvas.create_rectangle(self.page_x, self.page_y - 24, page_right, self.page_y, fill="#EEF2F6", outline="#A8B2BD", tags=("ruler",))
        self.canvas.create_rectangle(self.page_x - 32, self.page_y, self.page_x, page_bottom, fill="#EEF2F6", outline="#A8B2BD", tags=("ruler",))
        for millimetre in range(0, int(width / points_per_mm) + 1, 10):
            px = self.page_x + millimetre * points_per_mm * self.zoom
            major = millimetre % 50 == 0
            self.canvas.create_line(px, self.page_y - (14 if major else 8), px, self.page_y, fill="#52677C", tags=("ruler",))
            if major:
                self.canvas.create_text(px + 2, self.page_y - 16, text=str(millimetre), anchor="sw", font=("Sans", 7), fill="#385571", tags=("ruler",))
        for millimetre in range(0, int(height / points_per_mm) + 1, 10):
            py = self.page_y + millimetre * points_per_mm * self.zoom
            major = millimetre % 50 == 0
            self.canvas.create_line(self.page_x - (14 if major else 8), py, self.page_x, py, fill="#52677C", tags=("ruler",))
            if major:
                self.canvas.create_text(self.page_x - 16, py + 2, text=str(millimetre), anchor="ne", font=("Sans", 7), fill="#385571", tags=("ruler",))

    def _draw_object(self, index: int, item: PageObject) -> None:
        x, y = self.page_x + item.x * self.zoom, self.page_y + item.y * self.zoom
        w, h = item.width * self.zoom, item.height * self.zoom
        if self.zoom > 1.6:
            visible_left = self.canvas.canvasx(0) - 40
            visible_top = self.canvas.canvasy(0) - 40
            visible_right = self.canvas.canvasx(self.canvas.winfo_width()) + 40
            visible_bottom = self.canvas.canvasy(self.canvas.winfo_height()) + 40
            if (
                x + w < visible_left
                or x > visible_right
                or y + h < visible_top
                or y > visible_bottom
            ):
                return
        tag, selected = f"object:{index}", index in self.selected_indices
        if self._pending_text_link_id and item.kind == "text":
            outline = "#E47D16" if item.object_id == self._pending_text_link_id else "#1E9B66"
        else:
            outline = "#1769AA" if selected else "#72879C"
        tags = (tag, "object")
        if item.kind == "mask":
            fill = "" if item.fill.lower() == "transparent" else item.fill
            border = item.border_color if item.border_width > 0 else outline if selected else ""
            border_width = (
                max(1, round(item.border_width * self.zoom))
                if item.border_width > 0 else 3 if selected else 0
            )
            self.canvas.create_rectangle(
                x, y, x + w, y + h, fill=fill, outline=border,
                width=border_width, tags=tags,
            )
        elif item.kind == "image":
            try:
                with Image.open(item.image_path) as source:
                    preview = source.copy()
                preview = preview.resize(
                    (max(1, int(w)), max(1, int(h))), Image.Resampling.BILINEAR
                )
                picture = ImageTk.PhotoImage(preview)
                self._overlay_images.append(picture)
                self.canvas.create_image(x + w / 2, y + h / 2, image=picture, tags=tags)
            except OSError:
                self.canvas.create_text(x + 4, y + 4, text="Image introuvable", anchor="nw", tags=tags)
            border = item.border_color if item.border_width > 0 else outline
            border_width = max(1, round(item.border_width * self.zoom)) if item.border_width > 0 else (3 if selected else 1)
            dash = (6, 4) if item.border_style == "dashed" else (2, 3) if item.border_style == "dotted" else None
            self.canvas.create_rectangle(x, y, x + w, y + h, outline=border, width=border_width, dash=dash, tags=tags)
        elif item.kind == "table":
            cells = self._ensure_table_cells(item)
            rows = evaluate_table_cells(cells)
            columns = max((len(row) for row in rows), default=1)
            row_offsets = table_grid_offsets(item.table_row_heights, len(rows), h)
            column_offsets = table_grid_offsets(item.table_column_widths, columns, w)
            for row_index, row in enumerate(rows):
                for column_index in range(columns):
                    merge = self._table_merge_for_cell(item, row_index, column_index)
                    if merge and (row_index, column_index) != (merge[0], merge[1]):
                        continue
                    row_span, column_span = (merge[2], merge[3]) if merge else (1, 1)
                    cx = x + column_offsets[column_index]
                    cy = y + row_offsets[row_index]
                    cell_w = column_offsets[column_index + column_span] - column_offsets[column_index]
                    cell_h = row_offsets[row_index + row_span] - row_offsets[row_index]
                    metadata = cells[row_index][column_index]
                    default_fill, cell_text_color = table_cell_colors(item.table_style, row_index)
                    cell_fill = str(metadata.get("fill") or default_fill)
                    self.canvas.create_rectangle(
                        cx, cy, cx + cell_w, cy + cell_h,
                        fill=cell_fill,
                        outline=str(metadata.get("border_color", "")),
                        width=max(0, round(float(metadata.get("border_width", 0) or 0) * self.zoom)),
                        tags=tags,
                    )
                    value = row[column_index] if column_index < len(row) else ""
                    image_path = metadata.get("image_path", "")
                    vertical_align = metadata.get("vertical_align", "top")
                    horizontal_align = metadata.get("horizontal_align", "left")
                    cell_font_size = float(metadata.get("font_size", item.font_size) or item.font_size)
                    value, cell_font_size = fitted_table_cell_text(
                        value,
                        cell_w / self.zoom,
                        cell_h / self.zoom,
                        cell_font_size,
                        bold=bool(metadata.get("bold", False)),
                        italic=bool(metadata.get("italic", False)),
                    )
                    cell_font_style = " ".join(
                        name
                        for name, enabled in (
                            ("bold", metadata.get("bold")),
                            ("italic", metadata.get("italic")),
                            ("underline", metadata.get("underline")),
                        )
                        if enabled
                    ) or "normal"
                    text_x = cx + 4 if horizontal_align == "left" else cx + cell_w / 2 if horizontal_align == "center" else cx + cell_w - 4
                    text_y = cy + 3 if vertical_align == "top" else cy + cell_h / 2 if vertical_align == "middle" else cy + cell_h - 3
                    text_anchor = {
                        ("top", "left"): "nw", ("top", "center"): "n", ("top", "right"): "ne",
                        ("middle", "left"): "w", ("middle", "center"): "center", ("middle", "right"): "e",
                        ("bottom", "left"): "sw", ("bottom", "center"): "s", ("bottom", "right"): "se",
                    }.get((vertical_align, horizontal_align), "nw")
                    if image_path:
                        try:
                            with Image.open(image_path) as source:
                                preview = source.copy()
                            preview.thumbnail((max(1, int(cell_w - 8)), max(1, int(cell_h * 0.58))))
                            picture = ImageTk.PhotoImage(preview)
                            self._overlay_images.append(picture)
                            self.canvas.create_image(cx + cell_w / 2, cy + 3, image=picture, anchor="n", tags=tags)
                            text_y = cy + cell_h * 0.62
                        except OSError:
                            pass
                    hyperlink = metadata.get("hyperlink", "")
                    text_color = (
                        "#7FDBFF"
                        if hyperlink and row_index == 0 and item.table_style != "plain"
                        else "#1769AA"
                        if hyperlink
                        else str(metadata.get("color", cell_text_color))
                    )
                    cell_picture = self._table_cell_preview(
                        value,
                        max(1, round(cell_w)),
                        max(1, round(cell_h)),
                        cell_font_size,
                        horizontal_align=str(horizontal_align),
                        vertical_align=str(vertical_align),
                        color=text_color,
                        highlight=str(metadata.get("highlight", "")),
                        bold=bool(metadata.get("bold", False)),
                        italic=bool(metadata.get("italic", False)),
                        underline=bool(metadata.get("underline", False) or hyperlink),
                        bottom_text=str(metadata.get("bottom_text", "")),
                        bottom_color=str(metadata.get("bottom_color", text_color)),
                    )
                    self._overlay_images.append(cell_picture)
                    self.canvas.create_image(
                        cx,
                        cy,
                        image=cell_picture,
                        anchor="nw",
                        tags=tags,
                    )
                    active_cell = self._active_table_cell
                    if (
                        selected
                        and active_cell is not None
                        and active_cell == (item.object_id, row_index, column_index)
                    ):
                        self.canvas.create_rectangle(
                            cx + 1,
                            cy + 1,
                            cx + cell_w - 1,
                            cy + cell_h - 1,
                            fill="",
                            outline="#E47D16",
                            width=max(2, round(2 * self.zoom)),
                            tags=tags + ("active-table-cell",),
                        )
            inner_width = max(0, round(item.table_inner_border_width * self.zoom))
            border_color = item.border_color
            if inner_width:
                for column in range(1, columns):
                    grid_x = x + column_offsets[column]
                    for row in range(len(rows)):
                        if not self._table_grid_hidden(item, row, column - 1, row, column):
                            self.canvas.create_line(grid_x, y + row_offsets[row], grid_x, y + row_offsets[row + 1], fill=border_color, width=inner_width, tags=tags)
                for row in range(1, len(rows)):
                    grid_y = y + row_offsets[row]
                    row_width = item.table_row_border_widths.get(str(row - 1), item.table_inner_border_width)
                    for column in range(columns):
                        if not self._table_grid_hidden(item, row - 1, column, row, column):
                            self.canvas.create_line(x + column_offsets[column], grid_y, x + column_offsets[column + 1], grid_y, fill=border_color, width=max(1, round(row_width * self.zoom)), tags=tags)
            for row_text, row_width in item.table_row_border_widths.items():
                row = int(row_text)
                if 0 <= row < len(rows):
                    for grid_y in (y + row_offsets[row], y + row_offsets[row + 1]):
                        self.canvas.create_line(x, grid_y, x + w, grid_y, fill=border_color, width=max(1, round(row_width * self.zoom)), tags=tags)
            for border_range in item.table_border_ranges:
                left = int(border_range.get("left", 0))
                top = int(border_range.get("top", 0))
                right = int(border_range.get("right", left))
                bottom = int(border_range.get("bottom", top))
                line_width = max(1, round(float(border_range.get("width", 1.5)) * self.zoom))
                self.canvas.create_rectangle(
                    x + column_offsets[left], y + row_offsets[top],
                    x + column_offsets[right + 1], y + row_offsets[bottom + 1],
                    fill="", outline=border_color, width=line_width, tags=tags,
                )
            if item.table_outer_border_width > 0:
                self.canvas.create_rectangle(
                    x, y, x + w, y + h, fill="", outline=border_color,
                    width=max(1, round(item.table_outer_border_width * self.zoom)), tags=tags,
                )
            if selected:
                self.canvas.create_rectangle(x, y, x + w, y + h, outline=outline, width=3, tags=tags)
        elif item.kind == "shape":
            dash = (5, 3) if item.border_style == "dashed" else (1, 3) if item.border_style == "dotted" else None
            options = {
                "fill": "" if item.fill.lower() in {"", "none", "transparent"} else item.fill,
                "outline": item.border_color,
                "width": max(1, round(item.border_width * self.zoom)),
                "dash": dash,
                "tags": tags,
            }
            if item.shape in {"ellipse", "circle"}:
                self.canvas.create_oval(x, y, x + w, y + h, **options)
            elif item.shape == "triangle":
                self.canvas.create_polygon(x + w / 2, y, x + w, y + h, x, y + h, **options)
            elif item.shape == "trapezoid":
                inset = w * 0.2
                self.canvas.create_polygon(x + inset, y, x + w - inset, y, x + w, y + h, x, y + h, **options)
            elif item.shape == "arrow":
                if item.rotation % 180 == 90:
                    middle, head, thickness = x + w / 2, h * 0.28, w * 0.28
                    points = [
                        (middle - thickness, y), (middle - thickness, y + h - head),
                        (x, y + h - head), (middle, y + h), (x + w, y + h - head),
                        (middle + thickness, y + h - head), (middle + thickness, y),
                    ]
                    if item.flip_vertical:
                        points = [(px, 2 * y + h - py) for px, py in points]
                else:
                    middle, head, thickness = y + h / 2, w * 0.28, h * 0.28
                    points = [
                        (x, middle - thickness), (x + w - head, middle - thickness),
                        (x + w - head, y), (x + w, middle), (x + w - head, y + h),
                        (x + w - head, middle + thickness), (x, middle + thickness),
                    ]
                    if item.flip_horizontal:
                        points = [(2 * x + w - px, py) for px, py in points]
                self.canvas.create_polygon(*(coordinate for point in points for coordinate in point), **options)
            else:
                self.canvas.create_rectangle(x, y, x + w, y + h, **options)
        elif item.kind == "origin":
            size = 16
            self.canvas.create_line(x - size, y, x + size, y, fill="#C62828", width=2, arrow="last", tags=tags)
            self.canvas.create_line(x, y + size, x, y - size, fill="#C62828", width=2, arrow="last", tags=tags)
            self.canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill="white", outline="#C62828", width=2, tags=tags)
            self.canvas.create_text(x + 8, y - 8, text="X0 / Z0", fill="#C62828", anchor="sw", font=("Sans", 9, "bold"), tags=tags)
        elif item.kind == "line":
            dash = (8, 3, 2, 3) if item.shape == "axis" else (5, 3) if item.border_style == "dashed" else (1, 3) if item.border_style == "dotted" else None
            line_color = "#14804A" if item.shape == "axis" and item.locked else item.border_color
            self.canvas.create_line(x, y, x + w, y + h, fill=line_color, width=max(1, item.border_width * self.zoom), dash=dash, tags=tags)
            if item.shape == "axis" and item.locked:
                self.canvas.create_text(x + w, y - 8, text="🔒 axe 3D", fill="#14804A", anchor="se", font=("Sans", 8, "bold"), tags=tags)
        elif item.kind == "dimension":
            self._draw_dimension(item, x, y, w, h, tags, selected)
        elif item.kind == "polyline":
            dash = (5, 3) if item.border_style == "dashed" else (1, 3) if item.border_style == "dotted" else None
            closed = (
                len(item.points) >= 3
                and math.dist(item.points[0], item.points[-1]) <= 1e-6
            )
            coordinates = [
                coordinate
                for point in item.points
                for coordinate in (self.page_x + (item.x + point[0]) * self.zoom, self.page_y + (item.y + point[1]) * self.zoom)
            ]
            if len(coordinates) >= 4:
                if closed:
                    self.canvas.create_polygon(
                        *coordinates,
                        fill="" if item.fill.lower() in {"", "none", "transparent"} else item.fill,
                        outline=item.border_color,
                        width=max(1, item.border_width * self.zoom),
                        dash=dash,
                        tags=tags,
                    )
                else:
                    self.canvas.create_line(*coordinates, fill=item.border_color, width=max(1, item.border_width * self.zoom), dash=dash, tags=tags)
            if selected and len(self.selected_indices) == 1:
                for point_index, point in enumerate(item.points):
                    px = self.page_x + (item.x + point[0]) * self.zoom
                    py = self.page_y + (item.y + point[1]) * self.zoom
                    self.canvas.create_oval(
                        px - 5,
                        py - 5,
                        px + 5,
                        py + 5,
                        fill=(
                            "#C92828"
                            if self._selected_vertex == (index, point_index)
                            else "#E87524"
                        ),
                        outline="white",
                        width=1,
                        tags=(f"vertex:{index}:{point_index}", "vertex-handle"),
                    )
        elif item.kind == "chart":
            self._draw_chart_preview(item, x, y, w, h, tags)
        elif item.kind == "text" and item.source_id == "measurement":
            if selected:
                self.canvas.create_rectangle(
                    x, y, x + w, y + h, fill="", outline="#1769AA", width=2, tags=tags
                )
            self.canvas.create_text(
                x + 3,
                y + h / 2,
                text=item.text,
                anchor="w",
                fill=item.color,
                font=(
                    "Sans",
                    max(8, round(item.font_size * self.zoom)),
                    "bold" if item.bold else "normal",
                ),
                tags=tags,
            )
        else:
            source_name = Path(self.document.source_pdf).stem if self.document.source_pdf else (self.project_path.stem if self.project_path else "Nouveau document")
            flowed_text, style_source, flow_offset = flowed_text_context(
                item, self.document.objects
            )
            displayed_text = resolve_dynamic_text(flowed_text, self.current_page, self.document.page_count, source_name)
            render_item = copy.copy(item)
            if style_source.object_id != item.object_id:
                for attribute in (
                    "font_family", "font_size", "bold", "italic", "underline",
                    "strikethrough", "color", "align",
                ):
                    setattr(render_item, attribute, getattr(style_source, attribute))
                flow_end = flow_offset + len(flowed_text)
                render_item.text_styles = [
                    {
                        **run,
                        "start": max(0, int(run.get("start", 0)) - flow_offset),
                        "end": min(len(flowed_text), int(run.get("end", 0)) - flow_offset),
                    }
                    for run in style_source.text_styles
                    if int(run.get("start", 0)) < flow_end
                    and int(run.get("end", 0)) > flow_offset
                ]
                render_item.paragraph_alignments = [
                    {
                        **run,
                        "start": max(0, int(run.get("start", 0)) - flow_offset),
                        "end": min(len(flowed_text), int(run.get("end", 0)) - flow_offset),
                    }
                    for run in style_source.paragraph_alignments
                    if int(run.get("start", 0)) < flow_end
                    and int(run.get("end", 0)) > flow_offset
                ]
                render_item.text_links = [
                    {
                        **run,
                        "start": max(0, int(run.get("start", 0)) - flow_offset),
                        "end": min(len(flowed_text), int(run.get("end", 0)) - flow_offset),
                    }
                    for run in style_source.text_links
                    if int(run.get("start", 0)) < flow_end
                    and int(run.get("end", 0)) > flow_offset
                ]
            emphasized = selected or bool(self._pending_text_link_id and item.kind == "text")
            if item.kind != "text":
                self.canvas.create_rectangle(
                    x, y, x + w, y + h,
                    fill="" if item.fill.lower() in {"", "none", "transparent"} else item.fill,
                    outline=outline, width=4 if emphasized else 1, tags=tags,
                )
            try:
                crop_box: tuple[int, int, int, int] | None = None
                if self.zoom > 1.6 and not float(render_item.rotation) % 360:
                    visible_left = self.canvas.canvasx(0)
                    visible_top = self.canvas.canvasy(0)
                    visible_right = self.canvas.canvasx(self.canvas.winfo_width())
                    visible_bottom = self.canvas.canvasy(self.canvas.winfo_height())
                    crop_left = max(0, round(visible_left - x) - 24)
                    crop_top = max(0, round(visible_top - y) - 24)
                    crop_right = min(round(w), round(visible_right - x) + 24)
                    crop_bottom = min(round(h), round(visible_bottom - y) + 24)
                    if crop_right > crop_left and crop_bottom > crop_top:
                        crop_box = (crop_left, crop_top, crop_right, crop_bottom)
                picture = self._text_preview(
                    render_item,
                    displayed_text,
                    max(1, round(w)),
                    max(1, round(h)),
                    crop_box=crop_box,
                )
                self._overlay_images.append(picture)
                if crop_box is None:
                    picture_x, picture_y = x + w / 2, y + h / 2
                else:
                    crop_left, crop_top, crop_right, crop_bottom = crop_box
                    picture_x = x + (crop_left + crop_right) / 2
                    picture_y = y + (crop_top + crop_bottom) / 2
                self.canvas.create_image(
                    picture_x, picture_y, image=picture, anchor="center", tags=tags
                )
            except Exception as exc:
                # Même un ancien document mal formé doit rester borné par son
                # cadre et tourner avec lui. L'ancien secours Canvas dessinait
                # tout le texte sans découpage et sans rotation.
                print(
                    f"Lou Còdi: aperçu texte simplifié ({type(exc).__name__}: {exc})",
                    file=sys.stderr,
                )
                picture = self._basic_text_preview(
                    render_item, displayed_text, max(1, round(w)), max(1, round(h))
                )
                self._overlay_images.append(picture)
                self.canvas.create_image(
                    x + w / 2, y + h / 2, image=picture, anchor="center", tags=tags
                )
            if item.kind == "text" and emphasized:
                selection_points = [
                    coordinate
                    for point in rotated_rectangle_points(item)
                    for coordinate in (
                        self.page_x + point[0] * self.zoom,
                        self.page_y + point[1] * self.zoom,
                    )
                ]
                self.canvas.create_polygon(
                    *selection_points, fill="", outline=outline, width=2, dash=(6, 4), tags=tags,
                )
            elif item.kind != "text":
                self.canvas.create_rectangle(
                    x, y, x + w, y + h,
                    outline=outline if emphasized else "",
                    width=4 if emphasized else 0,
                    dash=None if emphasized or item.border_style == "solid" else (5, 3) if item.border_style == "dashed" else (1, 3),
                    tags=tags,
                )
            linked = item.flow_next_id or any(
                candidate.flow_next_id == item.object_id for candidate in self.document.objects
            )
            if linked:
                self.canvas.create_text(
                    x + w - 5,
                    y + h - 5,
                    text="↳",
                    fill="#1769AA",
                    anchor="se",
                    font=("Sans", 14, "bold"),
                    tags=tags,
                )
        if item.hyperlink:
            self.canvas.create_line(
                x + 2, y + h - 2, x + w - 2, y + h - 2,
                fill="#1769AA", width=2, tags=tags,
            )
            self.canvas.create_text(
                x + w - 4, y + 4, text="↗", anchor="ne", fill="#1769AA",
                font=("Sans", 11, "bold"), tags=tags,
            )
        if selected and len(self.selected_indices) == 1:
            size = 12
            if item.kind == "line":
                self.canvas.create_rectangle(
                    x - size / 2,
                    y - size / 2,
                    x + size / 2,
                    y + size / 2,
                    fill="#1769AA",
                    outline="white",
                    tags=(f"resize-start:{index}", "resize"),
                )
            resize_x, resize_y = x + w, y + h
            if item.kind == "text":
                bottom_right = rotated_rectangle_points(item)[2]
                resize_x = self.page_x + bottom_right[0] * self.zoom
                resize_y = self.page_y + bottom_right[1] * self.zoom
            self.canvas.create_rectangle(
                resize_x - size / 2,
                resize_y - size / 2,
                resize_x + size / 2,
                resize_y + size / 2,
                fill="#1769AA",
                outline="white",
                tags=(f"resize-end:{index}", "resize"),
            )

    def _draw_dimension(
        self,
        item: PageObject,
        x: float,
        y: float,
        width: float,
        height: float,
        tags: tuple[str, str],
        selected: bool,
    ) -> None:
        color = "#1769AA" if selected else item.border_color
        line_width = 2 if selected else 1
        anchors = item.points if len(item.points) == 2 else [[item.x, item.y], [item.x + item.width, item.y + item.height]]
        anchor_coordinates = [
            (
                self.page_x + float(point[0]) * self.zoom,
                self.page_y + float(point[1]) * self.zoom,
            )
            for point in anchors
        ]
        for anchor, endpoint in zip(anchor_coordinates, ((x, y), (x + width, y + height)), strict=True):
            self.canvas.create_line(
                anchor[0],
                anchor[1],
                endpoint[0],
                endpoint[1],
                fill=color,
                width=line_width,
                tags=tags,
            )
        self.canvas.create_line(
            x,
            y,
            x + width,
            y + height,
            fill=color,
            width=line_width,
            arrow="both",
            arrowshape=(8, 10, 4),
            tags=tags,
        )
        length = math.hypot(width, height)
        if length > 1:
            normal_x, normal_y = -height / length * 8, width / length * 8
            for px, py in ((x, y), (x + width, y + height)):
                self.canvas.create_line(
                    px - normal_x,
                    py - normal_y,
                    px + normal_x,
                    py + normal_y,
                    fill=color,
                    width=line_width,
                    tags=tags,
                )
        label_x, label_y, label_angle = dimension_label_layout(
            (x, y), (x + width, y + height), gap=13.0
        )
        self.canvas.create_text(
            label_x,
            label_y,
            text=f"{item.text} mm",
            fill=color,
            font=("Sans", 9, "bold"),
            anchor="center",
            angle=label_angle,
            tags=tags,
        )

    def _table_cell_preview(
        self,
        value: str,
        width: int,
        height: int,
        font_size: float,
        *,
        horizontal_align: str,
        vertical_align: str,
        color: str,
        highlight: str,
        bold: bool,
        italic: bool,
        underline: bool,
        bottom_text: str = "",
        bottom_color: str = "#000000",
    ) -> ImageTk.PhotoImage:
        """Draw one table cell into a clipped bitmap so it cannot cover neighbours."""
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        pixel_size = max(5, round(font_size * self.zoom))
        try:
            font_file = _font_file("Sans-serif", bold, italic)
            font = ImageFont.truetype(font_file, pixel_size) if font_file else ImageFont.load_default()
        except (OSError, TypeError):
            font = ImageFont.load_default()
        lines = value.split("\n") if value else []
        line_height = max(6, round(pixel_size * 1.2))
        block_height = len(lines) * line_height
        cell_padding = max(3, round(5 * self.zoom))
        if vertical_align == "middle":
            start_y = max(cell_padding, (height - block_height) // 2)
        elif vertical_align == "bottom":
            start_y = max(cell_padding, height - block_height - cell_padding)
        else:
            start_y = cell_padding
        safe_color = safe_pillow_color(color, "#000000")
        safe_highlight = safe_pillow_color(highlight, "", allow_transparent=True)
        for line_number, line in enumerate(lines):
            line_width = float(draw.textlength(line, font=font))
            if horizontal_align == "center":
                line_x = max(float(cell_padding), (width - line_width) / 2)
            elif horizontal_align == "right":
                line_x = max(
                    float(cell_padding), width - line_width - cell_padding
                )
            else:
                line_x = float(cell_padding)
            line_y = start_y + line_number * line_height
            if line_y >= height:
                break
            if safe_highlight:
                draw.rectangle(
                    (line_x, line_y, min(width - 1, line_x + line_width), min(height - 1, line_y + line_height)),
                    fill=safe_highlight,
                )
            draw.text((line_x, line_y), line, font=font, fill=safe_color)
            if underline:
                underline_y = min(height - 1, line_y + pixel_size + 1)
                draw.line((line_x, underline_y, min(width - 1, line_x + line_width), underline_y), fill=safe_color, width=1)
        if bottom_text:
            bottom_value = bottom_text.strip()
            bottom_width = float(draw.textlength(bottom_value, font=font))
            bottom_x = max(float(cell_padding), (width - bottom_width) / 2)
            bottom_y = max(cell_padding, height - line_height - cell_padding)
            draw.text(
                (bottom_x, bottom_y),
                bottom_value,
                font=font,
                fill=safe_pillow_color(bottom_color, safe_color),
            )
        return ImageTk.PhotoImage(image)

    def _text_preview(
        self,
        item: PageObject,
        text: str,
        width: int,
        height: int,
        *,
        crop_box: tuple[int, int, int, int] | None = None,
    ) -> ImageTk.PhotoImage:
        """Render a flat text frame, then rotate its transparent bitmap around its centre."""
        cache_key = (
            item.object_id,
            text,
            width,
            height,
            round(self.zoom, 4),
            item.font_family,
            item.font_size,
            item.bold,
            item.italic,
            item.underline,
            item.strikethrough,
            item.color,
            item.fill,
            item.border_color,
            item.border_width,
            item.border_style,
            item.rotation,
            repr(item.text_styles),
            repr(item.text_links),
            repr(item.paragraph_alignments),
            crop_box,
        )
        cache = getattr(self, "_text_preview_cache", None)
        if cache is None:
            cache = self._text_preview_cache = {}
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        render_item = copy.copy(item)
        render_item.font_size = safe_number(render_item.font_size, 12.0, minimum=1.0)
        render_item.border_width = safe_number(render_item.border_width, 0.0, minimum=0.0)
        render_item.rotation = safe_number(render_item.rotation, 0.0)
        render_item.font_family = str(render_item.font_family or "Sans-serif")
        render_item.color = safe_pillow_color(render_item.color, "#000000")
        render_item.border_color = safe_pillow_color(render_item.border_color, "#000000")
        render_item.fill = safe_pillow_color(render_item.fill, "#FFFFFF", allow_transparent=True)
        render_item.text_styles = [
            {
                **run,
                "start": safe_text_offset(run.get("start", 0)),
                "end": safe_text_offset(run.get("end", 0)),
            }
            for run in render_item.text_styles
            if isinstance(run, dict)
        ]
        render_item.text_links = [
            {
                **run,
                "start": safe_text_offset(run.get("start", 0)),
                "end": safe_text_offset(run.get("end", 0)),
            }
            for run in render_item.text_links
            if isinstance(run, dict)
        ]
        render_item.paragraph_alignments = [
            {
                **run,
                "start": safe_text_offset(run.get("start", 0)),
                "end": safe_text_offset(run.get("end", 0)),
            }
            for run in render_item.paragraph_alignments
            if isinstance(run, dict)
        ]
        render_width, render_height = max(1, width), max(1, height)
        origin_x = origin_y = 0
        bitmap_width, bitmap_height = render_width, render_height
        if crop_box is not None and not float(render_item.rotation) % 360:
            left, top, right, bottom = crop_box
            origin_x, origin_y = max(0, left), max(0, top)
            bitmap_width = max(1, min(render_width, right) - origin_x)
            bitmap_height = max(1, min(render_height, bottom) - origin_y)
        transparent = not render_item.fill
        image = Image.new("RGBA", (bitmap_width, bitmap_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        if not transparent:
            draw.rectangle((0, 0, bitmap_width - 1, bitmap_height - 1), fill=render_item.fill)
        if render_item.border_width > 0:
            border_width = max(1, round(render_item.border_width * self.zoom))
            draw_styled_rectangle(
                draw,
                (
                    border_width // 2 - origin_x,
                    border_width // 2 - origin_y,
                    render_width - 1 - border_width // 2 - origin_x,
                    render_height - 1 - border_width // 2 - origin_y,
                ),
                color=render_item.border_color,
                width=border_width,
                style=render_item.border_style,
            )
        size = max(7, round(render_item.font_size * self.zoom))
        suffix = "-BoldOblique" if render_item.bold and render_item.italic else "-Bold" if render_item.bold else "-Oblique" if render_item.italic else ""
        family = "DejaVuSansMono" if render_item.font_family == "Monospace" else "DejaVuSerif" if render_item.font_family == "Serif" else "DejaVuSans"
        try:
            font = ImageFont.truetype(f"{family}{suffix}.ttf", size)
        except OSError:
            font = ImageFont.load_default()
        lines = wrapped_text_ranges(text, render_item)
        style_lookup = resolved_text_styles(render_item, len(text))
        line_height = text_frame_line_height(render_item) * self.zoom
        visible_lines = text_frame_line_capacity(render_item)
        for row, (line, line_start, line_end) in enumerate(lines[:visible_lines]):
            py = text_frame_vertical_inset(render_item) * self.zoom + row * line_height
            if py + line_height < origin_y or py > origin_y + bitmap_height:
                continue
            boundaries = {line_start, line_end}
            for link in render_item.text_links:
                boundaries.add(max(line_start, min(line_end, safe_text_offset(link.get("start", 0)))))
                boundaries.add(max(line_start, min(line_end, safe_text_offset(link.get("end", 0)))))
            for style_run in render_item.text_styles:
                boundaries.add(max(line_start, min(line_end, safe_text_offset(style_run.get("start", 0)))))
                boundaries.add(max(line_start, min(line_end, safe_text_offset(style_run.get("end", 0)))))
            ordered = sorted(boundaries)
            fragments: list[tuple[str, dict[str, object], ImageFont.FreeTypeFont | ImageFont.ImageFont, bool, float]] = []
            for start, end in pairwise(ordered):
                fragment = text[start:end]
                fragment_style = (
                    style_lookup[start]
                    if 0 <= start < len(style_lookup)
                    else text_style_at(render_item, start)
                )
                fragment_size = max(7, round(safe_number(fragment_style.get("font_size"), render_item.font_size, minimum=1.0) * self.zoom))
                try:
                    fragment_file = _font_file(
                        str(fragment_style.get("font_family", render_item.font_family)),
                        bool(fragment_style.get("bold", render_item.bold)),
                        bool(fragment_style.get("italic", render_item.italic)),
                    )
                    fragment_font = ImageFont.truetype(fragment_file, fragment_size) if fragment_file else font
                except (OSError, TypeError):
                    fragment_font = font
                linked = any(
                    safe_text_offset(link.get("start", 0)) < end
                    and safe_text_offset(link.get("end", 0)) > start
                    and link.get("hyperlink")
                    for link in render_item.text_links
                )
                fragment_width = float(draw.textlength(fragment, font=fragment_font))
                fragments.append((fragment, fragment_style, fragment_font, linked, fragment_width))
            actual_line_width = sum(fragment[4] for fragment in fragments)
            padding = text_frame_horizontal_inset(render_item) * self.zoom
            line_alignment = paragraph_alignment_at(render_item, line_start)
            justify_line = (
                line_alignment == "justify"
                and line_end < len(text)
                and text[line_end : line_end + 1] != "\n"
            )
            spaces = sum(fragment[0].count(" ") for fragment in fragments)
            extra_space = (
                max(0.0, render_width - 2 * padding - actual_line_width) / spaces
                if justify_line and spaces
                else 0.0
            )
            cursor_x = aligned_text_x(
                render_width, actual_line_width, padding, line_alignment
            )
            for fragment, fragment_style, fragment_font, linked, fragment_width in fragments:
                fragment_size = max(7, round(safe_number(fragment_style.get("font_size"), render_item.font_size, minimum=1.0) * self.zoom))
                color = "#1769AA" if linked else safe_pillow_color(fragment_style.get("color"), render_item.color)
                highlight = safe_pillow_color(
                    fragment_style.get("highlight"), "", allow_transparent=True
                )
                displayed_width = fragment_width + fragment.count(" ") * extra_space
                if highlight:
                    draw.rectangle(
                        (
                            cursor_x - origin_x,
                            py - origin_y,
                            cursor_x + displayed_width - origin_x,
                            min(render_height - 1, py + line_height) - origin_y,
                        ),
                        fill=highlight,
                    )
                if extra_space:
                    # Dessiner mot par mot plutôt que caractère par caractère.
                    # Sur les longues clauses justifiées d'un DOCX, l'ancien
                    # chemin effectuait plusieurs milliers d'appels Pillow à
                    # chaque zoom ou validation.
                    fragment_x = cursor_x
                    for part in re.split(r"( +)", fragment):
                        if not part:
                            continue
                        base_width = float(draw.textlength(part, font=fragment_font))
                        if part.isspace():
                            fragment_x += base_width + len(part) * extra_space
                        else:
                            draw.text(
                                (fragment_x - origin_x, py - origin_y),
                                part,
                                font=fragment_font,
                                fill=color,
                            )
                            fragment_x += base_width
                else:
                    draw.text((cursor_x - origin_x, py - origin_y), fragment, font=fragment_font, fill=color)
                if linked or bool(fragment_style.get("underline", render_item.underline)):
                    underline_y = min(render_height - 1, py + fragment_size + 2) - origin_y
                    draw.line(
                        (cursor_x - origin_x, underline_y, cursor_x + displayed_width - origin_x, underline_y),
                        fill="#1769AA" if linked else color,
                        width=max(1, round(self.zoom)),
                    )
                if bool(
                    fragment_style.get(
                        "strikethrough", render_item.strikethrough
                    )
                ):
                    strike_y = min(render_height - 1, py + fragment_size * 0.55) - origin_y
                    draw.line(
                        (cursor_x - origin_x, strike_y, cursor_x + displayed_width - origin_x, strike_y),
                        fill=color, width=max(1, round(self.zoom)),
                    )
                cursor_x += displayed_width
        rotation = float(render_item.rotation) % 360
        if rotation:
            image = image.rotate(
                -rotation,
                expand=True,
                resample=Image.Resampling.BICUBIC,
                fillcolor=(0, 0, 0, 0),
            )
        if len(cache) >= 32:
            cache.pop(next(iter(cache)))
        picture = ImageTk.PhotoImage(image)
        cache[cache_key] = picture
        return picture

    def _basic_text_preview(
        self, item: PageObject, text: str, width: int, height: int
    ) -> ImageTk.PhotoImage:
        """Last-resort preview that still clips and rotates the complete frame."""
        render_item = copy.copy(item)
        render_item.font_size = safe_number(render_item.font_size, 12.0, minimum=1.0)
        render_item.border_width = safe_number(render_item.border_width, 0.0, minimum=0.0)
        render_item.rotation = safe_number(render_item.rotation, 0.0)
        render_item.color = safe_pillow_color(render_item.color, "#000000")
        render_item.border_color = safe_pillow_color(render_item.border_color, "#000000")
        render_item.fill = safe_pillow_color(render_item.fill, "#FFFFFF", allow_transparent=True)
        width, height = max(1, width), max(1, height)
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        if render_item.fill:
            draw.rectangle((0, 0, width - 1, height - 1), fill=render_item.fill)
        border_width = max(0, round(render_item.border_width * self.zoom))
        if border_width:
            draw_styled_rectangle(
                draw,
                (border_width // 2, border_width // 2, width - 1 - border_width // 2, height - 1 - border_width // 2),
                color=render_item.border_color,
                width=max(1, border_width),
                style=render_item.border_style if render_item.border_style in {"solid", "dashed", "dotted"} else "solid",
            )
        font_size = max(7, round(render_item.font_size * self.zoom))
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", font_size)
        except OSError:
            font = ImageFont.load_default()
        line_height = max(1, round(font_size * 1.25))
        text_x = max(2, round(text_frame_horizontal_inset(render_item) * self.zoom))
        y = max(2, round(text_frame_vertical_inset(render_item) * self.zoom))
        for line in wrapped_text_lines(text, render_item) or [""]:
            if y + line_height > height:
                break
            # Pillow clips at the image boundary: text cannot spill into the
            # following linked frame even in this emergency renderer.
            draw.text((text_x, y), line, font=font, fill=render_item.color)
            y += line_height
        if render_item.rotation % 360:
            image = image.rotate(
                -(render_item.rotation % 360),
                expand=True,
                resample=Image.Resampling.BICUBIC,
                fillcolor=(0, 0, 0, 0),
            )
        return ImageTk.PhotoImage(image)

    def _add_object(self, item: PageObject) -> None:
        self._checkpoint()
        self.document.objects.append(item)
        self.selected = len(self.document.objects) - 1
        self.selected_indices = {self.selected}
        self._render()

    def _add_text(self) -> None:
        self._cancel_current_action()
        self._drawing_text = True
        self._text_draw_start = None
        self.canvas.configure(cursor="crosshair")
        self.status.configure(
            text="Zone de texte : cliquez à son emplacement puis tirez jusqu’à la taille souhaitée. Échap annule."
        )

    def _open_chatgpt_for_selected(self) -> None:
        if self.selected is None or self.document.objects[self.selected].kind != "text":
            messagebox.showinfo(
                "Assistant ChatGPT",
                "Sélectionnez d’abord une zone de texte.",
                parent=self,
            )
            return
        text = self.document.objects[self.selected].text.strip()
        if text:
            prompt = (
                "Corrige et reformule le texte suivant en français clair et naturel. "
                "Conserve strictement le sens et rends uniquement le texte final, sans commentaire.\n\n"
                + text
            )
        else:
            prompt = (
                "Je vais dicter un texte. Transcris-le en français clair, corrige les erreurs "
                "sans changer le sens et rends uniquement le texte final, sans commentaire."
            )
        self.clipboard_clear()
        self.clipboard_append(prompt)
        self.update_idletasks()
        if not webbrowser.open("https://chatgpt.com/", new=2):
            messagebox.showerror(
                "Assistant ChatGPT",
                "Impossible d’ouvrir le navigateur par défaut.",
                parent=self,
            )
            return
        self.status.configure(
            text="Consigne copiée. Collez-la dans ChatGPT, puis copiez le résultat et utilisez 📋."
        )

    def _paste_chatgpt_result(self) -> None:
        if self.selected is None or self.document.objects[self.selected].kind != "text":
            messagebox.showinfo(
                "Assistant ChatGPT",
                "Sélectionnez d’abord la zone de texte qui recevra le résultat.",
                parent=self,
            )
            return
        try:
            value = normalize_external_text(self.clipboard_get()).strip()
        except tk.TclError:
            value = ""
        if not value:
            messagebox.showinfo(
                "Assistant ChatGPT",
                "Le presse-papiers ne contient aucun texte à insérer.",
                parent=self,
            )
            return
        insertion_range: tuple[int, int] | None = None
        if (
            self._editing_widget is not None
            and self._editing_object_id == self.document.objects[self.selected].object_id
        ):
            widget = self._editing_widget
            try:
                start = self._text_character_offset(widget, "sel.first")
                end = self._text_character_offset(widget, "sel.last")
            except tk.TclError:
                start = end = self._text_character_offset(widget, "insert")
            insertion_range = (start, end)
            self._commit_inline_editor(render=False)
        else:
            end = len(self.document.objects[self.selected].text)
            insertion_range = (end, end)
        self._open_message_assistant(value, self.selected, insertion_range=insertion_range)

    def _review_selected(self) -> None:
        if self.selected is None or self.document.objects[self.selected].kind != "text":
            messagebox.showinfo(
                "Assistant de rédaction",
                "Sélectionnez d’abord une zone de texte à corriger ou reformuler.",
                parent=self,
            )
            return
        self._open_message_assistant(self.document.objects[self.selected].text, self.selected)

    def _open_message_assistant(
        self,
        draft: str,
        target_index: int,
        *,
        insertion_range: tuple[int, int] | None = None,
    ) -> None:
        if target_index >= len(self.document.objects):
            return
        dialog = tk.Toplevel(self)
        dialog.title("Message — relecture")
        dialog.configure(bg=BACKGROUND)
        tk.Label(
            dialog,
            text="Relire et corriger le message",
            bg=NAVY,
            fg="white",
            font=("Sans", 17, "bold"),
            padx=20,
            pady=12,
        ).pack(fill="x")
        ttk.Label(
            dialog,
            text="Relisez le texte avant de l’insérer dans la zone sélectionnée.",
            style="Body.TLabel",
        ).pack(anchor="w", padx=18, pady=(14, 5))
        editor = tk.Text(dialog, wrap="word", undo=True, font=("Sans", 12), height=15)
        editor.pack(fill="both", expand=True, padx=18, pady=5)
        editor.insert("1.0", draft)
        actions = ttk.Frame(dialog, padding=(18, 4, 18, 16))
        actions.pack(fill="x")

        def apply_message() -> None:
            value = editor.get("1.0", "end-1c").strip()
            if not value or target_index >= len(self.document.objects):
                return
            self._checkpoint()
            target = self.document.objects[target_index]
            if insertion_range is None:
                target.text = value
            else:
                start, end = insertion_range
                before, after = target.text[:start], target.text[end:]
                separator_before = "\n" if before and not before.endswith(("\n", " ")) else ""
                separator_after = "\n" if after and not after.startswith(("\n", " ")) else ""
                target.text = before + separator_before + value + separator_after + after
            self.selected = target_index
            self.selected_indices = {target_index}
            dialog.destroy()
            self.status.configure(
                text="Message ajouté à la position du curseur dans la zone de texte."
                if insertion_range is not None
                else "Message relu et inséré dans la zone de texte."
            )
            self._render()
            self.after_idle(lambda target=target: self._start_inline_text_editor(target))

        ttk.Button(actions, text="Annuler", command=dialog.destroy).pack(side="right")
        ttk.Button(actions, text="Insérer dans la zone", command=apply_message).pack(
            side="right", padx=8
        )
        ttk.Button(
            actions,
            text="Revenir au texte initial",
            command=lambda: (
                editor.delete("1.0", "end"),
                editor.insert("1.0", draft),
            ),
        ).pack(side="left")
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        center_window(dialog, 760, 530)
        make_modal(dialog, self)
        editor.focus_set()

    def _add_image(self) -> None:
        files = choose_documents(self, {".png", ".jpg", ".jpeg", ".tif", ".tiff"})
        if files:
            display_width, display_height = 180.0, 120.0
            try:
                with Image.open(files[0]) as source:
                    source_width, source_height = source.size
                display_height = display_width * source_height / max(1, source_width)
                if display_height > 180:
                    display_height = 180.0
                    display_width = display_height * source_width / max(1, source_height)
            except OSError:
                pass
            self._add_object(PageObject(
                "image", self.current_page, 70, 80, display_width, display_height,
                image_path=str(files[0]),
            ))

    def _add_mask(self) -> None:
        self._add_object(PageObject("mask", self.current_page, 70, 80, 220, 55))

    def _add_table(self) -> None:
        size = ask_table_size(self)
        if size:
            rows, columns = size
            content = "\n".join("\t".join("" for _ in range(columns)) for _ in range(rows))
            cells = [[{"text": "", "hyperlink": "", "image_path": ""} for _ in range(columns)] for _ in range(rows)]
            self._add_object(PageObject("table", self.current_page, 70, 80, 360, max(80, rows * 46), text=content, table_cells=cells, font_size=10))

    def _add_line(self) -> None:
        self._cancel_current_action()
        self._drawing_line = True
        self._line_points.clear()
        self._line_raw_cursor = None
        self.canvas.configure(cursor="crosshair")
        self.status.configure(
            text="Trait : départ puis arrivée. Ctrl = horizontal/vertical, Maj = pas angulaire réglable, Alt = 30°."
        )

    def _add_axis(self) -> None:
        self._add_object(
            PageObject(
                "line",
                self.current_page,
                70,
                220,
                360,
                0,
                shape="axis",
                border_color="#6A7480",
                border_width=1,
                border_style="dashed",
            )
        )

    def _start_polyline(self) -> None:
        self._drawing_polyline = True
        self._polyline_points.clear()
        self._polyline_raw_cursor = None
        self._polyline_axis_index = next(
            (
                index
                for index in self.selected_indices
                if self.document.objects[index].kind == "line"
                and self.document.objects[index].shape == "axis"
            ),
            None,
        )
        self.canvas.configure(cursor="crosshair")
        self.status.configure(
            text=(
                "Profil accroché à l’axe sélectionné : le premier point partira exactement de cet axe. "
                if self._polyline_axis_index is not None
                else "Profil : approchez le premier point d’un axe pour vous y accrocher. "
            )
            + "Ctrl = horizontal/vertical, Maj = 45°, Alt = 30°, Entrée termine."
        )

    def _modifier_key_event(self, event: tk.Event[tk.Misc]) -> None:
        key_map = {
            "Control_L": "control",
            "Control_R": "control",
            "Shift_L": "shift",
            "Shift_R": "shift",
            "Alt_L": "alt",
            "Alt_R": "alt",
            "Meta_L": "alt",
            "Meta_R": "alt",
        }
        modifier = key_map.get(event.keysym)
        if modifier is None:
            return
        if event.type == tk.EventType.KeyPress:
            self._modifier_keys.add(modifier)
        else:
            self._modifier_keys.discard(modifier)
        if self._drawing_polyline and self._polyline_raw_cursor is not None:
            cursor = self._constrained_polyline_point(
                *self._polyline_raw_cursor, 0
            )
            self._draw_polyline_preview(cursor)
        elif self._drawing_line and self._line_raw_cursor is not None and self._line_points:
            cursor = self._constrained_drawing_point(
                self._line_points[-1], *self._line_raw_cursor, 0
            )
            cursor, snap_label = self._snap_drawing_point(*cursor)
            self._draw_line_preview(cursor, snap_label)
        elif self._drawing_rectangle and len(self._rectangle_points) == 1:
            self._draw_rectangle_angle_guides(0x0004 if "control" in self._modifier_keys else 0)
        elif self._drawing_triangle and len(self._triangle_points) == 1:
            self._draw_triangle_angle_guides(0x0004 if "control" in self._modifier_keys else 0)

    def _table_typing_event(self, event: tk.Event[tk.Misc]) -> str | None:
        """Enter/F2 or direct typing edits the active cell like a spreadsheet."""
        if self._editing_widget is not None or isinstance(event.widget, (tk.Entry, ttk.Entry, tk.Text)):
            return None
        if self.selected is None or self.selected >= len(self.document.objects):
            return None
        item = self.document.objects[self.selected]
        active = self._active_table_cell
        if item.kind != "table" or active is None or active[0] != item.object_id:
            return None
        direct_character = event.char if event.char and event.char.isprintable() else ""
        if event.keysym not in {"Return", "KP_Enter", "F2"} and not direct_character:
            return None
        row, column = active[1], active[2]

        def begin() -> None:
            self._start_inline_table_cell_editor(item, row, column)
            if direct_character and self._editing_widget is not None:
                self._editing_widget.delete("1.0", "end")
                self._editing_widget.insert("1.0", direct_character)
                self._editing_widget.mark_set("insert", "end-1c")

        self.after_idle(begin)
        return "break"

    def _constrained_drawing_point(
        self, start: tuple[float, float], x: float, y: float, state: int
    ) -> tuple[float, float]:
        start_x, start_y = start
        dx, dy = x - start_x, y - start_y
        control = bool(state & 0x0004) or "control" in self._modifier_keys
        shift = bool(state & 0x0001) or "shift" in self._modifier_keys
        alt = bool(state & 0x0008) or "alt" in self._modifier_keys
        if control:
            return (x, start_y) if abs(dx) >= abs(dy) else (start_x, y)
        if shift or alt:
            length = math.hypot(dx, dy)
            if length <= 1e-8:
                return x, y
            try:
                configured_increment = max(
                    0.1,
                    float(getattr(self, "rotation_step_var").get().replace(",", ".")),
                )
            except (AttributeError, ValueError):
                configured_increment = 45.0
            increment = math.pi / 6 if alt else math.radians(configured_increment)
            angle = round(math.atan2(dy, dx) / increment) * increment
            return start_x + length * math.cos(angle), start_y + length * math.sin(angle)
        return x, y

    def _constrained_polyline_point(
        self, x: float, y: float, state: int
    ) -> tuple[float, float]:
        if not self._polyline_points:
            axis_index = self._polyline_axis_index
            if axis_index is None:
                axes = [
                    (index, item)
                    for index, item in enumerate(self.document.objects)
                    if item.kind == "line" and item.shape == "axis"
                ]
                nearby = [
                    (
                        point_to_segment_distance(
                            x,
                            y,
                            Segment(item.x, item.y, item.x + item.width, item.y + item.height),
                        ),
                        index,
                    )
                    for index, item in axes
                ]
                if nearby:
                    distance, candidate = min(nearby)
                    if distance <= max(5.0, 12.0 / self.zoom):
                        axis_index = candidate
                        self._polyline_axis_index = candidate
            if axis_index is not None:
                axis_item = self.document.objects[axis_index]
                return project_point_onto_line(
                    x,
                    y,
                    Segment(
                        axis_item.x,
                        axis_item.y,
                        axis_item.x + axis_item.width,
                        axis_item.y + axis_item.height,
                    ),
                )
            return x, y
        return self._constrained_drawing_point(self._polyline_points[-1], x, y, state)

    def _drawing_segments(self) -> list[tuple[Segment, str]]:
        segments: list[tuple[Segment, str]] = []
        for item in self.document.objects:
            if self.current_page not in pages_for_object(item, self.document.page_count):
                continue
            if item.kind == "line":
                segments.append((Segment(item.x, item.y, item.x + item.width, item.y + item.height), "trait"))
                continue
            if item.kind == "polyline" and len(item.points) >= 2:
                points = [(item.x + point[0], item.y + point[1]) for point in item.points]
            else:
                points = self._closed_outline(item)
            segments.extend((Segment(*start, *end), "contour") for start, end in pairwise(points))
        return segments

    def _snap_drawing_point(self, x: float, y: float) -> tuple[tuple[float, float], str]:
        threshold = max(4.0, 11.0 / self.zoom)
        segments = self._drawing_segments()
        endpoints = [
            ((point_x, point_y), "extrémité")
            for segment, _label in segments
            for point_x, point_y in ((segment.x1, segment.y1), (segment.x2, segment.y2))
        ]
        if endpoints:
            point, label = min(endpoints, key=lambda candidate: math.dist((x, y), candidate[0]))
            if math.dist((x, y), point) <= threshold:
                return point, label
        intersections = [
            crossing
            for index, (first, _first_label) in enumerate(segments)
            for second, _second_label in segments[index + 1 :]
            if (crossing := segment_intersection(first, second)) is not None
        ]
        if intersections:
            point = min(intersections, key=lambda candidate: math.dist((x, y), candidate))
            if math.dist((x, y), point) <= threshold:
                return point, "sommet / intersection"
        candidates = [
            (closest_point_on_segment(x, y, segment), label)
            for segment, label in segments
        ]
        if candidates:
            point, label = min(candidates, key=lambda candidate: math.dist((x, y), candidate[0]))
            if math.dist((x, y), point) <= threshold:
                return point, label
        return (x, y), ""

    def _dimension_reference_at(
        self, x: float, y: float
    ) -> tuple[tuple[float, float], str, dict[str, object]]:
        threshold = max(4.0, 11.0 / self.zoom)
        candidates: list[
            tuple[float, int, tuple[float, float], str, dict[str, object]]
        ] = []
        edge_values: list[tuple[PageObject, int, Segment]] = []
        for item in self.document.objects:
            if item.kind == "dimension" or self.current_page not in pages_for_object(
                item, self.document.page_count
            ):
                continue
            if item.kind == "shape" and item.shape in {"circle", "ellipse"}:
                center = (item.x + item.width / 2, item.y + item.height / 2)
                candidates.append((
                    math.dist((x, y), center), 0, center, "centre",
                    {"kind": "center", "object_id": item.object_id},
                ))
            for edge_index, edge in enumerate(self._object_edges(item)):
                edge_values.append((item, edge_index, edge))
                dx, dy = edge.x2 - edge.x1, edge.y2 - edge.y1
                squared_length = dx * dx + dy * dy
                if squared_length <= 1e-12:
                    continue
                t = max(0.0, min(1.0, ((x - edge.x1) * dx + (y - edge.y1) * dy) / squared_length))
                point = (edge.x1 + t * dx, edge.y1 + t * dy)
                distance = math.dist((x, y), point)
                candidates.append((
                    distance, 4, point, "bord",
                    {"kind": "edge", "object_id": item.object_id, "edge": edge_index, "t": t},
                ))
                for endpoint_t, endpoint in ((0.0, (edge.x1, edge.y1)), (1.0, (edge.x2, edge.y2))):
                    candidates.append((
                        math.dist((x, y), endpoint), 1, endpoint, "sommet",
                        {"kind": "edge", "object_id": item.object_id, "edge": edge_index, "t": endpoint_t},
                    ))
                midpoint = ((edge.x1 + edge.x2) / 2, (edge.y1 + edge.y2) / 2)
                candidates.append((
                    math.dist((x, y), midpoint), 2, midpoint, "milieu",
                    {"kind": "edge", "object_id": item.object_id, "edge": edge_index, "t": 0.5},
                ))
        for first_index, (first_item, first_edge_index, first_edge) in enumerate(edge_values):
            for second_item, second_edge_index, second_edge in edge_values[first_index + 1 :]:
                if first_item.object_id == second_item.object_id:
                    continue
                crossing = segment_intersection(first_edge, second_edge)
                if crossing is None:
                    continue
                first_reference = {
                    "kind": "edge", "object_id": first_item.object_id,
                    "edge": first_edge_index, "t": self._segment_parameter(first_edge, crossing),
                }
                second_reference = {
                    "kind": "edge", "object_id": second_item.object_id,
                    "edge": second_edge_index, "t": self._segment_parameter(second_edge, crossing),
                }
                candidates.append((
                    math.dist((x, y), crossing), 0, crossing, "intersection",
                    {"kind": "intersection", "first": first_reference, "second": second_reference},
                ))
        if not candidates:
            return (x, y), "", {}
        distance, _priority, point, label, reference = min(
            candidates, key=lambda candidate: (candidate[0], candidate[1])
        )
        if distance <= threshold:
            return point, label, reference
        return (x, y), "", {}

    @staticmethod
    def _segment_parameter(edge: Segment, point: tuple[float, float]) -> float:
        dx, dy = edge.x2 - edge.x1, edge.y2 - edge.y1
        squared_length = dx * dx + dy * dy
        if squared_length <= 1e-12:
            return 0.0
        return max(
            0.0,
            min(1.0, ((point[0] - edge.x1) * dx + (point[1] - edge.y1) * dy) / squared_length),
        )

    def _resolve_dimension_reference(
        self, reference: dict[str, object]
    ) -> tuple[float, float] | None:
        kind = str(reference.get("kind", "edge"))
        if kind == "intersection":
            first = reference.get("first")
            second = reference.get("second")
            if not isinstance(first, dict) or not isinstance(second, dict):
                return None
            first_edge = self._resolve_dimension_edge(first)
            second_edge = self._resolve_dimension_edge(second)
            if first_edge is None or second_edge is None:
                return None
            return segment_intersection(first_edge, second_edge)
        object_id = str(reference.get("object_id", ""))
        item = next(
            (candidate for candidate in self.document.objects if candidate.object_id == object_id),
            None,
        )
        if item is None:
            return None
        if kind == "center":
            return item.x + item.width / 2, item.y + item.height / 2
        edge = self._resolve_dimension_edge(reference)
        if edge is None:
            return None
        t = max(0.0, min(1.0, float(reference.get("t", 0.0))))
        return (
            edge.x1 + (edge.x2 - edge.x1) * t,
            edge.y1 + (edge.y2 - edge.y1) * t,
        )

    def _resolve_dimension_edge(self, reference: dict[str, object]) -> Segment | None:
        object_id = str(reference.get("object_id", ""))
        item = next(
            (candidate for candidate in self.document.objects if candidate.object_id == object_id),
            None,
        )
        if item is None:
            return None
        edges = self._object_edges(item)
        edge_index = int(reference.get("edge", -1))
        if not 0 <= edge_index < len(edges):
            return None
        return edges[edge_index]

    def _update_associative_dimensions(self) -> None:
        for item in self.document.objects:
            if item.kind != "dimension" or len(item.dimension_refs) != 2 or len(item.points) != 2:
                continue
            resolved = [self._resolve_dimension_reference(reference) for reference in item.dimension_refs]
            if any(point is None for point in resolved):
                continue
            old_first = (float(item.points[0][0]), float(item.points[0][1]))
            old_second = (float(item.points[1][0]), float(item.points[1][1]))
            old_dx, old_dy = old_second[0] - old_first[0], old_second[1] - old_first[1]
            old_length = math.hypot(old_dx, old_dy)
            if old_length <= 1e-9:
                continue
            old_normal = (-old_dy / old_length, old_dx / old_length)
            offset = (
                (item.x - old_first[0]) * old_normal[0]
                + (item.y - old_first[1]) * old_normal[1]
            )
            first, second = resolved
            assert first is not None and second is not None
            dx, dy = second[0] - first[0], second[1] - first[1]
            length = math.hypot(dx, dy)
            if length <= 1e-9:
                continue
            normal = (-dy / length, dx / length)
            start = (first[0] + normal[0] * offset, first[1] + normal[1] * offset)
            end = (second[0] + normal[0] * offset, second[1] + normal[1] * offset)
            item.x, item.y = start
            item.width, item.height = end[0] - start[0], end[1] - start[1]
            item.points = [[first[0], first[1]], [second[0], second[1]]]
            item.text = f"{length * 25.4 / 72 * self.document.measurement_scale:.2f}"

    def _draw_snap_marker(self, point: tuple[float, float], label: str) -> None:
        self.canvas.delete("snap-preview")
        if not label:
            return
        px = self.page_x + point[0] * self.zoom
        py = self.page_y + point[1] * self.zoom
        self.canvas.create_oval(
            px - 6, py - 6, px + 6, py + 6,
            fill="#D9F5E5", outline="#14804A", width=2,
            tags=("snap-preview",),
        )
        self.canvas.create_text(px + 9, py - 9, text=f"Accroché : {label}", anchor="sw", fill="#14804A", font=("Sans", 8, "bold"), tags=("snap-preview",))

    def _draw_measurement_anchor_markers(self) -> None:
        self.canvas.delete("measurement-anchor")
        for number, point in enumerate(self._measurement_points, start=1):
            px = self.page_x + point[0] * self.zoom
            py = self.page_y + point[1] * self.zoom
            self.canvas.create_oval(
                px - 7, py - 7, px + 7, py + 7,
                fill="#21A366", outline="white", width=2,
                tags=("measurement-anchor",),
            )
            self.canvas.create_text(
                px, py, text=str(number), fill="white",
                font=("Sans", 8, "bold"), tags=("measurement-anchor",),
            )

    def _draw_line_preview(self, cursor: tuple[float, float], snap_label: str = "") -> None:
        self.canvas.delete("line-preview")
        if not self._line_points:
            return
        start = self._line_points[0]
        self.canvas.create_line(
            self.page_x + start[0] * self.zoom,
            self.page_y + start[1] * self.zoom,
            self.page_x + cursor[0] * self.zoom,
            self.page_y + cursor[1] * self.zoom,
            fill="#193B66", width=2, tags=("line-preview",),
        )
        self._draw_snap_marker(cursor, snap_label)

    def _draw_polyline_preview(self, cursor: tuple[float, float] | None = None) -> None:
        self.canvas.delete("polyline-preview")
        points = [*self._polyline_points]
        if cursor is not None and points:
            points.append(cursor)
        coordinates = [
            coordinate
            for point_x, point_y in points
            for coordinate in (
                self.page_x + point_x * self.zoom,
                self.page_y + point_y * self.zoom,
            )
        ]
        if len(coordinates) >= 4:
            self.canvas.create_line(
                *coordinates,
                fill="#193B66",
                width=2,
                tags=("polyline-preview",),
            )
        for point_x, point_y in self._polyline_points:
            px, py = self.page_x + point_x * self.zoom, self.page_y + point_y * self.zoom
            self.canvas.create_oval(
                px - 4,
                py - 4,
                px + 4,
                py + 4,
                fill="#E87524",
                outline="white",
                tags=("polyline-preview",),
            )
        for number, (start, end) in enumerate(pairwise(points), start=1):
            length_mm = math.dist(start, end) * 25.4 / 72
            middle_x = self.page_x + (start[0] + end[0]) / 2 * self.zoom
            middle_y = self.page_y + (start[1] + end[1]) / 2 * self.zoom
            self.canvas.create_text(
                middle_x,
                middle_y - 10,
                text=f"{number}: {length_mm:.2f} mm",
                fill="#A34D00",
                font=("Sans", 9, "bold"),
                tags=("polyline-preview",),
            )

    def _polyline_motion(self, event: tk.Event[tk.Misc]) -> None:
        if self._drawing_rectangle and self._rectangle_points:
            x = (self.canvas.canvasx(event.x) - self.page_x) / self.zoom
            y = (self.canvas.canvasy(event.y) - self.page_y) / self.zoom
            cursor = self._rectangle_cursor_point(x, y, event.state)
            self._draw_rectangle_angle_guides(event.state)
            self._draw_rectangle_preview(cursor)
            if len(self._rectangle_points) == 1:
                try:
                    increment = float(self.rotation_step_var.get().replace(",", "."))
                except ValueError:
                    increment = 15.0
                self.status.configure(
                    text=f"Premier côté : Ctrl accroche tous les {increment:g}°. Cliquez pour mémoriser sa longueur."
                )
            elif len(self._rectangle_points) == 2:
                self.status.configure(
                    text=(
                        "Carré : choisissez le côté de construction puis cliquez."
                        if self._rectangle_square
                        else "Largeur du rectangle : déplacez librement, ou maintenez Ctrl pour imposer un carré."
                    )
                )
            return
        if self._drawing_triangle and self._triangle_points:
            x = (self.canvas.canvasx(event.x) - self.page_x) / self.zoom
            y = (self.canvas.canvasy(event.y) - self.page_y) / self.zoom
            cursor = self._triangle_cursor_point(x, y, event.state)
            if len(self._triangle_points) == 1:
                self._draw_triangle_angle_guides(event.state)
            self._draw_triangle_preview(cursor)
            _snap_point, snap_label = self._snap_drawing_point(x, y)
            self._draw_snap_marker(cursor, snap_label)
            return
        if self._pending_right_triangle is not None:
            self._draw_right_triangle_preview(event)
            return
        if self._measurement_mode:
            x = (self.canvas.canvasx(event.x) - self.page_x) / self.zoom
            y = (self.canvas.canvasy(event.y) - self.page_y) / self.zoom
            width, height = self._page_size()
            if 0 <= x <= width and 0 <= y <= height:
                if self._measurement_mode == "dimension" and len(self._measurement_points) < 2:
                    point, snap_label, _reference = self._dimension_reference_at(x, y)
                elif self._measurement_mode == "dimension":
                    point, snap_label = (x, y), ""
                else:
                    point, snap_label = self._snap_drawing_point(x, y)
                self._draw_snap_marker(point, snap_label)
                if self._measurement_mode == "dimension" and len(self._measurement_points) == 2:
                    self._draw_dimension_placement_preview((x, y))
                if snap_label:
                    self.status.configure(
                        text=f"Accrochage de mesure : {snap_label}. Cliquez pour mémoriser ce point exact."
                    )
            return
        if self._drawing_line and self._line_points:
            x = (self.canvas.canvasx(event.x) - self.page_x) / self.zoom
            y = (self.canvas.canvasy(event.y) - self.page_y) / self.zoom
            width, height = self._page_size()
            if not (0 <= x <= width and 0 <= y <= height):
                return
            self._line_raw_cursor = (x, y)
            cursor = self._constrained_drawing_point(self._line_points[0], x, y, event.state)
            cursor, snap_label = self._snap_drawing_point(*cursor)
            self._draw_line_preview(cursor, snap_label)
            start = self._line_points[0]
            length_mm = math.dist(start, cursor) * 25.4 / 72
            angle = math.degrees(math.atan2(-(cursor[1] - start[1]), cursor[0] - start[0]))
            self.geometry_help.configure(text=f"Trait en cours : {length_mm:.2f} mm   angle {angle:.1f}°")
            self.status.configure(
                text=(f"Accroché sur une {snap_label}. " if snap_label else "Arrivée libre. ")
                + "Cliquez pour mémoriser le trait, ou appuyez sur Entrée."
            )
            return
        if not self._drawing_polyline or not self._polyline_points:
            return
        x = (self.canvas.canvasx(event.x) - self.page_x) / self.zoom
        y = (self.canvas.canvasy(event.y) - self.page_y) / self.zoom
        width, height = self._page_size()
        if not (0 <= x <= width and 0 <= y <= height):
            return
        self._polyline_raw_cursor = (x, y)
        cursor = self._constrained_polyline_point(x, y, event.state)
        cursor, snap_label = self._snap_drawing_point(*cursor)
        self._draw_polyline_preview(cursor)
        self._draw_snap_marker(cursor, snap_label)
        start = self._polyline_points[-1]
        dx_mm = (cursor[0] - start[0]) * 25.4 / 72
        dy_mm = (cursor[1] - start[1]) * 25.4 / 72
        length_mm = math.dist(start, cursor) * 25.4 / 72
        angle = math.degrees(math.atan2(cursor[1] - start[1], cursor[0] - start[0])) % 360
        mode = (
            "H/V"
            if "control" in self._modifier_keys or event.state & 0x0004
            else "30°"
            if "alt" in self._modifier_keys or event.state & 0x0008
            else "45°"
            if "shift" in self._modifier_keys or event.state & 0x0001
            else "libre"
        )
        self.geometry_help.configure(
            text=f"Segment en cours : {length_mm:.2f} mm   angle {angle:.1f}°   ΔX {dx_mm:.2f}   ΔY {dy_mm:.2f}   contrainte {mode}"
        )

    def _finish_polyline(self, _event: object = None) -> str | None:
        if not self._drawing_polyline:
            return None
        if len(self._polyline_points) >= 2:
            minimum_x = min(point[0] for point in self._polyline_points)
            minimum_y = min(point[1] for point in self._polyline_points)
            maximum_x = max(point[0] for point in self._polyline_points)
            maximum_y = max(point[1] for point in self._polyline_points)
            relative = [[x - minimum_x, y - minimum_y] for x, y in self._polyline_points]
            self._add_object(
                PageObject(
                    "polyline",
                    self.current_page,
                    minimum_x,
                    minimum_y,
                    max(1, maximum_x - minimum_x),
                    max(1, maximum_y - minimum_y),
                    points=relative,
                    border_color="#193B66",
                    border_width=1.5,
                )
            )
            self.status.configure(text=f"Polyligne créée avec {len(relative)} sommets.")
        self._drawing_polyline = False
        self._polyline_points.clear()
        self._polyline_raw_cursor = None
        self._polyline_axis_index = None
        self.canvas.configure(cursor="")
        self.canvas.delete("polyline-preview")
        return "break"

    def _finish_line(self, endpoint: tuple[float, float] | None = None) -> str | None:
        if not self._drawing_line:
            return None
        if endpoint is None and self._line_points and self._line_raw_cursor is not None:
            endpoint = self._constrained_drawing_point(
                self._line_points[0], *self._line_raw_cursor, 0
            )
            endpoint, _label = self._snap_drawing_point(*endpoint)
        if self._line_points and endpoint is not None and math.dist(self._line_points[0], endpoint) > 1e-6:
            start = self._line_points[0]
            self._add_object(
                PageObject(
                    "line", self.current_page, start[0], start[1],
                    endpoint[0] - start[0], endpoint[1] - start[1],
                    border_color="#193B66", border_width=1.5,
                )
            )
            self.status.configure(text="Trait créé. Ses extrémités sont géométriquement confondues avec les points accrochés.")
        self._drawing_line = False
        self._line_points.clear()
        self._line_raw_cursor = None
        self.canvas.configure(cursor="")
        self.canvas.delete("line-preview")
        self.canvas.delete("snap-preview")
        return "break"

    def _finish_drawing(self, event: object = None) -> str | None:
        if self._drawing_line:
            return self._finish_line()
        return self._finish_polyline(event)

    def _cancel_current_action(self, _event: object = None) -> str:
        self._dismiss_context_menu()
        if self._pdf_font_pick_mode:
            self._pdf_font_pick_mode = False
            self.canvas.configure(cursor="")
            self.status.configure(text="Pipette typographique annulée.")
            return "break"
        if self._crop_mode_index is not None:
            self._cancel_visual_crop()
            self.status.configure(text="Rognage annulé.")
            self._render()
            return "break"
        if self._drawing_text:
            self._drawing_text = False
            self._text_draw_start = None
            self.canvas.delete("text-frame-preview")
            self.canvas.configure(cursor="")
            self.status.configure(text="Création de la zone de texte annulée.")
            return "break"
        if self._measurement_mode:
            self._measurement_mode = ""
            self._measurement_points.clear()
            self._measurement_refs.clear()
            self.canvas.delete("dimension-preview")
            self.canvas.delete("snap-preview")
            self.canvas.delete("measurement-anchor")
            self.canvas.configure(cursor="")
            self.status.configure(text="Mesure annulée.")
            return "break"
        if self._drawing_triangle:
            self._drawing_triangle = False
            self._triangle_points.clear()
            self._triangle_right = False
            self.canvas.delete("triangle-preview")
            self.canvas.delete("angle-guide")
            self.canvas.delete("snap-preview")
            self.canvas.configure(cursor="")
            self.status.configure(text="Dessin du triangle annulé.")
            return "break"
        if self._drawing_rectangle:
            self._drawing_rectangle = False
            self._rectangle_points.clear()
            self._rectangle_square = False
            self.canvas.delete("rectangle-preview")
            self.canvas.delete("angle-guide")
            self.canvas.configure(cursor="")
            self.status.configure(text="Dessin du rectangle annulé.")
            return "break"
        if self._pending_right_triangle is not None:
            self._pending_right_triangle = None
            self.canvas.configure(cursor="")
            self.status.configure(text="Construction du triangle rectangle annulée.")
            return "break"
        if self._drawing_line:
            self._drawing_line = False
            self._line_points.clear()
            self._line_raw_cursor = None
            self.canvas.delete("line-preview")
            self.canvas.delete("snap-preview")
            self.canvas.configure(cursor="")
            self.status.configure(text="Tracé du trait annulé.")
            return "break"
        if self._placing_work_origin:
            self._placing_work_origin = False
            self.canvas.configure(cursor="")
            self.status.configure(text="Placement de l’origine annulé.")
            return "break"
        if self._pending_corner_treatment is not None:
            self._pending_corner_treatment = None
            self.canvas.configure(cursor="")
            self.status.configure(text="Traitement du coin annulé.")
            return "break"
        if self._pending_edge_snap is not None:
            self._pending_edge_snap = None
            self.canvas.configure(cursor="")
            self.status.configure(text="Alignement des bords annulé.")
            self._render()
            return "break"
        if self._pending_driving_dimension is not None:
            self._pending_driving_dimension = None
            self.canvas.configure(cursor="")
            self.status.configure(text="Cote pilotante annulée.")
            self._render()
            return "break"
        if self._drawing_polyline:
            self._drawing_polyline = False
            self._polyline_points.clear()
            self._polyline_raw_cursor = None
            self._polyline_axis_index = None
            self.canvas.delete("polyline-preview")
            self.canvas.configure(cursor="")
            self.status.configure(text="Tracé de la polyligne annulé.")
        else:
            self._cancel_text_link()
        return "break"

    def _add_shape(self, shape: str) -> None:
        width, height = (
            (180, 75) if shape == "arrow"
            else (110, 110) if shape == "circle"
            else (150, 100)
        )
        self._add_object(
            PageObject(
                "shape",
                self.current_page,
                80,
                100,
                width,
                height,
                shape=shape,
                color="#193B66",
                border_color="#193B66",
                border_width=1.5,
                fill="#FFFFFF",
            )
        )

    def _start_triangle(self, right: bool) -> None:
        self._cancel_current_action()
        self._drawing_triangle = True
        self._triangle_right = right
        self._triangle_points.clear()
        self.canvas.configure(cursor="crosshair")
        self.status.configure(
            text=(
                "Triangle rectangle orienté : sommet droit, premier côté avec Ctrl pour les guides, puis hauteur perpendiculaire."
                if right
                else "Triangle quelconque orienté : premier sommet, premier côté, puis troisième sommet. Ctrl affiche les guides angulaires."
            )
        )

    def _start_rectangle(self, square: bool = False) -> None:
        self._cancel_current_action()
        self._drawing_rectangle = True
        self._rectangle_square = square
        self._rectangle_points.clear()
        self.canvas.configure(cursor="crosshair")
        self.status.configure(
            text=(
                "Carré orienté : tracez un côté ; le troisième clic choisira uniquement le côté de construction."
                if square
                else "Rectangle orienté : tracez le premier côté, puis la largeur. Pendant la largeur, Ctrl impose un carré."
            )
        )

    def _rectangle_cursor_point(self, x: float, y: float, state: int = 0) -> tuple[float, float]:
        if not self._rectangle_points:
            return self._snap_drawing_point(x, y)[0]
        if len(self._rectangle_points) == 1:
            control = bool(state & 0x0004) or "control" in self._modifier_keys
            if control:
                try:
                    increment = max(0.1, float(self.rotation_step_var.get().replace(",", ".")))
                except ValueError:
                    increment = 15.0
                start = self._rectangle_points[0]
                distance = math.dist(start, (x, y))
                angle = math.atan2(y - start[1], x - start[0])
                snapped_angle = round(math.degrees(angle) / increment) * increment
                constrained = (
                    start[0] + distance * math.cos(math.radians(snapped_angle)),
                    start[1] + distance * math.sin(math.radians(snapped_angle)),
                )
            else:
                constrained = self._constrained_drawing_point(self._rectangle_points[0], x, y, state)
            return self._snap_drawing_point(*constrained)[0]
        start, end = self._rectangle_points[:2]
        base_x, base_y = end[0] - start[0], end[1] - start[1]
        length = math.hypot(base_x, base_y)
        if length <= 1e-8:
            return end
        normal_x, normal_y = -base_y / length, base_x / length
        signed_width = (x - end[0]) * normal_x + (y - end[1]) * normal_y
        control = bool(state & 0x0004) or "control" in self._modifier_keys
        if self._rectangle_square or control:
            signed_width = math.copysign(length, signed_width if abs(signed_width) > 1e-8 else 1.0)
        return end[0] + normal_x * signed_width, end[1] + normal_y * signed_width

    def _rectangle_vertices(self, cursor: tuple[float, float]) -> list[tuple[float, float]]:
        start, end = self._rectangle_points[:2]
        offset = (cursor[0] - end[0], cursor[1] - end[1])
        return [start, end, cursor, (start[0] + offset[0], start[1] + offset[1])]

    def _draw_rectangle_preview(self, cursor: tuple[float, float]) -> None:
        self.canvas.delete("rectangle-preview")
        if len(self._rectangle_points) == 1:
            vertices = [self._rectangle_points[0], cursor]
        else:
            vertices = self._rectangle_vertices(cursor)
        coordinates = [
            coordinate for px, py in vertices
            for coordinate in (self.page_x + px * self.zoom, self.page_y + py * self.zoom)
        ]
        if len(vertices) == 4:
            coordinates += coordinates[:2]
        self.canvas.create_line(*coordinates, fill="#193B66", width=2, tags=("rectangle-preview",))
        edges = list(pairwise(vertices + ([vertices[0]] if len(vertices) == 4 else [])))
        for start, end in edges:
            self.canvas.create_text(
                self.page_x + (start[0] + end[0]) / 2 * self.zoom,
                self.page_y + (start[1] + end[1]) / 2 * self.zoom - 9,
                text=f"{math.dist(start, end) * 25.4 / 72:.2f} mm",
                fill="#A34D00", font=("Sans", 8, "bold"), tags=("rectangle-preview",),
            )
        start = vertices[0]
        base_end = vertices[1]
        base_length = math.dist(start, base_end) * 25.4 / 72
        width = math.dist(vertices[1], vertices[2]) * 25.4 / 72 if len(vertices) == 4 else 0.0
        orientation = math.degrees(math.atan2(base_end[1] - start[1], base_end[0] - start[0])) % 360
        self.kind_label.configure(text="Rectangle en cours")
        self.property_vars["x"].set(f"{start[0] * 25.4 / 72:.2f}")
        self.property_vars["y"].set(f"{start[1] * 25.4 / 72:.2f}")
        self.property_vars["width"].set(f"{base_length:.2f}")
        self.property_vars["height"].set(f"{width:.2f}")
        self.shape_geometry_label.configure(
            text=f"Dimensions en direct : {base_length:.2f} × {width:.2f} mm  •  orientation {orientation:.1f}°"
        )

    def _draw_rectangle_angle_guides(self, state: int) -> None:
        self.canvas.delete("angle-guide")
        if len(self._rectangle_points) != 1:
            return
        control = bool(state & 0x0004) or "control" in self._modifier_keys
        if not control:
            return
        try:
            increment = max(0.1, float(self.rotation_step_var.get().replace(",", ".")))
        except ValueError:
            increment = 15.0
        start = self._rectangle_points[0]
        guide_length = 150 * self.zoom
        for degrees in range(0, 360, max(1, round(increment))):
            angle = math.radians(degrees)
            sx = self.page_x + start[0] * self.zoom
            sy = self.page_y + start[1] * self.zoom
            self.canvas.create_line(
                sx, sy,
                sx + guide_length * math.cos(angle),
                sy + guide_length * math.sin(angle),
                fill="#78A9D1", width=1, dash=(3, 4), tags=("angle-guide",),
            )
            if degrees % 15 == 0:
                self.canvas.create_text(
                    sx + (guide_length + 10) * math.cos(angle),
                    sy + (guide_length + 10) * math.sin(angle),
                    text=f"{degrees}°", fill="#47779E", font=("Sans", 7), tags=("angle-guide",),
                )

    def _finish_rectangle(self, cursor: tuple[float, float]) -> None:
        vertices = self._rectangle_vertices(cursor)
        if math.dist(vertices[0], vertices[1]) <= 1e-6 or math.dist(vertices[1], vertices[2]) <= 1e-6:
            return
        closed = [*vertices, vertices[0]]
        left = min(point[0] for point in closed)
        top = min(point[1] for point in closed)
        relative = [[x - left, y - top] for x, y in closed]
        self._drawing_rectangle = False
        was_square = self._rectangle_square
        self._rectangle_square = False
        self._rectangle_points.clear()
        self.canvas.delete("rectangle-preview")
        self.canvas.delete("angle-guide")
        self.canvas.configure(cursor="")
        self._add_object(
            PageObject(
                "polyline", self.current_page, left, top,
                max(point[0] for point in relative), max(point[1] for point in relative),
                points=relative, shape="square_geometry" if was_square else "rectangle_geometry",
                border_color="#193B66", border_width=1.5, fill="transparent",
            )
        )
        self.status.configure(
            text=("Carré orienté créé : quatre côtés égaux et quatre angles droits." if was_square else "Rectangle orienté créé avec quatre angles droits exacts.")
        )

    def _triangle_cursor_point(self, x: float, y: float, state: int = 0) -> tuple[float, float]:
        point, _label = self._snap_drawing_point(x, y)
        if len(self._triangle_points) == 1:
            start = self._triangle_points[0]
            control = bool(state & 0x0004) or "control" in self._modifier_keys
            if control:
                try:
                    increment = max(0.1, float(self.rotation_step_var.get().replace(",", ".")))
                except ValueError:
                    increment = 15.0
                distance = math.dist(start, (x, y))
                angle = math.atan2(y - start[1], x - start[0])
                snapped_angle = round(math.degrees(angle) / increment) * increment
                point = (
                    start[0] + distance * math.cos(math.radians(snapped_angle)),
                    start[1] + distance * math.sin(math.radians(snapped_angle)),
                )
            else:
                point = self._constrained_drawing_point(start, x, y, state)
        if not self._triangle_right or len(self._triangle_points) < 2:
            return point
        right_vertex, first_side = self._triangle_points[:2]
        base_x, base_y = first_side[0] - right_vertex[0], first_side[1] - right_vertex[1]
        length = math.hypot(base_x, base_y)
        if length <= 1e-8:
            return point
        normal_x, normal_y = -base_y / length, base_x / length
        signed_height = (x - right_vertex[0]) * normal_x + (y - right_vertex[1]) * normal_y
        return right_vertex[0] + normal_x * signed_height, right_vertex[1] + normal_y * signed_height

    def _draw_triangle_preview(self, cursor: tuple[float, float] | None = None) -> None:
        self.canvas.delete("triangle-preview")
        points = [*self._triangle_points]
        if cursor is not None:
            points.append(cursor)
        if len(points) >= 2:
            coordinates = [
                coordinate
                for px, py in points
                for coordinate in (self.page_x + px * self.zoom, self.page_y + py * self.zoom)
            ]
            self.canvas.create_line(*coordinates, fill="#193B66", width=2, tags=("triangle-preview",))
            if len(points) == 3:
                self.canvas.create_line(
                    self.page_x + points[-1][0] * self.zoom,
                    self.page_y + points[-1][1] * self.zoom,
                    self.page_x + points[0][0] * self.zoom,
                    self.page_y + points[0][1] * self.zoom,
                    fill="#193B66", width=2, tags=("triangle-preview",),
                )
        measured_edges = list(pairwise(points))
        if len(points) == 3:
            measured_edges.append((points[-1], points[0]))
        for start, end in measured_edges:
            middle_x = self.page_x + (start[0] + end[0]) / 2 * self.zoom
            middle_y = self.page_y + (start[1] + end[1]) / 2 * self.zoom
            self.canvas.create_text(
                middle_x, middle_y - 9,
                text=f"{math.dist(start, end) * 25.4 / 72:.2f} mm",
                fill="#A34D00", font=("Sans", 8, "bold"), tags=("triangle-preview",),
            )
        if len(points) == 3:
            center_x = sum(point[0] for point in points) / 3
            center_y = sum(point[1] for point in points) / 3
            for index, vertex in enumerate(points):
                previous = points[(index - 1) % 3]
                following = points[(index + 1) % 3]
                try:
                    angle = angle_at_vertex(previous, vertex, following)
                except ValueError:
                    continue
                label_x = vertex[0] + (center_x - vertex[0]) * 0.28
                label_y = vertex[1] + (center_y - vertex[1]) * 0.28
                self.canvas.create_text(
                    self.page_x + label_x * self.zoom,
                    self.page_y + label_y * self.zoom,
                    text=f"{angle:.1f}°",
                    fill="#1769AA", font=("Sans", 8, "bold"), tags=("triangle-preview",),
                )

    def _draw_triangle_angle_guides(self, state: int) -> None:
        self.canvas.delete("angle-guide")
        if len(self._triangle_points) != 1:
            return
        control = bool(state & 0x0004) or "control" in self._modifier_keys
        if not control:
            return
        try:
            increment = max(0.1, float(self.rotation_step_var.get().replace(",", ".")))
        except ValueError:
            increment = 15.0
        start = self._triangle_points[0]
        sx = self.page_x + start[0] * self.zoom
        sy = self.page_y + start[1] * self.zoom
        guide_length = 150 * self.zoom
        for degrees in range(0, 360, max(1, round(increment))):
            angle = math.radians(degrees)
            self.canvas.create_line(
                sx, sy,
                sx + guide_length * math.cos(angle),
                sy + guide_length * math.sin(angle),
                fill="#78A9D1", width=1, dash=(3, 4), tags=("angle-guide",),
            )
            if degrees % 15 == 0:
                self.canvas.create_text(
                    sx + (guide_length + 10) * math.cos(angle),
                    sy + (guide_length + 10) * math.sin(angle),
                    text=f"{degrees}°", fill="#47779E", font=("Sans", 7), tags=("angle-guide",),
                )

    def _finish_triangle(self) -> None:
        if len(self._triangle_points) != 3:
            return
        was_right = self._triangle_right
        absolute = [*self._triangle_points, self._triangle_points[0]]
        left = min(point[0] for point in absolute)
        top = min(point[1] for point in absolute)
        relative = [[x - left, y - top] for x, y in absolute]
        self._drawing_triangle = False
        self._triangle_right = False
        self._triangle_points.clear()
        self.canvas.delete("triangle-preview")
        self.canvas.delete("angle-guide")
        self.canvas.configure(cursor="")
        self._add_object(
            PageObject(
                "polyline", self.current_page, left, top,
                max(point[0] for point in relative), max(point[1] for point in relative),
                points=relative,
                shape="right_triangle_geometry" if was_right else "triangle_geometry",
                border_color="#193B66", border_width=1.5, fill="transparent",
            )
        )
        self.status.configure(text="Triangle créé. Côtés et angles sont disponibles dans les propriétés.")

    def _insert_symbol(self) -> None:
        symbol = pick_symbol(self)
        if not symbol:
            return
        if self._editing_widget is not None:
            widget = self._editing_widget
            try:
                widget.delete("sel.first", "sel.last")
            except tk.TclError:
                pass
            widget.insert("insert", symbol)
            widget.focus_set()
            return
        if self.selected is not None and self.document.objects[self.selected].kind == "text":
            self._checkpoint()
            self.document.objects[self.selected].text += symbol
            self._render()
        else:
            family = "Flèches" if symbol in "←→↑↓↔⇒⇐➜" else "Symboles"
            self._add_object(PageObject("text", self.current_page, 70, 80, 80, 50, text=symbol, font_size=24, font_family=family))

    def _add_chart(self, chart_type: str) -> None:
        if self.selected is None or self.document.objects[self.selected].kind != "table":
            messagebox.showinfo("Graphique", "Sélectionnez d’abord le tableau qui contient les données.", parent=self)
            return
        table = self.document.objects[self.selected]
        chart = PageObject(
            "chart", self.current_page, table.x, table.y + table.height + 25,
            320, 210, fill=chart_type, source_id=table.object_id,
        )
        self._add_object(chart)
        self.after_idle(lambda: self._edit_chart_settings(chart))

    @staticmethod
    def _chart_values(rows: list[list[str]], series_index: int) -> tuple[str, list[tuple[str, float]]]:
        if not rows:
            return "", []
        columns = max(len(row) for row in rows)
        series_index = min(max(0, series_index), max(0, columns - 1))
        header = rows[0][series_index] if series_index < len(rows[0]) else ""
        start = 1 if any(
            value and not value.replace(",", ".").replace("-", "", 1).isdigit()
            for value in rows[0]
        ) else 0
        values: list[tuple[str, float]] = []
        for index, row in enumerate(rows[start:], start=start):
            try:
                value = float(row[series_index].replace(",", "."))
            except (ValueError, IndexError):
                continue
            label = row[0] if row and series_index != 0 else str(index - start + 1)
            values.append((label or str(index - start + 1), value))
        return header, values

    @classmethod
    def _chart_series(
        cls, rows: list[list[str]], series_indices: list[int]
    ) -> list[tuple[str, list[tuple[str, float]]]]:
        return [cls._chart_values(rows, index) for index in series_indices]

    @staticmethod
    def _chart_oriented_rows(rows: list[list[str]], orientation: str) -> list[list[str]]:
        if orientation != "rows" or not rows:
            return rows
        width = max(len(row) for row in rows)
        padded = [row + [""] * (width - len(row)) for row in rows]
        return [list(column) for column in zip(*padded)]

    def _edit_chart_settings(self, item: PageObject) -> None:
        source = next(
            (candidate for candidate in self.document.objects if candidate.object_id == item.source_id),
            None,
        )
        cell_rows = self._ensure_table_cells(source) if source and source.kind == "table" else []
        rows = [[str(cell.get("text", "")) for cell in row] for row in cell_rows]
        dialog = tk.Toplevel(self)
        dialog.title("Paramètres du graphique")
        dialog.transient(self)
        dialog.resizable(False, False)
        body = ttk.Frame(dialog, padding=14)
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(1, weight=1)
        ttk.Label(body, text="Titre").grid(row=0, column=0, sticky="w", pady=4)
        title_var = tk.StringVar(value=item.chart_title)
        ttk.Entry(body, textvariable=title_var, width=28).grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Label(body, text="Type").grid(row=1, column=0, sticky="w", pady=4)
        chart_types = {
            "Colonnes": "bar",
            "Barres horizontales": "hbar",
            "Courbe": "line",
            "Camembert": "pie",
        }
        current_type = next((label for label, value in chart_types.items() if value == item.fill), "Colonnes")
        type_var = tk.StringVar(value=current_type)
        ttk.Combobox(
            body, textvariable=type_var, values=list(chart_types), state="readonly", width=26,
        ).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Label(body, text="Analyser par").grid(row=2, column=0, sticky="nw", pady=4)
        orientation_var = tk.StringVar(value=item.chart_data_orientation)
        orientation_frame = ttk.Frame(body)
        orientation_frame.grid(row=2, column=1, sticky="w", pady=4)
        ttk.Radiobutton(
            orientation_frame, text="Colonnes", variable=orientation_var, value="columns",
        ).pack(side="left")
        ttk.Radiobutton(
            orientation_frame, text="Lignes", variable=orientation_var, value="rows",
        ).pack(side="left", padx=(12, 0))
        ttk.Label(body, text="Séries de valeurs").grid(row=3, column=0, sticky="nw", pady=4)
        series_list = tk.Listbox(
            body,
            selectmode="extended",
            exportselection=False,
            height=6,
            width=28,
        )
        series_list.grid(row=3, column=1, sticky="ew", pady=4)

        def refresh_series(*_args: object) -> None:
            oriented = self._chart_oriented_rows(rows, orientation_var.get())
            headers = oriented[0] if oriented else ["Valeurs"]
            series_list.delete(0, "end")
            for index, header in enumerate(headers):
                series_list.insert("end", header or f"Colonne {index + 1}")
            selected = item.chart_series_indices or [item.chart_series_index]
            for index in selected:
                if 0 <= index < len(headers):
                    series_list.selection_set(index)
            if not series_list.curselection() and headers:
                series_list.selection_set(min(1, len(headers) - 1))

        orientation_var.trace_add("write", refresh_series)
        refresh_series()
        ttk.Label(
            body,
            text=(
                "Ctrl + clic pour choisir plusieurs colonnes. "
                "Un camembert utilise une seule série."
            ),
            foreground="#52677A",
            wraplength=340,
            justify="left",
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(0, 6))
        legend_var = tk.BooleanVar(value=item.chart_show_legend)
        values_var = tk.BooleanVar(value=item.chart_show_values)
        ttk.Checkbutton(body, text="Afficher la légende", variable=legend_var).grid(row=5, column=0, columnspan=2, sticky="w", pady=4)
        ttk.Checkbutton(body, text="Afficher les valeurs", variable=values_var).grid(row=6, column=0, columnspan=2, sticky="w", pady=4)

        def apply() -> None:
            self._checkpoint()
            item.chart_title = title_var.get().strip()
            chosen = [int(index) for index in series_list.curselection()]
            oriented = self._chart_oriented_rows(rows, orientation_var.get())
            headers = oriented[0] if oriented else ["Valeurs"]
            if not chosen:
                chosen = [min(1, len(headers) - 1)]
            item.fill = chart_types[type_var.get()]
            if item.fill == "pie" and len(chosen) > 1:
                chosen = chosen[:1]
            item.chart_series_indices = chosen
            item.chart_series_index = chosen[0]
            item.chart_data_orientation = orientation_var.get()
            item.chart_show_legend = legend_var.get()
            item.chart_show_values = values_var.get()
            dialog.destroy()
            self._render()

        buttons = ttk.Frame(body)
        buttons.grid(row=7, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Annuler", command=dialog.destroy).pack(side="left", padx=4)
        ttk.Button(buttons, text="Appliquer", command=apply).pack(side="left", padx=4)
        dialog.bind("<Return>", lambda _event: apply())
        dialog.update_idletasks()
        requested_width = max(480, dialog.winfo_reqwidth() + 8)
        requested_height = max(390, dialog.winfo_reqheight() + 8)
        center_window(
            dialog,
            min(requested_width, dialog.winfo_screenwidth() - 60),
            min(requested_height, dialog.winfo_screenheight() - 100),
        )

    def _draw_chart_preview(self, item: PageObject, x: float, y: float, width: float, height: float, tags: tuple[str, str]) -> None:
        source = next((candidate for candidate in self.document.objects if candidate.object_id == item.source_id), None)
        rows = (
            evaluate_table_cells(self._ensure_table_cells(source))
            if source and source.kind == "table"
            else []
        )
        rows = self._chart_oriented_rows(rows, item.chart_data_orientation)
        selected_series = item.chart_series_indices or [item.chart_series_index]
        series = self._chart_series(rows, selected_series)
        series_name, values = series[0] if series else ("", [])
        self.canvas.create_rectangle(x, y, x + width, y + height, fill="white", outline="#72879C", tags=tags)
        if not values:
            self.canvas.create_text(x + width / 2, y + height / 2, text="Aucune donnée numérique", tags=tags)
            return
        colors = ("#2368AF", "#E8642E", "#45A37D", "#F0B738", "#875CB5")
        top = y + 8
        if item.chart_title:
            self.canvas.create_text(x + width / 2, top, text=item.chart_title, anchor="n", font=("Sans", 10, "bold"), tags=tags)
            top += 20
        if item.fill == "pie":
            total = sum(abs(value) for _, value in values) or 1
            start = 0.0
            legend_width = width * 0.32 if item.chart_show_legend else 0
            size = min(width - legend_width, height - (top - y)) * 0.72
            pie_left = x + 8 + (width - legend_width - size) / 2
            pie_top = top + (height - (top - y) - size) / 2
            for index, (label, value) in enumerate(values):
                extent = 360 * abs(value) / total
                self.canvas.create_arc(pie_left, pie_top, pie_left + size, pie_top + size, start=start, extent=extent, fill=colors[index % len(colors)], outline="white", tags=tags)
                if item.chart_show_legend:
                    legend_x, legend_y = x + width - legend_width + 8, top + index * 18
                    self.canvas.create_rectangle(legend_x, legend_y + 2, legend_x + 10, legend_y + 12, fill=colors[index % len(colors)], outline="", tags=tags)
                    suffix = f" — {value:g}" if item.chart_show_values else ""
                    self.canvas.create_text(legend_x + 14, legend_y, text=f"{label}{suffix}", anchor="nw", font=("Sans", 8), tags=tags)
                start += extent
        elif item.fill == "line":
            all_values = [abs(value) for _name, entries in series for _label, value in entries]
            maximum = max(all_values, default=1) or 1
            categories = values
            plot_top = top + (18 if item.chart_show_legend else 0)
            plot_bottom = y + height - 22
            step = (width - 24) / max(1, len(categories) - 1)
            for series_index, (_name, entries) in enumerate(series):
                points: list[float] = []
                for index, (_label, value) in enumerate(entries):
                    point_x = x + 12 + index * step
                    point_y = plot_bottom - (plot_bottom - plot_top) * abs(value) / maximum
                    points.extend((point_x, point_y))
                    self.canvas.create_oval(point_x - 3, point_y - 3, point_x + 3, point_y + 3, fill=colors[series_index % len(colors)], outline="", tags=tags)
                    if item.chart_show_values:
                        self.canvas.create_text(point_x, point_y - 8, text=f"{value:g}", font=("Sans", 7), tags=tags)
                if len(points) >= 4:
                    self.canvas.create_line(*points, fill=colors[series_index % len(colors)], width=2, tags=tags)
            for index, (label, _value) in enumerate(categories):
                self.canvas.create_text(x + 12 + index * step, y + height - 10, text=label[:10], font=("Sans", 7), tags=tags)
            if item.chart_show_legend:
                self._draw_chart_legend(item, series, colors, x + 8, top, tags)
        elif item.fill == "hbar":
            all_values = [abs(value) for _name, entries in series for _label, value in entries]
            maximum = max(all_values, default=1) or 1
            categories = values
            plot_top = top + (18 if item.chart_show_legend else 0)
            category_gap = max(12.0, (y + height - plot_top - 8) / max(1, len(categories)))
            series_count = max(1, len(series))
            bar_height = max(3.0, category_gap - 5) / series_count
            plot_left = x + min(70, width * 0.24)
            for category_index, (label, _value) in enumerate(categories):
                center_y = plot_top + (category_index + 0.5) * category_gap
                self.canvas.create_text(plot_left - 5, center_y, text=label[:12], anchor="e", font=("Sans", 7), tags=tags)
                for series_index, (_name, entries) in enumerate(series):
                    if category_index >= len(entries):
                        continue
                    value = entries[category_index][1]
                    top_y = center_y - (series_count * bar_height) / 2 + series_index * bar_height
                    right = plot_left + (width - (plot_left - x) - 8) * abs(value) / maximum
                    self.canvas.create_rectangle(plot_left, top_y, right, top_y + max(2, bar_height - 2), fill=colors[series_index % len(colors)], outline="", tags=tags)
                    if item.chart_show_values:
                        self.canvas.create_text(right + 3, top_y, text=f"{value:g}", anchor="nw", font=("Sans", 7), tags=tags)
            if item.chart_show_legend:
                self._draw_chart_legend(item, series, colors, x + 8, top, tags)
        else:
            all_values = [abs(value) for _name, entries in series for _label, value in entries]
            maximum = max(all_values, default=1) or 1
            categories = values
            gap = width / max(1, len(categories))
            series_count = max(1, len(series))
            bar_gap = max(4.0, gap - 10) / series_count
            for category_index, (label, _value) in enumerate(categories):
                for series_index, (_name, entries) in enumerate(series):
                    if category_index >= len(entries):
                        continue
                    value = entries[category_index][1]
                    bar_height = (height - 42 - (top - y)) * abs(value) / maximum
                    left = x + category_index * gap + 5 + series_index * bar_gap
                    right = left + max(2, bar_gap - 3)
                    self.canvas.create_rectangle(left, y + height - 20 - bar_height, right, y + height - 20, fill=colors[series_index % len(colors)], outline="", tags=tags)
                    if item.chart_show_values:
                        self.canvas.create_text((left + right) / 2, y + height - 24 - bar_height, text=f"{value:g}", font=("Sans", 7), tags=tags)
                self.canvas.create_text(x + (category_index + 0.5) * gap, y + height - 10, text=label[:10], font=("Sans", 7), tags=tags)
            if item.chart_show_legend:
                self._draw_chart_legend(item, series, colors, x + 8, top, tags)

    def _draw_chart_legend(
        self,
        item: PageObject,
        series: list[tuple[str, list[tuple[str, float]]]],
        colors: tuple[str, ...],
        x: float,
        y: float,
        tags: tuple[str, str],
    ) -> None:
        legend_x = x
        for series_index, (name, _entries) in enumerate(series):
            self.canvas.create_rectangle(legend_x, y + 2, legend_x + 9, y + 11, fill=colors[series_index % len(colors)], outline="", tags=tags)
            label = name or f"Série {series_index + 1}"
            self.canvas.create_text(legend_x + 12, y, text=label, anchor="nw", font=("Sans", 7), tags=tags)
            legend_x += max(55, len(label) * 6 + 24)

    def _make_list(self, numbered: bool) -> None:
        if self.selected is None or self.document.objects[self.selected].kind != "text":
            return
        if self._editing_widget is not None:
            widget = self._editing_widget
            first_line, last_line = self._inline_selected_line_numbers(widget)
            # Modifier seulement le préfixe de chaque paragraphe. Remplacer le
            # bloc entier détruisait les tags Tk qui portent gras, taille,
            # couleur, surlignage et liens.
            for list_index, line_number in reversed(
                list(enumerate(range(first_line, last_line + 1), start=1))
            ):
                line_start = f"{line_number}.0"
                content = widget.get(line_start, f"{line_start} lineend")
                prefix_length = 0
                if content.startswith("• "):
                    prefix_length = 2
                else:
                    match = re.match(r"\d+\.\s+", content)
                    if match is not None:
                        prefix_length = match.end()
                if prefix_length:
                    widget.delete(line_start, f"{line_start} + {prefix_length} chars")
                prefix = f"{list_index}. " if numbered else "• "
                widget.insert(line_start, prefix)
            self._editing_selection_range = (
                self._text_character_offset(widget, f"{first_line}.0"),
                self._text_character_offset(widget, f"{last_line}.0 lineend"),
            )
            widget.focus_set()
            return
        self._checkpoint()
        item = self.document.objects[self.selected]
        lines = [line.removeprefix("• ").strip() for line in item.text.splitlines()]
        item.text = "\n".join(f"{index + 1}. {line}" if numbered else f"• {line}" for index, line in enumerate(lines))
        self._render()

    def _add_preset(self, kind: str) -> None:
        width, height = self._page_size()
        labels = {
            "header": ("Texte d’en-tête", 45, 30, width - 90, 45),
            "footer": ("Page {{PAGE}} / {{PAGES}}", 45, height - 65, width - 90, 35),
            "left_margin": ("Notes", 18, 90, 90, height - 160),
        }
        text, x, y, object_width, object_height = labels[kind]
        item = PageObject("text", self.current_page, x, y, object_width, object_height, text=text)
        item.pages = "all"
        self._add_object(item)

    def _insert_field(self, token: str) -> None:
        if self.selected is not None and self.document.objects[self.selected].kind == "text":
            self._checkpoint()
            item = self.document.objects[self.selected]
            item.text = f"{item.text} {token}".strip()
            self._render()
            return
        width, height = self._page_size()
        item = PageObject(
            "text",
            self.current_page,
            45,
            height - 65,
            width - 90,
            35,
            text=token,
            align="center",
            pages="all",
        )
        self._add_object(item)

    def _object_at_event(self, event: tk.Event[tk.Misc]) -> int | None:
        current = self.canvas.find_withtag("current")
        if current:
            for tag in self.canvas.gettags(current[0]):
                if tag.startswith("object:"):
                    return int(tag.split(":", 1)[1])
        page_x = (self.canvas.canvasx(event.x) - self.page_x) / self.zoom
        page_y = (self.canvas.canvasy(event.y) - self.page_y) / self.zoom
        tolerance = max(5.0, 9.0 / self.zoom)
        hit_order = sorted(
            range(len(self.document.objects)),
            key=lambda index: (self.document.objects[index].level, index),
            reverse=True,
        )
        for index in hit_order:
            item = self.document.objects[index]
            if self.current_page not in pages_for_object(item, self.document.page_count):
                continue
            if item.kind == "line":
                segment = Segment(item.x, item.y, item.x + item.width, item.y + item.height)
                if point_to_segment_distance(page_x, page_y, segment) <= tolerance:
                    return index
                continue
            if item.kind == "polyline" and len(item.points) >= 2:
                points = [(item.x + point[0], item.y + point[1]) for point in item.points]
                if any(
                    point_to_segment_distance(page_x, page_y, Segment(*start, *end))
                    <= tolerance
                    for start, end in pairwise(points)
                ):
                    return index
                continue
            left = min(item.x, item.x + item.width) - tolerance
            right = max(item.x, item.x + item.width) + tolerance
            top = min(item.y, item.y + item.height) - tolerance
            bottom = max(item.y, item.y + item.height) + tolerance
            if left <= page_x <= right and top <= page_y <= bottom:
                return index
        return None

    def _press(self, event: tk.Event[tk.Misc]) -> None:
        self._dismiss_context_menu()
        if self._pdf_font_pick_mode:
            self._pick_pdf_font(event)
            return
        if self._crop_mode_index is not None:
            self._start_crop_drag(event)
            return
        if self._insert_table_formula_reference(event):
            return
        self._commit_inline_editor(render=True)
        self.canvas.focus_set()
        if self._measurement_mode:
            page_x = (self.canvas.canvasx(event.x) - self.page_x) / self.zoom
            page_y = (self.canvas.canvasy(event.y) - self.page_y) / self.zoom
            self._capture_measurement_point(page_x, page_y)
            return
        if self._start_rotation_drag_if_hit(event):
            return
        if self._drawing_text:
            page_x = (self.canvas.canvasx(event.x) - self.page_x) / self.zoom
            page_y = (self.canvas.canvasy(event.y) - self.page_y) / self.zoom
            width, height = self._page_size()
            if 0 <= page_x <= width and 0 <= page_y <= height:
                self._text_draw_start = (page_x, page_y)
                self.canvas.delete("text-frame-preview")
            return
        if self._pending_right_triangle is not None:
            page_x = (self.canvas.canvasx(event.x) - self.page_x) / self.zoom
            page_y = (self.canvas.canvasy(event.y) - self.page_y) / self.zoom
            self._place_right_triangle_perpendicular(page_x, page_y)
            return
        if self._placing_work_origin:
            page_x = (self.canvas.canvasx(event.x) - self.page_x) / self.zoom
            page_y = (self.canvas.canvasy(event.y) - self.page_y) / self.zoom
            self._place_work_origin(page_x, page_y)
            return
        if self._pending_corner_treatment is not None:
            page_x = (self.canvas.canvasx(event.x) - self.page_x) / self.zoom
            page_y = (self.canvas.canvasy(event.y) - self.page_y) / self.zoom
            self._apply_corner_treatment(page_x, page_y)
            return
        if self._pending_edge_snap is not None:
            page_x = (self.canvas.canvasx(event.x) - self.page_x) / self.zoom
            page_y = (self.canvas.canvasy(event.y) - self.page_y) / self.zoom
            self._choose_edge_for_snap(page_x, page_y)
            return
        if self._pending_driving_dimension is not None:
            page_x = (self.canvas.canvasx(event.x) - self.page_x) / self.zoom
            page_y = (self.canvas.canvasy(event.y) - self.page_y) / self.zoom
            self._choose_edge_for_driving_dimension(page_x, page_y)
            return
        if self._drawing_triangle:
            page_x = (self.canvas.canvasx(event.x) - self.page_x) / self.zoom
            page_y = (self.canvas.canvasy(event.y) - self.page_y) / self.zoom
            point = self._triangle_cursor_point(page_x, page_y, event.state)
            self._triangle_points.append(point)
            self._draw_triangle_preview()
            if len(self._triangle_points) == 3:
                self._finish_triangle()
            else:
                self.status.configure(
                    text=f"Sommet {len(self._triangle_points)} mémorisé. Cliquez le sommet suivant."
                )
            return
        if self._drawing_rectangle:
            page_x = (self.canvas.canvasx(event.x) - self.page_x) / self.zoom
            page_y = (self.canvas.canvasy(event.y) - self.page_y) / self.zoom
            point = self._rectangle_cursor_point(page_x, page_y, event.state)
            if len(self._rectangle_points) < 2:
                self._rectangle_points.append(point)
                self.status.configure(
                    text=("Premier point mémorisé. Tracez le premier côté." if len(self._rectangle_points) == 1 else "Premier côté mémorisé. Réglez maintenant la largeur perpendiculaire.")
                )
            else:
                self._finish_rectangle(point)
            return
        if self._drawing_line:
            page_x = (self.canvas.canvasx(event.x) - self.page_x) / self.zoom
            page_y = (self.canvas.canvasy(event.y) - self.page_y) / self.zoom
            width, height = self._page_size()
            if not (0 <= page_x <= width and 0 <= page_y <= height):
                return
            if not self._line_points:
                point, snap_label = self._snap_drawing_point(page_x, page_y)
                self._line_points.append(point)
                self._draw_snap_marker(point, snap_label)
                self.status.configure(
                    text=(f"Départ accroché sur une {snap_label}. " if snap_label else "Point de départ placé. ")
                    + "Cliquez l’arrivée ou appuyez sur Entrée."
                )
            else:
                endpoint = self._constrained_drawing_point(self._line_points[0], page_x, page_y, event.state)
                endpoint, _snap_label = self._snap_drawing_point(*endpoint)
                self._finish_line(endpoint)
            return
        if self._drawing_polyline:
            page_x = (self.canvas.canvasx(event.x) - self.page_x) / self.zoom
            page_y = (self.canvas.canvasy(event.y) - self.page_y) / self.zoom
            width, height = self._page_size()
            if 0 <= page_x <= width and 0 <= page_y <= height:
                page_x, page_y = self._constrained_polyline_point(
                    page_x, page_y, event.state
                )
                page_x, page_y = self._snap_drawing_point(page_x, page_y)[0]
                self._polyline_points.append((page_x, page_y))
                self._draw_polyline_preview()
                self.kind_label.configure(
                    text=f"Profil en cours — sommet {len(self._polyline_points)}"
                )
                self.property_vars["x"].set(f"{page_x * 25.4 / 72:.2f}")
                self.property_vars["y"].set(f"{page_y * 25.4 / 72:.2f}")
                if len(self._polyline_points) >= 2:
                    start, end = self._polyline_points[-2:]
                    length_mm = math.dist(start, end) * 25.4 / 72
                    delta_x_mm = (end[0] - start[0]) * 25.4 / 72
                    delta_y_mm = (end[1] - start[1]) * 25.4 / 72
                    self.property_vars["width"].set(f"{abs(delta_x_mm):.2f}")
                    self.property_vars["height"].set(f"{abs(delta_y_mm):.2f}")
                    self.geometry_help.configure(
                        text=f"Segment {len(self._polyline_points) - 1} : {length_mm:.2f} mm   ΔX {delta_x_mm:.2f}   ΔY {delta_y_mm:.2f}"
                    )
                    self.status.configure(
                        text=f"Sommet {len(self._polyline_points)} — dernier segment : {length_mm:.2f} mm. Entrée termine."
                    )
            return
        current = self.canvas.find_withtag("current")
        if current:
            for tag in self.canvas.gettags(current[0]):
                if tag.startswith("vertex:"):
                    _, object_index, point_index = tag.split(":")
                    index = int(object_index)
                    self.selected = index
                    self.selected_indices = {index}
                    self._vertex_drag_origin = (
                        index,
                        int(point_index),
                        copy.deepcopy(self.document.objects[index].points),
                    )
                    self._selected_vertex = (index, int(point_index))
                    self._drag_before = copy.deepcopy(self.document)
                    self._drag_origin = None
                    return
            if (
                "assembly-resize" in self.canvas.gettags(current[0])
                and len(self.selected_indices) > 1
            ):
                objects = [self.document.objects[index] for index in self.selected_indices]
                if any(item.locked for item in objects):
                    self.status.configure(
                        text="L’assemblage contient un axe 3D verrouillé. Déverrouillez-le avant le redimensionnement."
                    )
                    return
                left, top, width, height = objects_bounds(objects)
                self._assembly_resize_origin = (
                    self.canvas.canvasx(event.x),
                    self.canvas.canvasy(event.y),
                    left,
                    top,
                    width,
                    height,
                )
                self._drag_before = copy.deepcopy(self.document)
                self._drag_origin = None
                return
            for tag in self.canvas.gettags(current[0]):
                if tag.startswith(("resize-start:", "resize-end:")):
                    mode, object_index = tag.split(":", 1)
                    self.selected = int(object_index)
                    item = self.document.objects[self.selected]
                    if item.locked:
                        self.status.configure(text="Cet objet est verrouillé.")
                        return
                    self._resize_origin = (
                        mode,
                        self.canvas.canvasx(event.x),
                        self.canvas.canvasy(event.y),
                        item.x,
                        item.y,
                        item.width,
                        item.height,
                    )
                    self._drag_origin = None
                    return
        clicked = self._object_at_event(event)
        self._selected_vertex = None
        if clicked is not None:
            self._last_clicked_index = clicked
        if self._pending_text_link_id:
            source = next(
                (item for item in self.document.objects if item.object_id == self._pending_text_link_id),
                None,
            )
            target = self.document.objects[clicked] if clicked is not None else None
            if source is not None and target is not None and target.kind == "text" and target.object_id != source.object_id:
                self._pending_text_link_id = ""
                self.canvas.configure(cursor="")
                self._connect_text_frames(source, target)
            else:
                self.status.configure(
                    text="Chaînage en attente : cliquez dans une autre zone de texte verte, ou Échap pour annuler."
                )
            return
        control = bool(event.state & 0x0004) or bool(
            sys.platform == "darwin" and event.state & 0x0008
        )
        if clicked is None:
            self._marquee_origin = (
                self.canvas.canvasx(event.x),
                self.canvas.canvasy(event.y),
            )
            self._marquee_initial_selection = set(self.selected_indices) if control else set()
            if not control:
                self.selected = None
                self.selected_indices.clear()
            self._drag_origin = None
            self._render()
            return
        elif control:
            if clicked in self.selected_indices:
                self.selected_indices.remove(clicked)
            else:
                self.selected_indices.add(clicked)
            self.selected = clicked if clicked in self.selected_indices else next(iter(self.selected_indices), None)
        else:
            self.selected = clicked
            group = self.document.objects[clicked].group
            self.selected_indices = {
                index for index, item in enumerate(self.document.objects) if group and item.group == group
            } or {clicked}
        if self.selected is not None:
            item = self.document.objects[self.selected]
            if item.kind == "table" and len(self.selected_indices) == 1:
                row, column = self._table_cell_at_event(item, event)
                self._active_table_cell = (item.object_id, row, column)
            if any(self.document.objects[index].locked for index in self.selected_indices):
                self._drag_origin = None
                self.status.configure(
                    text="L’axe 3D est verrouillé. Utilisez Profil ▾ → Déverrouiller l’axe pour le déplacer."
                )
                self._render()
                return
            self._drag_origin = (self.canvas.canvasx(event.x), self.canvas.canvasy(event.y), item.x, item.y)
            self._drag_positions = {
                index: (self.document.objects[index].x, self.document.objects[index].y)
                for index in self.selected_indices
            }
            self._drag_before = copy.deepcopy(self.document)
        else:
            self._drag_origin = None
        self._render()

    def _start_rotation_drag_if_hit(self, event: tk.Event[tk.Misc]) -> bool:
        if not self.selected_indices:
            return False
        indices = expanded_group_indices(self.document.objects, self.selected_indices)
        objects = [self.document.objects[index] for index in indices]
        if any(item.locked for item in objects):
            return False
        left, top, width, height = objects_bounds(objects)
        handle = (
            self.page_x + (left + width / 2) * self.zoom,
            self.page_y + top * self.zoom - 30,
        )
        if len(objects) == 1 and objects[0].kind == "text":
            item = objects[0]
            corners = rotated_rectangle_points(item)
            top_middle_x = (corners[0][0] + corners[1][0]) / 2
            top_middle_y = (corners[0][1] + corners[1][1]) / 2
            normal_x = top_middle_x - (item.x + item.width / 2)
            normal_y = top_middle_y - (item.y + item.height / 2)
            normal_length = max(1e-9, math.hypot(normal_x, normal_y))
            handle = (
                self.page_x + top_middle_x * self.zoom + normal_x / normal_length * 30,
                self.page_y + top_middle_y * self.zoom + normal_y / normal_length * 30,
            )
        pointer = (self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        if not point_hits_rotation_handle(pointer, handle):
            return False
        if getattr(self, "_editing_widget", None) is not None:
            self._commit_inline_editor(render=False)
        pivot_x, pivot_y = left + width / 2, top + height / 2
        pointer_x = (pointer[0] - self.page_x) / self.zoom
        pointer_y = (pointer[1] - self.page_y) / self.zoom
        start_angle = math.degrees(math.atan2(pointer_y - pivot_y, pointer_x - pivot_x))
        self.selected_indices = indices
        self.selected = min(indices)
        self._rotation_drag_origin = (pivot_x, pivot_y, start_angle)
        self._rotation_drag_delta = 0.0
        self._rotation_drag_before = copy.deepcopy(self.document)
        self._rotation_preview_applied = False
        self._drag_origin = None
        self.status.configure(
            text="Rotation guidée : maintenez le clic et déplacez la poignée autour de l’objet."
        )
        return True

    def _double_click(self, event: tk.Event[tk.Misc]) -> str:
        if self._drawing_line:
            page_x = (self.canvas.canvasx(event.x) - self.page_x) / self.zoom
            page_y = (self.canvas.canvasy(event.y) - self.page_y) / self.zoom
            endpoint = self._constrained_drawing_point(self._line_points[0], page_x, page_y, event.state)
            endpoint, _label = self._snap_drawing_point(*endpoint)
            return self._finish_line(endpoint) or "break"
        if self._drawing_polyline:
            if len(self._polyline_points) >= 2 and math.dist(self._polyline_points[-2], self._polyline_points[-1]) <= max(2.0, 5.0 / self.zoom):
                self._polyline_points.pop()
            return self._finish_polyline(event) or "break"
        clicked = self._object_at_event(event)
        if clicked is not None and self.document.objects[clicked].kind == "table":
            item = self.document.objects[clicked]
            row, column = self._table_cell_at_event(item, event)
            self.selected = clicked
            self.selected_indices = {clicked}
            self.after_idle(lambda: self._start_inline_table_cell_editor(item, row, column))
            return "break"
        if clicked is not None and self.document.objects[clicked].kind == "chart":
            item = self.document.objects[clicked]
            self.selected = clicked
            self.selected_indices = {clicked}
            self.after_idle(lambda: self._edit_chart_settings(item))
            return "break"
        if self._last_clicked_index is not None and self._last_clicked_index < len(self.document.objects):
            self.selected = self._last_clicked_index
            self.selected_indices = {self.selected}
            self.after_idle(self._edit_selected)
        return "break"

    def _drag(self, event: tk.Event[tk.Misc]) -> None:
        if self._crop_drag_edge is not None:
            self._drag_crop_edge(event)
            return
        if self._rotation_drag_origin is not None:
            pivot_x, pivot_y, start_angle = self._rotation_drag_origin
            pointer_x = (self.canvas.canvasx(event.x) - self.page_x) / self.zoom
            pointer_y = (self.canvas.canvasy(event.y) - self.page_y) / self.zoom
            current_angle = math.degrees(math.atan2(pointer_y - pivot_y, pointer_x - pivot_x))
            try:
                step = float(self.rotation_step_var.get().replace(",", "."))
            except ValueError:
                step = 15.0
            step = rotation_step_for_objects(
                [self.document.objects[index] for index in self.selected_indices], step
            )
            self._rotation_drag_delta = snapped_rotation_delta(start_angle, current_angle, step)
            indices = expanded_group_indices(self.document.objects, self.selected_indices)
            if self._rotation_drag_before is not None and not any(
                self.document.objects[index].kind == "image" for index in indices
            ):
                for index in indices:
                    self.document.objects[index] = copy.deepcopy(
                        self._rotation_drag_before.objects[index]
                    )
                for index in indices:
                    item = self.document.objects[index]
                    item_pivot = (pivot_x, pivot_y) if item.group else (
                        item.x + item.width / 2,
                        item.y + item.height / 2,
                    )
                    self._rotate_item_about(item, self._rotation_drag_delta, item_pivot)
                self._rotation_preview_applied = True
                self._render()
            self.canvas.delete("rotation-guide")
            canvas_pivot_x = self.page_x + pivot_x * self.zoom
            canvas_pivot_y = self.page_y + pivot_y * self.zoom
            radius = max(42.0, min(90.0, math.dist(
                (canvas_pivot_x, canvas_pivot_y),
                (self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)),
            )))
            self.canvas.create_oval(
                canvas_pivot_x - radius, canvas_pivot_y - radius,
                canvas_pivot_x + radius, canvas_pivot_y + radius,
                outline="#78A9D1", dash=(4, 4), width=2, tags=("rotation-guide",),
            )
            angle = math.radians(start_angle + self._rotation_drag_delta)
            self.canvas.create_line(
                canvas_pivot_x, canvas_pivot_y,
                canvas_pivot_x + radius * math.cos(angle),
                canvas_pivot_y + radius * math.sin(angle),
                fill="#E47D16", width=3, arrow="last", tags=("rotation-guide",),
            )
            self.canvas.create_text(
                canvas_pivot_x, canvas_pivot_y - radius - 12,
                text=f"{self._rotation_drag_delta:g}°", fill="#A34D00",
                font=("Sans", 10, "bold"), tags=("rotation-guide",),
            )
            self.status.configure(text=f"Rotation guidée : {self._rotation_drag_delta:g}°")
            return
        if (
            (self._drawing_rectangle and self._rectangle_points)
            or (self._drawing_triangle and self._triangle_points)
            or (self._drawing_line and self._line_points)
            or (self._drawing_polyline and self._polyline_points)
        ):
            # A drawing gesture must preview identically whether the user moves the
            # pointer after releasing the click or keeps the mouse button pressed.
            self._polyline_motion(event)
            return
        if self._drawing_text and self._text_draw_start is not None:
            start_x, start_y = self._text_draw_start
            page_width, page_height = self._page_size()
            end_x = max(0.0, min(page_width, (self.canvas.canvasx(event.x) - self.page_x) / self.zoom))
            end_y = max(0.0, min(page_height, (self.canvas.canvasy(event.y) - self.page_y) / self.zoom))
            self.canvas.delete("text-frame-preview")
            self.canvas.create_rectangle(
                self.page_x + start_x * self.zoom,
                self.page_y + start_y * self.zoom,
                self.page_x + end_x * self.zoom,
                self.page_y + end_y * self.zoom,
                outline="#1769AA",
                width=2,
                dash=(5, 3),
                fill="#DCEBFA",
                stipple="gray25",
                tags=("text-frame-preview",),
            )
            width_mm = abs(end_x - start_x) * 25.4 / 72
            height_mm = abs(end_y - start_y) * 25.4 / 72
            self.status.configure(text=f"Zone de texte : {width_mm:.1f} × {height_mm:.1f} mm.")
            return
        if self._vertex_drag_origin is not None:
            object_index, point_index, _original_points = self._vertex_drag_origin
            item = self.document.objects[object_index]
            absolute = [(item.x + x, item.y + y) for x, y in item.points]
            absolute[point_index] = (
                (self.canvas.canvasx(event.x) - self.page_x) / self.zoom,
                (self.canvas.canvasy(event.y) - self.page_y) / self.zoom,
            )
            self._set_polyline_absolute_points(item, absolute)
            self._render()
            return
        if self._marquee_origin is not None:
            start_x, start_y = self._marquee_origin
            end_x = self.canvas.canvasx(event.x)
            end_y = self.canvas.canvasy(event.y)
            self.canvas.delete("selection-marquee")
            self.canvas.create_rectangle(
                start_x,
                start_y,
                end_x,
                end_y,
                fill="#BBD9F3",
                stipple="gray25",
                outline="#1769AA",
                width=2,
                dash=(5, 3),
                tags=("selection-marquee",),
            )
            self.status.configure(text="Relâchez la souris pour sélectionner les objets entourés.")
            return
        if self._assembly_resize_origin is not None and self._drag_before is not None:
            sx, sy, left, top, old_width, old_height = self._assembly_resize_origin
            delta_x = (self.canvas.canvasx(event.x) - sx) / self.zoom
            delta_y = (self.canvas.canvasy(event.y) - sy) / self.zoom
            new_width = max(10.0, old_width + delta_x)
            new_height = max(10.0, old_height + delta_y)
            if event.state & 0x0001 and old_width and old_height:
                scale = max(new_width / old_width, new_height / old_height)
                new_width, new_height = old_width * scale, old_height * scale
            for index in self.selected_indices:
                self.document.objects[index] = copy.deepcopy(
                    self._drag_before.objects[index]
                )
            objects = [self.document.objects[index] for index in self.selected_indices]
            transform_object_assembly(objects, left, top, new_width, new_height)
            self._render()
            self.status.configure(
                text=f"Assemblage : {new_width * 25.4 / 72:.1f} × "
                f"{new_height * 25.4 / 72:.1f} mm."
            )
            return
        if self.selected is not None and self._resize_origin is not None:
            mode, sx, sy, old_x, old_y, old_width, old_height = self._resize_origin
            item = self.document.objects[self.selected]
            delta_x = (self.canvas.canvasx(event.x) - sx) / self.zoom
            delta_y = (self.canvas.canvasy(event.y) - sy) / self.zoom
            if item.kind == "line":
                if mode == "resize-start":
                    item.x = old_x + delta_x
                    item.y = old_y + delta_y
                    new_width = old_width - delta_x
                    new_height = old_height - delta_y
                else:
                    new_width = old_width + delta_x
                    new_height = old_height + delta_y
            else:
                new_width = max(20, old_width + delta_x)
                new_height = max(20, old_height + delta_y)
            control = bool(event.state & 0x0004) or "control" in self._modifier_keys
            if item.kind == "shape" and item.shape == "circle":
                if control:
                    item.shape = "ellipse"
                    self.status.configure(
                        text="Cercle converti en ellipse : largeur et hauteur sont maintenant indépendantes."
                    )
                else:
                    diameter = resized_circle_diameter(old_width, delta_x, delta_y)
                    new_width = new_height = diameter
            elif control and item.kind not in {"line", "polyline"}:
                new_width, new_height = proportional_resize(
                    old_width, old_height, new_width, new_height
                )
            if item.kind == "polyline" and item.width and item.height:
                item.points = [
                    [point[0] * new_width / item.width, point[1] * new_height / item.height]
                    for point in item.points
                ]
            item.width, item.height = new_width, new_height
            self._render()
            width_mm, height_mm = item.width * 25.4 / 72, item.height * 25.4 / 72
            guide = f"{width_mm:.1f} × {height_mm:.1f} mm"
            if item.kind == "line":
                length_mm = math.hypot(item.width, item.height) * 25.4 / 72
                guide = f"{length_mm:.1f} mm  •  {self._object_angle(item):.1f}°"
            self.canvas.create_text(
                self.page_x + (item.x + item.width) * self.zoom + 8,
                self.page_y + (item.y + item.height) * self.zoom + 8,
                text=guide,
                anchor="nw",
                fill="white",
                font=("Sans", 9, "bold"),
                tags=("dimension-guide",),
            )
            self.canvas.create_rectangle(
                self.canvas.bbox("dimension-guide"),
                fill="#193B66",
                outline="",
                tags=("dimension-guide-bg",),
            )
            self.canvas.tag_raise("dimension-guide")
            self.status.configure(text=f"Dimensions : {guide}")
            return
        if self.selected is None or self._drag_origin is None:
            return
        sx, sy, _object_x, _object_y = self._drag_origin
        pw, ph = self._page_size()
        dx = (self.canvas.canvasx(event.x) - sx) / self.zoom
        dy = (self.canvas.canvasy(event.y) - sy) / self.zoom
        if abs(dx) > 1e-8 or abs(dy) > 1e-8:
            self._coincident_edge_highlight = None
        moving_assembly = len(self._drag_positions) > 1
        if moving_assembly:
            original_objects = [
                self._drag_before.objects[index]
                for index in self._drag_positions
            ] if self._drag_before is not None else [
                self.document.objects[index] for index in self._drag_positions
            ]
            left, top, group_width, group_height = objects_bounds(original_objects)
            dx = max(-left, min(pw - (left + group_width), dx))
            dy = max(-top, min(ph - (top + group_height), dy))
        for index, (start_x, start_y) in self._drag_positions.items():
            item = self.document.objects[index]
            if moving_assembly:
                new_x, new_y = start_x + dx, start_y + dy
            elif item.kind == "dimension":
                length = math.hypot(item.width, item.height)
                if length <= 1e-8:
                    continue
                normal_x, normal_y = -item.height / length, item.width / length
                projected = dx * normal_x + dy * normal_y
                new_x = start_x + projected * normal_x
                new_y = start_y + projected * normal_y
            elif item.kind == "line":
                minimum_x, maximum_x = min(0.0, item.width), max(0.0, item.width)
                minimum_y, maximum_y = min(0.0, item.height), max(0.0, item.height)
                new_x = max(-minimum_x, min(pw - maximum_x, start_x + dx))
                new_y = max(-minimum_y, min(ph - maximum_y, start_y + dy))
            else:
                new_x = max(0, min(pw - item.width, start_x + dx))
                new_y = max(0, min(ph - item.height, start_y + dy))
            move_x = (new_x - item.x) * self.zoom
            move_y = (new_y - item.y) * self.zoom
            item.x, item.y = new_x, new_y
            self.canvas.move(f"object:{index}", move_x, move_y)
            self.canvas.move(f"resize-start:{index}", move_x, move_y)
            self.canvas.move(f"resize-end:{index}", move_x, move_y)
        moved_ids = {
            self.document.objects[index].object_id for index in self._drag_positions
        }
        if any(
            item.kind == "dimension"
            and any(str(reference.get("object_id", "")) in moved_ids for reference in item.dimension_refs)
            for item in self.document.objects
        ):
            self._render()
        if self.selected is not None:
            if len(self.selected_indices) > 1:
                self._update_assembly_geometry_fields()
            else:
                self._update_geometry_fields(self.document.objects[self.selected])

    def _release(self, event: tk.Event[tk.Misc]) -> None:
        if self._crop_drag_edge is not None:
            self._drag_crop_edge(event)
            self._apply_visual_crop()
            return
        if self._rotation_drag_origin is not None:
            degrees = self._rotation_drag_delta
            self._rotation_drag_origin = None
            self._rotation_drag_delta = 0.0
            self.canvas.delete("rotation-guide")
            if self._rotation_preview_applied and self._rotation_drag_before is not None:
                if abs(degrees) > 1e-8:
                    self.undo_stack.append(self._rotation_drag_before)
                    self.undo_stack = self.undo_stack[-80:]
                    self.redo_stack.clear()
                self._rotation_drag_before = None
                self._rotation_preview_applied = False
                self._render()
                self.status.configure(text=f"Rotation guidée appliquée : {degrees:g}°.")
            elif abs(degrees) > 1e-8:
                self._rotation_drag_before = None
                self._rotate_selected_degrees(degrees)
                self.status.configure(text=f"Rotation guidée appliquée : {degrees:g}°.")
            else:
                self._rotation_drag_before = None
                self._rotation_preview_applied = False
                self._render()
            return
        if self._drawing_text and self._text_draw_start is not None:
            start_x, start_y = self._text_draw_start
            page_width, page_height = self._page_size()
            end_x = max(0.0, min(page_width, (self.canvas.canvasx(event.x) - self.page_x) / self.zoom))
            end_y = max(0.0, min(page_height, (self.canvas.canvasy(event.y) - self.page_y) / self.zoom))
            left, top = min(start_x, end_x), min(start_y, end_y)
            width, height = abs(end_x - start_x), abs(end_y - start_y)
            if width < 8 or height < 8:
                left = min(left, max(0.0, page_width - 40.0))
                top = min(top, max(0.0, page_height - 30.0))
                width = min(280.0, page_width - left)
                height = min(80.0, page_height - top)
            self._drawing_text = False
            self._text_draw_start = None
            self.canvas.delete("text-frame-preview")
            self.canvas.configure(cursor="")
            self._add_object(PageObject(
                "text", self.current_page, left, top, max(40, width), max(30, height),
                border_width=1.5,
            ))
            self.status.configure(text="Zone de texte créée. Saisissez son contenu.")
            self.after_idle(
                lambda: self._start_inline_text_editor(self.document.objects[self.selected])
                if self.selected is not None
                else None
            )
            return
        if self._vertex_drag_origin is not None:
            object_index, _point_index, original_points = self._vertex_drag_origin
            self._vertex_drag_origin = None
            if self.document.objects[object_index].points != original_points and self._drag_before is not None:
                self.undo_stack.append(self._drag_before)
                self.redo_stack.clear()
            self._drag_before = None
            self.status.configure(text="Sommet du profil ajusté précisément.")
            self._render()
            return
        if self._marquee_origin is not None:
            start_x, start_y = self._marquee_origin
            end_x = self.canvas.canvasx(event.x)
            end_y = self.canvas.canvasy(event.y)
            self._marquee_origin = None
            self.canvas.delete("selection-marquee")
            selected = set(self._marquee_initial_selection)
            if abs(end_x - start_x) >= 5 or abs(end_y - start_y) >= 5:
                left = (min(start_x, end_x) - self.page_x) / self.zoom
                right = (max(start_x, end_x) - self.page_x) / self.zoom
                top = (min(start_y, end_y) - self.page_y) / self.zoom
                bottom = (max(start_y, end_y) - self.page_y) / self.zoom
                for index, item in enumerate(self.document.objects):
                    if self.current_page not in pages_for_object(
                        item, self.document.page_count
                    ):
                        continue
                    item_left, item_top, item_width, item_height = objects_bounds([item])
                    if (
                        left <= item_left
                        and item_left + item_width <= right
                        and top <= item_top
                        and item_top + item_height <= bottom
                    ):
                        selected.add(index)
            self.selected_indices = selected
            self.selected = next(iter(selected), None)
            self._marquee_initial_selection.clear()
            self.canvas.configure(cursor="")
            self.status.configure(text=f"Sélection par zone : {len(selected)} objet(s).")
            self._render()
            return
        changed = False
        if self._assembly_resize_origin is not None and self._drag_before is not None:
            before = [self._drag_before.objects[index] for index in self.selected_indices]
            after = [self.document.objects[index] for index in self.selected_indices]
            if objects_bounds(before) != objects_bounds(after):
                changed = True
                self.undo_stack.append(self._drag_before)
                self.redo_stack.clear()
        self._assembly_resize_origin = None
        if self._resize_origin is not None and self.selected is not None:
            _, _, _, old_x, old_y, old_width, old_height = self._resize_origin
            item = self.document.objects[self.selected]
            if (item.x, item.y, item.width, item.height) != (
                old_x, old_y, old_width, old_height
            ):
                changed = True
                snapshot = copy.deepcopy(self.document)
                snapshot.objects[self.selected].x = old_x
                snapshot.objects[self.selected].y = old_y
                snapshot.objects[self.selected].width = old_width
                snapshot.objects[self.selected].height = old_height
                if self._drag_before is not None:
                    snapshot.objects[self.selected].shape = self._drag_before.objects[self.selected].shape
                self.undo_stack.append(snapshot)
                self.redo_stack.clear()
        self._resize_origin = None
        moved = self._drag_origin is not None and self._drag_before is not None and any(
            (self.document.objects[index].x, self.document.objects[index].y) != position
            for index, position in self._drag_positions.items()
        )
        if moved:
            changed = True
            self.undo_stack.append(self._drag_before)
            self.redo_stack.clear()
        self._drag_origin = None
        self._drag_before = None
        if changed:
            self._render()

    def _edit_selected(self, _event: object = None) -> None:
        if (
            self.selected is None
            and self._last_clicked_index is not None
            and 0 <= self._last_clicked_index < len(self.document.objects)
        ):
            self.selected = self._last_clicked_index
            self.selected_indices = {self.selected}
        if self.selected is None:
            return
        item = self.document.objects[self.selected]
        if item.kind not in {"text", "table"}:
            return
        if item.kind == "table":
            self._start_inline_table_cell_editor(item, 0, 0)
            return
        self._start_inline_text_editor(item)

    @staticmethod
    def _tk_font_family(family: str) -> str:
        return {
            "Sans-serif": "DejaVu Sans",
            "Serif": "DejaVu Serif",
            "Monospace": "DejaVu Sans Mono",
            "Cursive": "Comic Relief",
            "Manuscrite ancienne": "Z003",
            "Inter": "Inter",
            "JetBrains Mono": "JetBrains Mono",
            "Symboles": "DejaVu Sans",
        }.get(family, family or "DejaVu Sans")

    def _choose_inline_font_family(self, family: str) -> None:
        self.font_family_var.set(family)
        self._apply_font_family()
        self._update_font_sample()

    def _populate_inline_font_menu(self, menu: tk.Menu) -> None:
        menu.delete(0, "end")
        menu.add_command(
            label="Rechercher ou installer une police…",
            command=self._show_font_catalog,
        )
        menu.add_separator()
        groups: dict[str, list[str]] = {}
        for family in available_font_families():
            groups.setdefault(family[0].upper() if family else "#", []).append(family)
        for group, names in sorted(groups.items()):
            submenu = tk.Menu(menu, tearoff=False)
            for family in names:
                submenu.add_command(
                    label=f"{family}   AaBb 123",
                    font=(self._tk_font_family(family), 12),
                    command=lambda selected=family: self._choose_inline_font_family(selected),
                )
            menu.add_cascade(label=f"{group}  ({len(names)})", menu=submenu)

    def _update_font_sample(self) -> None:
        preview = Image.new("RGBA", (92, 26), "#FFFFFF")
        draw = ImageDraw.Draw(preview)
        font_file = _font_file(self.font_family_var.get(), False, False)
        try:
            font = ImageFont.truetype(font_file, 15) if font_file else ImageFont.load_default()
        except (OSError, TypeError):
            font = ImageFont.load_default()
        draw.text((4, 3), "AaBb 123", font=font, fill="#193B66")
        self._font_sample_image = ImageTk.PhotoImage(preview)
        self.font_sample.configure(image=self._font_sample_image)

    def _configure_text_style_tag(
        self, widget: tk.Text, tag: str, item: PageObject, style: dict[str, object]
    ) -> None:
        family = self._tk_font_family(str(style.get("font_family", item.font_family)))
        size = inline_editor_font_size(style.get("font_size", item.font_size), self.zoom)
        bold = bool(style.get("bold", item.bold))
        italic = bool(style.get("italic", item.italic))
        weight = "bold" if bold else "normal"
        slant = "italic" if italic else "roman"
        highlight = str(style.get("highlight", ""))
        widget.tag_configure(
            tag,
            font=(family, size, f"{weight} {slant}"),
            foreground=str(style.get("color", item.color)),
            underline=bool(style.get("underline", item.underline)),
            overstrike=bool(style.get("strikethrough", item.strikethrough)),
            # An empty Tk background is "unspecified" and therefore does not erase
            # a lower-priority highlight tag. Paint the editor background explicitly.
            background=highlight or str(widget.cget("background")),
        )

    def _selected_inline_text_range(self, item: PageObject) -> tuple[int, int] | None:
        widget = self._editing_widget
        if widget is None or self._editing_object_id != item.object_id:
            return None
        if self._editing_selection_range is not None:
            return self._editing_selection_range
        try:
            start = self._text_character_offset(widget, "sel.first")
            end = self._text_character_offset(widget, "sel.last")
        except tk.TclError:
            if self._editing_dialog is not None:
                end = self._text_character_offset(widget, "end-1c")
                return (0, end) if end > 0 else None
            return None
        return (start, end) if end > start else None

    def _remember_inline_text_selection(self, widget: tk.Text) -> None:
        """Freeze the user's last deliberate text selection before toolbar clicks."""
        if widget is not self._editing_widget:
            return
        try:
            start = self._text_character_offset(widget, "sel.first")
            end = self._text_character_offset(widget, "sel.last")
        except tk.TclError:
            self._editing_selection_range = None
            return
        self._editing_selection_range = (start, end) if end > start else None
        if self._editing_selection_range is not None and self.selected is not None:
            item = self.document.objects[self.selected]
            if item.kind in {"text", "table"} and item.object_id == self._editing_object_id:
                style = self._inline_text_style_at(widget, item, start)
                self.font_size_var.set(f"{float(style['font_size']):g}")
                self.font_family_var.set(str(style["font_family"]))

    @staticmethod
    def _text_character_offset(widget: tk.Text, index: object) -> int:
        """Return a character offset; Tk represents a zero-length count as None."""
        counted = widget.count("1.0", index, "chars")
        return int(counted[0]) if counted else 0

    def _inline_text_style_at(
        self, widget: tk.Text, item: PageObject, position: int
    ) -> dict[str, object]:
        """Resolve persisted and live toolbar styles at one character."""
        if item.kind == "table" and self._editing_table_cell is not None:
            row, column = self._editing_table_cell
            cell = self._ensure_table_cells(item)[row][column]
            style = {
                "bold": bool(cell.get("bold", item.bold)),
                "italic": bool(cell.get("italic", item.italic)),
                "underline": bool(cell.get("underline", item.underline)),
                "strikethrough": bool(
                    cell.get("strikethrough", item.strikethrough)
                ),
                "color": str(cell.get("color", item.color)),
                "highlight": "",
                "font_family": str(cell.get("font_family", item.font_family)),
                "font_size": safe_number(
                    cell.get("font_size"), item.font_size, minimum=1.0
                ),
            }
            for run in cell.get("text_styles", []):
                if (
                    isinstance(run, dict)
                    and int(run.get("start", 0)) <= position < int(run.get("end", 0))
                ):
                    for key in TEXT_STYLE_KEYS:
                        if key in run:
                            style[key] = run[key]
        else:
            style = text_style_at(item, position)
        index = f"1.0 + {position} chars"
        for tag in widget.tag_names(index):
            live_style = self._editing_style_tags.get(tag)
            if live_style:
                style.update(live_style)
        return style

    def _apply_inline_text_style(self, item: PageObject, style: dict[str, object]) -> bool:
        selection = self._selected_inline_text_range(item)
        widget = self._editing_widget
        if selection is None or widget is None:
            return False
        start, end = selection
        combined_style = self._inline_text_style_at(widget, item, start)
        combined_style.update(style)
        tag = f"style_live_{uuid.uuid4().hex}"
        self._editing_style_tags[tag] = combined_style
        self._configure_text_style_tag(widget, tag, item, combined_style)
        widget.tag_add(tag, f"1.0 + {start} chars", f"1.0 + {end} chars")
        widget.tag_raise(tag)
        # Keep the native selection visible above yellow/green/cyan highlighting.
        widget.tag_raise("sel")
        self.status.configure(text="Mise en forme appliquée uniquement au texte sélectionné.")
        return True

    def _start_inline_text_editor(self, item: PageObject) -> None:
        if self._editing_widget is not None:
            self._commit_inline_editor(render=False)
        # The complete text-zone appearance controls now live in the inline
        # toolbar.  Keep the former floating palette out of the way so two UI
        # surfaces cannot mutate the same frame while it is being edited.
        self.palette_visible_vars["text_zone_style"].set(False)
        self._set_palette_visibility("text_zone_style")
        segment, style_source, flow_offset = flowed_text_context(item, self.document.objects)
        linked_segment = style_source.object_id != item.object_id
        editor_text = segment if linked_segment else item.text
        editor_styles = (
            _slice_text_ranges(style_source.text_styles, flow_offset, len(editor_text))
            if linked_segment else copy.deepcopy(item.text_styles)
        )
        editor_links = (
            _slice_text_ranges(style_source.text_links, flow_offset, len(editor_text))
            if linked_segment else copy.deepcopy(item.text_links)
        )
        editor_alignments = (
            _slice_text_ranges(style_source.paragraph_alignments, flow_offset, len(editor_text))
            if linked_segment else copy.deepcopy(item.paragraph_alignments)
        )
        x = self.page_x + item.x * self.zoom
        y = self.page_y + item.y * self.zoom
        editor_pad_x, editor_pad_y = inline_editor_padding(self.zoom)
        widget = tk.Text(
            self.canvas,
            wrap="word",
            font=(
                self._tk_font_family(style_source.font_family),
                inline_editor_font_size(style_source.font_size, self.zoom),
                "bold italic" if style_source.bold and style_source.italic else "bold" if style_source.bold else "italic" if style_source.italic else "normal",
            ),
            bg=item.fill if item.fill.lower() not in {"", "none", "transparent"} else "white",
            fg=style_source.color,
            relief="flat",
            borderwidth=0,
            padx=editor_pad_x,
            pady=editor_pad_y,
            highlightthickness=max(0, round(item.border_width * self.zoom)),
            highlightbackground=item.border_color,
            highlightcolor=item.border_color,
            undo=True,
            exportselection=False,
        )
        # Keep only the widget and native Text bindings.  The application-wide
        # pointer bindings are deliberately excluded: they used to continue a
        # selection after the mouse button had been released.
        widget.bindtags((str(widget), "Text"))
        widget.insert("1.0", editor_text)
        widget.bind("<Control-a>", self._select_all_inline_text)
        widget.bind("<Control-c>", self._copy_inline_text)
        widget.bind("<Control-x>", self._cut_inline_text)
        widget.bind("<Control-v>", self._paste_clean_text_widget)
        widget.bind("<Control-V>", self._paste_clean_text_widget)
        widget.bind("<Shift-Insert>", self._paste_clean_text_widget)
        widget.bind("<Control-z>", self._undo_inline_text)
        widget.bind("<Control-y>", self._redo_inline_text)
        widget.bind("<Control-Shift-Z>", self._redo_inline_text)
        # Let Tk's mature Text bindings resolve click/drag positions.  The
        # former hand-written selection used ``@x,y`` indexes and expanded a
        # drag to the whole visual line when that line was centred or aligned
        # to the right.  Native selection remains character-precise for every
        # paragraph alignment; we only remember it once the drag is complete.
        widget.bind("<ButtonRelease-1>", self._inline_text_mouse_release, add="+")
        widget.bind(
            "<KeyRelease>",
            lambda _event: self.after_idle(
                lambda current=widget: self._remember_inline_text_selection(current)
            ),
            add="+",
        )
        widget.bind("<Tab>", self._insert_inline_tab)
        widget.bind("<Shift-Tab>", self._remove_inline_tab)
        widget.bind("<ISO_Left_Tab>", self._remove_inline_tab)
        widget.bind("<Button-3>", self._show_inline_text_context_menu)
        self._editing_widget = widget
        self._editing_object_id = item.object_id
        self._editing_original_text = style_source.text
        self._editing_original_styles = copy.deepcopy(style_source.text_styles)
        self._editing_original_align = style_source.align
        self._editing_original_fill = item.fill
        self._editing_original_border_color = item.border_color
        self._editing_original_border_width = item.border_width
        self._editing_original_border_style = item.border_style
        self._editing_original_paragraph_alignments = copy.deepcopy(style_source.paragraph_alignments)
        self._editing_flow_root_id = style_source.object_id if linked_segment else ""
        self._editing_flow_offset = flow_offset if linked_segment else 0
        self._editing_flow_original_segment = editor_text if linked_segment else ""
        self._editing_flow_original_links = copy.deepcopy(style_source.text_links)
        self._editing_flow_local_links = copy.deepcopy(editor_links)
        self._editing_alignment_tags = {}
        self._editing_selection_range = None
        self._editing_drag_anchor = None
        self._editing_word_range = None
        self.canvas.create_window(
            x,
            y,
            window=widget,
            anchor="nw",
            width=max(60, item.width * self.zoom),
            height=max(35, item.height * self.zoom),
            tags=("inline-editor",),
        )
        link_toolbar = tk.Frame(self.canvas, bg="#E8EEF5", relief="solid", borderwidth=1)
        primary = tk.Frame(link_toolbar, bg="#E8EEF5")
        primary.pack(fill="x")
        secondary = tk.Frame(link_toolbar, bg="#E8EEF5")
        secondary.pack(fill="x")

        def tool(parent: tk.Misc, label: str, command: object, help_text: str) -> tk.Button:
            button = tk.Button(parent, text=label, relief="flat", command=command, padx=6)
            button.pack(side="left", padx=1, pady=2)
            button.bind(
                "<ButtonPress-1>",
                lambda _event, current=widget: self._preserve_inline_text_selection(current),
                add="+",
            )
            self._add_tooltip(button, help_text)
            return button

        tool(primary, "↶", self._undo_inline_text, "Annuler")
        tool(primary, "↷", self._redo_inline_text, "Rétablir")
        families = tk.Menubutton(
            primary,
            textvariable=self.font_family_var,
            relief="flat",
            width=19,
            anchor="w",
            padx=5,
        )
        family_menu = tk.Menu(families, tearoff=False)

        self._inline_font_menu = family_menu
        self._populate_inline_font_menu(family_menu)
        families.configure(menu=family_menu)
        families.pack(side="left", padx=2, pady=2)
        families.bind(
            "<ButtonPress-1>",
            lambda _event, current=widget: self._preserve_inline_text_selection(current),
            add="+",
        )
        tool(
            primary,
            "Aa+",
            self._show_font_catalog,
            "Afficher, rechercher ou installer une police sans quitter la zone de texte",
        )
        sizes = ttk.Combobox(
            primary,
            textvariable=self.font_size_var,
            values=("8", "9", "10", "11", "12", "14", "16", "18", "20", "24", "28", "32", "36", "48", "60", "72"),
            width=4,
        )
        sizes.pack(side="left", padx=2, pady=2)
        sizes.bind(
            "<ButtonPress-1>",
            lambda _event, current=widget: self._preserve_inline_text_selection(current),
            add="+",
        )
        sizes.bind("<<ComboboxSelected>>", lambda _event: self._apply_font_size())
        sizes.bind("<Return>", lambda _event: self._apply_font_size())
        tool(primary, "A−", lambda: self._change_font(-1), "Réduire la taille du texte")
        tool(primary, "A+", lambda: self._change_font(1), "Agrandir la taille du texte")
        tool(primary, "G", lambda: self._toggle("bold"), "Gras")
        tool(primary, "I", lambda: self._toggle("italic"), "Italique")
        tool(primary, "S̲", lambda: self._toggle("underline"), "Souligné")
        tool(primary, "B̶", lambda: self._toggle("strikethrough"), "Barré")
        tool(primary, "A▾", lambda: self._choose_color("color"), "Couleur du texte")
        highlight = tk.Menubutton(primary, text="Fluo ▾", relief="flat", padx=6)
        highlight_menu = tk.Menu(highlight, tearoff=False)
        for label, color in (
            ("Jaune", "#FFF176"),
            ("Vert", "#A7F3A1"),
            ("Violet", "#D8B4FE"),
            ("Cyan", "#8BE9FD"),
            ("Retirer", ""),
        ):
            highlight_menu.add_command(
                label=label,
                command=lambda value=color: self._set_text_highlight(value),
            )
        highlight.configure(menu=highlight_menu)
        highlight.pack(side="left", padx=2, pady=2)
        highlight.bind(
            "<ButtonPress-1>",
            lambda _event, current=widget: self._preserve_inline_text_selection(current),
            add="+",
        )
        background = tk.Menubutton(primary, text="Fond ▾", relief="flat", padx=6)
        background_menu = tk.Menu(background, tearoff=False)
        background_menu.add_command(
            label="Transparent", command=lambda: self._set_inline_text_frame_fill("transparent")
        )
        for label, color in (
            ("Blanc", "#FFFFFF"),
            ("Jaune pâle", "#FFF9C4"),
            ("Vert pâle", "#DDF3E4"),
            ("Bleu pâle", "#DCEBFA"),
        ):
            background_menu.add_command(
                label=label,
                command=lambda value=color: self._set_inline_text_frame_fill(value),
            )
        background_menu.add_separator()
        background_menu.add_command(label="Autre couleur…", command=self._choose_inline_text_frame_fill)
        background.configure(menu=background_menu)
        background.pack(side="left", padx=2, pady=2)
        tool(primary, "≡←", lambda: self._align("left"), "Aligner à gauche")
        tool(primary, "←≡→", lambda: self._align("center"), "Centrer")
        tool(primary, "→≡", lambda: self._align("right"), "Aligner à droite")
        tool(primary, "≡", lambda: self._align("justify"), "Justifier")

        tool(secondary, "• Liste", lambda: self._make_list(False), "Liste à puces")
        tool(secondary, "1. Liste", lambda: self._make_list(True), "Liste numérotée")
        tool(secondary, "⇤", self._remove_inline_tab, "Diminuer le retrait")
        tool(secondary, "⇥", self._insert_inline_tab, "Insérer une tabulation ou augmenter le retrait")
        tool(secondary, "Ω", self._insert_symbol, "Caractères spéciaux")
        tool(secondary, "🖌", self._copy_format, "Copier la mise en forme")
        tool(secondary, "🖌✓", self._apply_format, "Appliquer la mise en forme")
        tool(secondary, "🔗", self._set_selected_hyperlink, "Ajouter ou modifier un lien")
        tool(secondary, "✕🔗", self._remove_selected_hyperlink, "Retirer le lien")
        border = tk.Menubutton(secondary, text="Bordure ▾", relief="flat", padx=6)
        border_menu = tk.Menu(border, tearoff=False)
        border_menu.add_command(label="Sans bordure", command=lambda: self._set_border_width_value(0))
        for label, width in (("Fine — 0,5", 0.5), ("Normale — 1,5", 1.5), ("Épaisse — 3", 3.0), ("Très épaisse — 5", 5.0)):
            border_menu.add_command(
                label=label, command=lambda value=width: self._set_border_width_value(value)
            )
        border_menu.add_separator()
        border_menu.add_command(label="Continue", command=lambda: self._set_border_style_value("solid"))
        border_menu.add_command(label="Tirets", command=lambda: self._set_border_style_value("dashed"))
        border_menu.add_command(label="Pointillée", command=lambda: self._set_border_style_value("dotted"))
        border_menu.add_separator()
        border_menu.add_command(label="Couleur…", command=lambda: self._choose_color("border_color"))
        border.configure(menu=border_menu)
        border.pack(side="left", padx=2, pady=2)
        tool(secondary, "−1°", lambda: self._rotate_selected_degrees(-1), "Tourner la zone d’un degré vers la gauche")
        tool(secondary, "+1°", lambda: self._rotate_selected_degrees(1), "Tourner la zone d’un degré vers la droite")
        tool(secondary, "∠°", self._ask_absolute_angle, "Saisir l’angle exact de la zone")
        tool(secondary, "🤖", self._open_chatgpt_for_selected, "Ouvrir ChatGPT")
        tool(secondary, "Coller IA", self._paste_chatgpt_result, "Coller le résultat de ChatGPT")
        tool(secondary, "✓ Terminer", self._commit_inline_editor, "Terminer l’édition")
        link_toolbar.update_idletasks()
        toolbar_width = link_toolbar.winfo_reqwidth()
        toolbar_height = link_toolbar.winfo_reqheight()
        page_right = self.page_x + self._page_size()[0] * self.zoom
        page_bottom = self.page_y + self._page_size()[1] * self.zoom
        visible_left = self.canvas.canvasx(0)
        visible_top = self.canvas.canvasy(0)
        visible_right = self.canvas.canvasx(self.canvas.winfo_width())
        visible_bottom = self.canvas.canvasy(self.canvas.winfo_height())
        toolbar_x = max(
            self.page_x,
            visible_left,
            min(x, page_right - toolbar_width, visible_right - toolbar_width),
        )
        toolbar_y = y - toolbar_height - 6
        if toolbar_y < max(self.page_y, visible_top):
            toolbar_y = y + max(35, item.height * self.zoom) + 6
        toolbar_y = max(
            self.page_y,
            visible_top,
            min(
                toolbar_y,
                page_bottom - toolbar_height,
                visible_bottom - toolbar_height,
            ),
        )
        self.canvas.create_window(
            toolbar_x,
            toolbar_y,
            window=link_toolbar,
            anchor="nw", tags=("inline-editor",),
        )

        widget.bind("<Control-Return>", lambda _event: self._commit_inline_editor())
        widget.edit_modified(False)
        widget.focus_set()
        widget.tag_configure("align", justify=style_source.align if style_source.align != "justify" else "left")
        widget.tag_add("align", "1.0", "end")
        widget.tag_configure("hyperlink", foreground="#1769AA", underline=True)
        for link in editor_links:
            start = max(0, int(link.get("start", 0)))
            end = max(start, int(link.get("end", 0)))
            if link.get("hyperlink") and end > start:
                widget.tag_add("hyperlink", f"1.0 + {start} chars", f"1.0 + {end} chars")
        self._editing_style_tags = {}
        configured_style_tags: dict[tuple[tuple[str, object], ...], str] = {}
        for run in editor_styles:
            start = max(0, int(run.get("start", 0)))
            end = max(start, int(run.get("end", 0)))
            if end <= start:
                continue
            style = {key: value for key, value in run.items() if key in TEXT_STYLE_KEYS}
            style_key = tuple(sorted(style.items()))
            tag = configured_style_tags.get(style_key, "")
            if not tag:
                tag = f"style_{len(configured_style_tags)}"
                configured_style_tags[style_key] = tag
                self._editing_style_tags[tag] = style
                self._configure_text_style_tag(widget, tag, style_source, style)
            widget.tag_add(tag, f"1.0 + {start} chars", f"1.0 + {end} chars")
        for number, run in enumerate(editor_alignments):
            start = max(0, int(run.get("start", 0)))
            end = max(start, int(run.get("end", 0)))
            value = str(run.get("align", style_source.align))
            if end <= start or value not in {"left", "center", "right", "justify"}:
                continue
            tag = f"paragraph_align_{number}"
            self._editing_alignment_tags[tag] = value
            widget.tag_configure(tag, justify=value if value != "justify" else "left")
            widget.tag_add(tag, f"1.0 + {start} chars", f"1.0 + {end} chars")
        widget.tag_raise("sel")
        self.status.configure(
            text="Saisie directe : double-clic = mot, clic-glissé = passage, clic droit = mise en forme, Tab = retrait."
        )

    def _inline_text_mouse_press(self, event: tk.Event[tk.Text]) -> str:
        widget = event.widget
        index = widget.index(f"@{event.x},{event.y}")
        widget.focus_set()
        widget.mark_set("insert", index)
        widget.tag_remove("sel", "1.0", "end")
        self._editing_drag_anchor = index
        self._editing_selection_range = None
        return "break"

    def _inline_text_mouse_drag(self, event: tk.Event[tk.Text]) -> str:
        widget = event.widget
        if self._editing_drag_anchor is None:
            return "break"
        current = widget.index(f"@{event.x},{event.y}")
        anchor = self._editing_drag_anchor
        widget.tag_remove("sel", "1.0", "end")
        if widget.compare(current, "<", anchor):
            start, end = current, anchor
        else:
            start, end = anchor, current
        if widget.compare(start, "!=", end):
            widget.tag_add("sel", start, end)
            widget.mark_set("insert", end)
        return "break"

    def _inline_text_mouse_release(self, event: tk.Event[tk.Text]) -> str:
        widget = event.widget
        self._editing_drag_anchor = None
        self._remember_inline_text_selection(widget)
        return "break"

    def _inline_text_select_word(self, event: tk.Event[tk.Text]) -> str:
        widget = event.widget
        text = widget.get("1.0", "end-1c")
        position = min(self._text_character_offset(widget, f"@{event.x},{event.y}"), len(text))
        if not text:
            return "break"
        if position == len(text):
            position -= 1

        def same_word(character: str) -> bool:
            return character.isalnum() or character in "_’-'‑-"

        word_character = same_word(text[position])
        start = position
        end = position + 1
        while start > 0 and same_word(text[start - 1]) == word_character and text[start - 1] != "\n":
            start -= 1
        while end < len(text) and same_word(text[end]) == word_character and text[end] != "\n":
            end += 1
        widget.tag_remove("sel", "1.0", "end")
        widget.tag_add("sel", f"1.0 + {start} chars", f"1.0 + {end} chars")
        widget.mark_set("insert", f"1.0 + {end} chars")
        self._editing_drag_anchor = None
        self._remember_inline_text_selection(widget)
        return "break"

    def _inline_text_select_line(self, event: tk.Event[tk.Text]) -> str:
        widget = event.widget
        index = widget.index(f"@{event.x},{event.y}")
        start = widget.index(f"{index} linestart")
        end = widget.index(f"{index} lineend")
        widget.tag_remove("sel", "1.0", "end")
        widget.tag_add("sel", start, end)
        widget.mark_set("insert", end)
        self._editing_drag_anchor = None
        self._remember_inline_text_selection(widget)
        return "break"

    def _preserve_inline_text_selection(self, widget: tk.Text) -> None:
        """Keep the selection when focus moves from the text to its toolbar."""
        if widget is not self._editing_widget:
            return
        try:
            start = self._text_character_offset(widget, "sel.first")
            end = self._text_character_offset(widget, "sel.last")
        except tk.TclError:
            return
        if end > start:
            self._editing_selection_range = (start, end)

    def _inline_selected_line_numbers(self, widget: tk.Text) -> tuple[int, int]:
        """Resolve selected paragraphs after a toolbar button has taken focus."""
        if self._editing_selection_range is not None:
            start_offset, end_offset = self._editing_selection_range
            start = widget.index(f"1.0 + {start_offset} chars")
            end = widget.index(f"1.0 + {end_offset} chars")
            if end_offset > start_offset and widget.compare(end, "==", f"{end} linestart"):
                end = widget.index(f"{end} - 1 chars")
        else:
            try:
                start = widget.index("sel.first")
                end = widget.index("sel.last")
            except tk.TclError:
                start = end = widget.index("insert")
        return int(start.split(".", 1)[0]), int(end.split(".", 1)[0])

    def _insert_inline_tab(self, _event: object = None) -> str:
        widget = self._editing_widget
        if widget is None:
            return "break"
        if self._editing_selection_range is None:
            widget.insert("insert", "\t")
        else:
            first_line, last_line = self._inline_selected_line_numbers(widget)
            for line_number in range(last_line, first_line - 1, -1):
                widget.insert(f"{line_number}.0", "\t")
            self._editing_selection_range = (
                self._text_character_offset(widget, f"{first_line}.0"),
                self._text_character_offset(widget, f"{last_line}.0 lineend"),
            )
        widget.focus_set()
        return "break"

    def _remove_inline_tab(self, _event: object = None) -> str:
        widget = self._editing_widget
        if widget is None:
            return "break"
        first_line, last_line = self._inline_selected_line_numbers(widget)
        for line_number in range(last_line, first_line - 1, -1):
            line_start = f"{line_number}.0"
            content = widget.get(line_start, f"{line_start} lineend")
            if content.startswith("\t"):
                widget.delete(line_start, f"{line_start} + 1 chars")
            elif content.startswith("    "):
                widget.delete(line_start, f"{line_start} + 4 chars")
        self._editing_selection_range = (
            self._text_character_offset(widget, f"{first_line}.0"),
            self._text_character_offset(widget, f"{last_line}.0 lineend"),
        )
        widget.focus_set()
        return "break"

    def _show_inline_text_context_menu(self, event: tk.Event[tk.Text]) -> str:
        widget = self._editing_widget
        if widget is None:
            return "break"
        self._remember_inline_text_selection(widget)
        if self._editing_selection_range is None:
            widget.mark_set("insert", widget.index(f"@{event.x},{event.y}"))
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="Annuler    Ctrl+Z", command=self._undo_inline_text)
        menu.add_command(label="Rétablir    Ctrl+Y", command=self._redo_inline_text)
        menu.add_separator()
        menu.add_command(label="Couper    Ctrl+X", command=self._cut_inline_text)
        menu.add_command(label="Copier    Ctrl+C", command=self._copy_inline_text)
        menu.add_command(label="Coller avec mise en forme    Ctrl+V", command=self._paste_clean_text_widget)
        menu.add_command(label="Coller en texte brut", command=self._paste_plain_text_widget)
        menu.add_command(label="Tout sélectionner    Ctrl+A", command=self._select_all_inline_text)
        menu.add_separator()
        menu.add_command(label="Gras", command=lambda: self._toggle("bold"))
        menu.add_command(label="Italique", command=lambda: self._toggle("italic"))
        menu.add_command(label="Souligné", command=lambda: self._toggle("underline"))
        menu.add_command(label="Barré", command=lambda: self._toggle("strikethrough"))
        highlight = tk.Menu(menu, tearoff=False)
        for label, color in (("Jaune", "#FFF176"), ("Vert", "#A7F3A1"), ("Violet", "#D8B4FE"), ("Cyan", "#8BE9FD"), ("Retirer", "")):
            highlight.add_command(label=label, command=lambda value=color: self._set_text_highlight(value))
        menu.add_cascade(label="Surlignage", menu=highlight)
        menu.add_command(label="Couleur du texte…", command=lambda: self._choose_color("color"))
        alignment = tk.Menu(menu, tearoff=False)
        for label, value in (("À gauche", "left"), ("Centré", "center"), ("À droite", "right"), ("Justifié", "justify")):
            alignment.add_command(label=label, command=lambda selected=value: self._align(selected))
        menu.add_cascade(label="Alignement", menu=alignment)
        frame_fill = tk.Menu(menu, tearoff=False)
        frame_fill.add_command(
            label="Transparent",
            command=lambda: self._set_inline_text_frame_fill("transparent"),
        )
        for label, color in (
            ("Blanc", "#FFFFFF"),
            ("Jaune pâle", "#FFF9C4"),
            ("Vert pâle", "#DDF3E4"),
            ("Bleu pâle", "#DCEBFA"),
        ):
            frame_fill.add_command(
                label=label,
                command=lambda selected=color: self._set_inline_text_frame_fill(selected),
            )
        frame_fill.add_separator()
        frame_fill.add_command(
            label="Autre couleur…", command=self._choose_inline_text_frame_fill
        )
        menu.add_cascade(label="Fond de la zone", menu=frame_fill)
        menu.add_separator()
        menu.add_command(label="Tabulation / augmenter le retrait", command=self._insert_inline_tab)
        menu.add_command(label="Diminuer le retrait", command=self._remove_inline_tab)
        menu.add_command(label="Liste à puces", command=lambda: self._make_list(False))
        menu.add_command(label="Liste numérotée", command=lambda: self._make_list(True))
        menu.add_separator()
        menu.add_command(label="Copier la mise en forme", command=self._copy_format)
        menu.add_command(label="Appliquer la mise en forme", command=self._apply_format)
        menu.add_command(label="Ajouter / modifier un hyperlien…", command=self._set_selected_hyperlink)
        menu.add_command(label="Caractères spéciaux…", command=self._insert_symbol)
        menu.add_separator()
        menu.add_command(label="Terminer l’édition", command=self._commit_inline_editor)
        self._editing_text_context_menu = menu
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
            widget.focus_set()
        return "break"

    def _select_all_inline_text(self, _event: object = None) -> str:
        widget = self._editing_widget
        if widget is None:
            return "break"
        widget.tag_remove("sel", "1.0", "end")
        if widget.compare("end-1c", ">", "1.0"):
            widget.tag_add("sel", "1.0", "end-1c")
            widget.mark_set("insert", "end-1c")
        self._remember_inline_text_selection(widget)
        widget.focus_set()
        return "break"

    def _copy_inline_text(self, _event: object = None) -> str:
        widget = self._editing_widget
        if widget is None:
            return "break"
        try:
            value = widget.get("sel.first", "sel.last")
        except tk.TclError:
            return "break"
        self.clipboard_clear()
        self.clipboard_append(value)
        widget.focus_set()
        return "break"

    def _cut_inline_text(self, _event: object = None) -> str:
        widget = self._editing_widget
        if widget is None:
            return "break"
        try:
            value = widget.get("sel.first", "sel.last")
            widget.edit_separator()
            widget.delete("sel.first", "sel.last")
            widget.edit_separator()
        except tk.TclError:
            return "break"
        self.clipboard_clear()
        self.clipboard_append(value)
        self._editing_selection_range = None
        widget.focus_set()
        return "break"

    def _undo_inline_text(self, _event: object = None) -> str:
        widget = self._editing_widget
        if widget is None:
            return "break"
        try:
            widget.edit_undo()
        except tk.TclError:
            pass
        self._editing_selection_range = None
        widget.focus_set()
        return "break"

    def _redo_inline_text(self, _event: object = None) -> str:
        widget = self._editing_widget
        if widget is None:
            return "break"
        try:
            widget.edit_redo()
        except tk.TclError:
            pass
        self._editing_selection_range = None
        widget.focus_set()
        return "break"

    @staticmethod
    def _ensure_table_cells(item: PageObject) -> list[list[dict[str, str]]]:
        if item.table_cells:
            width = max((len(row) for row in item.table_cells), default=1)
            for row in item.table_cells:
                row.extend(
                    {"text": "", "hyperlink": "", "image_path": ""}
                    for _ in range(width - len(row))
                )
                for cell in row:
                    cell.setdefault("text", "")
                    cell.setdefault("hyperlink", "")
                    cell.setdefault("image_path", "")
            return item.table_cells
        legacy_rows = [row.split("\t") for row in item.text.splitlines()] or [[""]]
        width = max((len(row) for row in legacy_rows), default=1)
        item.table_cells = [
            [
                {
                    "text": row[column] if column < len(row) else "",
                    "hyperlink": "",
                    "image_path": "",
                }
                for column in range(width)
            ]
            for row in legacy_rows
        ]
        return item.table_cells

    @staticmethod
    def _sync_table_text(item: PageObject) -> None:
        item.text = "\n".join(
            "\t".join(cell.get("text", "").replace("\n", " ") for cell in row)
            for row in item.table_cells
        )

    def _table_cell_at_event(
        self, item: PageObject, event: tk.Event[tk.Misc]
    ) -> tuple[int, int]:
        cells = self._ensure_table_cells(item)
        rows = max(1, len(cells))
        columns = max(1, max((len(row) for row in cells), default=1))
        page_x = (self.canvas.canvasx(event.x) - self.page_x) / self.zoom
        page_y = (self.canvas.canvasy(event.y) - self.page_y) / self.zoom
        column_offsets = table_grid_offsets(item.table_column_widths, columns, item.width)
        row_offsets = table_grid_offsets(item.table_row_heights, rows, item.height)
        local_x, local_y = page_x - item.x, page_y - item.y
        column = next((index for index in range(columns) if local_x < column_offsets[index + 1]), columns - 1)
        row = next((index for index in range(rows) if local_y < row_offsets[index + 1]), rows - 1)
        merge = self._table_merge_for_cell(item, row, column)
        return (merge[0], merge[1]) if merge else (row, column)

    @staticmethod
    def _table_merge_for_cell(item: PageObject, row: int, column: int) -> list[int] | None:
        for merge in item.table_merges:
            if len(merge) == 4:
                top, left, row_span, column_span = merge
                if top <= row < top + row_span and left <= column < left + column_span:
                    return merge
        return None

    @classmethod
    def _table_grid_hidden(
        cls, item: PageObject, row_a: int, column_a: int, row_b: int, column_b: int
    ) -> bool:
        merge_a = cls._table_merge_for_cell(item, row_a, column_a)
        return merge_a is not None and merge_a == cls._table_merge_for_cell(item, row_b, column_b)

    def _start_inline_table_cell_editor(
        self, item: PageObject, row: int, column: int
    ) -> None:
        if self._editing_widget is not None:
            self._commit_inline_editor(render=False)
        cells = self._ensure_table_cells(item)
        if not cells:
            return
        row = min(max(0, row), len(cells) - 1)
        column = min(max(0, column), len(cells[row]) - 1)
        cell = cells[row][column]
        rows = len(cells)
        columns = max(len(candidate) for candidate in cells)
        column_offsets = table_grid_offsets(item.table_column_widths, columns, item.width * self.zoom)
        row_offsets = table_grid_offsets(item.table_row_heights, rows, item.height * self.zoom)
        cell_width = column_offsets[column + 1] - column_offsets[column]
        cell_height = row_offsets[row + 1] - row_offsets[row]
        cell_x = self.page_x + item.x * self.zoom + column_offsets[column]
        cell_y = self.page_y + item.y * self.zoom + row_offsets[row]
        page_width, page_height = self._page_size()
        editor_width, editor_height = table_cell_editor_size(
            cell_width,
            cell_height,
            page_width * self.zoom,
            page_height * self.zoom,
        )
        page_right = self.page_x + page_width * self.zoom
        page_bottom = self.page_y + page_height * self.zoom
        x = max(self.page_x, min(cell_x, page_right - editor_width))
        y = max(self.page_y, min(cell_y, page_bottom - editor_height))
        widget = tk.Text(
            self.canvas,
            wrap="word",
            font=(
                self._tk_font_family(
                    str(cell.get("font_family") or item.font_family or "Sans-serif")
                ),
                inline_editor_font_size(
                    cell.get("font_size", item.font_size), self.zoom
                ),
                " ".join(
                    part
                    for part, enabled in (
                        ("bold", bool(cell.get("bold", False))),
                        ("italic", bool(cell.get("italic", False))),
                    )
                    if enabled
                ) or "normal",
            ),
            bg=str(cell.get("fill") or "#FFFFFF"),
            fg=str(cell.get("color") or "#000000"),
            relief="solid",
            borderwidth=2,
            undo=True,
            exportselection=False,
            # The two-pixel editor border plus this padding equals the
            # five-point inset used by the clipped table preview.
            padx=max(1, round(3 * self.zoom)),
            pady=max(1, round(3 * self.zoom)),
        )
        widget.insert("1.0", cell.get("text", ""))
        widget.tag_configure(
            "cell-style",
            underline=bool(cell.get("underline", False)),
            justify={"center": "center", "right": "right"}.get(
                str(cell.get("horizontal_align", "left")), "left"
            ),
        )
        widget.tag_add("cell-style", "1.0", "end")
        self._editing_style_tags = {}
        configured_style_tags: dict[tuple[tuple[str, object], ...], str] = {}
        for run in cell.get("text_styles", []):
            if not isinstance(run, dict):
                continue
            start = max(0, int(run.get("start", 0)))
            end = max(start, int(run.get("end", 0)))
            if end <= start:
                continue
            style = {key: value for key, value in run.items() if key in TEXT_STYLE_KEYS}
            style = {
                "bold": bool(cell.get("bold", item.bold)),
                "italic": bool(cell.get("italic", item.italic)),
                "underline": bool(cell.get("underline", item.underline)),
                "strikethrough": bool(
                    cell.get("strikethrough", item.strikethrough)
                ),
                "color": str(cell.get("color", item.color)),
                "highlight": "",
                "font_family": str(cell.get("font_family", item.font_family)),
                "font_size": safe_number(
                    cell.get("font_size"), item.font_size, minimum=1.0
                ),
                **style,
            }
            style_key = tuple(sorted(style.items()))
            tag = configured_style_tags.get(style_key, "")
            if not tag:
                tag = f"cell_style_{len(configured_style_tags)}"
                configured_style_tags[style_key] = tag
                self._editing_style_tags[tag] = style
                self._configure_text_style_tag(widget, tag, item, style)
            widget.tag_add(tag, f"1.0 + {start} chars", f"1.0 + {end} chars")
        widget.tag_raise("sel")
        self._editing_widget = widget
        self._editing_object_id = item.object_id
        self._editing_original_text = cell.get("text", "")
        self._editing_table_cell = (row, column)
        self._active_table_cell = (item.object_id, row, column)
        self._editing_table_original = copy.deepcopy(cell)
        self.canvas.create_window(
            x,
            y,
            window=widget,
            anchor="nw",
            width=editor_width,
            height=editor_height,
            tags=("inline-editor",),
        )
        toolbar = tk.Frame(self.canvas, bg="#E8EEF5", relief="solid", borderwidth=1)
        tk.Label(
            toolbar,
            text=f"Cellule {row + 1},{column + 1}",
            bg="#D8E4F0",
            fg="#193B66",
            padx=6,
        ).pack(side="left", padx=2, pady=2)
        tk.Button(
            toolbar, text="🔗 Lien", relief="flat",
            command=lambda: self._set_table_cell_link(item, row, column),
        ).pack(side="left", padx=2, pady=2)
        tk.Button(
            toolbar, text="✕ Lien", relief="flat",
            command=lambda: self._remove_table_cell_link(item, row, column),
        ).pack(side="left", padx=2, pady=2)
        tk.Button(
            toolbar, text="▧ Image", relief="flat",
            command=lambda: self._set_table_cell_image(item, row, column),
        ).pack(side="left", padx=2, pady=2)
        border_button = tk.Menubutton(toolbar, text="Bordures ▾", relief="flat")
        border_menu = tk.Menu(border_button, tearoff=False)
        border_menu.add_command(label="Contour fin", command=lambda: self._outline_active_table_cell(0.6))
        border_menu.add_command(label="Contour épais", command=lambda: self._outline_active_table_cell(3.0))
        border_menu.add_command(label="Contour de la ligne", command=lambda: self._outline_active_table_row_or_column("row", 3.0))
        border_menu.add_command(label="Contour de la colonne", command=lambda: self._outline_active_table_row_or_column("column", 3.0))
        border_button.configure(menu=border_menu)
        border_button.pack(side="left", padx=2, pady=2)
        align_button = tk.Menubutton(toolbar, text="Aligner ▾", relief="flat")
        align_menu = tk.Menu(align_button, tearoff=False)
        for label, alignment in (("À gauche", "left"), ("Au centre", "center"), ("À droite", "right")):
            align_menu.add_command(label=label, command=lambda value=alignment: self._set_table_cell_alignment(item, row, column, horizontal=value))
        align_menu.add_separator()
        for label, alignment in (("En haut", "top"), ("Au milieu verticalement", "middle"), ("En bas", "bottom")):
            align_menu.add_command(label=label, command=lambda value=alignment: self._set_table_cell_alignment(item, row, column, vertical=value))
        align_button.configure(menu=align_menu)
        align_button.pack(side="left", padx=2, pady=2)
        merge_button = tk.Menubutton(toolbar, text="Cellules ▾", relief="flat")
        merge_menu = tk.Menu(merge_button, tearoff=False)
        merge_menu.add_command(label="Fusionner avec la cellule de droite", command=lambda: self._merge_table_cell(item, row, column, 1, 2))
        merge_menu.add_command(label="Fusionner avec la cellule du dessous", command=lambda: self._merge_table_cell(item, row, column, 2, 1))
        merge_menu.add_command(label="Séparer les cellules", command=lambda: self._unmerge_table_cell(item, row, column))
        merge_menu.add_separator()
        merge_menu.add_command(label="Insérer une ligne au-dessus", command=lambda: self._change_table_structure("insert_row_before"))
        merge_menu.add_command(label="Insérer une ligne en dessous", command=lambda: self._change_table_structure("insert_row_after"))
        merge_menu.add_command(label="Supprimer cette ligne", command=lambda: self._change_table_structure("delete_row"))
        merge_menu.add_command(label="Insérer une colonne à gauche", command=lambda: self._change_table_structure("insert_column_before"))
        merge_menu.add_command(label="Insérer une colonne à droite", command=lambda: self._change_table_structure("insert_column_after"))
        merge_menu.add_command(label="Supprimer cette colonne", command=lambda: self._change_table_structure("delete_column"))
        merge_button.configure(menu=merge_menu)
        merge_button.pack(side="left", padx=2, pady=2)
        function_button = tk.Menubutton(toolbar, text="fx ▾", relief="flat")
        function_menu = tk.Menu(function_button, tearoff=False)
        for label, function in (
            ("Somme", "SOMME"), ("Moyenne", "MOYENNE"),
            ("Minimum", "MIN"), ("Maximum", "MAX"), ("Compter les nombres", "NB"),
        ):
            function_menu.add_command(
                label=label,
                command=lambda name=function: self._insert_table_function(name),
            )
        function_menu.add_separator()
        function_menu.add_command(label="Aide et exemples…", command=self._show_table_formula_help)
        function_button.configure(menu=function_menu)
        function_button.pack(side="left", padx=2, pady=2)
        tk.Button(
            toolbar, text="✓ Terminer", relief="flat", command=self._commit_inline_editor,
        ).pack(side="left", padx=2, pady=2)
        toolbar.update_idletasks()
        toolbar_width = toolbar.winfo_reqwidth()
        toolbar_height = toolbar.winfo_reqheight()
        visible_left = self.canvas.canvasx(0)
        visible_top = self.canvas.canvasy(0)
        visible_right = self.canvas.canvasx(self.canvas.winfo_width())
        toolbar_x = max(
            self.page_x,
            visible_left,
            min(x, page_right - toolbar_width, visible_right - toolbar_width),
        )
        toolbar_y = y - toolbar_height - 4
        if toolbar_y < max(self.page_y, visible_top):
            toolbar_y = y + editor_height + 4
        toolbar_y = max(self.page_y, visible_top, min(toolbar_y, page_bottom - toolbar_height))
        self.canvas.create_window(
            toolbar_x,
            toolbar_y,
            window=toolbar,
            anchor="nw",
            tags=("inline-editor",),
        )
        widget.bind("<Control-Return>", lambda _event: self._commit_inline_editor() or "break")
        widget.bind("<Escape>", lambda _event: self._commit_inline_editor() or "break")
        widget.bind("<Delete>", self._edit_table_delete)
        widget.bind("<BackSpace>", self._edit_table_backspace)
        widget.bind("<Control-z>", lambda _event: widget.edit_undo() or "break")
        widget.bind("<ButtonRelease-1>", self._inline_text_mouse_release, add="+")
        widget.focus_set()
        self.status.configure(
            text=f"Cellule {row + 1},{column + 1} : Entrée = nouvelle ligne, Ctrl+Entrée = terminer."
        )

    def _edit_table_delete(self, _event: tk.Event[tk.Misc]) -> str:
        if self._editing_widget is not None:
            try:
                self._editing_widget.delete("sel.first", "sel.last")
            except tk.TclError:
                self._editing_widget.delete("insert")
        return "break"

    def _edit_table_backspace(self, _event: tk.Event[tk.Misc]) -> str:
        if self._editing_widget is not None:
            try:
                self._editing_widget.delete("sel.first", "sel.last")
            except tk.TclError:
                if self._editing_widget.compare("insert", ">", "1.0"):
                    self._editing_widget.delete("insert - 1 chars")
        return "break"

    def _insert_table_formula_reference(self, event: tk.Event[tk.Misc]) -> bool:
        if self._editing_widget is None or self._editing_table_cell is None:
            return False
        formula = self._editing_widget.get("1.0", "end-1c").lstrip()
        if not formula.startswith("="):
            return False
        clicked = self._object_at_event(event)
        if clicked is None:
            return False
        item = self.document.objects[clicked]
        if item.kind != "table" or item.object_id != self._editing_object_id:
            return False
        row, column = self._table_cell_at_event(item, event)
        if (row, column) == self._editing_table_cell:
            return False
        reference = f"{spreadsheet_column_name(column)}{row + 1}"
        self._editing_widget.insert("insert", reference)
        self._editing_widget.focus_set()
        self.status.configure(text=f"Référence {reference} ajoutée à la formule.")
        return True

    def _insert_table_function(self, name: str) -> None:
        if self._editing_widget is None or self._editing_table_cell is None:
            return
        widget = self._editing_widget
        if not widget.get("1.0", "end-1c").strip():
            widget.insert("1.0", f"={name}()")
            widget.mark_set("insert", f"1.{len(name) + 2}")
        else:
            widget.insert("insert", f"{name}()")
            widget.mark_set("insert", "insert - 1 chars")
        widget.focus_set()

    def _show_table_formula_help(self) -> None:
        messagebox.showinfo(
            "Formules du tableau",
            "Une formule commence toujours par le signe =\n\n"
            "Calculs simples\n"
            "  =A1+B1\n"
            "  =A2-B2\n"
            "  =A1*20%\n"
            "  =(A1+B1)/2\n\n"
            "Fonctions sur une plage\n"
            "  =SOMME(A1:A5)\n"
            "  =MOYENNE(B1:B5)\n"
            "  =MIN(C1:C10)\n"
            "  =MAX(C1:C10)\n"
            "  =NB(A1:A20)\n\n"
            "Les noms anglais SUM, AVERAGE et COUNT sont également acceptés.\n\n"
            "Astuce : commencez la formule par =, puis cliquez sur une autre cellule "
            "pour insérer automatiquement sa référence.",
            parent=self,
        )

    def _set_table_cell_link(self, item: PageObject, row: int, column: int) -> None:
        cell = self._ensure_table_cells(item)[row][column]
        value = ask_text(
            self, "Lien hypertexte", "Adresse du lien (https://… ou mailto:…) :", cell.get("hyperlink", "")
        )
        if value is None:
            return
        if value and ":" not in value:
            value = f"https://{value}"
        cell["hyperlink"] = value
        self.status.configure(text="Lien hypertexte ajouté à la cellule.")

    def _set_table_cell_image(self, item: PageObject, row: int, column: int) -> None:
        files = choose_documents(self, {".png", ".jpg", ".jpeg", ".tif", ".tiff"})
        if not files:
            return
        self._ensure_table_cells(item)[row][column]["image_path"] = str(files[0])
        self.status.configure(text="Image ajoutée à la cellule.")

    def _remove_table_cell_link(self, item: PageObject, row: int, column: int) -> None:
        cell = self._ensure_table_cells(item)[row][column]
        cell["hyperlink"] = ""
        self.status.configure(text="Lien hypertexte retiré de la cellule.")

    def _selected_table(self) -> PageObject | None:
        if self.selected is None:
            return None
        item = self.document.objects[self.selected]
        if item.kind != "table":
            self.status.configure(text="Sélectionnez d’abord un tableau.")
            return None
        return item

    def _set_table_border_preset(self, preset: str) -> None:
        item = self._selected_table()
        if item is None:
            return
        outer, inner = {
            "standard": (1.5, 0.6),
            "outer": (3.0, 0.6),
            "thin": (0.6, 0.6),
            "none": (0.0, 0.0),
        }[preset]
        self._checkpoint()
        item.table_outer_border_width = outer
        item.table_inner_border_width = inner
        if preset == "none":
            item.table_row_border_widths.clear()
        self.status.configure(text="Bordures du tableau mises à jour.")
        self._render()

    def _set_table_style(self, style: str) -> None:
        item = self._selected_table()
        if item is None:
            return
        if style not in {"plain", "blue", "green"}:
            return
        self._checkpoint()
        item.table_style = style
        messages = {
            "plain": "Style de tableau neutre appliqué.",
            "blue": "En-tête bleu et lignes bleues alternées appliqués.",
            "green": "En-tête vert et lignes vertes alternées appliqués.",
        }
        self.status.configure(text=messages[style])
        self._render()

    def _set_table_inner_border(self, width: float) -> None:
        item = self._selected_table()
        if item is None:
            return
        self._checkpoint()
        item.table_inner_border_width = max(0.0, min(6.0, width))
        self.status.configure(
            text="Quadrillage intérieur masqué."
            if item.table_inner_border_width == 0
            else f"Épaisseur du quadrillage intérieur : {item.table_inner_border_width:g}."
        )
        self._render()

    def _change_table_inner_border(self, delta: float) -> None:
        item = self._selected_table()
        if item is not None:
            self._set_table_inner_border(item.table_inner_border_width + delta)

    def _set_table_cell_alignment(
        self, item: PageObject, row: int, column: int, *,
        horizontal: str | None = None, vertical: str | None = None,
    ) -> None:
        self._commit_inline_editor(render=False)
        self._checkpoint()
        cell = self._ensure_table_cells(item)[row][column]
        if horizontal is not None:
            cell["horizontal_align"] = horizontal
        if vertical is not None:
            cell["vertical_align"] = vertical
        self._sync_table_text(item)
        self.status.configure(text="Alignement de la cellule mis à jour.")
        self._render()

    def _merge_table_cell(
        self, item: PageObject, row: int, column: int, row_span: int, column_span: int
    ) -> None:
        cells = self._ensure_table_cells(item)
        if row + row_span > len(cells) or column + column_span > len(cells[row]):
            self.status.configure(text="Il n’y a pas de cellule disponible dans cette direction.")
            return
        for current_row in range(row, row + row_span):
            for current_column in range(column, column + column_span):
                if self._table_merge_for_cell(item, current_row, current_column):
                    self.status.configure(text="Séparez d’abord les cellules déjà fusionnées.")
                    return
        self._commit_inline_editor(render=False)
        self._checkpoint()
        master = cells[row][column]
        extra = []
        for current_row in range(row, row + row_span):
            for current_column in range(column, column + column_span):
                if (current_row, current_column) == (row, column):
                    continue
                text = cells[current_row][current_column].get("text", "").strip()
                if text:
                    extra.append(text)
                cells[current_row][current_column]["text"] = ""
        if extra:
            master["text"] = "\n".join(filter(None, [master.get("text", ""), *extra]))
        item.table_merges.append([row, column, row_span, column_span])
        self._sync_table_text(item)
        self.status.configure(text="Cellules fusionnées.")
        self._render()

    def _unmerge_table_cell(self, item: PageObject, row: int, column: int) -> None:
        merge = self._table_merge_for_cell(item, row, column)
        if merge is None:
            self.status.configure(text="Cette cellule n’est pas fusionnée.")
            return
        self._commit_inline_editor(render=False)
        self._checkpoint()
        item.table_merges.remove(merge)
        self.status.configure(text="Cellules séparées.")
        self._render()

    @staticmethod
    def _empty_table_cell() -> dict[str, str]:
        return {
            "text": "",
            "hyperlink": "",
            "image_path": "",
            "horizontal_align": "left",
            "vertical_align": "top",
        }

    def _change_table_structure(self, operation: str) -> None:
        item = self._selected_table()
        if item is None:
            return
        coordinates = self._active_table_coordinates(item)
        if coordinates is None:
            self.status.configure(
                text="Cliquez d’abord dans une cellule pour choisir la ligne ou la colonne."
            )
            return
        self._commit_inline_editor(render=False)
        cells = self._ensure_table_cells(item)
        row, column = coordinates
        rows = len(cells)
        columns = max((len(candidate) for candidate in cells), default=1)
        if operation == "delete_row" and rows <= 1:
            self.status.configure(text="Un tableau doit conserver au moins une ligne.")
            return
        if operation == "delete_column" and columns <= 1:
            self.status.configure(text="Un tableau doit conserver au moins une colonne.")
            return
        self._checkpoint()
        old_row_height = (
            item.table_row_heights[row]
            if len(item.table_row_heights) == rows
            else item.height / max(1, rows)
        )
        old_column_width = (
            item.table_column_widths[column]
            if len(item.table_column_widths) == columns
            else item.width / max(1, columns)
        )
        if operation.startswith("insert_row"):
            index = row if operation.endswith("before") else row + 1
            cells.insert(index, [self._empty_table_cell() for _ in range(columns)])
            if len(item.table_row_heights) == rows:
                item.table_row_heights.insert(index, old_row_height)
            item.height += old_row_height
            row = index
        elif operation == "delete_row":
            cells.pop(row)
            if len(item.table_row_heights) == rows:
                item.table_row_heights.pop(row)
            item.height = max(24.0, item.height - old_row_height)
            row = min(row, len(cells) - 1)
        elif operation.startswith("insert_column"):
            index = column if operation.endswith("before") else column + 1
            for candidate in cells:
                candidate.insert(index, self._empty_table_cell())
            if len(item.table_column_widths) == columns:
                item.table_column_widths.insert(index, old_column_width)
            item.width += old_column_width
            column = index
        elif operation == "delete_column":
            for candidate in cells:
                candidate.pop(column)
            if len(item.table_column_widths) == columns:
                item.table_column_widths.pop(column)
            item.width = max(24.0, item.width - old_column_width)
            column = min(column, len(cells[0]) - 1)
        else:
            return
        # Structural edits can cross merged cells and custom outlines. Resetting those
        # two decorations prevents invisible or out-of-range cell references.
        item.table_merges.clear()
        item.table_row_border_widths.clear()
        item.table_border_ranges.clear()
        self._sync_table_text(item)
        self._active_table_cell = (item.object_id, row, column)
        labels = {
            "insert_row_before": "Ligne insérée au-dessus.",
            "insert_row_after": "Ligne insérée en dessous.",
            "delete_row": "Ligne supprimée.",
            "insert_column_before": "Colonne insérée à gauche.",
            "insert_column_after": "Colonne insérée à droite.",
            "delete_column": "Colonne supprimée.",
        }
        self.status.configure(text=labels[operation])
        self._render()

    def _active_table_row(self, item: PageObject) -> int | None:
        if self._active_table_cell and self._active_table_cell[0] == item.object_id:
            return self._active_table_cell[1]
        self.status.configure(text="Double-cliquez d’abord dans une cellule de la ligne concernée.")
        return None

    def _emphasize_active_table_row(self) -> None:
        item = self._selected_table()
        if item is None:
            return
        row = self._active_table_row(item)
        if row is None:
            return
        self._checkpoint()
        item.table_row_border_widths[str(row)] = 2.5
        self.status.configure(text=f"Bordures de la ligne {row + 1} épaissies.")
        self._render()

    def _reset_active_table_row(self) -> None:
        item = self._selected_table()
        if item is None:
            return
        row = self._active_table_row(item)
        if row is None:
            return
        self._checkpoint()
        item.table_row_border_widths.pop(str(row), None)
        self.status.configure(text=f"Bordures de la ligne {row + 1} rétablies.")
        self._render()

    def _active_table_coordinates(self, item: PageObject) -> tuple[int, int] | None:
        if self._active_table_cell and self._active_table_cell[0] == item.object_id:
            return self._active_table_cell[1], self._active_table_cell[2]
        self.status.configure(text="Double-cliquez d’abord dans une cellule du tableau.")
        return None

    def _append_table_border_range(
        self, item: PageObject, top: int, left: int, bottom: int, right: int, width: float
    ) -> None:
        self._checkpoint()
        item.table_border_ranges.append({
            "top": float(top), "left": float(left),
            "bottom": float(bottom), "right": float(right), "width": float(width),
        })
        self.status.configure(text="Contour personnalisé appliqué sans modifier le quadrillage intérieur.")
        self._render()

    def _outline_active_table_cell(self, width: float) -> None:
        item = self._selected_table()
        if item is None:
            return
        coordinates = self._active_table_coordinates(item)
        if coordinates is None:
            return
        row, column = coordinates
        merge = self._table_merge_for_cell(item, row, column)
        if merge:
            top, left, row_span, column_span = merge
            self._append_table_border_range(
                item, top, left, top + row_span - 1, left + column_span - 1, width
            )
        else:
            self._append_table_border_range(item, row, column, row, column, width)

    def _outline_active_table_row_or_column(self, direction: str, width: float) -> None:
        item = self._selected_table()
        if item is None:
            return
        coordinates = self._active_table_coordinates(item)
        if coordinates is None:
            return
        row, column = coordinates
        cells = self._ensure_table_cells(item)
        rows = len(cells)
        columns = max((len(candidate) for candidate in cells), default=1)
        if direction == "row":
            self._append_table_border_range(item, row, 0, row, columns - 1, width)
        else:
            self._append_table_border_range(item, 0, column, rows - 1, column, width)

    def _start_table_border_range(self) -> None:
        item = self._selected_table()
        if item is None:
            return
        coordinates = self._active_table_coordinates(item)
        if coordinates is None:
            return
        self._table_border_range_start = (item.object_id, coordinates[0], coordinates[1])
        self.status.configure(
            text="Premier coin mémorisé. Double-cliquez dans la cellule opposée, puis appliquez le contour de plage."
        )

    def _finish_table_border_range(self, width: float) -> None:
        item = self._selected_table()
        if item is None:
            return
        coordinates = self._active_table_coordinates(item)
        start = self._table_border_range_start
        if coordinates is None or start is None or start[0] != item.object_id:
            self.status.configure(text="Définissez d’abord le premier coin de la plage.")
            return
        row, column = coordinates
        _object_id, start_row, start_column = start
        self._table_border_range_start = None
        self._append_table_border_range(
            item, min(start_row, row), min(start_column, column),
            max(start_row, row), max(start_column, column), width,
        )

    def _clear_table_border_ranges(self) -> None:
        item = self._selected_table()
        if item is None or not item.table_border_ranges:
            return
        self._checkpoint()
        item.table_border_ranges.clear()
        self.status.configure(text="Contours personnalisés effacés ; quadrillage intérieur conservé.")
        self._render()

    def _start_linked_text_editor(self, item: PageObject) -> None:
        dialog = tk.Toplevel(self, class_="Loucodiworkshop")
        dialog.title("Texte chaîné — Lou Còdi")
        dialog.configure(bg=BACKGROUND)
        dialog.transient(self)
        dialog.geometry(
            f"720x300+{max(20, self.winfo_screenwidth() - 750)}+{max(80, self.winfo_rooty() + 120)}"
        )
        tk.Label(
            dialog,
            text="Modifier le texte chaîné",
            bg=NAVY,
            fg="white",
            font=("Sans", 16, "bold"),
            padx=18,
            pady=10,
        ).pack(fill="x")
        tk.Label(
            dialog,
            text="Écrivez ou collez ici : la page montre immédiatement la répartition entre les cadres liés.",
            bg=BACKGROUND,
            fg="#385571",
            font=("Sans", 10),
            padx=16,
            pady=7,
        ).pack(fill="x")
        widget = tk.Text(
            dialog,
            wrap="word",
            font=("Liberation Sans", 12),
            bg="white",
            fg=item.color,
            relief="solid",
            borderwidth=1,
            undo=True,
            padx=8,
            pady=8,
        )
        widget.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        widget.insert("1.0", item.text)
        widget.bind("<Control-v>", self._paste_clean_text_widget)
        actions = tk.Frame(dialog, bg=BACKGROUND)
        actions.pack(fill="x", padx=14, pady=(0, 10))
        distribution = tk.Label(actions, bg=BACKGROUND, fg="#385571", font=("Sans", 9))
        distribution.pack(side="left")
        tk.Button(
            actions,
            text="Terminer",
            command=self._commit_inline_editor,
            bg="#2368AF",
            fg="white",
            activebackground="#174D85",
            activeforeground="white",
            relief="flat",
            padx=18,
            pady=6,
        ).pack(side="right")
        tk.Button(
            actions,
            text="Passer au cadre suivant →",
            command=lambda: widget.insert("insert", f"\n{FLOW_BREAK_TOKEN}\n"),
            relief="flat",
            padx=12,
            pady=6,
        ).pack(side="right", padx=(8, 0))
        self._editing_widget = widget
        self._editing_dialog = dialog
        self._editing_object_id = item.object_id
        self._editing_original_text = item.text

        def preview(_event: object = None) -> None:
            if not widget.edit_modified():
                return
            item.text = widget.get("1.0", "end-1c")
            widget.edit_modified(False)
            self._redraw_text_chain(item)
            chain: list[PageObject] = []
            cursor = item
            known = {candidate.object_id: candidate for candidate in self.document.objects}
            visited: set[str] = set()
            while cursor.object_id not in visited:
                visited.add(cursor.object_id)
                chain.append(cursor)
                if not cursor.flow_next_id or cursor.flow_next_id not in known:
                    break
                cursor = known[cursor.flow_next_id]
            counts = [len(flowed_text_for_object(frame, self.document.objects)) for frame in chain]
            distribution.configure(
                text="Répartition : "
                + "  •  ".join(
                    f"cadre {number + 1} : {count}" for number, count in enumerate(counts)
                )
            )

        widget.bind("<<Modified>>", preview)
        widget.bind("<Control-Return>", lambda _event: self._commit_inline_editor())
        widget.edit_modified(False)
        widget.edit_modified(True)
        preview()
        dialog.protocol("WM_DELETE_WINDOW", self._commit_inline_editor)
        dialog.lift()
        widget.focus_set()

    def _paste_clean_text_widget(
        self, event: tk.Event[tk.Text] | None = None, *, rich: bool = True
    ) -> str | None:
        """Paste office text with its character styles, or clean plain text."""
        rich_text = ""
        rich_styles: list[dict[str, object]] = []
        if rich:
            html_value = self._clipboard_html()
            if html_value:
                try:
                    rich_text, rich_styles = parse_rich_clipboard_html(html_value)
                except (UnicodeError, ValueError):
                    pass
        try:
            value = normalize_external_text(self.clipboard_get())
        except tk.TclError:
            return None
        if rich_text and (
            rich_styles or rich_clipboard_matches_plain(rich_text, value)
        ):
            value = rich_text
        else:
            rich_styles = []
            value = (
                normalize_rich_plain_fallback(value)
                if rich
                else normalize_plain_paste(value)
            )
        if not value or value == "LOUCODI_OBJECTS":
            return "break"
        widget = event.widget if event is not None else self._editing_widget
        if widget is None:
            return "break"
        widget.edit_separator()
        try:
            widget.delete("sel.first", "sel.last")
        except tk.TclError:
            pass
        insertion_start = self._text_character_offset(widget, "insert")
        widget.insert("insert", value)
        item = next(
            (
                candidate
                for candidate in self.document.objects
                if candidate.object_id == self._editing_object_id
            ),
            None,
        )
        if item is not None:
            for run in rich_styles:
                start = insertion_start + int(run["start"])
                end = insertion_start + int(run["end"])
                style = {
                    key: style_value
                    for key, style_value in run.items()
                    if key in TEXT_STYLE_KEYS
                }
                if not style or end <= start:
                    continue
                tag = f"style_paste_{uuid.uuid4().hex}"
                self._editing_style_tags[tag] = style
                self._configure_text_style_tag(widget, tag, item, style)
                widget.tag_add(tag, f"1.0 + {start} chars", f"1.0 + {end} chars")
        widget.edit_separator()
        self._editing_selection_range = None
        widget.focus_set()
        return "break"

    def _paste_plain_text_widget(self) -> str:
        return self._paste_clean_text_widget(rich=False) or "break"

    def _clipboard_html(self) -> str:
        """Read the rich clipboard target, including Linux office fallbacks."""
        target_names = [
            "text/html",
            "text/html;charset=utf-8",
            "text/html;charset=UTF-8",
            "HTML Format",
        ]
        for target in target_names:
            try:
                value = self.selection_get(selection="CLIPBOARD", type=target)
                if value:
                    return str(value)
            except tk.TclError:
                continue
        commands: list[list[str]] = []
        if shutil.which("wl-paste"):
            try:
                available = subprocess.run(
                    ["wl-paste", "--list-types"],
                    capture_output=True,
                    check=True,
                    timeout=2,
                    text=True,
                ).stdout.splitlines()
            except (OSError, subprocess.SubprocessError):
                available = []
            target_names = [
                target
                for target in available
                if "html" in target.casefold()
            ] or ["text/html"]
            commands.extend(
                ["wl-paste", "--no-newline", "--type", target]
                for target in target_names
            )
        if shutil.which("xclip"):
            try:
                available = subprocess.run(
                    [
                        "xclip",
                        "-selection",
                        "clipboard",
                        "-t",
                        "TARGETS",
                        "-o",
                    ],
                    capture_output=True,
                    check=True,
                    timeout=2,
                ).stdout.decode("utf-8", errors="replace").splitlines()
            except (OSError, subprocess.SubprocessError):
                available = []
            target_names = [
                target
                for target in available
                if "html" in target.casefold()
            ] or ["text/html"]
            commands.extend(
                ["xclip", "-selection", "clipboard", "-t", target, "-o"]
                for target in target_names
            )
        for command in commands:
            try:
                result = subprocess.run(
                    command, capture_output=True, check=True, timeout=2
                )
            except (OSError, subprocess.SubprocessError):
                continue
            if result.stdout:
                return result.stdout.decode("utf-8", errors="replace")
        return ""

    def _redraw_text_chain(self, root: PageObject) -> None:
        chain_ids = {root.object_id}
        cursor = root
        visited: set[str] = set()
        by_id = {candidate.object_id: candidate for candidate in self.document.objects}
        while cursor.flow_next_id and cursor.object_id not in visited:
            visited.add(cursor.object_id)
            chain_ids.add(cursor.flow_next_id)
            cursor = by_id.get(cursor.flow_next_id, cursor)
        for index, candidate in enumerate(self.document.objects):
            if candidate.object_id in chain_ids and self.current_page in pages_for_object(
                candidate, self.document.page_count
            ):
                if (
                    candidate.object_id == self._editing_object_id
                    and self._editing_widget is not None
                    and self._editing_dialog is None
                ):
                    continue
                self.canvas.delete(f"object:{index}")
                self.canvas.delete(f"resize-start:{index}")
                self.canvas.delete(f"resize-end:{index}")
                self._draw_object(index, candidate)

    def _commit_inline_editor(self, *, render: bool = True) -> None:
        widget = self._editing_widget
        if widget is None:
            return
        value = normalize_external_text(widget.get("1.0", "end-1c"))
        item = next(
            (
                candidate
                for candidate in self.document.objects
                if candidate.object_id == self._editing_object_id
            ),
            None,
        )
        original_text = self._editing_original_text
        original_styles = self._editing_original_styles
        original_align = self._editing_original_align
        original_fill = self._editing_original_fill
        original_border_color = self._editing_original_border_color
        original_border_width = self._editing_original_border_width
        original_border_style = self._editing_original_border_style
        original_paragraph_alignments = self._editing_original_paragraph_alignments
        flow_root_id = self._editing_flow_root_id
        flow_offset = self._editing_flow_offset
        flow_original_segment = self._editing_flow_original_segment
        flow_original_links = self._editing_flow_original_links
        flow_local_links = self._editing_flow_local_links
        table_cell = self._editing_table_cell
        table_original = self._editing_table_original
        self._editing_widget = None
        self._inline_font_family_combo = None
        self._inline_font_menu = None
        dialog = self._editing_dialog
        self._editing_dialog = None
        self._editing_object_id = ""
        self._editing_original_text = ""
        self._editing_original_styles = []
        self._editing_original_align = "left"
        self._editing_original_fill = "#FFFFFF"
        self._editing_original_border_color = "#000000"
        self._editing_original_border_width = 1.0
        self._editing_original_border_style = "solid"
        self._editing_original_paragraph_alignments = []
        self._editing_flow_root_id = ""
        self._editing_flow_offset = 0
        self._editing_flow_original_segment = ""
        self._editing_flow_original_links = []
        self._editing_flow_local_links = []
        self._editing_selection_range = None
        self._editing_drag_anchor = None
        self._editing_table_cell = None
        self._editing_table_original = None
        if item is not None:
            if table_cell is not None and item.kind == "table":
                row, column = table_cell
                cell = self._ensure_table_cells(item)[row][column]
                cell["text"] = value
                styles: list[dict[str, object]] = []
                for tag, style in self._editing_style_tags.items():
                    ranges = widget.tag_ranges(tag)
                    for start_index, end_index in zip(
                        ranges[::2], ranges[1::2], strict=True
                    ):
                        start = self._text_character_offset(widget, start_index)
                        end = self._text_character_offset(widget, end_index)
                        if end > start:
                            styles.append({"start": start, "end": end, **style})
                cell["text_styles"] = styles
                self._sync_table_text(item)
                # Editing one verbose imported cell must not multiply the
                # complete table height by that cell's number of lines.
                item.height = stable_table_height_after_cell_edit(
                    item.height,
                    len(item.table_cells),
                )
                changed = cell != table_original
            else:
                styles: list[dict[str, object]] = []
                for tag, style in self._editing_style_tags.items():
                    ranges = widget.tag_ranges(tag)
                    for start_index, end_index in zip(ranges[::2], ranges[1::2], strict=True):
                        start = self._text_character_offset(widget, start_index)
                        end = self._text_character_offset(widget, end_index)
                        if end > start:
                            styles.append({"start": start, "end": end, **style})
                flow_root = next(
                    (
                        candidate
                        for candidate in self.document.objects
                        if candidate.object_id == flow_root_id
                    ),
                    None,
                ) if flow_root_id else None
                style_owner = flow_root or item
                paragraph_alignments: list[dict[str, object]] = []
                last_line = int(widget.index("end-1c").split(".", 1)[0])
                for line_number in range(1, last_line + 1):
                    start_index = f"{line_number}.0"
                    end_index = widget.index(f"{start_index} lineend")
                    start = self._text_character_offset(widget, start_index)
                    end = self._text_character_offset(widget, end_index)
                    if end <= start:
                        continue
                    alignment = style_owner.align
                    for tag in widget.tag_names(start_index):
                        if tag in self._editing_alignment_tags:
                            alignment = self._editing_alignment_tags[tag]
                    if alignment != style_owner.align:
                        paragraph_alignments.append(
                            {"start": start, "end": end, "align": alignment}
                        )
                if flow_root is not None:
                    old_length = len(flow_original_segment)
                    flow_root.text = (
                        original_text[:flow_offset]
                        + value
                        + original_text[flow_offset + old_length:]
                    )
                    flow_root.text_styles = _replace_text_ranges(
                        original_styles, flow_offset, old_length, styles, len(value)
                    )
                    flow_root.paragraph_alignments = _replace_text_ranges(
                        original_paragraph_alignments,
                        flow_offset,
                        old_length,
                        paragraph_alignments,
                        len(value),
                    )
                    flow_root.text_links = _replace_text_ranges(
                        flow_original_links,
                        flow_offset,
                        old_length,
                        flow_local_links,
                        len(value),
                    )
                    changed = (
                        value != flow_original_segment
                        or flow_root.text_styles != original_styles
                        or flow_root.paragraph_alignments != original_paragraph_alignments
                        or flow_root.text_links != flow_original_links
                        or item.fill != original_fill
                        or item.border_color != original_border_color
                        or item.border_width != original_border_width
                        or item.border_style != original_border_style
                    )
                else:
                    item.text = value
                    item.text_styles = styles
                    item.paragraph_alignments = paragraph_alignments
                    changed = (
                        value != original_text
                        or styles != original_styles
                        or item.align != original_align
                        or item.fill != original_fill
                        or item.border_color != original_border_color
                        or item.border_width != original_border_width
                        or item.border_style != original_border_style
                        or paragraph_alignments != original_paragraph_alignments
                        or item.text_links != flow_original_links
                    )
            if changed:
                snapshot = copy.deepcopy(self.document)
                snapshot_item = next(
                    candidate for candidate in snapshot.objects if candidate.object_id == item.object_id
                )
                if table_cell is not None and snapshot_item.kind == "table" and table_original is not None:
                    row, column = table_cell
                    self._ensure_table_cells(snapshot_item)[row][column] = table_original
                    self._sync_table_text(snapshot_item)
                else:
                    snapshot_root = next(
                        (
                            candidate
                            for candidate in snapshot.objects
                            if candidate.object_id == flow_root_id
                        ),
                        snapshot_item,
                    )
                    snapshot_root.text = original_text
                    snapshot_root.text_styles = original_styles
                    snapshot_root.align = original_align
                    snapshot_root.text_links = flow_original_links
                    snapshot_root.paragraph_alignments = original_paragraph_alignments
                    snapshot_item.fill = original_fill
                    snapshot_item.border_color = original_border_color
                    snapshot_item.border_width = original_border_width
                    snapshot_item.border_style = original_border_style
                self.undo_stack.append(snapshot)
                self.undo_stack = self.undo_stack[-80:]
                self.redo_stack.clear()
        if dialog is not None:
            dialog.destroy()
        elif widget.winfo_exists():
            widget.destroy()
        self._editing_style_tags = {}
        self._editing_alignment_tags = {}
        if render:
            self._render()

    def _mutate(self, mutation: object) -> None:
        if self.selected is not None:
            self._checkpoint()
            mutation(self.document.objects[self.selected])  # type: ignore[operator]
            self._render()

    def _toggle(self, name: str) -> None:
        if self.selected is not None:
            item = self.document.objects[self.selected]
            selection = self._selected_inline_text_range(item)
            if item.kind in {"text", "table"} and self._editing_widget is not None:
                if selection is None:
                    self.status.configure(text="Sélectionnez d’abord le texte à mettre en forme.")
                    self._editing_widget.focus_set()
                    return
                widget = self._editing_widget
                current = bool(
                    self._inline_text_style_at(widget, item, selection[0]).get(name, getattr(item, name))
                )
                self._apply_inline_text_style(item, {name: not current})
                return
        self._mutate(lambda item: setattr(item, name, not getattr(item, name)))

    def _align(self, value: str) -> None:
        if self.selected is not None:
            item = self.document.objects[self.selected]
            widget = self._editing_widget
            if (
                item.kind == "text"
                and widget is not None
                and self._editing_object_id == item.object_id
            ):
                selection = self._editing_selection_range
                if selection is None:
                    start_index = widget.index("insert display linestart")
                    end_index = widget.index("insert display lineend")
                else:
                    start_offset, end_offset = selection
                    start_index = widget.index(f"1.0 + {start_offset} chars linestart")
                    raw_end = widget.index(f"1.0 + {end_offset} chars")
                    if end_offset > start_offset and widget.compare(
                        raw_end, "==", f"{raw_end} linestart"
                    ):
                        raw_end = widget.index(f"{raw_end} - 1 chars")
                    end_index = widget.index(f"{raw_end} lineend")
                for tag in self._editing_alignment_tags:
                    widget.tag_remove(tag, start_index, end_index)
                tag = f"paragraph_align_live_{uuid.uuid4().hex}"
                self._editing_alignment_tags[tag] = value
                # Tk ne fournit pas de justification pleine. L'aperçu final
                # répartit réellement les espaces après validation.
                widget.tag_configure(tag, justify=value if value != "justify" else "left")
                widget.tag_add(tag, start_index, end_index)
                widget.tag_raise("sel")
                widget.focus_set()
                self.status.configure(
                    text=(
                        "Paragraphe justifié : le résultat exact apparaît après Terminer."
                        if value == "justify"
                        else "Alignement appliqué au paragraphe ou aux paragraphes sélectionnés."
                    )
                )
                return
        self._mutate(lambda item: setattr(item, "align", value))

    def _set_object_color(self, attribute: str, value: str) -> None:
        if attribute == "fill" and value.lower() == "transparent":
            if (
                self.selected is not None
                and self.document.objects[self.selected].kind == "mask"
            ):
                self.status.configure(
                    text="Un masque doit conserver un fond visible. Utilisez Supprimer pour l’enlever."
                )
                return
            self._mutate(lambda item: setattr(item, "fill", "transparent"))
            return
        normalized = value if value.startswith("#") else f"#{value}"
        try:
            self.winfo_rgb(normalized)
        except tk.TclError:
            messagebox.showerror(
                "Couleur incorrecte",
                "Utilisez un code hexadécimal, par exemple #2368AF.",
                parent=self,
            )
            return
        if attribute == "color" and self.selected is not None:
            item = self.document.objects[self.selected]
            if item.kind in {"text", "table"} and self._editing_widget is not None:
                if not self._apply_inline_text_style(item, {"color": normalized.upper()}):
                    self.status.configure(text="Sélectionnez d’abord le texte à colorer.")
                    self._editing_widget.focus_set()
                return
        if attribute == "border_color" and self.selected is not None:
            item = self.document.objects[self.selected]
            if item.kind == "text" and self._editing_widget is not None:
                item.border_color = normalized.upper()
                item.border_width = max(1.5, item.border_width)
                self._editing_widget.configure(
                    highlightthickness=max(1, round(item.border_width * self.zoom)),
                    highlightbackground=item.border_color,
                    highlightcolor=item.border_color,
                )
                self._editing_widget.focus_set()
                self.status.configure(text="Couleur de bordure appliquée à la zone.")
                return
            if item.kind == "text":
                def apply_text_border(target: PageObject) -> None:
                    target.border_color = normalized.upper()
                    target.border_width = max(1.5, target.border_width)

                self._mutate(apply_text_border)
                return
        self._mutate(lambda item: setattr(item, attribute, normalized.upper()))

    def _set_text_highlight(self, color: str) -> None:
        if self.selected is None:
            return
        item = self.document.objects[self.selected]
        if item.kind not in {"text", "table"}:
            self.status.configure(text="Le surlignage s’applique au texte en cours d’édition.")
            return
        if self._apply_inline_text_style(item, {"highlight": color}):
            return
        self.status.configure(
            text="Double-cliquez dans la zone, sélectionnez le passage, puis choisissez la couleur de surlignage."
        )

    def _set_inline_text_frame_fill(self, color: str) -> None:
        if self.selected is None:
            return
        item = self.document.objects[self.selected]
        if item.kind != "text":
            return
        item.fill = color
        widget = self._editing_widget
        if widget is not None and self._editing_object_id == item.object_id:
            background = color if color.lower() not in {"", "none", "transparent"} else "white"
            widget.configure(bg=background)
            for tag, style in self._editing_style_tags.items():
                self._configure_text_style_tag(widget, tag, item, style)
            widget.tag_raise("sel")
            widget.focus_set()
        self.status.configure(
            text=("Fond de la zone rendu transparent." if color == "transparent" else "Couleur de fond appliquée à la zone.")
        )

    def _choose_inline_text_frame_fill(self) -> None:
        if self.selected is None:
            return
        item = self.document.objects[self.selected]
        initial = item.fill if item.fill.startswith("#") else "#FFFFFF"
        chosen = choose_color(self, "Couleur de fond de la zone", initial)
        if chosen:
            self._set_inline_text_frame_fill(chosen)

    def _set_border_width_value(self, value: float) -> None:
        if self.selected is not None:
            item = self.document.objects[self.selected]
            if item.kind == "text" and self._editing_widget is not None:
                item.border_width = value
                self._editing_widget.configure(
                    highlightthickness=max(0, round(value * self.zoom))
                )
                self._editing_widget.focus_set()
                self.status.configure(text="Épaisseur de bordure appliquée à la zone.")
                return
        self._mutate(lambda item: setattr(item, "border_width", value))

    def _set_border_style_value(self, value: str) -> None:
        if self.selected is not None:
            item = self.document.objects[self.selected]
            if item.kind == "text" and self._editing_widget is not None:
                item.border_style = value
                self._commit_inline_editor(render=True)
                self.status.configure(
                    text="Style de bordure appliqué à la zone. Double-cliquez pour reprendre la saisie."
                )
                return
        self._mutate(lambda item: setattr(item, "border_style", value))

    def _write_edited_image(
        self, source: Image.Image, suffix: str = ".png", *, optimize: bool = True
    ) -> Path:
        directory = module_output_directory("Document Studio") / "Images modifiées"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"image_{uuid.uuid4().hex[:10]}{suffix}"
        if suffix.lower() in {".jpg", ".jpeg"}:
            source.convert("RGB").save(target, "JPEG", quality=88, optimize=optimize)
        else:
            source.save(target, "PNG", optimize=optimize)
        return target

    def _replace_image_pixels(
        self, item: PageObject, image: Image.Image, *, optimize: bool = True
    ) -> None:
        item.image_path = str(self._write_edited_image(image, optimize=optimize))

    def _crop_selected_image(self) -> None:
        if self.selected is None or self.document.objects[self.selected].kind != "image":
            self.status.configure(text="Sélectionnez d’abord une image à rogner.")
            return
        item = self.document.objects[self.selected]
        self._crop_mode_index = self.selected
        self._crop_box = [item.x, item.y, item.x + item.width, item.y + item.height]
        self._crop_drag_edge = None
        self.canvas.configure(cursor="crosshair")
        self.status.configure(
            text="Rognage visuel : faites glisser le bord gauche, droit, haut ou bas de l’image."
        )
        self._render()

    def _draw_crop_overlay(self) -> None:
        if self._crop_mode_index is None or self._crop_box is None:
            return
        if self._crop_mode_index >= len(self.document.objects):
            self._cancel_visual_crop()
            return
        left, top, right, bottom = self._crop_box
        x1, y1 = self.page_x + left * self.zoom, self.page_y + top * self.zoom
        x2, y2 = self.page_x + right * self.zoom, self.page_y + bottom * self.zoom
        self.canvas.create_rectangle(
            x1, y1, x2, y2, outline="#E47D16", width=3, dash=(7, 4),
            tags=("crop-overlay",),
        )
        for x, y in (
            ((x1 + x2) / 2, y1), (x2, (y1 + y2) / 2),
            ((x1 + x2) / 2, y2), (x1, (y1 + y2) / 2),
        ):
            self.canvas.create_rectangle(
                x - 6, y - 6, x + 6, y + 6,
                fill="white", outline="#E47D16", width=2, tags=("crop-overlay",),
            )

    def _start_crop_drag(self, event: tk.Event[tk.Misc]) -> None:
        if self._crop_box is None:
            return
        pointer_x = (self.canvas.canvasx(event.x) - self.page_x) / self.zoom
        pointer_y = (self.canvas.canvasy(event.y) - self.page_y) / self.zoom
        left, top, right, bottom = self._crop_box
        tolerance = 14 / self.zoom
        candidates = {
            "left": abs(pointer_x - left), "right": abs(pointer_x - right),
            "top": abs(pointer_y - top), "bottom": abs(pointer_y - bottom),
        }
        edge = min(candidates, key=candidates.get)
        within = (
            top - tolerance <= pointer_y <= bottom + tolerance
            if edge in {"left", "right"}
            else left - tolerance <= pointer_x <= right + tolerance
        )
        if candidates[edge] <= tolerance and within:
            self._crop_drag_edge = edge
            self.canvas.configure(cursor="sb_h_double_arrow" if edge in {"left", "right"} else "sb_v_double_arrow")
        else:
            self.status.configure(text="Attrapez une poignée orange placée au milieu d’un bord.")

    def _drag_crop_edge(self, event: tk.Event[tk.Misc]) -> None:
        if self._crop_box is None or self._crop_drag_edge is None:
            return
        pointer_x = (self.canvas.canvasx(event.x) - self.page_x) / self.zoom
        pointer_y = (self.canvas.canvasy(event.y) - self.page_y) / self.zoom
        left, top, right, bottom = self._crop_box
        item = self.document.objects[self._crop_mode_index]  # type: ignore[index]
        original_left, original_top = item.x, item.y
        original_right, original_bottom = item.x + item.width, item.y + item.height
        minimum = max(8.0, 12.0 / self.zoom)
        if self._crop_drag_edge == "left":
            left = min(right - minimum, max(original_left, pointer_x))
        elif self._crop_drag_edge == "right":
            right = max(left + minimum, min(original_right, pointer_x))
        elif self._crop_drag_edge == "top":
            top = min(bottom - minimum, max(original_top, pointer_y))
        else:
            bottom = max(top + minimum, min(original_bottom, pointer_y))
        self._crop_box[:] = [left, top, right, bottom]
        self.canvas.delete("crop-overlay")
        self._draw_crop_overlay()

    def _apply_visual_crop(self) -> None:
        if self._crop_mode_index is None or self._crop_box is None:
            return
        item = self.document.objects[self._crop_mode_index]
        try:
            with Image.open(item.image_path) as source:
                image = source.copy()
        except OSError as exc:
            messagebox.showerror("Image illisible", str(exc), parent=self)
            self._cancel_visual_crop()
            return
        width, height = image.size
        left, top, right, bottom = self._crop_box
        relative_left = (left - item.x) / max(1e-9, item.width)
        relative_top = (top - item.y) / max(1e-9, item.height)
        relative_right = (right - item.x) / max(1e-9, item.width)
        relative_bottom = (bottom - item.y) / max(1e-9, item.height)
        box = (
            round(width * relative_left), round(height * relative_top),
            round(width * relative_right), round(height * relative_bottom),
        )
        self._checkpoint()
        cropped = image.crop(box)
        item.x, item.y = left, top
        item.width, item.height = right - left, bottom - top
        # A fast save is sufficient here: final package embedding can optimise later.
        self._replace_image_pixels(item, cropped, optimize=False)
        self._crop_mode_index = None
        self._crop_box = None
        self._crop_drag_edge = None
        self.canvas.configure(cursor="")
        self.status.configure(
            text=f"Image rognée : {cropped.width} × {cropped.height} pixels. Ctrl+Z restaure l’image précédente."
        )
        self._render()

    def _cancel_visual_crop(self) -> None:
        self._crop_mode_index = None
        self._crop_box = None
        self._crop_drag_edge = None
        self.canvas.configure(cursor="")
        self.canvas.delete("crop-overlay")

    def _resize_selected_image_pixels(self) -> None:
        if self.selected is None or self.document.objects[self.selected].kind != "image":
            return
        item = self.document.objects[self.selected]
        try:
            with Image.open(item.image_path) as source:
                image = source.copy()
        except OSError as exc:
            messagebox.showerror("Image illisible", str(exc), parent=self)
            return
        maximum = ask_number(
            self, "Réduire l’image", "Dimension maximale en pixels (ratio conservé) :",
            float(max(image.size)), minimum=32,
        )
        if maximum is None:
            return
        resized = image.copy()
        maximum_pixels = max(32, round(maximum))
        resized.thumbnail((maximum_pixels, maximum_pixels), Image.Resampling.LANCZOS)
        self._checkpoint()
        self._replace_image_pixels(item, resized)
        self.status.configure(text=f"Image optimisée : {resized.width} × {resized.height} pixels, ratio conservé.")
        self._render()

    def _export_selected_image(self) -> None:
        if self.selected is None or self.document.objects[self.selected].kind != "image":
            return
        item = self.document.objects[self.selected]
        extension = (ask_text(self, "Exporter l’image", "Format : PNG ou JPEG", "PNG") or "").strip().lower()
        suffix = ".jpg" if extension in {"jpg", "jpeg"} else ".png"
        target = choose_save_path(
            self, document_destination(), f"image_{self.project_path.stem if self.project_path else 'document'}", suffix
        )
        if not target:
            return
        try:
            with Image.open(item.image_path) as source:
                if suffix == ".jpg":
                    source.convert("RGB").save(target, "JPEG", quality=92, optimize=True)
                else:
                    source.save(target, "PNG", optimize=True)
        except OSError as exc:
            messagebox.showerror("Export impossible", str(exc), parent=self)
            return
        self.status.configure(text=f"Image exportée : {Path(target).name}")

    def _set_selected_hyperlink(self) -> None:
        if self.selected is None:
            return
        item = self.document.objects[self.selected]
        text_selection: tuple[int, int] | None = None
        if (
            item.kind == "text"
            and self._editing_widget is not None
            and self._editing_object_id == item.object_id
        ):
            text_selection = self._selected_inline_text_range(item)
        if item.kind == "text" and text_selection is None:
            self.status.configure(
                text="Dans une zone de texte, sélectionnez d’abord les mots qui porteront le lien."
            )
            if self._editing_widget is not None:
                self._editing_widget.focus_set()
            return
        value = ask_text(
            self,
            "Lien hypertexte",
            (
                "Adresse du lien pour le texte sélectionné (https://… ou mailto:…) :"
                if text_selection
                else "Adresse du lien (https://… ou mailto:…) :"
            ),
            "" if item.kind == "text" else item.hyperlink,
        )
        if value is None:
            return
        if value and ":" not in value:
            value = f"https://{value}"
        self._checkpoint()
        if text_selection and self._editing_widget is not None:
            start, end = text_selection
            links = self._editing_flow_local_links if self._editing_flow_root_id else item.text_links
            links[:] = [
                link for link in links
                if int(link.get("end", 0)) <= start or int(link.get("start", 0)) >= end
            ]
            links.append({"start": start, "end": end, "hyperlink": value})
            links.sort(key=lambda link: int(link.get("start", 0)))
        else:
            item.hyperlink = value
        self.status.configure(
            text=("Lien ajouté au texte sélectionné." if text_selection else "Lien hypertexte ajouté à l’objet.")
        )
        if text_selection and self._editing_widget is not None:
            start, end = text_selection
            self._editing_widget.tag_add(
                "hyperlink", f"1.0 + {start} chars", f"1.0 + {end} chars"
            )
            self._editing_widget.tag_raise("sel")
            return
        self._render()

    def _remove_selected_hyperlink(self) -> None:
        if self.selected is None:
            return
        item = self.document.objects[self.selected]
        if (
            item.kind == "text"
            and self._editing_widget is not None
            and self._editing_object_id == item.object_id
        ):
            try:
                start = self._text_character_offset(self._editing_widget, "sel.first")
                end = self._text_character_offset(self._editing_widget, "sel.last")
            except tk.TclError:
                start = end = -1
            if end > start:
                links = self._editing_flow_local_links if self._editing_flow_root_id else item.text_links
                previous = len(links)
                links[:] = [
                    link for link in links
                    if int(link.get("end", 0)) <= start or int(link.get("start", 0)) >= end
                ]
                if len(links) != previous:
                    self.status.configure(text="Lien retiré du texte sélectionné.")
                    self._editing_widget.tag_remove(
                        "hyperlink", f"1.0 + {start} chars", f"1.0 + {end} chars"
                    )
                    self._editing_widget.tag_raise("sel")
                    return
        if item.kind == "text":
            self.status.configure(
                text="Sélectionnez les mots dont vous voulez retirer le lien hypertexte."
            )
            if self._editing_widget is not None:
                self._editing_widget.focus_set()
            return
        if not item.hyperlink:
            self.status.configure(text="Cet objet ne contient aucun lien hypertexte.")
            return
        self._checkpoint()
        item.hyperlink = ""
        self.status.configure(text="Lien hypertexte supprimé.")
        self._render()

    def _open_selected_hyperlink(self) -> None:
        if self.selected is None:
            return
        address = self.document.objects[self.selected].hyperlink.strip()
        if not address:
            self.status.configure(text="Sélectionnez un objet lié ou un passage lié dans son texte.")
            return
        if not webbrowser.open(address, new=2):
            messagebox.showwarning(
                "Ouverture du lien",
                "Aucun navigateur n’a accepté l’ouverture automatique.\n\n"
                f"Adresse : {address}",
                parent=self,
            )

    def _enter_hex_color(self, attribute: str) -> None:
        if self.selected is None:
            return
        current = getattr(self.document.objects[self.selected], attribute)
        value = ask_text(self, "Code couleur", "Code hexadécimal (exemple : #2368AF) :", current)
        if value:
            self._set_object_color(attribute, value.strip())

    def _choose_color(self, attribute: str = "color") -> None:
        if self.selected is not None:
            chosen = choose_color(self, "Choisir une couleur", getattr(self.document.objects[self.selected], attribute))
            if chosen:
                self._set_object_color(attribute, chosen)

    def _change_font(self, change: int) -> None:
        if self.selected is not None:
            item = self.document.objects[self.selected]
            selection = self._selected_inline_text_range(item)
            if item.kind in {"text", "table"} and self._editing_widget is not None:
                if selection is None:
                    self.status.configure(text="Sélectionnez d’abord le texte à redimensionner.")
                    self._editing_widget.focus_set()
                    return
                widget = self._editing_widget
                current = float(
                    self._inline_text_style_at(widget, item, selection[0]).get("font_size", item.font_size)
                )
                new_size = max(6, current + change)
                self._apply_inline_text_style(item, {"font_size": new_size})
                self.font_size_var.set(f"{new_size:g}")
                return
        if self.selected is not None:
            new_size = max(6, self.document.objects[self.selected].font_size + change)
            self._mutate(lambda item: setattr(item, "font_size", new_size))
            self.font_size_var.set(f"{new_size:g}")

    def _apply_font_size(self) -> None:
        try:
            value = max(6.0, min(144.0, float(self.font_size_var.get().replace(",", "."))))
        except ValueError:
            return
        if self.selected is not None:
            item = self.document.objects[self.selected]
            if item.kind in {"text", "table"} and self._editing_widget is not None:
                if not self._apply_inline_text_style(item, {"font_size": value}):
                    self.status.configure(text="Sélectionnez d’abord le texte à redimensionner.")
                    self._editing_widget.focus_set()
                return
        self._mutate(lambda item: setattr(item, "font_size", value))

    def _apply_font_family(self) -> None:
        if self.selected is not None:
            item = self.document.objects[self.selected]
            if item.kind in {"text", "table"} and self._editing_widget is not None:
                if not self._apply_inline_text_style(
                    item, {"font_family": self.font_family_var.get()}
                ):
                    self.status.configure(text="Sélectionnez d’abord le texte dont vous voulez changer la police.")
                    self._editing_widget.focus_set()
                return
        self._mutate(lambda item: setattr(item, "font_family", self.font_family_var.get()))

    def _resize(self, factor: float) -> None:
        def resize(item: PageObject) -> None:
            item.width, item.height = max(20, item.width * factor), max(20, item.height * factor)
        self._mutate(resize)

    def _copy_format(self) -> None:
        if self.selected is not None:
            item = self.document.objects[self.selected]
            selection = self._selected_inline_text_range(item)
            if item.kind == "text" and selection is not None:
                widget = self._editing_widget
                self._format_clipboard = (
                    self._inline_text_style_at(widget, item, selection[0])
                    if widget is not None else text_style_at(item, selection[0])
                )
                self.status.configure(text="Format du texte sélectionné copié.")
            else:
                keys = ("font_size", "font_family", "bold", "italic", "underline", "strikethrough", "align", "color", "fill")
                self._format_clipboard = {key: getattr(item, key) for key in keys}
                self.status.configure(text="Format du cadre entier copié. Sélectionnez la destination puis appliquez-le.")

    def _apply_format(self) -> None:
        if not self._format_clipboard:
            return
        if self.selected is not None:
            item = self.document.objects[self.selected]
            inline = {key: value for key, value in self._format_clipboard.items() if key in TEXT_STYLE_KEYS}
            if item.kind == "text" and inline and self._apply_inline_text_style(item, inline):
                return
        def apply(item: PageObject) -> None:
            for key, value in self._format_clipboard.items():
                setattr(item, key, value)
        self._mutate(apply)

    def _copy_objects(self) -> None:
        indices = sorted(self.selected_indices)
        if not indices and self.selected is not None:
            indices = [self.selected]
        if not indices:
            self.status.configure(text="Sélectionnez un ou plusieurs objets à copier.")
            return
        self._object_clipboard = [copy.deepcopy(self.document.objects[index]) for index in indices]
        if len(self._object_clipboard) == 1 and self._object_clipboard[0].kind == "image":
            if self._copy_image_to_system_clipboard(self._object_clipboard[0]):
                self.status.configure(
                    text="Image copiée comme PNG : vous pouvez la coller dans Pinta, OnlyOffice ou Lou Còdi."
                )
                return
        self.clipboard_clear()
        self.clipboard_append("LOUCODI_OBJECTS")
        self.status.configure(
            text=f"{len(self._object_clipboard)} objet(s) copié(s). Changez de page puis utilisez Coller."
        )

    def _copy_image_to_system_clipboard(self, item: PageObject) -> bool:
        """Expose a Lou Còdi image as a standard PNG clipboard target on Linux."""
        try:
            with Image.open(item.image_path) as source:
                stream = io.BytesIO()
                source.save(stream, format="PNG")
                payload = stream.getvalue()
        except (OSError, ValueError):
            return False
        commands: list[list[str]] = []
        if shutil.which("wl-copy"):
            commands.append(["wl-copy", "--type", "image/png"])
        if shutil.which("xclip"):
            commands.append(["xclip", "-selection", "clipboard", "-t", "image/png", "-i"])
        for command in commands:
            try:
                subprocess.run(
                    command, input=payload, check=True, timeout=3,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            return True
        return False

    def _copy_shortcut(self, _event: object = None) -> str | None:
        if isinstance(self.focus_get(), (tk.Text, tk.Entry, ttk.Entry)):
            return None
        self._copy_objects()
        return "break"

    def _paste_shortcut(self, _event: object = None) -> str | None:
        if isinstance(self.focus_get(), (tk.Text, tk.Entry, ttk.Entry)):
            return None
        self._paste_from_system_clipboard()
        return "break"

    def _clipboard_image(self) -> Image.Image | None:
        try:
            content = ImageGrab.grabclipboard()
        except (OSError, NotImplementedError):
            content = None
        if isinstance(content, Image.Image):
            return content.copy()
        if isinstance(content, list):
            for raw_path in content:
                path = Path(raw_path)
                if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"} and path.is_file():
                    with Image.open(path) as source:
                        return source.copy()
        for mime_type in ("image/png", "image/jpeg"):
            try:
                raw = self.tk.call("selection", "get", "-selection", "CLIPBOARD", "-type", mime_type)
                if isinstance(raw, bytes):
                    with Image.open(io.BytesIO(raw)) as source:
                        return source.copy()
            except (tk.TclError, OSError, ValueError):
                continue
        commands = []
        if shutil.which("wl-paste"):
            commands.append(["wl-paste", "--no-newline", "--type", "image/png"])
        if shutil.which("xclip"):
            commands.append(["xclip", "-selection", "clipboard", "-t", "image/png", "-o"])
        for command in commands:
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    check=False,
                    timeout=3,
                )
                if result.returncode == 0 and result.stdout:
                    with Image.open(io.BytesIO(result.stdout)) as source:
                        return source.copy()
            except (OSError, subprocess.TimeoutExpired, ValueError):
                continue
        return None

    def _store_clipboard_image(self, image: Image.Image) -> Path:
        directory = module_output_directory("Document Studio") / "Images collées"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"image_collee_{uuid.uuid4().hex[:10]}.png"
        image.convert("RGBA").save(target, "PNG")
        return target

    @staticmethod
    def _clipboard_file_from_text(value: str) -> Path | None:
        lines = [line.strip() for line in value.splitlines() if line.strip()]
        if lines and lines[0].lower() in {"copy", "cut"}:
            lines = lines[1:]
        for line in lines:
            if line.startswith("file://"):
                parsed = urlparse(line)
                uri_path = url2pathname(unquote(parsed.path))
                if parsed.netloc:
                    uri_path = f"//{parsed.netloc}{uri_path}"
                candidate = Path(uri_path)
            else:
                candidate = Path(line)
            if candidate.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"} and candidate.is_file():
                return candidate
        return None

    def _clipboard_image_file(self, text_value: str = "") -> Path | None:
        candidate = self._clipboard_file_from_text(text_value) if text_value else None
        if candidate is not None:
            return candidate
        for target_type in ("x-special/gnome-copied-files", "text/uri-list"):
            try:
                raw = self.tk.call(
                    "selection", "get", "-selection", "CLIPBOARD", "-type", target_type
                )
            except tk.TclError:
                continue
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            candidate = self._clipboard_file_from_text(str(raw))
            if candidate is not None:
                return candidate
        return None

    def _paste_from_system_clipboard(self) -> None:
        try:
            text_value = self.clipboard_get()
        except tk.TclError:
            text_value = ""
        if text_value == "LOUCODI_OBJECTS" and self._object_clipboard:
            self._paste_objects()
            return
        rich_table_cells: list[list[dict[str, object]]] = []
        column_widths: list[float] = []
        row_heights: list[float] = []
        html_value = self._clipboard_html()
        if html_value:
            rich_table_cells, column_widths, row_heights = parse_tabular_clipboard_html(html_value)
        table_cells = rich_table_cells or parse_tabular_clipboard(text_value)
        if table_cells:
            rows, columns = len(table_cells), len(table_cells[0])
            natural_width = sum(column_widths) if any(column_widths) else columns * 105.0
            natural_height = sum(row_heights) if any(row_heights) else rows * 38.0
            self._add_object(PageObject(
                "table", self.current_page, 70, 80,
                min(500.0, max(180.0, natural_width)),
                min(520.0, max(70.0, natural_height)),
                table_cells=table_cells, font_size=10,
                table_column_widths=column_widths,
                table_row_heights=row_heights,
            ))
            self.status.configure(text=f"Tableau modifiable collé : {rows} ligne(s) × {columns} colonne(s).")
            return
        image = self._clipboard_image()
        image_path = self._clipboard_image_file(text_value)
        if image is not None or image_path is not None:
            if image is not None:
                image_path = self._store_clipboard_image(image)
                width, height = image.size
            else:
                assert image_path is not None
                with Image.open(image_path) as source:
                    image = source.convert("RGBA")
                    width, height = source.size
            if (
                self.selected is not None
                and self.document.objects[self.selected].kind == "image"
                and image is not None
            ):
                self._checkpoint()
                target = self.document.objects[self.selected]
                self._replace_image_pixels(target, image, optimize=False)
                self._render()
                self.status.configure(
                    text="Image remplacée sans modifier la taille ni les proportions de son cadre."
                )
                return
            display_width = min(320.0, max(80.0, float(width)))
            display_height = min(240.0, max(60.0, display_width * height / max(1, width)))
            self._add_object(PageObject("image", self.current_page, 70, 80, display_width, display_height, image_path=str(image_path)))
            self.status.configure(text="Image collée depuis le presse-papiers.")
            return
        value = normalize_external_text(text_value).strip("\n")
        if not value:
            self.status.configure(text="Le presse-papiers ne contient ni texte ni image exploitable.")
            return
        if self.selected is not None and self.document.objects[self.selected].kind == "text":
            self._checkpoint()
            target = self.document.objects[self.selected]
            separator = "\n" if target.text and not target.text.endswith("\n") else ""
            target.text += separator + value
            self._render()
            self.status.configure(text="Texte collé à la suite de la zone sélectionnée.")
            return
        self._add_object(PageObject("text", self.current_page, 70, 80, 320, 100, text=value))
        self.status.configure(text="Texte collé dans une nouvelle zone.")

    def _paste_objects(self) -> None:
        if not self._object_clipboard:
            self.status.configure(text="Aucun objet n’a encore été copié.")
            return
        self._checkpoint()
        id_map = {item.object_id: uuid.uuid4().hex for item in self._object_clipboard}
        group_map: dict[str, str] = {}
        pasted: list[int] = []
        for original in self._object_clipboard:
            item = copy.deepcopy(original)
            item.object_id = id_map[original.object_id]
            item.page = self.current_page
            item.pages = ""
            item.x += 12
            item.y += 12
            if item.group:
                group_map.setdefault(item.group, uuid.uuid4().hex)
                item.group = group_map[item.group]
            item.source_id = id_map.get(item.source_id, "")
            item.flow_next_id = id_map.get(item.flow_next_id, "")
            for reference in item.dimension_refs:
                reference["object_id"] = id_map.get(
                    str(reference.get("object_id", "")),
                    str(reference.get("object_id", "")),
                )
            self.document.objects.append(item)
            pasted.append(len(self.document.objects) - 1)
        self.selected_indices = set(pasted)
        self.selected = pasted[-1]
        self.status.configure(
            text=f"{len(pasted)} copie(s) indépendante(s) collée(s) sur la page {self.current_page + 1}."
        )
        self._render()

    def _duplicate_objects(self) -> None:
        self._copy_objects()
        self._paste_objects()

    def _link_text_frames(self) -> None:
        indices = sorted(
            index
            for index in self.selected_indices
            if self.document.objects[index].kind == "text"
        )
        if len(indices) == 1:
            source = self.document.objects[indices[0]]
            self._pending_text_link_id = source.object_id
            self.canvas.configure(cursor="crosshair")
            self.status.configure(
                text="Chaînage actif : cliquez maintenant sur la zone de texte qui doit recevoir la suite."
            )
            self._render()
            return
        if len(indices) != 2:
            messagebox.showinfo(
                "Chaînage du texte",
                "Sélectionnez une zone de texte, cliquez sur Chaîner, puis cliquez sur la zone suivante.",
                parent=self,
            )
            return
        first, second = (self.document.objects[index] for index in indices)
        if (second.page, second.y, second.x) < (first.page, first.y, first.x):
            first, second = second, first
        self._connect_text_frames(first, second)

    def _cancel_text_link(self) -> None:
        if not self._pending_text_link_id:
            return
        self._pending_text_link_id = ""
        self.canvas.configure(cursor="")
        self.status.configure(text="Chaînage annulé.")
        self._render()

    def _connect_text_frames(self, first: PageObject, second: PageObject) -> None:
        by_id = {item.object_id: item for item in self.document.objects}
        cursor = second
        visited: set[str] = set()
        while cursor.flow_next_id and cursor.object_id not in visited:
            visited.add(cursor.object_id)
            if cursor.flow_next_id == first.object_id:
                messagebox.showwarning(
                    "Chaînage du texte",
                    "Ce lien créerait une boucle entre les zones de texte.",
                    parent=self,
                )
                return
            cursor = by_id.get(cursor.flow_next_id, cursor)
        self._checkpoint()
        first.flow_next_id = second.object_id
        if second.text and second.text.strip():
            first.text = f"{first.text}\n{second.text}".strip()
            second.text = ""
        first_index = self.document.objects.index(first)
        self.selected = first_index
        self.selected_indices = {first_index}
        self.status.configure(
            text="Liaison validée automatiquement. Écrivez directement dans le premier cadre : la suite apparaît dans les suivants."
        )
        self._render()
        self.after_idle(lambda: self._start_inline_text_editor(first))

    def _copy_previous_text_frame_appearance(self) -> None:
        """Copy only frame appearance, never the linked text content."""
        if self.selected is None:
            return
        target = self.document.objects[self.selected]
        predecessor = next(
            (
                candidate
                for candidate in self.document.objects
                if candidate.kind == "text" and candidate.flow_next_id == target.object_id
            ),
            None,
        )
        if target.kind != "text" or predecessor is None:
            self.status.configure(text="Cette zone n’a pas de cadre précédent.")
            return
        self._checkpoint()
        for attribute in ("fill", "border_color", "border_width", "border_style"):
            setattr(target, attribute, getattr(predecessor, attribute))
        self._render()
        self.status.configure(
            text="Fond et bordure repris du cadre précédent ; dimensions et rotation conservées."
        )

    def _unlink_text_frame(self) -> None:
        if self.selected is None or self.document.objects[self.selected].kind != "text":
            return
        item = self.document.objects[self.selected]
        predecessor = next(
            (
                candidate
                for candidate in self.document.objects
                if candidate.kind == "text" and candidate.flow_next_id == item.object_id
            ),
            None,
        )
        if not item.flow_next_id and predecessor is None:
            return
        self._checkpoint()
        if predecessor is not None:
            predecessor.flow_next_id = ""
        item.flow_next_id = ""
        self.status.configure(text="Zone de texte déliée.")
        self._render()

    def _delete_selected(self) -> None:
        if self.selected is not None:
            self._checkpoint()
            del self.document.objects[self.selected]
            self.selected = None
            self.selected_indices.clear()
            self._render()

    def _align_objects(self, mode: str) -> None:
        indices = sorted(self.selected_indices)
        if len(indices) < 2:
            return
        self._checkpoint()
        objects = [self.document.objects[index] for index in indices]
        anchor = objects[0]
        for item in objects[1:]:
            if mode == "left":
                item.x = anchor.x
            elif mode == "center":
                item.x = anchor.x + (anchor.width - item.width) / 2
            elif mode == "right":
                item.x = anchor.x + anchor.width - item.width
            elif mode == "top":
                item.y = anchor.y
            elif mode == "middle":
                item.y = anchor.y + (anchor.height - item.height) / 2
            elif mode == "bottom":
                item.y = anchor.y + anchor.height - item.height
        self._render()

    def _split_crossing_lines(self) -> None:
        indices = sorted(self.selected_indices)
        if len(indices) != 2 or any(self.document.objects[index].kind != "line" for index in indices):
            messagebox.showinfo(
                "Découper au croisement",
                "Avec Ctrl, sélectionnez exactement deux traits qui se croisent.",
                parent=self,
            )
            return
        originals = [self.document.objects[index] for index in indices]
        segments = split_at_intersection(
            Segment(originals[0].x, originals[0].y, originals[0].x + originals[0].width, originals[0].y + originals[0].height),
            Segment(originals[1].x, originals[1].y, originals[1].x + originals[1].width, originals[1].y + originals[1].height),
        )
        if not segments:
            messagebox.showinfo(
                "Découper au croisement",
                "Les traits doivent se croiser à l’intérieur de leurs segments et ne pas être parallèles.",
                parent=self,
            )
            return
        self._checkpoint()
        for index in reversed(indices):
            del self.document.objects[index]
        new_indices: list[int] = []
        for position, segment in enumerate(segments):
            source = originals[0] if position < 2 else originals[1]
            clone = copy.deepcopy(source)
            clone.object_id = uuid.uuid4().hex
            clone.x, clone.y = segment.x1, segment.y1
            clone.width, clone.height = segment.x2 - segment.x1, segment.y2 - segment.y1
            clone.rotation = round(self._object_angle(clone))
            self.document.objects.append(clone)
            new_indices.append(len(self.document.objects) - 1)
        self.selected_indices = set(new_indices)
        self.selected = new_indices[-1]
        self.status.configure(text="Croisement découpé en quatre segments indépendants. Supprimez les branches inutiles.")
        self._render()

    def _split_selection_automatically(self) -> None:
        """Choose the appropriate cutting algorithm from the two selected objects."""
        indices = sorted(self.selected_indices)
        if len(indices) != 2:
            messagebox.showinfo(
                "Découpe automatique",
                "Sélectionnez exactement deux éléments avec Ctrl : deux traits, un trait et une forme, ou deux formes.",
                parent=self,
            )
            return
        first, second = (self.document.objects[index] for index in indices)
        if first.kind == second.kind == "line":
            self._split_crossing_lines()
            return
        outlines = [bool(self._closed_outline(item)) for item in (first, second)]
        if (first.kind == "line" and outlines[1]) or (second.kind == "line" and outlines[0]):
            self._split_shape_with_line()
            return
        if all(outlines):
            self._split_two_shapes()
            return
        messagebox.showinfo(
            "Découpe impossible",
            "Cette combinaison ne peut pas encore être découpée. Utilisez deux traits, un trait traversant une forme fermée, ou deux formes fermées.",
            parent=self,
        )

    def _start_measurement(self) -> None:
        if len(self.selected_indices) == 2:
            items = [self.document.objects[index] for index in sorted(self.selected_indices)]
            if all(item.kind == "line" for item in items):
                first, second = items
                angle = angle_between_segments(
                    Segment(first.x, first.y, first.x + first.width, first.y + first.height),
                    Segment(second.x, second.y, second.x + second.width, second.y + second.height),
                )
                summary = f"Angle entre les deux traits : {angle:.1f}°"
                self.measurement_result.configure(text=summary)
                self.status.configure(text=summary)
                if self.write_measurement_var.get() and self.measurement_label_vars["angle"].get():
                    center_x = (first.x + first.width / 2 + second.x + second.width / 2) / 2
                    center_y = (first.y + first.height / 2 + second.y + second.height / 2) / 2
                    self._write_measurement_label(f"∠ {angle:.1f}°", center_x + 10, center_y - 24)
                return
        if len(self.selected_indices) == 1:
            item = self.document.objects[next(iter(self.selected_indices))]
            summary = self._selected_measurement_summary(item)
            if summary:
                self.measurement_result.configure(text=summary)
                self.status.configure(text=summary)
                if self.write_measurement_var.get():
                    label = self._measurement_label_for_item(item)
                    if label:
                        self._write_measurement_label(
                            label,
                            item.x + item.width / 2 + 8,
                            item.y + item.height / 2 - 22,
                        )
                return
        self._measurement_mode = "measure"
        self._measurement_points.clear()
        self.canvas.delete("measurement-anchor")
        self.canvas.configure(cursor="crosshair")
        self.status.configure(text="Mesure : cliquez sur le premier point, puis sur le second. Échap annule.")

    def _start_dimension_measurement(self) -> None:
        self._measurement_mode = "dimension"
        self._measurement_points.clear()
        self._measurement_refs.clear()
        self.canvas.delete("dimension-preview")
        self.canvas.delete("measurement-anchor")
        self.canvas.configure(cursor="crosshair")
        self.status.configure(
            text="Cotation : cliquez deux points, arêtes ou sommets, puis placez la ligne de cote. Échap annule."
        )

    def _draw_dimension_placement_preview(self, placement: tuple[float, float]) -> None:
        self.canvas.delete("dimension-preview")
        if len(self._measurement_points) != 2:
            return
        first, second = self._measurement_points
        geometry = dimension_line_geometry(first, second, placement)
        if geometry is None:
            return
        start, end = geometry

        def canvas_point(point: tuple[float, float]) -> tuple[float, float]:
            return self.page_x + point[0] * self.zoom, self.page_y + point[1] * self.zoom

        first_canvas, second_canvas = canvas_point(first), canvas_point(second)
        start_canvas, end_canvas = canvas_point(start), canvas_point(end)
        for anchor, endpoint in ((first_canvas, start_canvas), (second_canvas, end_canvas)):
            self.canvas.create_line(
                *anchor, *endpoint, fill="#E87524", dash=(4, 3),
                tags=("dimension-preview",),
            )
        self.canvas.create_line(
            *start_canvas, *end_canvas, fill="#1769AA", width=2,
            arrow="both", tags=("dimension-preview",),
        )
        measured = math.dist(first, second) * 25.4 / 72 * self.document.measurement_scale
        label_x, label_y, label_angle = dimension_label_layout(
            start_canvas, end_canvas, gap=13.0
        )
        self.canvas.create_text(
            label_x,
            label_y,
            text=f"{measured:.2f} mm", fill="#1769AA",
            font=("Sans", 9, "bold"), angle=label_angle,
            tags=("dimension-preview",),
        )

    def _dimension_selected_circle(self) -> None:
        if len(self.selected_indices) != 1:
            messagebox.showinfo("Coter un cercle", "Sélectionnez un cercle.", parent=self)
            return
        item = self.document.objects[next(iter(self.selected_indices))]
        if item.kind != "shape" or item.shape != "circle":
            messagebox.showinfo(
                "Coter un cercle", "L’objet sélectionné n’est pas un cercle paramétrique.", parent=self
            )
            return
        left = (item.x, item.y + item.height / 2)
        right = (item.x + item.width, item.y + item.height / 2)
        offset = max(18.0, item.height * 0.18)
        start, end = (left[0], left[1] - offset), (right[0], right[1] - offset)
        diameter = abs(item.width) * 25.4 / 72 * self.document.measurement_scale
        self._add_object(PageObject(
            "dimension", self.current_page, start[0], start[1],
            end[0] - start[0], end[1] - start[1], text=f"Ø {diameter:.2f}",
            border_color="#1769AA", border_width=1,
            points=[[left[0], left[1]], [right[0], right[1]]],
        ))
        self.status.configure(text=f"Cote de diamètre créée : Ø {diameter:.2f} mm.")

    def _measure_selected_area(self) -> None:
        if len(self.selected_indices) != 1:
            messagebox.showinfo("Calculer l’aire", "Sélectionnez un contour fermé.", parent=self)
            return
        item = self.document.objects[next(iter(self.selected_indices))]
        outline = self._closed_outline(item)
        if not outline:
            messagebox.showinfo(
                "Calculer l’aire", "Le contour sélectionné n’est pas fermé.", parent=self
            )
            return
        scale = 25.4 / 72 * self.document.measurement_scale
        area = polygon_area(outline) * scale * scale
        result = f"Aire du contour : {area:.2f} mm²"
        self.measurement_result.configure(text=result)
        self.status.configure(text=result)
        if self.write_measurement_var.get() and self.measurement_label_vars["area"].get():
            self._write_measurement_label(
                f"A = {area:.2f} mm²",
                item.x + item.width / 2 + 8,
                item.y + item.height / 2 - 22,
            )

    def _start_angle_measurement(self) -> None:
        self._measurement_mode = "angle"
        self._measurement_points.clear()
        self.canvas.delete("measurement-anchor")
        self.canvas.configure(cursor="crosshair")
        self.status.configure(
            text="Angle : cliquez un point du premier côté, le sommet, puis un point du second côté."
        )

    def _start_right_triangle(self) -> None:
        indices = sorted(self.selected_indices)
        if len(indices) != 2 or any(self.document.objects[index].kind != "line" for index in indices):
            messagebox.showinfo(
                "Triangle rectangle",
                "Sélectionnez d’abord deux traits avec Ctrl : la base et le trait que la perpendiculaire doit rejoindre.",
                parent=self,
            )
            return
        self._pending_right_triangle = (indices[0], indices[1])
        self.canvas.configure(cursor="crosshair")
        self.status.configure(
            text="Triangle rectangle : cliquez sur le trait qui servira de base, à l’emplacement du pied de la perpendiculaire."
        )

    def _right_triangle_geometry(
        self, x: float, y: float
    ) -> tuple[Segment, tuple[float, float], tuple[float, float]] | None:
        if self._pending_right_triangle is None:
            return None
        first_index, second_index = self._pending_right_triangle
        first_item, second_item = self.document.objects[first_index], self.document.objects[second_index]
        first = Segment(first_item.x, first_item.y, first_item.x + first_item.width, first_item.y + first_item.height)
        second = Segment(second_item.x, second_item.y, second_item.x + second_item.width, second_item.y + second_item.height)
        if point_to_segment_distance(x, y, second) < point_to_segment_distance(x, y, first):
            first, second = second, first
        foot = closest_point_on_segment(x, y, first)
        direction_x, direction_y = first.x2 - first.x1, first.y2 - first.y1
        perpendicular = Segment(foot[0], foot[1], foot[0] - direction_y, foot[1] + direction_x)
        crossing = line_intersection(perpendicular, second)
        if crossing is None or point_to_segment_distance(crossing[0], crossing[1], second) > 1e-6:
            return None
        return first, foot, crossing

    def _draw_right_triangle_preview(self, event: tk.Event[tk.Misc]) -> None:
        self.canvas.delete("right-triangle-preview")
        x = (self.canvas.canvasx(event.x) - self.page_x) / self.zoom
        y = (self.canvas.canvasy(event.y) - self.page_y) / self.zoom
        geometry = self._right_triangle_geometry(x, y)
        if geometry is None:
            self.status.configure(text="Déplacez le pointeur : la perpendiculaire doit couper le second segment.")
            return
        base, foot, crossing = geometry
        distance_mm = math.dist((base.x1, base.y1), foot) * 25.4 / 72
        self.canvas.create_line(
            self.page_x + foot[0] * self.zoom, self.page_y + foot[1] * self.zoom,
            self.page_x + crossing[0] * self.zoom, self.page_y + crossing[1] * self.zoom,
            fill="#E87524", width=3, dash=(5, 3), tags=("right-triangle-preview",),
        )
        self.canvas.create_text(
            self.page_x + foot[0] * self.zoom + 8,
            self.page_y + foot[1] * self.zoom - 10,
            text=f"pied à {distance_mm:.2f} mm  •  90°",
            anchor="sw", fill="#A34D00", font=("Sans", 9, "bold"),
            tags=("right-triangle-preview",),
        )
        self.status.configure(
            text=f"Pied de la perpendiculaire : {distance_mm:.2f} mm depuis l’extrémité du trait. Cliquez pour valider."
        )

    def _place_right_triangle_perpendicular(self, x: float, y: float) -> None:
        geometry = self._right_triangle_geometry(x, y)
        if geometry is None:
            messagebox.showinfo(
                "Triangle rectangle",
                "La perpendiculaire ne coupe pas le second segment à cet endroit. Déplacez le pied ou prolongez le second trait.",
                parent=self,
            )
            return
        _base, foot, crossing = geometry
        self._pending_right_triangle = None
        self.canvas.configure(cursor="")
        self.canvas.delete("right-triangle-preview")
        self._add_object(
            PageObject(
                "line", self.current_page, foot[0], foot[1],
                crossing[0] - foot[0], crossing[1] - foot[1],
                border_color="#193B66", border_width=1.5,
            )
        )
        self.status.configure(
            text="Perpendiculaire créée : angle droit exact de 90° et intersection exacte avec le second trait."
        )

    def _selected_measurement_summary(self, item: PageObject) -> str:
        scale = 25.4 / 72 * self.document.measurement_scale
        if item.kind == "line":
            return (
                f"Trait : {math.hypot(item.width, item.height) * scale:.2f} mm  •  "
                f"angle {self._object_angle(item):.1f}°"
            )
        if item.kind == "shape" and item.shape in {"ellipse", "circle"}:
            width, height = abs(item.width) * scale, abs(item.height) * scale
            if abs(width - height) <= max(width, height) * 0.01:
                return (
                    f"Cercle : Ø {width:.2f} mm  •  rayon {width / 2:.2f} mm"
                    f"  •  circonférence {math.pi * width:.2f} mm"
                    f"  •  aire {math.pi * (width / 2) ** 2:.2f} mm²"
                )
            return f"Ellipse : {width:.2f} × {height:.2f} mm"
        if item.kind == "polyline" and len(item.points) >= 2:
            length = sum(math.dist(first, second) for first, second in pairwise(item.points)) * scale
            outline = self._closed_outline(item)
            area = f"  •  aire {polygon_area(outline) * scale * scale:.2f} mm²" if outline else ""
            return f"Polyligne : longueur cumulée {length:.2f} mm  •  {len(item.points) - 1} segment(s){area}"
        if item.kind in {"shape", "image", "text", "table", "mask"}:
            return f"Dimensions : {abs(item.width) * scale:.2f} × {abs(item.height) * scale:.2f} mm"
        return ""

    def _measurement_label_for_item(self, item: PageObject) -> str:
        """Build only the measurement fields explicitly requested for the drawing."""
        scale = 25.4 / 72 * self.document.measurement_scale
        fields: list[str] = []
        if item.kind == "line":
            if self.measurement_label_vars["distance"].get():
                fields.append(f"L = {math.hypot(item.width, item.height) * scale:.2f} mm")
            if self.measurement_label_vars["angle"].get():
                fields.append(f"∠ {self._object_angle(item):.1f}°")
            return "  •  ".join(fields)

        outline = self._closed_outline(item)
        if item.kind == "shape" and item.shape == "circle":
            diameter = abs(item.width) * scale
            if self.measurement_label_vars["distance"].get():
                fields.append(f"Ø {diameter:.2f} mm")
            if self.measurement_label_vars["perimeter"].get():
                fields.append(f"P = {math.pi * diameter:.2f} mm")
            if self.measurement_label_vars["area"].get():
                fields.append(f"A = {math.pi * (diameter / 2) ** 2:.2f} mm²")
            return "  •  ".join(fields)

        if item.kind == "polyline" and len(item.points) >= 2:
            length = sum(math.dist(first, second) for first, second in pairwise(item.points)) * scale
            if self.measurement_label_vars["distance"].get() and not outline:
                fields.append(f"L = {length:.2f} mm")
            if self.measurement_label_vars["perimeter"].get() and outline:
                fields.append(f"P = {length:.2f} mm")
            if self.measurement_label_vars["area"].get() and outline:
                fields.append(f"A = {polygon_area(outline) * scale * scale:.2f} mm²")
            if self.measurement_label_vars["segments"].get():
                fields.append(f"{len(item.points) - 1} segment(s)")
            return "  •  ".join(fields)

        if self.measurement_label_vars["distance"].get():
            fields.append(f"{abs(item.width) * scale:.2f} × {abs(item.height) * scale:.2f} mm")
        if self.measurement_label_vars["perimeter"].get() and outline:
            fields.append(
                f"P = {sum(math.dist(first, second) for first, second in pairwise(outline)) * scale:.2f} mm"
            )
        if self.measurement_label_vars["area"].get() and outline:
            fields.append(f"A = {polygon_area(outline) * scale * scale:.2f} mm²")
        return "  •  ".join(fields)

    def _write_measurement_label(self, text: str, x: float, y: float) -> None:
        self._checkpoint()
        self.document.objects.append(
            PageObject(
                "text", self.current_page, x, y, max(90, min(250, len(text) * 7.5)), 28,
                text=text, font_size=10, bold=True, color="#1769AA",
                fill="transparent", border_color="transparent", border_width=0,
                source_id="measurement",
            )
        )
        self._render()
        self.canvas.update_idletasks()

    def _start_scale_calibration(self) -> None:
        self._measurement_mode = "calibrate"
        self._measurement_points.clear()
        self.canvas.delete("measurement-anchor")
        self.canvas.configure(cursor="crosshair")
        self.status.configure(
            text="Étalonnage : cliquez sur les deux extrémités d’une longueur connue du plan."
        )

    def _capture_measurement_point(self, x: float, y: float) -> None:
        width, height = self._page_size()
        if not (0 <= x <= width and 0 <= y <= height):
            return
        if self._measurement_mode == "dimension" and len(self._measurement_points) == 2:
            geometry = dimension_line_geometry(
                self._measurement_points[0], self._measurement_points[1], (x, y)
            )
            if geometry is None:
                self.status.configure(text="Les deux références doivent être différentes.")
                return
            first, second = self._measurement_points
            references = copy.deepcopy(self._measurement_refs)
            start, end = geometry
            measured = math.dist(first, second) * 25.4 / 72 * self.document.measurement_scale
            self._measurement_mode = ""
            self._measurement_points.clear()
            self._measurement_refs.clear()
            self.canvas.delete("dimension-preview")
            self.canvas.delete("snap-preview")
            self.canvas.delete("measurement-anchor")
            self.canvas.configure(cursor="")
            self._add_object(PageObject(
                "dimension", self.current_page, start[0], start[1],
                end[0] - start[0], end[1] - start[1], text=f"{measured:.2f}",
                border_color="#1769AA", border_width=1,
                points=[[first[0], first[1]], [second[0], second[1]]],
                dimension_refs=references,
            ))
            result = f"Cote créée : {measured:.2f} mm."
            self.measurement_result.configure(text=result)
            self.status.configure(text=result)
            return
        if self._measurement_mode == "dimension":
            snapped, snap_label, reference = self._dimension_reference_at(x, y)
            self._measurement_refs.append(reference)
        else:
            snapped, snap_label = self._snap_drawing_point(x, y)
        self._measurement_points.append(snapped)
        self._draw_measurement_anchor_markers()
        if self._measurement_mode == "angle" and len(self._measurement_points) < 3:
            instruction = "Cliquez maintenant le sommet." if len(self._measurement_points) == 1 else "Cliquez un point du second côté."
            self.status.configure(text=(f"Point accroché sur une {snap_label}. " if snap_label else "Point mémorisé. ") + instruction)
            return
        if self._measurement_mode != "angle" and len(self._measurement_points) == 1:
            self.status.configure(text="Premier point mémorisé. Cliquez sur le second point.")
            return
        if self._measurement_mode == "dimension" and len(self._measurement_points) == 2:
            self.status.configure(
                text="Références mémorisées. Déplacez la souris puis cliquez pour placer la cote."
            )
            return
        if self._measurement_mode == "angle":
            first, vertex, second = self._measurement_points[:3]
            self._measurement_mode = ""
            self._measurement_points.clear()
            self.canvas.delete("measurement-anchor")
            self.canvas.configure(cursor="")
            self.canvas.delete("snap-preview")
            try:
                angle = angle_at_vertex(first, vertex, second)
            except ValueError as error:
                self.status.configure(text=str(error))
                return
            first_length = math.dist(first, vertex) * 25.4 / 72 * self.document.measurement_scale
            second_length = math.dist(second, vertex) * 25.4 / 72 * self.document.measurement_scale
            length_detail = f"  •  prises de cote {first_length:.2f} / {second_length:.2f} mm" if self.show_measurement_length_var.get() else ""
            result = f"Angle intérieur : {angle:.1f}°{length_detail}"
            self.measurement_result.configure(text=result)
            self.status.configure(text=result)
            if self.write_measurement_var.get() and self.measurement_label_vars["angle"].get():
                label = f"∠ {angle:.1f}°"
                if self.show_measurement_length_var.get():
                    label += f"  ({first_length:.1f} / {second_length:.1f} mm)"
                self._write_measurement_label(label, vertex[0] + 10, vertex[1] - 30)
            self.after_idle(self._render)
            self.after(1, self._render)
            return
        start, end = self._measurement_points[:2]
        raw_mm = math.dist(start, end) * 25.4 / 72
        mode = self._measurement_mode
        self._measurement_mode = ""
        self._measurement_points.clear()
        self.canvas.delete("measurement-anchor")
        self.canvas.configure(cursor="")
        self.canvas.delete("snap-preview")
        if raw_mm <= 1e-9:
            self.status.configure(text="Les deux points doivent être différents.")
            return
        if mode == "calibrate":
            actual = ask_number(self, "Étalonner le plan", "Distance réelle entre ces deux points (en mm) :", minimum=0.0001)
            if actual is None:
                return
            self._checkpoint()
            self.document.measurement_scale = actual / raw_mm
            self.measurement_result.configure(
                text=f"Échelle étalonnée : {raw_mm:.2f} mm à l’écran = {actual:g} mm réels."
            )
            self.status.configure(text="Échelle du plan étalonnée. Les mesures utilisent maintenant cette échelle.")
            self._render()
            return
        measured_mm = raw_mm * self.document.measurement_scale
        dx_mm = abs(end[0] - start[0]) * 25.4 / 72 * self.document.measurement_scale
        dy_mm = abs(end[1] - start[1]) * 25.4 / 72 * self.document.measurement_scale
        angle = math.degrees(math.atan2(-(end[1] - start[1]), end[0] - start[0]))
        result = f"Distance {measured_mm:.2f} mm  •  ΔX {dx_mm:.2f}  •  ΔY {dy_mm:.2f}  •  angle {angle:.1f}°"
        self.measurement_result.configure(text=result)
        self.status.configure(text=result)
        if self.write_measurement_var.get():
            self._checkpoint()
            if self.measurement_label_vars["distance"].get():
                self.document.objects.append(
                    PageObject(
                        "dimension",
                        self.current_page,
                        start[0],
                        start[1],
                        end[0] - start[0],
                        end[1] - start[1],
                        text=f"{measured_mm:.2f}",
                        border_color="#1769AA",
                        border_width=1,
                        points=[[start[0], start[1]], [end[0], end[1]]],
                    )
                )
            if self.measurement_label_vars["angle"].get():
                self.document.objects.append(
                    PageObject(
                        "text", self.current_page,
                        (start[0] + end[0]) / 2 + 8,
                        (start[1] + end[1]) / 2 - 26,
                        85, 24, text=f"∠ {angle:.1f}°", font_size=10, bold=True,
                        color="#1769AA", fill="transparent", border_color="transparent",
                        source_id="measurement",
                    )
                )
            self._render()
            self.canvas.update_idletasks()

    @staticmethod
    def _closed_outline(item: PageObject) -> list[tuple[float, float]]:
        if item.kind == "polyline":
            points = [(item.x + point[0], item.y + point[1]) for point in item.points]
            if points and math.dist(points[0], points[-1]) <= 1e-6:
                return points
            return []
        if item.kind != "shape" or item.shape == "arrow":
            return []
        x, y, width, height = item.x, item.y, item.width, item.height
        if item.shape in {"ellipse", "circle"}:
            center_x, center_y = x + width / 2, y + height / 2
            return [
                (
                    center_x + width / 2 * math.cos(2 * math.pi * (step + 0.5) / 72),
                    center_y + height / 2 * math.sin(2 * math.pi * (step + 0.5) / 72),
                )
                for step in range(73)
            ]
        if item.shape == "triangle":
            return [(x + width / 2, y), (x + width, y + height), (x, y + height), (x + width / 2, y)]
        if item.shape == "trapezoid":
            inset = width * 0.2
            return [(x + inset, y), (x + width - inset, y), (x + width, y + height), (x, y + height), (x + inset, y)]
        return [(x, y), (x + width, y), (x + width, y + height), (x, y + height), (x, y)]

    @staticmethod
    def _polyline_from_path(source: PageObject, path: list[tuple[float, float]]) -> PageObject:
        left = min(point[0] for point in path)
        top = min(point[1] for point in path)
        right = max(point[0] for point in path)
        bottom = max(point[1] for point in path)
        return PageObject(
            "polyline",
            source.page,
            left,
            top,
            right - left,
            bottom - top,
            points=[[x - left, y - top] for x, y in path],
            border_color=source.border_color,
            border_width=source.border_width,
            border_style=source.border_style,
            fill="transparent",
        )

    @staticmethod
    def _set_polyline_absolute_points(
        item: PageObject, path: list[tuple[float, float]]
    ) -> None:
        left = min(point[0] for point in path)
        top = min(point[1] for point in path)
        right = max(point[0] for point in path)
        bottom = max(point[1] for point in path)
        item.x, item.y = left, top
        item.width, item.height = max(1.0, right - left), max(1.0, bottom - top)
        item.points = [[x - left, y - top] for x, y in path]

    def _split_shape_with_line(self) -> None:
        indices = sorted(self.selected_indices)
        if len(indices) != 2:
            messagebox.showinfo(
                "Découper une forme",
                "Avec Ctrl, sélectionnez un trait et une forme fermée.",
                parent=self,
            )
            return
        line_index = next(
            (index for index in indices if self.document.objects[index].kind == "line"),
            None,
        )
        shape_index = next((index for index in indices if index != line_index), None)
        if line_index is None or shape_index is None:
            messagebox.showinfo(
                "Découper une forme",
                "La sélection doit contenir exactement un trait et une forme fermée.",
                parent=self,
            )
            return
        line = self.document.objects[line_index]
        source = self.document.objects[shape_index]
        outline = self._closed_outline(source)
        paths = split_closed_polyline_by_segment(
            outline,
            Segment(line.x, line.y, line.x + line.width, line.y + line.height),
        )
        line_segments = split_segment_by_closed_polyline(
            Segment(line.x, line.y, line.x + line.width, line.y + line.height),
            outline,
        )
        if not paths or len(line_segments) < 3:
            messagebox.showinfo(
                "Découper une forme",
                "Le trait doit traverser deux fois l’intérieur du contour fermé.",
                parent=self,
            )
            return
        self._checkpoint()
        for index in reversed(indices):
            del self.document.objects[index]
        new_indices: list[int] = []
        for path in paths:
            self.document.objects.append(self._polyline_from_path(source, path))
            new_indices.append(len(self.document.objects) - 1)
        for segment in line_segments:
            clone = copy.deepcopy(line)
            clone.object_id = uuid.uuid4().hex
            clone.group = ""
            clone.x, clone.y = segment.x1, segment.y1
            clone.width, clone.height = segment.x2 - segment.x1, segment.y2 - segment.y1
            self.document.objects.append(clone)
            new_indices.append(len(self.document.objects) - 1)
        self.selected_indices = set(new_indices)
        self.selected = new_indices[-1]
        self.status.configure(
            text="Forme et trait découpés en morceaux indépendants. Supprimez les portions inutiles."
        )
        self._render()

    def _split_two_shapes(self) -> None:
        indices = sorted(self.selected_indices)
        if len(indices) != 2:
            messagebox.showinfo(
                "Découper deux formes",
                "Avec Ctrl, sélectionnez exactement deux formes fermées qui se croisent.",
                parent=self,
            )
            return
        first, second = (self.document.objects[index] for index in indices)
        first_outline = self._closed_outline(first)
        second_outline = self._closed_outline(second)
        first_paths = split_closed_polyline_by_polyline(first_outline, second_outline)
        second_paths = split_closed_polyline_by_polyline(second_outline, first_outline)
        if not first_paths or not second_paths:
            messagebox.showinfo(
                "Découper deux formes",
                "Les deux contours doivent être fermés et se croiser au moins deux fois.",
                parent=self,
            )
            return
        self._checkpoint()
        for index in reversed(indices):
            del self.document.objects[index]
        new_indices: list[int] = []
        for source, paths in ((first, first_paths), (second, second_paths)):
            for path in paths:
                self.document.objects.append(self._polyline_from_path(source, path))
                new_indices.append(len(self.document.objects) - 1)
        self.selected_indices = set(new_indices)
        self.selected = new_indices[-1]
        self.status.configure(
            text="Les deux formes sont décomposées à leurs intersections. Supprimez les profils inutiles puis assemblez les autres."
        )
        self._render()

    def _selected_line_segments(self) -> list[Segment]:
        segments: list[Segment] = []
        for index in sorted(self.selected_indices):
            item = self.document.objects[index]
            if item.kind == "line":
                segments.append(
                    Segment(item.x, item.y, item.x + item.width, item.y + item.height)
                )
            elif item.kind == "polyline" and len(item.points) >= 2:
                absolute = [(item.x + x, item.y + y) for x, y in item.points]
                segments.extend(Segment(*start, *end) for start, end in pairwise(absolute))
            else:
                return []
        return segments

    def _check_contour(self) -> None:
        segments = self._selected_line_segments()
        if len(segments) < 2:
            messagebox.showinfo(
                "Contrôle du contour",
                "Sélectionnez au moins deux traits ou polylignes avec Ctrl ou la sélection par zone.",
                parent=self,
            )
            return
        tolerance_mm = ask_number(self, "Contrôle du contour", "Tolérance entre les extrémités (mm) :", 1.0, minimum=0.01)
        if tolerance_mm is None:
            return
        points, gap, closed = join_segments(segments, tolerance_mm * 72 / 25.4)
        if len(points) != len(segments) + 1:
            messagebox.showwarning(
                "Contour discontinu",
                "Les éléments ne forment pas une seule chaîne continue dans la tolérance choisie.",
                parent=self,
            )
            return
        gap_mm = gap * 25.4 / 72
        messagebox.showinfo(
            "Contrôle du contour",
            (
                f"Contour fermé : {len(segments)} segment(s), écart final {gap_mm:.3f} mm."
                if closed
                else f"Chaîne continue, mais contour ouvert : écart final {gap_mm:.3f} mm."
            ),
            parent=self,
        )

    def _close_contour(self) -> None:
        if len(self.selected_indices) == 1:
            selected_index = next(iter(self.selected_indices))
            selected = self.document.objects[selected_index]
            if selected.kind == "polyline" and len(selected.points) >= 2:
                if math.dist(selected.points[0], selected.points[-1]) <= 1e-6:
                    self.status.configure(text="Cette polyligne est déjà fermée.")
                    return
                self._checkpoint()
                selected.points.append(list(selected.points[0]))
                self.status.configure(
                    text="Polyligne fermée : un segment relie maintenant le dernier point au premier."
                )
                self._render()
                return
        segments = self._selected_line_segments()
        if len(segments) < 2:
            messagebox.showinfo(
                "Fermer le contour",
                "Sélectionnez les traits constituant le contour.",
                parent=self,
            )
            return
        tolerance_mm = ask_number(self, "Fermer le contour", "Tolérance maximale de raccordement (mm) :", 1.0, minimum=0.01)
        if tolerance_mm is None:
            return
        points, gap, closed = join_segments(segments, tolerance_mm * 72 / 25.4)
        if len(points) != len(segments) + 1:
            messagebox.showwarning(
                "Contour discontinu",
                "Impossible d’ordonner tous les éléments en une seule chaîne. Rapprochez les extrémités ou augmentez la tolérance.",
                parent=self,
            )
            return
        if not closed:
            messagebox.showwarning(
                "Contour ouvert",
                f"L’écart restant est de {gap * 25.4 / 72:.3f} mm, au-delà de la tolérance.",
                parent=self,
            )
            return
        source = self.document.objects[min(self.selected_indices)]
        points[-1] = points[0]
        contour = self._polyline_from_path(source, points)
        contour.fill = "transparent"
        contour.group = ""
        self._checkpoint()
        for index in sorted(self.selected_indices, reverse=True):
            del self.document.objects[index]
        self.document.objects.append(contour)
        self.selected = len(self.document.objects) - 1
        self.selected_indices = {self.selected}
        self.status.configure(text="Contour contrôlé, raccordé et converti en profil fermé.")
        self._render()

    def _hatch_selected(self, preset: str = "custom") -> None:
        if len(self.selected_indices) != 1:
            messagebox.showinfo(
                "Hachures",
                "Sélectionnez exactement une forme ou un profil fermé.",
                parent=self,
            )
            return
        source = self.document.objects[next(iter(self.selected_indices))]
        outline = self._closed_outline(source)
        if not outline:
            messagebox.showwarning(
                "Hachures",
                "L’objet sélectionné n’est pas un contour fermé.",
                parent=self,
            )
            return
        presets = {
            "steel": (3.0, (45.0,)),
            "aluminium": (5.0, (45.0,)),
            "cast_iron": (5.0, (45.0,)),
            "cross": (4.0, (45.0, 135.0)),
            "vertical": (3.0, (90.0,)),
        }
        if preset == "custom":
            spacing_mm = ask_number(self, "Hachures personnalisées", "Espacement des hachures (mm) :", 3.0, minimum=0.3)
            if spacing_mm is None:
                return
            angle = ask_number(self, "Hachures personnalisées", "Angle des hachures (degrés) :", 45.0)
            if angle is None:
                return
            angles = (angle,)
        else:
            spacing_mm, angles = presets[preset]
        if preset == "aluminium":
            pair_gap = 1.0 * 72 / 25.4
            repeat = spacing_mm * 72 / 25.4
            segments = [
                segment
                for shift in (0.0, pair_gap)
                for angle in angles
                for segment in hatch_segments(outline, repeat, angle, shift)
            ]
        else:
            segments = [
                segment
                for angle in angles
                for segment in hatch_segments(outline, spacing_mm * 72 / 25.4, angle)
            ]
        if not segments:
            messagebox.showwarning("Hachures", "Aucune hachure ne peut être créée.", parent=self)
            return
        self._checkpoint()
        group = source.group or uuid.uuid4().hex
        source.group = group
        new_indices = {next(iter(self.selected_indices))}
        for segment in segments:
            hatch = PageObject(
                "line",
                source.page,
                segment.x1,
                segment.y1,
                segment.x2 - segment.x1,
                segment.y2 - segment.y1,
                pages=source.pages,
                group=group,
                source_id=source.object_id,
                shape="hatch",
                border_color=source.border_color,
                border_width=max(0.5, source.border_width * 0.65),
            )
            self.document.objects.append(hatch)
            new_indices.add(len(self.document.objects) - 1)
        self.selected_indices = new_indices
        self.selected = max(new_indices)
        self.status.configure(text=f"{len(segments)} hachure(s) créée(s) et assemblée(s) au contour.")
        self._render()

    def _remove_selected_hatches(self) -> None:
        if not self.selected_indices:
            self.status.configure(text="Sélectionnez une forme hachurée ou l’une de ses hachures.")
            return
        selected_objects = [self.document.objects[index] for index in self.selected_indices]
        group_ids = {item.group for item in selected_objects if item.group}
        source_ids = {
            item.source_id for item in selected_objects if item.shape == "hatch" and item.source_id
        } | {
            item.object_id for item in selected_objects if item.kind != "line"
        }
        explicit = {
            index
            for index, item in enumerate(self.document.objects)
            if item.shape == "hatch"
            and (item.source_id in source_ids or (item.group and item.group in group_ids))
        }
        legacy: set[int] = set()
        for group_id in group_ids:
            members = [
                (index, item)
                for index, item in enumerate(self.document.objects)
                if item.group == group_id
            ]
            has_closed_source = any(
                self._closed_outline(item)
                for _index, item in members
                if item.kind != "line"
            )
            legacy_line_only_hatch = (
                len(members) >= 3
                and all(item.kind == "line" for _index, item in members)
                and all(not item.shape and not item.source_id for _index, item in members)
            )
            if has_closed_source or legacy_line_only_hatch:
                legacy.update(
                    index
                    for index, item in members
                    if item.kind == "line" and not item.shape
                )
        to_delete = explicit | legacy
        if not to_delete:
            self.status.configure(text="Aucune hachure associée à cette sélection.")
            return
        self._checkpoint()
        for index in sorted(to_delete, reverse=True):
            del self.document.objects[index]
        for item in self.document.objects:
            if item.group in group_ids and not any(
                candidate.group == item.group and candidate.shape == "hatch"
                for candidate in self.document.objects
            ):
                item.group = ""
        self.selected = None
        self.selected_indices.clear()
        self.status.configure(text=f"{len(to_delete)} hachure(s) supprimée(s) en une seule opération.")
        self._render()

    def _chamfer_selected(self) -> None:
        indices = sorted(self.selected_indices)
        if len(indices) != 2 or any(
            self.document.objects[index].kind != "line" for index in indices
        ):
            messagebox.showinfo(
                "Chanfrein",
                "Sélectionnez exactement deux traits non parallèles.",
                parent=self,
            )
            return
        distance_mm = ask_number(self, "Chanfrein", "Longueur du retrait sur chaque trait (mm) :", 5.0, minimum=0.1)
        if distance_mm is None:
            return
        sources = [self.document.objects[index] for index in indices]
        result = chamfer_segments(
            Segment(sources[0].x, sources[0].y, sources[0].x + sources[0].width, sources[0].y + sources[0].height),
            Segment(sources[1].x, sources[1].y, sources[1].x + sources[1].width, sources[1].y + sources[1].height),
            distance_mm * 72 / 25.4,
        )
        if result is None:
            messagebox.showwarning(
                "Chanfrein",
                "Impossible de créer ce chanfrein : traits parallèles, trop courts ou retrait trop grand.",
                parent=self,
            )
            return
        self._checkpoint()
        for index, segment in zip(indices, result[:2]):
            item = self.document.objects[index]
            item.x, item.y = segment.x1, segment.y1
            item.width, item.height = segment.x2 - segment.x1, segment.y2 - segment.y1
        connector = copy.deepcopy(sources[0])
        connector.object_id = uuid.uuid4().hex
        connector.group = ""
        connector.x, connector.y = result[2].x1, result[2].y1
        connector.width = result[2].x2 - result[2].x1
        connector.height = result[2].y2 - result[2].y1
        self.document.objects.append(connector)
        self.selected_indices = {*indices, len(self.document.objects) - 1}
        self.selected = len(self.document.objects) - 1
        self.status.configure(text=f"Chanfrein de {distance_mm:g} mm créé en trois segments indépendants.")
        self._render()

    def _treat_shape_corner(self) -> None:
        if len(self.selected_indices) != 1:
            messagebox.showinfo(
                "Traitement d’un coin",
                "Sélectionnez exactement un rectangle, une forme ou un profil fermé.",
                parent=self,
            )
            return
        index = next(iter(self.selected_indices))
        selected = self.document.objects[index]
        selected_points = (
            [(selected.x + x, selected.y + y) for x, y in selected.points]
            if selected.kind == "polyline"
            else self._closed_outline(selected)
        )
        if len(selected_points) < 3:
            messagebox.showwarning(
                "Traitement d’un coin",
                "L’objet sélectionné doit être une forme ou une polyligne possédant au moins trois sommets.",
                parent=self,
            )
            return
        treatment = ask_text(self, "Traitement d’un coin", "Tapez C pour un chanfrein ou A pour un arrondi :", "C")
        if not treatment:
            return
        treatment = "round" if treatment.strip().lower().startswith("a") else "chamfer"
        distance_mm = ask_number(self, "Traitement d’un coin", "Rayon ou retrait (mm) :", 5.0, minimum=0.1)
        if distance_mm is None:
            return
        self._pending_corner_treatment = (index, treatment, distance_mm * 72 / 25.4)
        self.canvas.configure(cursor="crosshair")
        self.status.configure(
            text="Cliquez maintenant sur le coin à modifier. Échap annule l’opération."
        )

    def _apply_corner_treatment(self, page_x: float, page_y: float) -> None:
        pending = self._pending_corner_treatment
        if pending is None:
            return
        index, treatment, distance = pending
        if index >= len(self.document.objects):
            return
        source = self.document.objects[index]
        outline = (
            [(source.x + x, source.y + y) for x, y in source.points]
            if source.kind == "polyline"
            else self._closed_outline(source)
        )
        closed = bool(outline and math.dist(outline[0], outline[-1]) <= 1e-6)
        if closed:
            outline.pop()
        if len(outline) < 3:
            return
        corner_index = min(
            range(len(outline)),
            key=lambda position: math.dist(outline[position], (page_x, page_y)),
        )
        if not closed and corner_index in {0, len(outline) - 1}:
            messagebox.showwarning(
                "Traitement d’un coin",
                "Choisissez un sommet intermédiaire : une extrémité ouverte ne possède pas deux côtés.",
                parent=self,
            )
            return
        previous = outline[(corner_index - 1) % len(outline)]
        corner = outline[corner_index]
        following = outline[(corner_index + 1) % len(outline)]
        before_length = math.dist(previous, corner)
        after_length = math.dist(corner, following)
        if min(before_length, after_length) <= distance * 1.05:
            messagebox.showwarning(
                "Traitement d’un coin",
                "Le rayon ou le retrait est trop grand pour les côtés de ce coin.",
                parent=self,
            )
            return
        before = (
            corner[0] + (previous[0] - corner[0]) * distance / before_length,
            corner[1] + (previous[1] - corner[1]) * distance / before_length,
        )
        after = (
            corner[0] + (following[0] - corner[0]) * distance / after_length,
            corner[1] + (following[1] - corner[1]) * distance / after_length,
        )
        replacement = [before, after]
        if treatment == "round":
            replacement = []
            for step in range(7):
                ratio = step / 6
                inverse = 1 - ratio
                replacement.append(
                    (
                        inverse * inverse * before[0]
                        + 2 * inverse * ratio * corner[0]
                        + ratio * ratio * after[0],
                        inverse * inverse * before[1]
                        + 2 * inverse * ratio * corner[1]
                        + ratio * ratio * after[1],
                    )
                )
        path = [*outline[:corner_index], *replacement, *outline[corner_index + 1 :]]
        if closed:
            path.append(path[0])
        result = self._polyline_from_path(source, path)
        result.object_id = source.object_id
        result.group = source.group
        result.pages = source.pages
        result.fill = source.fill
        self._checkpoint()
        self.document.objects[index] = result
        self.selected = index
        self.selected_indices = {index}
        label = "Arrondi" if treatment == "round" else "Chanfrein"
        self.status.configure(
            text=f"{label} appliqué. Le mode reste actif : cliquez sur un autre coin, ou Échap pour terminer."
        )
        self._render()
        self.canvas.configure(cursor="crosshair")

    def _snap_profile_to_axis(self) -> None:
        indices = sorted(self.selected_indices)
        if len(indices) != 2:
            messagebox.showinfo(
                "Ajuster le profil à l’axe",
                "Sélectionnez avec Ctrl une polyligne ouverte et un trait d’axe.",
                parent=self,
            )
            return
        axis_index = next(
            (
                index
                for index in indices
                if self.document.objects[index].kind == "line"
                and self.document.objects[index].shape == "axis"
            ),
            None,
        )
        profile_index = next(
            (index for index in indices if self.document.objects[index].kind == "polyline"),
            None,
        )
        if axis_index is None or profile_index is None:
            messagebox.showwarning(
                "Ajuster le profil à l’axe",
                "La sélection doit contenir une polyligne ouverte et un trait créé avec le bouton Axe.",
                parent=self,
            )
            return
        profile = self.document.objects[profile_index]
        absolute = [(profile.x + x, profile.y + y) for x, y in profile.points]
        if len(absolute) < 2 or math.dist(absolute[0], absolute[-1]) <= 1e-6:
            messagebox.showwarning(
                "Ajuster le profil à l’axe",
                "Le profil doit être une polyligne ouverte.",
                parent=self,
            )
            return
        axis_item = self.document.objects[axis_index]
        axis = Segment(
            axis_item.x,
            axis_item.y,
            axis_item.x + axis_item.width,
            axis_item.y + axis_item.height,
        )
        first_projection = project_point_onto_line(*absolute[0], axis)
        last_projection = project_point_onto_line(*absolute[-1], axis)
        if math.dist(first_projection, absolute[0]) > 1e-6:
            absolute.insert(0, first_projection)
        if math.dist(last_projection, absolute[-1]) > 1e-6:
            absolute.append(last_projection)
        result = self._polyline_from_path(profile, absolute)
        result.object_id = profile.object_id
        result.group = profile.group
        result.pages = profile.pages
        self._checkpoint()
        self.document.objects[profile_index] = result
        self.selected_indices = {axis_index, profile_index}
        self.selected = profile_index
        self.status.configure(
            text="Deux raccords perpendiculaires ont été ajoutés jusqu’à l’axe sans déformer le profil. Utilisez “Symétrie axe + copie”."
        )
        self._render()

    def _object_edges(self, item: PageObject) -> list[Segment]:
        if item.kind == "line":
            return [Segment(item.x, item.y, item.x + item.width, item.y + item.height)]
        points = (
            [(item.x + x, item.y + y) for x, y in item.points]
            if item.kind == "polyline"
            else self._closed_outline(item)
        )
        return [Segment(*start, *end) for start, end in pairwise(points)]

    def _selected_profile_and_axis(self) -> tuple[int, int] | None:
        indices = expanded_group_indices(self.document.objects, self.selected_indices)
        axis_indices = [
            index
            for index in indices
            if self.document.objects[index].kind == "line"
            and self.document.objects[index].shape == "axis"
        ]
        profile_indices = [
            index
            for index in indices
            if self.document.objects[index].kind in {"polyline", "shape"}
        ]
        if len(axis_indices) == 1 and len(profile_indices) == 1:
            return profile_indices[0], axis_indices[0]
        messagebox.showinfo(
            "Profil de révolution",
            "Sélectionnez exactement un profil et un axe avec Ctrl.",
            parent=self,
        )
        return None

    def _place_axis_on_profile_base(self) -> None:
        selection = self._selected_profile_and_axis()
        if selection is None:
            return
        profile_index, axis_index = selection
        profile = self.document.objects[profile_index]
        axis = self.document.objects[axis_index]
        if abs(axis.height) > max(1.0, abs(axis.width) * 0.02):
            messagebox.showwarning(
                "Axe du profil",
                "Cette commande attend un axe horizontal.",
                parent=self,
            )
            return
        horizontal_edges = [
            edge
            for edge in self._object_edges(profile)
            if abs(edge.y2 - edge.y1) <= max(1.0, abs(edge.x2 - edge.x1) * 0.02)
        ]
        if not horizontal_edges:
            messagebox.showwarning(
                "Axe du profil",
                "Aucun fond horizontal n’a été trouvé sur ce profil.",
                parent=self,
            )
            return
        base = max(horizontal_edges, key=lambda edge: (edge.y1 + edge.y2) / 2)
        target_y = (base.y1 + base.y2) / 2
        self._checkpoint()
        axis.y = target_y
        axis.height = 0
        axis.locked = True
        self._coincident_edge_highlight = Segment(base.x1, target_y, base.x2, target_y)
        self.status.configure(
            text="BIM : l’axe est confondu avec le fond du profil et verrouillé pour la révolution 3D."
        )
        self._render()

    def _start_work_origin(self) -> None:
        self._placing_work_origin = True
        self.canvas.configure(cursor="crosshair")
        self.status.configure(
            text="Cliquez le point qui deviendra X0 / Z0. Le point s’aimante aux sommets et aux axes proches."
        )

    def _place_work_origin(self, page_x: float, page_y: float) -> None:
        candidates: list[tuple[float, float]] = []
        axes: list[Segment] = []
        for item in self.document.objects:
            if item.page != self.current_page and item.pages != "all":
                continue
            if item.kind == "origin":
                continue
            for edge in self._object_edges(item):
                candidates.extend(((edge.x1, edge.y1), (edge.x2, edge.y2)))
                if item.kind == "line" and item.shape == "axis":
                    axes.append(edge)
        tolerance = max(6.0, 12.0 / max(self.zoom, 0.1))
        if candidates:
            nearest = min(candidates, key=lambda point: math.dist(point, (page_x, page_y)))
            if math.dist(nearest, (page_x, page_y)) <= tolerance:
                page_x, page_y = nearest
        if axes:
            axis = min(axes, key=lambda edge: point_to_segment_distance(page_x, page_y, edge))
            if point_to_segment_distance(page_x, page_y, axis) <= tolerance:
                page_x, page_y = project_point_onto_line(page_x, page_y, axis)
        self._checkpoint()
        self.document.objects = [
            item
            for item in self.document.objects
            if not (item.kind == "origin" and item.page == self.current_page)
        ]
        origin = PageObject("origin", self.current_page, page_x, page_y, 0, 0)
        self.document.objects.append(origin)
        self.selected = len(self.document.objects) - 1
        self.selected_indices = {self.selected}
        self._placing_work_origin = False
        self.canvas.configure(cursor="")
        self.status.configure(
            text="Origine pièce X0 / Z0 placée. Elle servira au futur calcul du parcours et du G-code."
        )
        self._render()

    def _show_revolution_preview(self) -> None:
        indices = expanded_group_indices(self.document.objects, self.selected_indices)
        axis_indices = [
            index
            for index in indices
            if self.document.objects[index].kind == "line"
            and self.document.objects[index].shape == "axis"
        ]
        profile_indices = [
            index for index in indices if self.document.objects[index].kind in {"polyline", "shape"}
        ]
        if len(axis_indices) != 1 or not profile_indices:
            messagebox.showinfo(
                "Aperçu 3D",
                "Sélectionnez l’axe et un demi-profil, ou l’axe et les deux moitiés symétriques.",
                parent=self,
            )
            return
        axis = self.document.objects[axis_indices[0]]
        if abs(axis.height) > max(1.0, abs(axis.width) * 0.02):
            messagebox.showwarning(
                "Aperçu 3D",
                "La première version de l’aperçu attend un axe horizontal.",
                parent=self,
            )
            return
        outlines = [self._closed_outline(self.document.objects[index]) for index in profile_indices]
        expected_y, mode = self._expected_revolution_axis(profile_indices, axis.y)
        tolerance = max(1.5, (max(y for outline in outlines for _x, y in outline) - min(y for outline in outlines for _x, y in outline)) * 0.01)
        if abs(axis.y - expected_y) > tolerance:
            messagebox.showerror(
                "Axe de révolution invalide",
                f"L’axe a été déplacé et ne correspond plus au {mode} du profil.\n\n"
                "Utilisez Profil ▾ → Valider et verrouiller l’axe 3D avant de générer la vue.",
                parent=self,
            )
            return
        try:
            stations = revolution_stations(outlines, axis.y)
        except ValueError:
            messagebox.showwarning(
                "Aperçu 3D",
                "Le profil ne contient pas assez de points pour créer une révolution.",
                parent=self,
            )
            return
        RevolutionPreview(self, stations)

    def _expected_revolution_axis(
        self, profile_indices: list[int], current_axis_y: float
    ) -> tuple[float, str]:
        profiles = [self.document.objects[index] for index in profile_indices]
        outlines = [self._closed_outline(profile) for profile in profiles]
        full_profile = len(profiles) > 1 or any(
            profile.shape == "revolution_full" for profile in profiles
        )
        return revolution_axis_target(
            outlines,
            full_profile=full_profile,
            current_axis_y=current_axis_y,
        )

    def _validate_and_lock_revolution_axis(self) -> None:
        indices = expanded_group_indices(self.document.objects, self.selected_indices)
        axis_indices = [
            index
            for index in indices
            if self.document.objects[index].kind == "line"
            and self.document.objects[index].shape == "axis"
        ]
        profile_indices = [
            index for index in indices if self.document.objects[index].kind in {"polyline", "shape"}
        ]
        if len(axis_indices) != 1 or not profile_indices:
            messagebox.showinfo(
                "Verrouiller l’axe 3D",
                "Sélectionnez le profil et son axe avec Ctrl.",
                parent=self,
            )
            return
        axis = self.document.objects[axis_indices[0]]
        if abs(axis.height) > max(1.0, abs(axis.width) * 0.02):
            messagebox.showwarning(
                "Verrouiller l’axe 3D",
                "L’axe de révolution doit être horizontal.",
                parent=self,
            )
            return
        target_y, mode = self._expected_revolution_axis(profile_indices, axis.y)
        self._checkpoint()
        axis.y = target_y
        axis.height = 0
        axis.locked = True
        self.status.configure(
            text=f"Axe 3D recalé sur le {mode} et verrouillé. La révolution est maintenant sécurisée."
        )
        self._render()

    def _center_revolution_axis(self) -> None:
        """Force an axis onto the mid-plane of a complete revolution profile."""
        indices = expanded_group_indices(self.document.objects, self.selected_indices)
        axis_indices = [
            index
            for index in indices
            if self.document.objects[index].kind == "line"
            and self.document.objects[index].shape == "axis"
        ]
        profile_indices = [
            index for index in indices if self.document.objects[index].kind in {"polyline", "shape"}
        ]
        if len(axis_indices) != 1 or not profile_indices:
            messagebox.showinfo(
                "Recentrer l’axe",
                "Sélectionnez le profil complet et son axe avec Ctrl.",
                parent=self,
            )
            return
        axis = self.document.objects[axis_indices[0]]
        if abs(axis.height) > max(1.0, abs(axis.width) * 0.02):
            messagebox.showwarning(
                "Recentrer l’axe",
                "L’axe de révolution doit être horizontal.",
                parent=self,
            )
            return
        outlines = [self._closed_outline(self.document.objects[index]) for index in profile_indices]
        target_y, _mode = revolution_axis_target(
            outlines,
            full_profile=True,
            current_axis_y=axis.y,
        )
        self._checkpoint()
        axis.y = target_y
        axis.height = 0
        axis.locked = True
        self.status.configure(
            text="Axe replacé exactement à mi-hauteur du profil complet et verrouillé."
        )
        self._render()

    def _unlock_revolution_axis(self) -> None:
        axes = [
            self.document.objects[index]
            for index in self.selected_indices
            if self.document.objects[index].kind == "line"
            and self.document.objects[index].shape == "axis"
        ]
        if len(axes) != 1:
            messagebox.showinfo(
                "Déverrouiller l’axe",
                "Sélectionnez un seul axe de révolution.",
                parent=self,
            )
            return
        self._checkpoint()
        axes[0].locked = False
        self.status.configure(text="Axe déverrouillé : il peut de nouveau être déplacé.")
        self._render()

    def _merge_mirrored_profiles(self) -> None:
        indices = expanded_group_indices(self.document.objects, self.selected_indices)
        axis_indices = [
            index
            for index in indices
            if self.document.objects[index].kind == "line"
            and self.document.objects[index].shape == "axis"
        ]
        profile_indices = [
            index for index in indices if self.document.objects[index].kind == "polyline"
        ]
        if len(axis_indices) != 1 or len(profile_indices) != 2:
            messagebox.showinfo(
                "Fusion des profils symétriques",
                "Sélectionnez les deux demi-profils et leur axe avec Ctrl.",
                parent=self,
            )
            return
        axis = self.document.objects[axis_indices[0]]
        if abs(axis.height) > max(1.0, abs(axis.width) * 0.02):
            messagebox.showwarning(
                "Fusion des profils symétriques",
                "Cette commande attend un axe horizontal.",
                parent=self,
            )
            return
        profiles = [self.document.objects[index] for index in profile_indices]
        outlines = [self._closed_outline(profile) for profile in profiles]
        try:
            contour = merge_mirrored_outlines(outlines, axis.y)
        except ValueError:
            messagebox.showwarning(
                "Fusion des profils symétriques",
                "Les deux moitiés doivent se rejoindre exactement aux mêmes extrémités sur l’axe.",
                parent=self,
            )
            return
        left = min(x for x, _y in contour)
        top = min(y for _x, y in contour)
        right = max(x for x, _y in contour)
        bottom = max(y for _x, y in contour)
        source = profiles[0]
        merged = PageObject(
            "polyline",
            self.current_page,
            left,
            top,
            right - left,
            bottom - top,
            points=[[x - left, y - top] for x, y in contour],
            fill=source.fill,
            border_color=source.border_color,
            border_width=source.border_width,
            border_style=source.border_style,
            shape="revolution_full",
        )
        self._checkpoint()
        for index in sorted(profile_indices, reverse=True):
            del self.document.objects[index]
        self.document.objects.append(merged)
        axis_index = self.document.objects.index(axis)
        profile_index = len(self.document.objects) - 1
        self.selected_indices = {axis_index, profile_index}
        self.selected = profile_index
        self.status.configure(
            text="Les deux moitiés forment maintenant un contour extérieur unique ; le trait intérieur sur l’axe a été supprimé."
        )
        self._render()

    def _merge_rectangles_as_profile(self) -> None:
        indices = sorted(self.selected_indices)
        if len(indices) != 2 or any(
            self.document.objects[index].kind != "shape"
            or self.document.objects[index].shape not in {"", "rectangle"}
            for index in indices
        ):
            messagebox.showinfo(
                "Fusionner en profil",
                "Sélectionnez exactement deux rectangles qui se touchent ou se chevauchent.",
                parent=self,
            )
            return
        rectangles = []
        for index in indices:
            item = self.document.objects[index]
            rectangles.append(
                (
                    min(item.x, item.x + item.width),
                    min(item.y, item.y + item.height),
                    max(item.x, item.x + item.width),
                    max(item.y, item.y + item.height),
                )
            )
        try:
            contour = union_axis_aligned_rectangles(rectangles)
        except ValueError:
            messagebox.showwarning(
                "Fusionner en profil",
                "Les deux rectangles doivent former un seul contour continu.",
                parent=self,
            )
            return
        left = min(point[0] for point in contour)
        top = min(point[1] for point in contour)
        right = max(point[0] for point in contour)
        bottom = max(point[1] for point in contour)
        first = self.document.objects[indices[0]]
        profile = PageObject(
            "polyline",
            self.current_page,
            left,
            top,
            right - left,
            bottom - top,
            points=[[x - left, y - top] for x, y in contour],
            fill=first.fill,
            border_color=first.border_color,
            border_width=max(1.0, first.border_width),
        )
        self._checkpoint()
        for index in reversed(indices):
            del self.document.objects[index]
        self.document.objects.append(profile)
        self.selected = len(self.document.objects) - 1
        self.selected_indices = {self.selected}
        self._coincident_edge_highlight = None
        self.status.configure(
            text="Les deux rectangles forment maintenant un profil unique. Utilisez Profil ▾ → Chanfrein ou arrondi sur des coins."
        )
        self._render()

    def _snap_selected_edges(self) -> None:
        indices = sorted(self.selected_indices)
        if len(indices) != 2:
            messagebox.showinfo(
                "Bords confondus",
                "Sélectionnez exactement deux formes ou traits. Sélectionnez d’abord l’objet fixe, puis ajoutez l’objet à déplacer avec Ctrl.",
                parent=self,
            )
            return
        moving_index = (
            self._last_clicked_index
            if self._last_clicked_index in self.selected_indices
            else indices[1]
        )
        fixed_index = next(index for index in indices if index != moving_index)
        fixed = self.document.objects[fixed_index]
        moving = self.document.objects[moving_index]
        if not self._object_edges(fixed) or not self._object_edges(moving):
            messagebox.showwarning(
                "Bords confondus",
                "Ces objets ne possèdent pas de bord utilisable.",
                parent=self,
            )
            return
        self._pending_edge_snap = {
            "fixed": fixed_index,
            "moving": moving_index,
            "stage": "fixed",
            "fixed_edge": None,
        }
        self._coincident_edge_highlight = None
        self.canvas.configure(cursor="crosshair")
        self.status.configure(
            text="Bords confondus 1/2 : cliquez le bord de référence de l’objet fixe. Échap annule."
        )
        self._render()

    def _nearest_object_edge(
        self, item: PageObject, page_x: float, page_y: float
    ) -> Segment | None:
        edges = self._object_edges(item)
        if not edges:
            return None
        edge = min(
            edges,
            key=lambda candidate: point_to_segment_distance(page_x, page_y, candidate),
        )
        tolerance = max(6.0, 12.0 / max(self.zoom, 0.1))
        if point_to_segment_distance(page_x, page_y, edge) > tolerance:
            return None
        return edge

    def _choose_edge_for_snap(self, page_x: float, page_y: float) -> None:
        pending = self._pending_edge_snap
        if pending is None:
            return
        fixed_index = int(pending["fixed"])
        moving_index = int(pending["moving"])
        if max(fixed_index, moving_index) >= len(self.document.objects):
            self._cancel_current_action()
            return
        if pending["stage"] == "fixed":
            fixed_edge = self._nearest_object_edge(
                self.document.objects[fixed_index], page_x, page_y
            )
            if fixed_edge is None:
                self.status.configure(
                    text="Cliquez plus près du bord voulu sur l’objet fixe."
                )
                return
            pending["fixed_edge"] = fixed_edge
            pending["stage"] = "moving"
            self.status.configure(
                text="Bords confondus 2/2 : cliquez maintenant le bord de l’objet mobile."
            )
            self._render()
            return

        fixed_edge = pending.get("fixed_edge")
        moving_edge = self._nearest_object_edge(
            self.document.objects[moving_index], page_x, page_y
        )
        if not isinstance(fixed_edge, Segment) or moving_edge is None:
            self.status.configure(
                text="Cliquez plus près du bord voulu sur l’objet mobile."
            )
            return
        try:
            delta_x, delta_y = edge_coincidence_translation(fixed_edge, moving_edge)
        except ValueError:
            self.status.configure(
                text="Ces deux bords ne sont pas parallèles. Cliquez un autre bord mobile."
            )
            return
        self._checkpoint()
        moving = self.document.objects[moving_index]
        moving.x += delta_x
        moving.y += delta_y
        self._coincident_edge_highlight = Segment(
            moving_edge.x1 + delta_x,
            moving_edge.y1 + delta_y,
            moving_edge.x2 + delta_x,
            moving_edge.y2 + delta_y,
        )
        self._pending_edge_snap = None
        self.canvas.configure(cursor="")
        self.status.configure(
            text="BIM : les deux bords choisis sont confondus. Seul l’objet mobile a été déplacé."
        )
        self._render()

    def _start_driving_dimension(self) -> None:
        indices = sorted(self.selected_indices)
        if len(indices) != 2:
            messagebox.showinfo(
                "Cote pilotante",
                "Sélectionnez deux objets : d’abord la référence fixe, puis l’objet à déplacer avec Ctrl.",
                parent=self,
            )
            return
        moving_index = (
            self._last_clicked_index
            if self._last_clicked_index in self.selected_indices
            else indices[1]
        )
        fixed_index = next(index for index in indices if index != moving_index)
        if not self._object_edges(self.document.objects[fixed_index]) or not self._object_edges(
            self.document.objects[moving_index]
        ):
            messagebox.showwarning(
                "Cote pilotante",
                "Ces objets ne possèdent pas de bord utilisable.",
                parent=self,
            )
            return
        self._pending_driving_dimension = {
            "fixed": fixed_index,
            "moving": moving_index,
            "stage": "fixed",
            "fixed_edge": None,
        }
        self._coincident_edge_highlight = None
        self.canvas.configure(cursor="crosshair")
        self.status.configure(
            text="Cote pilotante 1/2 : cliquez le bord ou l’axe de référence fixe."
        )
        self._render()

    def _choose_edge_for_driving_dimension(
        self, page_x: float, page_y: float
    ) -> None:
        pending = self._pending_driving_dimension
        if pending is None:
            return
        fixed_index = int(pending["fixed"])
        moving_index = int(pending["moving"])
        if max(fixed_index, moving_index) >= len(self.document.objects):
            self._cancel_current_action()
            return
        if pending["stage"] == "fixed":
            fixed_edge = self._nearest_object_edge(
                self.document.objects[fixed_index], page_x, page_y
            )
            if fixed_edge is None:
                self.status.configure(text="Cliquez plus près du bord fixe voulu.")
                return
            pending["fixed_edge"] = fixed_edge
            pending["stage"] = "moving"
            self.status.configure(
                text="Cote pilotante 2/2 : cliquez le bord de l’objet qui doit se déplacer."
            )
            self._render()
            return

        fixed_edge = pending.get("fixed_edge")
        moving_edge = self._nearest_object_edge(
            self.document.objects[moving_index], page_x, page_y
        )
        if not isinstance(fixed_edge, Segment) or moving_edge is None:
            self.status.configure(text="Cliquez plus près du bord mobile voulu.")
            return
        fixed_dx = fixed_edge.x2 - fixed_edge.x1
        fixed_dy = fixed_edge.y2 - fixed_edge.y1
        moving_dx = moving_edge.x2 - moving_edge.x1
        moving_dy = moving_edge.y2 - moving_edge.y1
        fixed_length = math.hypot(fixed_dx, fixed_dy)
        moving_length = math.hypot(moving_dx, moving_dy)
        parallel_error = (
            abs(fixed_dx * moving_dy - fixed_dy * moving_dx)
            / (fixed_length * moving_length)
            if min(fixed_length, moving_length) > 1e-8
            else 1.0
        )
        if parallel_error > 0.02:
            self.status.configure(
                text="Une cote de distance nécessite deux bords parallèles. Choisissez un autre bord."
            )
            return
        distance_mm = ask_number(self, "Cote pilotante", "Distance entre les deux bords (mm) :", 10.0, minimum=0.0)
        if distance_mm is None:
            return
        moving = self.document.objects[moving_index]
        moving_center = (moving.x + moving.width / 2, moving.y + moving.height / 2)
        delta_x, delta_y, dimension_start, final_middle = (
            driving_dimension_translation(
                fixed_edge,
                moving_edge,
                moving_center,
                distance_mm * 72 / 25.4,
            )
        )

        self._checkpoint()
        moving.x += delta_x
        moving.y += delta_y
        dimension = PageObject(
            "dimension",
            self.current_page,
            dimension_start[0],
            dimension_start[1],
            final_middle[0] - dimension_start[0],
            final_middle[1] - dimension_start[1],
            text=f"{distance_mm:g}",
            border_color="#284F7A",
            border_width=1.0,
            points=[list(dimension_start), list(final_middle)],
        )
        self.document.objects.append(dimension)
        self._pending_driving_dimension = None
        self.canvas.configure(cursor="")
        self.selected = moving_index
        self.selected_indices = {moving_index}
        self.status.configure(
            text=f"Cote pilotante appliquée : {distance_mm:g} mm. L’objet mobile a été repositionné."
        )
        self._render()

    def _explain_marquee_selection(self) -> None:
        self.canvas.configure(cursor="crosshair")
        self.status.configure(
            text="Sélection par zone : cliquez dans un espace vide puis entourez les objets. Ctrl ajoute à la sélection."
        )

    def _rotate_selected(self, direction: int = 1) -> None:
        if not self.selected_indices:
            return
        try:
            degrees = float(self.rotation_step_var.get().replace(",", ".")) * direction
        except ValueError:
            degrees = 15.0 * direction
        self._rotate_selected_degrees(degrees)

    def _rotate_selected_degrees(self, degrees: float) -> None:
        if not self.selected_indices:
            return
        if getattr(self, "_editing_widget", None) is not None:
            self._commit_inline_editor(render=False)
        indices = expanded_group_indices(self.document.objects, self.selected_indices)
        objects = [self.document.objects[index] for index in indices]
        left, top, width, height = objects_bounds(objects)
        assembly_pivot = (left + width / 2, top + height / 2)
        self._checkpoint()
        for index in indices:
            item = self.document.objects[index]
            if item.kind == "image":
                try:
                    with Image.open(item.image_path) as source:
                        rotated = source.rotate(-degrees, expand=True, resample=Image.Resampling.BICUBIC)
                    self._replace_image_pixels(item, rotated)
                except OSError:
                    pass
            pivot = assembly_pivot if item.group else (
                item.x + item.width / 2,
                item.y + item.height / 2,
            )
            self._rotate_item_about(item, degrees, pivot)
        self.selected_indices = indices
        self.selected = min(indices)
        self._render()

    def _rotate_item_about(
        self, item: PageObject, degrees: float, pivot: tuple[float, float]
    ) -> None:
        """Rotate one object about a shared pivot, preserving an assembled hatch group."""
        if item.kind == "line":
            start = self._rotate_point_about((item.x, item.y), pivot, degrees)
            end = self._rotate_point_about(
                (item.x + item.width, item.y + item.height), pivot, degrees
            )
            item.x, item.y = start
            item.width, item.height = end[0] - start[0], end[1] - start[1]
            item.rotation = round((item.rotation + degrees) % 360)
            return
        if item.kind == "polyline" and item.points:
            absolute = [
                self._rotate_point_about((item.x + x, item.y + y), pivot, degrees)
                for x, y in item.points
            ]
            left = min(point[0] for point in absolute)
            top = min(point[1] for point in absolute)
            item.x, item.y = left, top
            item.width = max(point[0] for point in absolute) - left
            item.height = max(point[1] for point in absolute) - top
            item.points = [[x - left, y - top] for x, y in absolute]
            item.rotation = round((item.rotation + degrees) % 360)
            return
        center = self._rotate_point_about(
            (item.x + item.width / 2, item.y + item.height / 2), pivot, degrees
        )
        if abs(degrees) % 180 == 90:
            item.width, item.height = item.height, item.width
        item.x, item.y = center[0] - item.width / 2, center[1] - item.height / 2
        item.rotation = 0 if item.kind == "image" else round((item.rotation + degrees) % 360)

    def _rotate_free(self) -> None:
        degrees = ask_number(self, "Rotation libre", "Angle de rotation en degrés :", 0.0)
        if degrees is not None:
            self._rotate_selected_degrees(degrees)

    @staticmethod
    def _rotate_point_about(
        point: tuple[float, float], pivot: tuple[float, float], degrees: float
    ) -> tuple[float, float]:
        angle = math.radians(degrees)
        cosine, sine = math.cos(angle), math.sin(angle)
        relative_x, relative_y = point[0] - pivot[0], point[1] - pivot[1]
        return (
            pivot[0] + relative_x * cosine - relative_y * sine,
            pivot[1] + relative_x * sine + relative_y * cosine,
        )

    def _rotated_copy_about(
        self, source: PageObject, degrees: float, pivot: tuple[float, float]
    ) -> PageObject:
        item = copy.deepcopy(source)
        item.object_id = uuid.uuid4().hex
        item.group = ""
        if item.kind == "line":
            start = self._rotate_point_about((item.x, item.y), pivot, degrees)
            end = self._rotate_point_about((item.x + item.width, item.y + item.height), pivot, degrees)
            item.x, item.y = start
            item.width, item.height = end[0] - start[0], end[1] - start[1]
        elif item.kind == "polyline":
            absolute = [
                self._rotate_point_about((item.x + x, item.y + y), pivot, degrees)
                for x, y in item.points
            ]
            left = min(point[0] for point in absolute)
            top = min(point[1] for point in absolute)
            item.x, item.y = left, top
            item.width = max(point[0] for point in absolute) - left
            item.height = max(point[1] for point in absolute) - top
            item.points = [[x - left, y - top] for x, y in absolute]
        else:
            center = self._rotate_point_about(
                (item.x + item.width / 2, item.y + item.height / 2), pivot, degrees
            )
            item.x, item.y = center[0] - item.width / 2, center[1] - item.height / 2
            item.rotation = round((item.rotation + degrees) % 360)
        return item

    def _rotate_with_copy(self) -> None:
        if not self.selected_indices:
            return
        degrees = ask_number(self, "Rotation avec copie", "Décalage angulaire de la copie (degrés) :", 30.0)
        if degrees is None:
            return
        objects = [self.document.objects[index] for index in self.selected_indices]
        left, top, width, height = objects_bounds(objects)
        pivot = (left + width / 2, top + height / 2)
        if len(objects) == 1 and objects[0].kind == "line":
            pivot = (objects[0].x, objects[0].y)
        self._checkpoint()
        new_indices: set[int] = set()
        for source in objects:
            self.document.objects.append(self._rotated_copy_about(source, degrees, pivot))
            new_indices.add(len(self.document.objects) - 1)
        self.selected_indices = new_indices
        self.selected = min(new_indices)
        self.status.configure(text=f"Copie créée avec une rotation de {degrees:g}°.")
        self._render()

    def _repeat_rotation(self) -> None:
        if len(self.selected_indices) != 1:
            messagebox.showinfo("Répétition circulaire", "Sélectionnez un seul objet à répéter.", parent=self)
            return
        step = ask_number(self, "Répétition circulaire", "Pas angulaire entre les copies (degrés) :", 15.0, minimum=0.1)
        if step is None:
            return
        count_value = ask_number(self, "Répétition circulaire", "Nombre de copies à créer :", 5.0, minimum=1)
        if count_value is None:
            return
        count = max(1, round(count_value))
        source = self.document.objects[next(iter(self.selected_indices))]
        pivot = (source.x, source.y) if source.kind == "line" else (source.x + source.width / 2, source.y + source.height / 2)
        self._checkpoint()
        new_indices: set[int] = set()
        for number in range(1, count + 1):
            self.document.objects.append(self._rotated_copy_about(source, step * number, pivot))
            new_indices.add(len(self.document.objects) - 1)
        self.selected_indices = new_indices
        self.selected = min(new_indices)
        self.status.configure(text=f"{count} copie(s) créée(s), espacées de {step:g}°.")
        self._render()

    def _apply_absolute_angle(self) -> None:
        if not self.selected_indices:
            return
        try:
            target = float(self.angle_var.get().replace(",", "."))
        except ValueError:
            return
        if getattr(self, "_editing_widget", None) is not None:
            self._commit_inline_editor(render=False)
        self._checkpoint()
        for index in self.selected_indices:
            item = self.document.objects[index]
            delta = target - self._object_angle(item)
            if item.kind == "line":
                self._rotate_line(item, delta)
            elif item.kind == "polyline":
                self._rotate_polyline(item, delta)
            else:
                item.rotation = round(target % 360)
        self._render()

    def _set_absolute_angle_value(self, degrees: float) -> None:
        self.angle_var.set(f"{degrees:g}")
        self._apply_absolute_angle()

    def _ask_absolute_angle(self) -> None:
        current = 0.0
        if self.selected is not None:
            current = self._object_angle(self.document.objects[self.selected])
        degrees = ask_number(
            self, "Orientation exacte", "Angle absolu en degrés :", current,
        )
        if degrees is not None:
            self._set_absolute_angle_value(degrees)

    @staticmethod
    def _object_angle(item: PageObject) -> float:
        if item.kind == "line":
            return math.degrees(math.atan2(item.height, item.width)) % 360
        return float(item.rotation)

    @staticmethod
    def _rotate_line(item: PageObject, degrees: float) -> None:
        center_x, center_y = item.x + item.width / 2, item.y + item.height / 2
        length = math.hypot(item.width, item.height)
        angle = math.atan2(item.height, item.width) + math.radians(degrees)
        delta_x, delta_y = length * math.cos(angle), length * math.sin(angle)
        item.x, item.y = center_x - delta_x / 2, center_y - delta_y / 2
        item.width, item.height = delta_x, delta_y
        item.rotation = round(math.degrees(angle) % 360)

    @staticmethod
    def _rotate_polyline(item: PageObject, degrees: float) -> None:
        if not item.points:
            return
        center_x, center_y = item.x + item.width / 2, item.y + item.height / 2
        angle = math.radians(degrees)
        cosine, sine = math.cos(angle), math.sin(angle)
        rotated: list[tuple[float, float]] = []
        for point_x, point_y in item.points:
            absolute_x, absolute_y = item.x + point_x, item.y + point_y
            relative_x, relative_y = absolute_x - center_x, absolute_y - center_y
            rotated.append(
                (
                    center_x + relative_x * cosine - relative_y * sine,
                    center_y + relative_x * sine + relative_y * cosine,
                )
            )
        minimum_x = min(point[0] for point in rotated)
        minimum_y = min(point[1] for point in rotated)
        maximum_x = max(point[0] for point in rotated)
        maximum_y = max(point[1] for point in rotated)
        item.x, item.y = minimum_x, minimum_y
        item.width, item.height = maximum_x - minimum_x, maximum_y - minimum_y
        item.points = [[x - minimum_x, y - minimum_y] for x, y in rotated]
        item.rotation = round((item.rotation + degrees) % 360)

    def _mirror_selected(self, direction: str) -> None:
        if not self.selected_indices:
            return
        indices = expanded_group_indices(self.document.objects, self.selected_indices)
        self._checkpoint()
        objects = [self.document.objects[index] for index in indices]
        left = min(item.x for item in objects)
        right = max(item.x + item.width for item in objects)
        top = min(item.y for item in objects)
        bottom = max(item.y + item.height for item in objects)
        for item in objects:
            if direction == "horizontal":
                if item.kind == "line":
                    start_x = left + right - item.x
                    end_x = left + right - (item.x + item.width)
                    item.x = start_x
                    item.width = end_x - start_x
                    item.flip_horizontal = not item.flip_horizontal
                    continue
                item.x = left + right - item.x - item.width
                item.flip_horizontal = not item.flip_horizontal
                if item.kind == "polyline":
                    item.points = [[item.width - point[0], point[1]] for point in item.points]
                elif item.kind == "image":
                    try:
                        with Image.open(item.image_path) as source:
                            self._replace_image_pixels(item, ImageOps.mirror(source))
                        item.flip_horizontal = False
                    except OSError:
                        pass
            else:
                if item.kind == "line":
                    start_y = top + bottom - item.y
                    end_y = top + bottom - (item.y + item.height)
                    item.y = start_y
                    item.height = end_y - start_y
                    item.flip_vertical = not item.flip_vertical
                    continue
                item.y = top + bottom - item.y - item.height
                item.flip_vertical = not item.flip_vertical
                if item.kind == "polyline":
                    item.points = [[point[0], item.height - point[1]] for point in item.points]
                elif item.kind == "image":
                    try:
                        with Image.open(item.image_path) as source:
                            self._replace_image_pixels(item, ImageOps.flip(source))
                        item.flip_vertical = False
                    except OSError:
                        pass
        self._render()

    def _mirror_copy_about_axis(self) -> None:
        indices = sorted(
            expanded_group_indices(self.document.objects, self.selected_indices)
        )
        axis_indices = [
            index
            for index in indices
            if self.document.objects[index].kind == "line"
            and self.document.objects[index].shape == "axis"
        ]
        profile_indices = [index for index in indices if index not in axis_indices]
        if len(axis_indices) != 1 or not profile_indices:
            messagebox.showinfo(
                "Symétrie de révolution",
                "Avec Ctrl, sélectionnez un trait d’axe et les éléments du profil, puis relancez « Miroir + copie ».",
                parent=self,
            )
            return
        axis = self.document.objects[axis_indices[0]]
        axis_segment = Segment(axis.x, axis.y, axis.x + axis.width, axis.y + axis.height)
        if math.hypot(axis.width, axis.height) < 1e-8:
            messagebox.showerror(
                "Symétrie axiale",
                "Le trait d’axe doit avoir une longueur non nulle.",
                parent=self,
            )
            return
        self._checkpoint()
        copies: list[int] = []
        copied_groups: dict[str, str] = {}
        for index in profile_indices:
            source = self.document.objects[index]
            clone = self._reflected_copy(source, axis_segment)
            clone.object_id = uuid.uuid4().hex
            clone.flow_next_id = ""
            clone.source_id = ""
            clone.group = (
                copied_groups.setdefault(source.group, uuid.uuid4().hex)
                if source.group
                else ""
            )
            self.document.objects.append(clone)
            copies.append(len(self.document.objects) - 1)
        self.selected_indices = set(copies)
        self.selected = copies[-1]
        self.status.configure(
            text=f"Symétrie axiale créée : {len(copies)} élément(s) copiés perpendiculairement à l’axe."
        )
        self._render()

    def _reflected_copy(self, source: PageObject, axis: Segment) -> PageObject:
        if source.kind == "line":
            start = reflect_point_across_line(source.x, source.y, axis)
            end = reflect_point_across_line(
                source.x + source.width, source.y + source.height, axis
            )
            clone = copy.deepcopy(source)
            clone.x, clone.y = start
            clone.width, clone.height = end[0] - start[0], end[1] - start[1]
            clone.rotation = round(self._object_angle(clone))
            return clone
        outline = self._closed_outline(source)
        if source.kind == "polyline" and not outline:
            outline = [(source.x + x, source.y + y) for x, y in source.points]
        if outline:
            reflected = [reflect_point_across_line(x, y, axis) for x, y in outline]
            clone = self._polyline_from_path(source, reflected)
            clone.pages = source.pages
            return clone
        center_x = source.x + source.width / 2
        center_y = source.y + source.height / 2
        reflected_center = reflect_point_across_line(center_x, center_y, axis)
        clone = copy.deepcopy(source)
        clone.x = reflected_center[0] - source.width / 2
        clone.y = reflected_center[1] - source.height / 2
        clone.flip_horizontal = not source.flip_horizontal
        return clone

    def _apply_border_style(self) -> None:
        styles = {"Continu": "solid", "Pointillé": "dotted", "Tirets": "dashed"}
        self._mutate(lambda item: setattr(item, "border_style", styles[self.border_style_var.get()]))

    def _apply_border_width(self) -> None:
        try:
            width = max(0.0, min(20.0, float(self.border_width_var.get().replace(",", "."))))
        except ValueError:
            return
        self._mutate(lambda item: setattr(item, "border_width", width))

    def _group_selected(self) -> None:
        if len(self.selected_indices) < 2:
            return
        self._checkpoint()
        group = uuid.uuid4().hex
        for index in self.selected_indices:
            self.document.objects[index].group = group
        self.status.configure(text="Objets regroupés : ils se déplacent désormais ensemble.")
        self._render()

    def _ungroup_selected(self) -> None:
        if not self.selected_indices:
            return
        self._checkpoint()
        for index in self.selected_indices:
            self.document.objects[index].group = ""
        self.status.configure(text="Objets dissociés.")
        self._render()

    def _scale_selected_assembly(self, factor: float) -> None:
        indices = expanded_group_indices(self.document.objects, self.selected_indices)
        if not indices:
            self.status.configure(text="Sélectionnez d’abord un objet ou un assemblage.")
            return
        objects = [self.document.objects[index] for index in indices]
        left, top, width, height = objects_bounds(objects)
        self._checkpoint()
        transform_object_assembly(objects, left, top, width * factor, height * factor)
        self.selected_indices = indices
        self.selected = min(indices)
        self.status.configure(
            text=("Sélection agrandie de 10 %." if factor > 1 else "Sélection réduite de 10 %.")
        )
        self._render()

    def _show_properties(self) -> None:
        if self.selected is None or self.selected >= len(self.document.objects):
            if self._properties_details_visible:
                for widget, _layout in self._properties_static_layout:
                    widget.pack_forget()
                self._properties_details_visible = False
            self.triangle_frame.pack_forget()
            self.circle_frame.pack_forget()
            self.kind_label.configure(text="Sélectionnez un objet pour afficher ses propriétés.")
            self.geometry_help.configure(text="")
            self.shape_geometry_label.configure(text="")
            self.hyperlink_status.configure(text="Aucun lien")
            for var in self.property_vars.values():
                var.set("")
            self.scope_var.set("Cette page")
            self.pages_var.set("")
            return
        if not self._properties_details_visible:
            for widget, layout in self._properties_static_layout:
                options = dict(layout)
                options.pop("in", None)
                widget.pack(**options)
            self._properties_details_visible = True
        item = self.document.objects[self.selected]
        self._set_property_layout_visibility(
            self._measurement_property_layout,
            item.kind in {"line", "polyline", "shape", "dimension", "image"},
        )
        self._set_property_layout_visibility(
            self._scope_property_layout,
            item.kind in {"text", "image", "mask", "table", "shape", "chart"},
        )
        self.hyperlink_status.configure(
            text=(f"Lien actif : {item.hyperlink}" if item.hyperlink else "Aucun lien")
        )
        is_triangle = (
            item.kind == "polyline"
            and item.shape in {"triangle_geometry", "right_triangle_geometry"}
            and len(item.points) >= 3
        )
        if is_triangle:
            self.triangle_frame.pack(fill="x", pady=(4, 8), before=self.assembly_actions)
            self._update_triangle_property_fields(item)
        else:
            self.triangle_frame.pack_forget()
        is_circle = item.kind == "shape" and item.shape == "circle"
        if is_circle:
            self.circle_frame.pack(fill="x", pady=(4, 8), before=self.assembly_actions)
            self._update_circle_property_fields(item)
        else:
            self.circle_frame.pack_forget()
        selected_vertex = (
            self._selected_vertex
            if self._selected_vertex is not None
            and self._selected_vertex[0] == self.selected
            and item.kind == "polyline"
            and self._selected_vertex[1] < len(item.points)
            else None
        )
        names = {"text": "Zone de texte", "image": "Image", "mask": "Masque", "table": "Tableau", "line": "Trait", "polyline": "Polyligne", "chart": "Graphique", "shape": "Forme"}
        if is_circle:
            names["shape"] = "Cercle paramétrique"
        if item.kind == "polyline" and item.shape in {"triangle_geometry", "right_triangle_geometry"}:
            names["polyline"] = (
                "Triangle rectangle verrouillé"
                if item.shape == "right_triangle_geometry"
                else "Triangle géométrique"
            )
        elif item.kind == "polyline" and item.shape == "rectangle_geometry":
            names["polyline"] = "Rectangle orienté"
        elif item.kind == "polyline" and item.shape == "square_geometry":
            names["polyline"] = "Carré orienté"
        selection = f" — {len(self.selected_indices)} objets" if len(self.selected_indices) > 1 else ""
        grouped = len(self.selected_indices) > 1
        self.kind_label.configure(
            text=("Assemblage" if grouped else names.get(item.kind, item.kind)) + selection
        )
        help_text = ""
        if selected_vertex is not None:
            point_index = selected_vertex[1]
            point = item.points[point_index]
            absolute_x, absolute_y = item.x + point[0], item.y + point[1]
            self.kind_label.configure(text=f"Sommet {point_index + 1} du profil")
            self.property_vars["x"].set(f"{absolute_x * 25.4 / 72:.2f}")
            self.property_vars["y"].set(f"{absolute_y * 25.4 / 72:.2f}")
            if point_index:
                previous = item.points[point_index - 1]
                self.property_vars["width"].set(
                    f"{abs(point[0] - previous[0]) * 25.4 / 72:.2f}"
                )
                self.property_vars["height"].set(
                    f"{abs(point[1] - previous[1]) * 25.4 / 72:.2f}"
                )
            help_text = "Modifiez X/Y puis Entrée ou Tab pour positionner exactement ce sommet. Largeur/hauteur indiquent ΔX/ΔY du segment précédent."
        elif grouped:
            help_text = "X/Y : coin supérieur gauche du cadre orange. Largeur et hauteur redimensionnent tout l’assemblage."
        elif item.kind == "polyline" and len(item.points) >= 2:
            lengths = [
                math.dist(start, end) * 25.4 / 72
                for start, end in pairwise(item.points)
            ]
            help_text = "Segments : " + "  •  ".join(
                f"{index}: {length:.2f} mm"
                for index, length in enumerate(lengths, start=1)
            )
            help_text += "\nGlissez les points orange pour reprendre chaque sommet."
            if is_triangle:
                help_text += "\nLes côtés et les angles se recalculent automatiquement. Modifiez une valeur dans le cadre Triangle puis validez."
        self.geometry_help.configure(text=help_text)
        self.shape_geometry_label.configure(
            text="" if grouped else self._shape_geometry_summary(item)
        )
        if selected_vertex is not None:
            pass
        elif grouped:
            self._update_assembly_geometry_fields()
        else:
            self._update_geometry_fields(item)
        self.font_size_var.set(f"{item.font_size:g}")
        self.font_family_var.set(item.font_family)
        self.border_width_var.set(f"{item.border_width:g}")
        self.border_style_var.set({"solid": "Continu", "dotted": "Pointillé", "dashed": "Tirets"}.get(item.border_style, "Continu"))
        self.angle_var.set(f"{self._object_angle(item):g}")
        self.scope_var.set("Toutes les pages" if item.pages == "all" else "Pages choisies" if item.pages else "Cette page")
        self.pages_var.set("" if item.pages == "all" else item.pages)

    @staticmethod
    def _set_property_layout_visibility(
        layout_items: list[tuple[tk.Widget, dict[str, object]]], visible: bool
    ) -> None:
        for widget, layout in layout_items:
            if visible:
                if not widget.winfo_manager():
                    options = dict(layout)
                    options.pop("in", None)
                    widget.pack(**options)
            elif widget.winfo_manager():
                widget.pack_forget()

    def _shape_geometry_summary(self, item: PageObject) -> str:
        scale = 25.4 / 72
        position = (
            f"Position sur la feuille : X {item.x * scale:.2f} mm  •  "
            f"Y {item.y * scale:.2f} mm  •  niveau {item.level}"
        )
        if item.kind == "line":
            return (
                f"{position}\nLongueur : {math.hypot(item.width, item.height) * scale:.2f} mm"
                f"  •  Angle : {self._object_angle(item):.2f}°"
            )
        if item.kind == "polyline" and item.shape in {"rectangle_geometry", "square_geometry"} and len(item.points) >= 4:
            points = [(item.x + x, item.y + y) for x, y in item.points[:4]]
            length = math.dist(points[0], points[1]) * scale
            width = math.dist(points[1], points[2]) * scale
            orientation = math.degrees(
                math.atan2(points[1][1] - points[0][1], points[1][0] - points[0][0])
            ) % 360
            return (
                f"{position}\n{'Carré' if item.shape == 'square_geometry' else 'Rectangle'} : {length:.2f} × {width:.2f} mm"
                f"  •  Orientation : {orientation:.2f}°  •  angles 90°"
            )
        if item.kind == "polyline" and item.shape in {"triangle_geometry", "right_triangle_geometry"} and len(item.points) >= 3:
            metrics = self._triangle_metrics(item)
            return (
                f"{position}\nPérimètre : {metrics['ab'] + metrics['bc'] + metrics['ca']:.2f} mm"
                "  •  détails modifiables ci-dessous"
            )
        if item.kind == "shape" and item.shape == "circle":
            diameter = abs(item.width) * scale
            return (
                f"{position}\nCercle : Ø {diameter:.2f} mm  •  rayon {diameter / 2:.2f} mm"
                f"  •  périmètre {math.pi * diameter:.2f} mm"
                f"  •  aire {math.pi * (diameter / 2) ** 2:.2f} mm²"
            )
        if item.kind == "shape" and item.shape == "ellipse":
            horizontal = abs(item.width) * scale
            vertical = abs(item.height) * scale
            return (
                f"{position}\nDiamètres : {horizontal:.2f} × {vertical:.2f} mm"
                f"  •  rayons : {horizontal / 2:.2f} × {vertical / 2:.2f} mm"
            )
        if item.kind == "shape":
            return (
                f"{position}\nEncombrement : {abs(item.width) * scale:.2f} × "
                f"{abs(item.height) * scale:.2f} mm  •  Rotation : {item.rotation:g}°"
            )
        return position

    def _update_circle_property_fields(self, item: PageObject) -> None:
        diameter = abs(item.width) * 25.4 / 72
        values = {
            "diameter": diameter,
            "radius": diameter / 2,
            "perimeter": math.pi * diameter,
            "area": math.pi * (diameter / 2) ** 2,
        }
        self._circle_property_originals = values
        for key, value in values.items():
            self.circle_vars[key].set(f"{value:.2f}")

    def _apply_circle_properties(self) -> None:
        if self.selected is None:
            return
        item = self.document.objects[self.selected]
        if item.kind != "shape" or item.shape != "circle":
            return
        try:
            requested = {
                key: float(variable.get().replace(",", "."))
                for key, variable in self.circle_vars.items()
            }
        except ValueError:
            messagebox.showerror("Cercle", "Utilisez uniquement des nombres.", parent=self)
            return
        changed = next(
            (key for key, value in requested.items() if abs(value - self._circle_property_originals.get(key, value)) > 0.005),
            None,
        )
        if changed is None:
            return
        value = requested[changed]
        if value <= 0:
            messagebox.showerror("Cercle", "La valeur doit être positive.", parent=self)
            return
        diameter = (
            value if changed == "diameter"
            else value * 2 if changed == "radius"
            else value / math.pi if changed == "perimeter"
            else 2 * math.sqrt(value / math.pi)
        )
        self._checkpoint()
        center_x, center_y = item.x + item.width / 2, item.y + item.height / 2
        size = diameter * 72 / 25.4
        item.x, item.y = center_x - size / 2, center_y - size / 2
        item.width = item.height = size
        self.status.configure(text=f"Cercle recalculé : Ø {diameter:.2f} mm.")
        self._render()

    @staticmethod
    def _triangle_absolute_points(item: PageObject) -> list[tuple[float, float]]:
        return [(item.x + point[0], item.y + point[1]) for point in item.points[:3]]

    def _triangle_metrics(self, item: PageObject) -> dict[str, float]:
        a, b, c = self._triangle_absolute_points(item)
        scale = 25.4 / 72
        return {
            "ab": math.dist(a, b) * scale,
            "bc": math.dist(b, c) * scale,
            "ca": math.dist(c, a) * scale,
            "angle_a": angle_at_vertex(b, a, c),
            "angle_b": angle_at_vertex(a, b, c),
            "angle_c": angle_at_vertex(a, c, b),
        }

    def _update_triangle_property_fields(self, item: PageObject) -> None:
        is_right = item.shape == "right_triangle_geometry"
        self.triangle_frame.configure(
            text=(
                "TRIANGLE RECTANGLE VERROUILLÉ — CÔTÉS ET ANGLES"
                if is_right
                else "TRIANGLE — CÔTÉS ET ANGLES"
            )
        )
        for entry in self.triangle_entries.values():
            entry.state(["!disabled"])
        metrics = self._triangle_metrics(item)
        self._triangle_property_originals = metrics
        for key, value in metrics.items():
            self.triangle_vars[key].set(f"{value:.2f}")
        if is_right:
            self.triangle_vars["angle_a"].set("90.00")
            self.triangle_entries["angle_a"].state(["disabled"])

    def _apply_triangle_properties(self) -> None:
        if self.selected is None:
            return
        item = self.document.objects[self.selected]
        if (
            item.kind != "polyline"
            or item.shape not in {"triangle_geometry", "right_triangle_geometry"}
            or len(item.points) < 3
        ):
            return
        try:
            requested = {key: float(variable.get().replace(",", ".")) for key, variable in self.triangle_vars.items()}
        except ValueError:
            messagebox.showerror("Triangle", "Utilisez uniquement des valeurs numériques.", parent=self)
            return
        changed = [key for key, value in requested.items() if abs(value - self._triangle_property_originals.get(key, value)) > 0.005]
        if not changed:
            return
        points = self._triangle_absolute_points(item)
        if item.shape == "right_triangle_geometry":
            if not self._apply_right_triangle_properties(item, points, requested, changed):
                return
            self.status.configure(
                text="Triangle rectangle recalculé : l’angle droit reste verrouillé à 90°."
            )
            self._render()
            return
        self._checkpoint()
        angle_key = next((key for key in changed if key.startswith("angle_")), None)
        if angle_key is not None:
            target = requested[angle_key]
            if not 0 < target < 180:
                messagebox.showerror("Triangle", "Un angle doit être strictement compris entre 0° et 180°.", parent=self)
                return
            vertex_index = {"angle_a": 0, "angle_b": 1, "angle_c": 2}[angle_key]
            previous_index = (vertex_index - 1) % 3
            next_index = (vertex_index + 1) % 3
            vertex = points[vertex_index]
            fixed = points[next_index]
            moving = points[previous_index]
            base_angle = math.atan2(fixed[1] - vertex[1], fixed[0] - vertex[0])
            cross = (fixed[0] - vertex[0]) * (moving[1] - vertex[1]) - (fixed[1] - vertex[1]) * (moving[0] - vertex[0])
            direction = 1 if cross >= 0 else -1
            radius = math.dist(vertex, moving)
            new_angle = base_angle + direction * math.radians(target)
            points[previous_index] = (
                vertex[0] + radius * math.cos(new_angle),
                vertex[1] + radius * math.sin(new_angle),
            )
        else:
            side_key = next(key for key in changed if key in {"ab", "bc", "ca"})
            start_index, end_index = {"ab": (0, 1), "bc": (1, 2), "ca": (0, 2)}[side_key]
            target = requested[side_key] * 72 / 25.4
            if target <= 0:
                messagebox.showerror("Triangle", "La longueur d’un côté doit être positive.", parent=self)
                return
            start, end = points[start_index], points[end_index]
            current = math.dist(start, end)
            points[end_index] = (
                start[0] + (end[0] - start[0]) * target / current,
                start[1] + (end[1] - start[1]) * target / current,
            )
        self._set_polyline_absolute_points(item, [*points, points[0]])
        self.status.configure(text="Triangle recalculé : côtés et angles mis à jour.")
        self._render()

    def _apply_right_triangle_properties(
        self,
        item: PageObject,
        points: list[tuple[float, float]],
        requested: dict[str, float],
        changed: list[str],
    ) -> bool:
        """Modify a right triangle while keeping A as its locked 90-degree vertex."""
        a, b, c = points
        ab = math.dist(a, b)
        ac = math.dist(a, c)
        hypotenuse = math.dist(b, c)
        if min(ab, ac, hypotenuse) <= 1e-8:
            messagebox.showerror(
                "Triangle rectangle", "Le triangle est trop petit pour être recalculé.", parent=self
            )
            return False
        ux, uy = (b[0] - a[0]) / ab, (b[1] - a[1]) / ab
        vx, vy = (c[0] - a[0]) / ac, (c[1] - a[1]) / ac
        angle_key = next((key for key in changed if key.startswith("angle_")), None)
        side_key = next((key for key in changed if key in {"ab", "bc", "ca"}), None)
        if angle_key == "angle_a":
            messagebox.showinfo(
                "Triangle rectangle",
                "L’angle A est verrouillé à 90° pour conserver un triangle rectangle.",
                parent=self,
            )
            self._update_triangle_property_fields(item)
            return False
        if angle_key in {"angle_b", "angle_c"}:
            target = requested[angle_key]
            if not 0 < target < 90:
                messagebox.showerror(
                    "Triangle rectangle",
                    "Les deux angles aigus doivent être strictement compris entre 0° et 90°.",
                    parent=self,
                )
                return False
            beta = target if angle_key == "angle_b" else 90 - target
            radians = math.radians(beta)
            ab = hypotenuse * math.cos(radians)
            ac = hypotenuse * math.sin(radians)
        elif side_key is not None:
            target = requested[side_key] * 72 / 25.4
            if target <= 0:
                messagebox.showerror(
                    "Triangle rectangle", "La longueur d’un côté doit être positive.", parent=self
                )
                return False
            if side_key == "ab":
                ab = target
            elif side_key == "ca":
                ac = target
            else:
                ratio = target / hypotenuse
                ab *= ratio
                ac *= ratio
        else:
            return False
        b = (a[0] + ux * ab, a[1] + uy * ab)
        c = (a[0] + vx * ac, a[1] + vy * ac)
        self._checkpoint()
        self._set_polyline_absolute_points(item, [a, b, c, a])
        return True

    def _apply_scope(self) -> None:
        if self.selected is None:
            return
        scope = self.scope_var.get()
        pages = "all" if scope == "Toutes les pages" else self.pages_var.get().strip() if scope == "Pages choisies" else ""
        self._mutate(lambda item: setattr(item, "pages", pages))

    def _update_geometry_fields(self, item: PageObject) -> None:
        for key, var in self.property_vars.items():
            value = getattr(item, key)
            if key in {"x", "y", "width", "height"}:
                value = value * 25.4 / 72
            digits = 2 if key in {"x", "y", "width", "height"} else 0 if key == "level" else 1
            var.set(f"{value:.{digits}f}")

    def _update_assembly_geometry_fields(self) -> None:
        objects = [self.document.objects[index] for index in self.selected_indices]
        x, y, width, height = objects_bounds(objects)
        for key, value in (("x", x), ("y", y), ("width", width), ("height", height)):
            self.property_vars[key].set(f"{value * 25.4 / 72:.2f}")
        if objects:
            self.property_vars["font_size"].set(f"{objects[0].font_size:.1f}")
            levels = {item.level for item in objects}
            self.property_vars["level"].set(str(objects[0].level) if len(levels) == 1 else "0")

    def _apply_properties(self, *, silent: bool = False) -> None:
        if self.selected is None:
            return
        if any(self.document.objects[index].locked for index in self.selected_indices):
            if not silent:
                messagebox.showinfo(
                    "Objet verrouillé",
                    "Déverrouillez l’axe 3D avant de modifier ses coordonnées.",
                    parent=self,
                )
            return
        try:
            values = {key: float(var.get().replace(",", ".")) for key, var in self.property_vars.items()}
        except ValueError:
            if not silent:
                messagebox.showerror("Valeur incorrecte", "Utilisez uniquement des nombres.", parent=self)
            return
        if (
            self._selected_vertex is not None
            and self._selected_vertex[0] == self.selected
            and self.document.objects[self.selected].kind == "polyline"
        ):
            object_index, point_index = self._selected_vertex
            item = self.document.objects[object_index]
            absolute = [(item.x + x, item.y + y) for x, y in item.points]
            if point_index >= len(absolute):
                return
            self._checkpoint()
            absolute[point_index] = (
                max(0.0, values["x"] * 72 / 25.4),
                max(0.0, values["y"] * 72 / 25.4),
            )
            self._set_polyline_absolute_points(item, absolute)
            self.status.configure(
                text=f"Sommet {point_index + 1} placé à X {values['x']:.2f} mm, Y {values['y']:.2f} mm."
            )
            self._render()
            return
        if len(self.selected_indices) > 1:
            target_x = max(0.0, values["x"] * 72 / 25.4)
            target_y = max(0.0, values["y"] * 72 / 25.4)
            target_width = max(0.1, values["width"] * 72 / 25.4)
            target_height = max(0.1, values["height"] * 72 / 25.4)
            self._checkpoint()
            objects = [self.document.objects[index] for index in self.selected_indices]
            transform_object_assembly(
                objects, target_x, target_y, target_width, target_height
            )
            for item in objects:
                item.font_size = max(6.0, values["font_size"])
                item.level = round(values["level"])
            self.status.configure(
                text=f"Assemblage placé à X {values['x']:.2f} mm, Y {values['y']:.2f} mm."
            )
            self._render()
            return

        def apply(item: PageObject) -> None:
            old_width, old_height = item.width, item.height
            for key, value in values.items():
                if key in {"x", "y", "width", "height"}:
                    value = value * 72 / 25.4
                if key == "level":
                    value = round(value)
                if key in {"x", "y"}:
                    value = max(0, value)
                elif key == "font_size":
                    value = max(6, value)
                elif key in {"width", "height"} and item.kind != "line":
                    value = max(6, value)
                setattr(item, key, value)
            if item.kind == "shape" and item.shape == "circle":
                item.height = item.width
            if item.kind == "polyline" and old_width and old_height:
                item.points = [
                    [point[0] * item.width / old_width, point[1] * item.height / old_height]
                    for point in item.points
                ]
        self._mutate(apply)

    def _set_selected_level(self, level: int) -> None:
        if not self.selected_indices:
            return
        self._checkpoint()
        for index in self.selected_indices:
            self.document.objects[index].level = int(level)
        self.status.configure(text=f"Objet(s) placé(s) au niveau {level}.")
        self._render()

    def _change_selected_level(self, delta: int) -> None:
        if not self.selected_indices:
            return
        self._checkpoint()
        for index in self.selected_indices:
            self.document.objects[index].level += delta
        level = self.document.objects[self.selected].level if self.selected is not None else 0
        self.status.configure(text=f"Niveau modifié : {level}.")
        self._render()

    def _nudge_selected(self, event: tk.Event[tk.Misc], horizontal: int, vertical: int) -> str | None:
        if event.widget.winfo_class() in {"Entry", "TEntry", "Text", "TCombobox"}:
            return None
        if not self.selected_indices:
            return None
        try:
            millimetres = float(self.nudge_var.get().replace(",", "."))
        except ValueError:
            millimetres = 1.0
        if event.state & 0x0001:
            millimetres *= 10
        delta = millimetres * 72 / 25.4
        self._checkpoint()
        page_width, page_height = self._page_size()
        for index in self.selected_indices:
            item = self.document.objects[index]
            if item.locked:
                continue
            if item.kind == "line":
                minimum_x, maximum_x = min(0.0, item.width), max(0.0, item.width)
                minimum_y, maximum_y = min(0.0, item.height), max(0.0, item.height)
                item.x = max(-minimum_x, min(page_width - maximum_x, item.x + horizontal * delta))
                item.y = max(-minimum_y, min(page_height - maximum_y, item.y + vertical * delta))
            else:
                item.x = max(0, min(page_width - item.width, item.x + horizontal * delta))
                item.y = max(0, min(page_height - item.height, item.y + vertical * delta))
        self._render()
        self.status.configure(text=f"Déplacement précis : {millimetres:g} mm.")
        return "break"

    def _change_page(self, change: int) -> None:
        self._commit_inline_editor(render=False)
        page = self.current_page + change
        if 0 <= page < self.document.page_count:
            self.current_page, self.selected = page, None
            self.selected_indices.clear()
            self._render()

    def _add_blank_page(self) -> None:
        self._commit_inline_editor(render=False)
        self._checkpoint()
        self.document.page_count += 1
        self.current_page, self.selected = self.document.page_count - 1, None
        self.selected_indices.clear()
        self._render()

    def _set_zoom(self, change: float) -> None:
        self._commit_inline_editor(render=False)
        self.zoom = max(0.25, min(4.0, self.zoom + change))
        self._schedule_zoom_render()

    def _schedule_zoom_render(self) -> None:
        """Regroupe les crans rapides d'un geste de zoom en un seul rendu."""
        if self._zoom_render_after_id is not None:
            try:
                self.after_cancel(self._zoom_render_after_id)
            except tk.TclError:
                pass
        self.zoom_label.configure(text=f"{round(self.zoom * 100)} %")
        self._zoom_render_after_id = self.after(90, self._finish_scheduled_zoom)

    def _finish_scheduled_zoom(self) -> None:
        self._zoom_render_after_id = None
        self._render()

    def _mouse_scroll(
        self, event: tk.Event[tk.Misc], linux_direction: int | None = None
    ) -> str:
        """Fait défiler la feuille à la molette sur Windows, macOS et X11."""
        direction = linux_direction
        if direction is None:
            direction = 1 if int(getattr(event, "delta", 0)) > 0 else -1
        units = -3 if direction > 0 else 3
        if int(getattr(event, "state", 0)) & 0x0001:
            self.canvas.xview_scroll(units, "units")
        else:
            before = self.canvas.yview()
            self.canvas.yview_scroll(units, "units")
            after = self.canvas.yview()
            at_edge = (direction > 0 and after[0] <= 0.0001) or (
                direction < 0 and after[1] >= 0.9999
            )
            moved = any(abs(first - second) > 1e-6 for first, second in zip(before, after, strict=True))
            if not at_edge or moved:
                self._page_edge_wheel = None
            else:
                event_time = int(getattr(event, "time", 0))
                previous = self._page_edge_wheel
                count = (
                    previous[1] + 1
                    if previous and previous[0] == direction and event_time - previous[2] < 900
                    else 1
                )
                self._page_edge_wheel = (direction, count, event_time)
                target = self.current_page - 1 if direction > 0 else self.current_page + 1
                if 0 <= target < self.document.page_count:
                    if count == 1:
                        self.status.configure(
                            text="Fin de page — continuez la molette pour changer de page."
                        )
                    else:
                        self._page_edge_wheel = None
                        self._change_page(-1 if direction > 0 else 1)
                        self.canvas.yview_moveto(1.0 if direction > 0 else 0.0)
        return "break"

    def _zoom_page_width(self) -> None:
        self._commit_inline_editor(render=False)
        self.canvas.update_idletasks()
        available = max(100, self.canvas.winfo_width() - 70)
        self.zoom = max(0.25, min(4.0, available / self.document.page_width))
        self._render()
        self.canvas.xview_moveto(0)

    def _zoom_full_page(self) -> None:
        self._commit_inline_editor(render=False)
        self.canvas.update_idletasks()
        available_width = max(100, self.canvas.winfo_width() - 70)
        available_height = max(100, self.canvas.winfo_height() - 70)
        self.zoom = max(
            0.25,
            min(
                4.0,
                available_width / self.document.page_width,
                available_height / self.document.page_height,
            ),
        )
        self._render()
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)

    def _mouse_zoom(
        self, event: tk.Event[tk.Misc], linux_direction: int | None = None
    ) -> str:
        """Zoom around the document position currently under the mouse pointer."""
        old_zoom = self.zoom
        direction = linux_direction
        if direction is None:
            direction = 1 if getattr(event, "delta", 0) > 0 else -1
        factor = 1.15 if direction > 0 else 1 / 1.15
        new_zoom = max(0.25, min(4.0, old_zoom * factor))
        if abs(new_zoom - old_zoom) < 1e-9:
            return "break"
        self._commit_inline_editor(render=False)
        self.zoom = new_zoom
        # Une molette physique émet souvent des dizaines d'événements. Le rendu
        # riche complet à chaque cran saturait un cœur CPU et accumulait les
        # aperçus bitmap. Le dernier niveau demandé est rendu après le geste.
        self._schedule_zoom_render()
        return "break"

    def _set_orientation(self, orientation: str) -> None:
        if self.document.source_pdf:
            messagebox.showinfo("Orientation", "Pour un PDF importé, utilisez le module Organiser les PDF afin de faire pivoter les pages.", parent=self)
            return
        self._checkpoint()
        if orientation == "landscape":
            self.document.page_width, self.document.page_height = max(self.document.page_width, self.document.page_height), min(self.document.page_width, self.document.page_height)
        else:
            self.document.page_width, self.document.page_height = min(self.document.page_width, self.document.page_height), max(self.document.page_width, self.document.page_height)
        self._render()

    def _set_page_format(self) -> None:
        if self.document.source_pdf:
            messagebox.showinfo("Format de page", "Le format d’un PDF importé est conservé.", parent=self)
            return
        landscape = self.document.page_width > self.document.page_height
        dimensions = {
            "A4": (A4_WIDTH, A4_HEIGHT),
            "A3": (A4_HEIGHT, 1190.55),
        }
        width, height = dimensions.get(self.page_format_var.get(), dimensions["A4"])
        self._checkpoint()
        self.document.page_width, self.document.page_height = ((height, width) if landscape else (width, height))
        self.status.configure(text=f"Format {self.page_format_var.get()} appliqué.")
        self._render()

    def _project_directory(self) -> Path:
        return settings_path().parent / "modeles" if self.template_mode else document_destination()

    def _save(self) -> bool:
        self._commit_inline_editor(render=False)
        if self.project_path is None:
            return self._save_as(commit_inline=False)
        self._write_project(self.project_path)
        return True

    def _save_as(
        self,
        *,
        commit_inline: bool = True,
        initial_directory: Path | None = None,
    ) -> bool:
        """Save a new independent project and make it the current project."""
        if commit_inline:
            self._commit_inline_editor(render=False)
        initial_name = self.project_path.stem if self.project_path else "nouveau_document"
        destination = initial_directory or self._project_directory()
        destination.mkdir(parents=True, exist_ok=True)
        selected = choose_save_path(
            self,
            destination,
            initial_name,
            ".cod",
        )
        if not selected:
            return False
        path = Path(selected)
        self._write_project(path)
        return True

    def _write_project(self, path: Path) -> None:
        self.document.is_template = False
        self.document.save(path)
        self.project_path = path
        self._saved_document = copy.deepcopy(self.document)
        self._store_active_document_tab(path.name)
        self._refresh_document_tabs()
        self.status.configure(text=f"Projet enregistré : {path.name}")

    def _save_as_template(self) -> bool:
        self._commit_inline_editor(render=False)
        directory = settings_path().parent / "modeles"
        directory.mkdir(parents=True, exist_ok=True)
        initial_name = f"modele_{self.project_path.stem}" if self.project_path else "nouveau_modele"
        selected = choose_save_path(self, directory, initial_name, ".cod")
        if not selected:
            return False
        template = copy.deepcopy(self.document)
        template.is_template = True
        template.save(Path(selected))
        self.status.configure(
            text=f"Modèle enregistré : {Path(selected).name}. Le document courant reste indépendant."
        )
        return True

    def _use_loaded_document(self, loaded: CanvasDocument, path: Path) -> None:
        opened_from_template = loaded.is_template
        loaded.is_template = False
        self.document = loaded
        self.project_path = None if opened_from_template else path
        self._saved_document = copy.deepcopy(loaded)
        self.current_page, self.selected = 0, None
        self.selected_indices.clear()
        self.status.configure(
            text=(
                f"Nouveau document créé depuis le modèle {path.name}. Enregistrer demandera un nouveau nom."
                if opened_from_template
                else f"Projet ouvert : {path.name}"
            )
        )
        self._render()

    def _load_template(self) -> None:
        directory = settings_path().parent / "modeles"
        directory.mkdir(parents=True, exist_ok=True)
        files = choose_documents(
            self,
            {".cod", ".loucodi-document"},
            initial_directory=directory,
        )
        if not files:
            return
        try:
            loaded = CanvasDocument.load(files[0])
        except (OSError, ValueError, TypeError, KeyError) as exc:
            messagebox.showerror("Modèle illisible", str(exc), parent=self)
            return
        loaded.is_template = True
        self._checkpoint()
        self._use_loaded_document(loaded, files[0])

    def _load(self) -> None:
        files = choose_documents(
            self,
            {".cod", ".loucodi-document"},
            initial_directory=self._project_directory(),
        )
        if not files:
            return
        try:
            loaded = CanvasDocument.load(files[0])
        except (OSError, ValueError, TypeError, KeyError) as exc:
            messagebox.showerror("Document illisible", str(exc), parent=self)
            return
        opened_from_template = loaded.is_template
        loaded.is_template = False
        self._open_document_tab(
            loaded,
            files[0].name,
            project_path=None if opened_from_template else files[0],
        )
        self.status.configure(
            text=(
                f"Nouveau document créé depuis le modèle {files[0].name}."
                if opened_from_template
                else f"Projet ouvert : {files[0].name}"
            )
        )

    def _import_docx(self) -> None:
        files = choose_documents(
            self,
            {".docx"},
            initial_directory=document_destination(),
        )
        if not files:
            return
        try:
            loaded = import_docx_as_canvas(files[0])
        except (OSError, ValueError, TypeError, KeyError) as exc:
            messagebox.showerror("DOCX illisible", str(exc), parent=self)
            return
        self._open_document_tab(loaded, files[0].name)
        self.status.configure(
            text=(
                f"DOCX importé : {files[0].name}. Textes, listes, styles et images "
                "sont modifiables dans Document Studio."
            )
        )

    def _append_docx(self) -> None:
        files = choose_documents(self, {".docx"}, initial_directory=document_destination())
        if not files:
            return
        try:
            loaded = import_docx_as_canvas(files[0])
            self._checkpoint()
            first_page = self.document.page_count
            append_canvas_document(self.document, loaded)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            messagebox.showerror("Insertion impossible", str(exc), parent=self)
            return
        self.current_page = first_page
        self.selected = None
        self.selected_indices.clear()
        self.status.configure(text=f"DOCX inséré à la suite : {files[0].name}")
        self._render()

    def _start_pdf_font_picker(self) -> None:
        if not self.document.source_pdf or not Path(self.document.source_pdf).is_file():
            messagebox.showinfo("Pipette typographique", "Importez d’abord un PDF contenant du texte sélectionnable.", parent=self)
            return
        self._pdf_font_pick_mode = True
        self.canvas.configure(cursor="crosshair")
        self.status.configure(text="Pipette typographique : cliquez sur un caractère du PDF. Échap annule.")

    def _pick_pdf_font(self, event: tk.Event[tk.Misc]) -> None:
        self._pdf_font_pick_mode = False
        self.canvas.configure(cursor="")
        x = (self.canvas.canvasx(event.x) - self.page_x) / self.zoom
        y = (self.canvas.canvasy(event.y) - self.page_y) / self.zoom
        spans: list[dict[str, object]] = []
        try:
            with pymupdf.open(self.document.source_pdf) as pdf:
                page = pdf[self.current_page]
                for block in page.get_text("dict").get("blocks", []):
                    for line in block.get("lines", []):
                        spans.extend(line.get("spans", []))
        except (OSError, RuntimeError, ValueError, IndexError) as exc:
            messagebox.showerror("Pipette typographique", str(exc), parent=self)
            return
        def distance(span: dict[str, object]) -> float:
            x0, y0, x1, y1 = (float(value) for value in span.get("bbox", (0, 0, 0, 0)))
            dx = max(x0 - x, 0, x - x1)
            dy = max(y0 - y, 0, y - y1)
            return math.hypot(dx, dy)
        if not spans:
            messagebox.showinfo("Pipette typographique", "Aucun texte sélectionnable sur cette page. Utilisez l’OCR pour une page scannée.", parent=self)
            return
        span = min(spans, key=distance)
        detected = normalize_font_name(str(span.get("font", "")))
        fallback = closest_family(detected)
        self.font_family_var.set(fallback or detected)
        self.font_size_var.set(f"{float(span.get('size', 12.0)):.1f}")
        color = int(span.get("color", 0)) & 0xFFFFFF
        sample = str(span.get("text", "Texte")) or "Texte"
        self._update_font_sample()
        self.status.configure(text=f"Police détectée : {detected} — {span.get('size', 12)} pt. Police locale : {fallback or 'introuvable'}.")
        if self.selected is not None and self.document.objects[self.selected].kind == "text":
            self._checkpoint()
            item = self.document.objects[self.selected]
            item.font_family = fallback or detected
            item.font_size = float(span.get("size", 12.0))
            item.color = f"#{color:06X}"
            flags = int(span.get("flags", 0))
            item.bold = bool(flags & 16)
            item.italic = bool(flags & 2)
            self._render()
        else:
            self._add_object(PageObject("text", self.current_page, x, y, 220, 55, text=sample, font_family=fallback or detected, font_size=float(span.get("size", 12.0)), color=f"#{color:06X}", fill="transparent", border_width=0))

    def _show_font_catalog(self) -> None:
        families = list(installed_families())
        dialog = tk.Toplevel(self)
        dialog.title("Catalogue des polices")
        dialog.geometry("680x500")
        dialog.configure(bg=BACKGROUND)
        ttk.Label(dialog, text="Polices disponibles sur cet ordinateur", font=("Sans", 15, "bold")).pack(anchor="w", padx=18, pady=(16, 6))
        search = tk.StringVar(value="")
        entry = ttk.Entry(dialog, textvariable=search)
        entry.pack(fill="x", padx=18, pady=6)
        listbox = tk.Listbox(dialog, font=("Sans", 11))
        listbox.pack(fill="both", expand=True, padx=18, pady=6)
        info = ttk.Label(dialog, text="", wraplength=640)
        info.pack(fill="x", padx=18, pady=6)
        def refresh(*_args: object) -> None:
            needle = search.get().casefold().strip()
            listbox.delete(0, "end")
            visible = [family for family in families if not needle or needle in family.casefold()]
            for family in visible:
                listbox.insert("end", family)
            suggestion = closest_family(search.get(), families)
            info.configure(text=f"Police la plus proche installée : {suggestion or 'aucune'}")
        def install_font() -> None:
            selected_files = choose_documents(
                dialog,
                {".ttf", ".otf", ".ttc", ".zip"},
                initial_directory=downloads_directory(),
                window_title="Installer des polices — Téléchargements",
                heading="Choisir des polices ou une archive ZIP",
                accept_label="Installer les polices sélectionnées",
                selection_help="Sélectionnez une archive ZIP ou des fichiers .ttf, .otf ou .ttc.",
            )
            if not selected_files:
                return
            try:
                installed = tuple(
                    font
                    for selected in selected_files
                    for font in install_user_fonts(selected)
                )
                families[:] = refresh_font_catalog()
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                messagebox.showerror("Installation impossible", str(exc), parent=dialog)
                return
            self.font_family_combo.configure(
                values=available_font_families()
            )
            if (
                self._inline_font_family_combo is not None
                and self._inline_font_family_combo.winfo_exists()
            ):
                self._inline_font_family_combo.configure(values=available_font_families())
            if self._inline_font_menu is not None:
                self._populate_inline_font_menu(self._inline_font_menu)
            first_name = installed[0].stem
            search.set(closest_family(first_name, tuple(families)) or first_name)
            refresh()
            messagebox.showinfo(
                "Police installée",
                f"{len(installed)} fichier(s) de police installé(s) pour votre compte. "
                "Ils sont maintenant disponibles dans Lou Còdi.",
                parent=dialog,
            )
        search.trace_add("write", refresh)
        refresh()
        actions = ttk.Frame(dialog, padding=18)
        actions.pack(fill="x")
        def use_selected() -> None:
            selection = listbox.curselection()
            family = listbox.get(selection[0]) if selection else closest_family(search.get(), families)
            if family:
                self.font_family_var.set(family)
                self._apply_font_family()
                self._update_font_sample()
                dialog.destroy()
        ttk.Button(actions, text="Utiliser la police", command=use_selected).pack(side="right")
        ttk.Button(actions, text="Installer une police…", command=install_font).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Chercher une police proche sur Google Fonts", command=lambda: webbrowser.open("https://fonts.google.com/?query=" + search.get().replace(" ", "+"), new=2)).pack(side="left")
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        entry.focus_set()

    def _show_bundled_fonts(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Polices livrées avec Lou Còdi")
        dialog.geometry("780x560")
        dialog.configure(bg=BACKGROUND)
        tk.Label(
            dialog,
            text="Polices réellement incluses dans le paquet Lou Còdi",
            bg=NAVY,
            fg="white",
            font=("Sans", 17, "bold"),
            padx=20,
            pady=12,
        ).pack(fill="x")
        ttk.Label(
            dialog,
            text=(
                "Ces polices fonctionnent même si elles ne sont pas installées sur l’ordinateur. "
                "Une autre police ne peut être ajoutée au paquet qu’avec une licence autorisant "
                "explicitement sa redistribution."
            ),
            wraplength=730,
        ).pack(fill="x", padx=18, pady=(14, 8))
        tree = ttk.Treeview(dialog, columns=("style", "file"), show="tree headings")
        tree.heading("#0", text="Famille — aperçu")
        tree.heading("style", text="Style")
        tree.heading("file", text="Fichier embarqué")
        tree.column("#0", width=330)
        tree.column("style", width=150)
        tree.column("file", width=240)
        tree.pack(fill="both", expand=True, padx=18, pady=8)
        for index, face in enumerate(bundled_fonts()):
            tag = f"bundled-font-{index}"
            tree.tag_configure(tag, font=(face.family, 13))
            tree.insert(
                "", "end", text=f"{face.family} — AaBb 123",
                values=(face.style, face.path.name), tags=(tag,),
            )
        ttk.Button(dialog, text="Fermer", command=dialog.destroy).pack(
            anchor="e", padx=18, pady=(4, 16)
        )
        dialog.bind("<Escape>", lambda _event: dialog.destroy())

    def _ocr_pdf_page(self) -> None:
        executable = shutil.which("tesseract")
        if not executable:
            messagebox.showinfo("OCR facultatif", "Le moteur Tesseract n’est pas installé. La pipette reste disponible pour les PDF contenant déjà du texte.", parent=self)
            return
        if not self.document.source_pdf:
            messagebox.showinfo("OCR facultatif", "Importez d’abord un PDF.", parent=self)
            return
        try:
            with pymupdf.open(self.document.source_pdf) as pdf:
                pixmap = pdf[self.current_page].get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
                with tempfile.TemporaryDirectory(prefix="lou-codi-ocr-") as directory:
                    image = Path(directory) / "page.png"
                    pixmap.save(image)
                    languages = subprocess.run(
                        [executable, "--list-langs"], capture_output=True, text=True,
                        check=False, timeout=10,
                    ).stdout.splitlines()
                    available = {language.strip() for language in languages[1:]}
                    requested = "+".join(language for language in ("fra", "eng") if language in available)
                    command = [executable, str(image), "stdout"]
                    if requested:
                        command.extend(("-l", requested))
                    result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=90)
            text = result.stdout.strip()
        except (OSError, RuntimeError, ValueError, IndexError, subprocess.TimeoutExpired) as exc:
            messagebox.showerror("OCR impossible", str(exc), parent=self)
            return
        if not text:
            messagebox.showinfo("OCR", "Aucun texte n’a été reconnu sur cette page.", parent=self)
            return
        self._add_object(PageObject("text", self.current_page, 45, 45, self._page_size()[0] - 90, self._page_size()[1] - 90, text=text, fill="transparent", border_width=0, font_size=10))
        self.status.configure(text="OCR terminé : le texte reconnu a été ajouté dans une zone modifiable.")

    def _choose_export(self, extension: str, label: str) -> Path | None:
        stem = self.project_path.stem if self.project_path else "nouveau_document"
        return choose_save_path(self, document_destination(), stem, extension)

    def _export_pdf(self) -> None:
        self._commit_inline_editor(render=False)
        target = self._choose_export(".pdf", "Document PDF")
        if target:
            try:
                export_canvas_pdf(self.document, target)
            except (OSError, RuntimeError, ValueError) as exc:
                messagebox.showerror("Export impossible", str(exc), parent=self)
                return
            self.last_export = target
            self.status.configure(text=f"PDF créé : {target.name}")

    def _export_docx(self, *, compatibility_mode: bool = False) -> None:
        self._commit_inline_editor(render=False)
        target = self._choose_export(".docx", "Document Word")
        if target is None:
            return
        try:
            export_editable_docx(
                self.document,
                target,
                compatibility_mode=compatibility_mode,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            messagebox.showerror("Export impossible", str(exc), parent=self)
            return
        self.last_export = target
        if compatibility_mode:
            self.status.configure(
                text=f"DOCX compatible créé : {target.name}. Mise en page fidèle, non modifiable."
            )
        else:
            self.status.configure(
                text=f"DOCX modifiable créé : {target.name}. Prévu pour Word et OnlyOffice."
            )

    def _print(self) -> None:
        self._commit_inline_editor(render=False)
        target = Path(tempfile.gettempdir()) / "lou-codi-document-a-imprimer.pdf"
        try:
            export_canvas_pdf(self.document, target)
        except (OSError, RuntimeError, ValueError) as exc:
            messagebox.showerror("Impression impossible", str(exc), parent=self)
            return
        printers = self._available_printers()
        if not printers:
            open_path(target)
            messagebox.showinfo(
                "Impression",
                "Aucune imprimante système n’a été détectée. Le PDF a été ouvert dans le lecteur.",
                parent=self,
            )
            return
        dialog = tk.Toplevel(self, class_="Loucodiworkshop")
        dialog.title("Imprimer le document")
        dialog.configure(bg=BACKGROUND)
        tk.Label(
            dialog,
            text="Imprimer",
            bg=NAVY,
            fg="white",
            font=("Sans", 16, "bold"),
            padx=18,
            pady=10,
        ).pack(fill="x")
        form = ttk.Frame(dialog, padding=18)
        form.pack(fill="both", expand=True)
        ttk.Label(form, text="Imprimante").grid(row=0, column=0, sticky="w", pady=5)
        printer_var = tk.StringVar(value=printers[0])
        ttk.Combobox(
            form, textvariable=printer_var, values=printers, state="readonly", width=42
        ).grid(row=0, column=1, sticky="ew", pady=5)
        ttk.Label(form, text="Nombre de copies").grid(row=1, column=0, sticky="w", pady=5)
        copies_var = tk.IntVar(value=1)
        ttk.Spinbox(form, from_=1, to=99, textvariable=copies_var, width=6).grid(
            row=1, column=1, sticky="w", pady=5
        )
        form.columnconfigure(1, weight=1)
        actions = ttk.Frame(dialog, padding=(18, 0, 18, 18))
        actions.pack(fill="x")

        def send() -> None:
            try:
                self._send_to_printer(target, printer_var.get(), max(1, copies_var.get()))
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                messagebox.showerror("Impression impossible", str(exc), parent=dialog)
                return
            dialog.destroy()
            self.status.configure(text=f"Document envoyé à l’imprimante {printer_var.get()}.")

        ttk.Button(actions, text="Annuler", command=dialog.destroy).pack(side="right")
        ttk.Button(actions, text="Imprimer", style="Primary.TButton", command=send).pack(
            side="right", padx=8
        )
        center_window(dialog, 560, 230)
        make_modal(dialog, self)

    @staticmethod
    def _available_printers() -> list[str]:
        if sys.platform == "win32":
            try:
                result = subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-Command",
                        "Get-Printer | Select-Object -ExpandProperty Name",
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=8,
                )
            except (OSError, subprocess.SubprocessError):
                return ["Imprimante par défaut"]
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if shutil.which("lpstat"):
            try:
                result = subprocess.run(
                    ["lpstat", "-p"], check=True, capture_output=True, text=True, timeout=8
                )
            except (OSError, subprocess.SubprocessError):
                return []
            return [
                line.split()[1]
                for line in result.stdout.splitlines()
                if line.startswith("printer ") and len(line.split()) >= 2
            ]
        return []

    @staticmethod
    def _send_to_printer(target: Path, printer: str, copies: int) -> None:
        if sys.platform == "win32":
            # Windows delegates PDF rendering to the registered PDF application.
            for _copy in range(copies):
                result = subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-Command",
                        "Start-Process -FilePath $args[0] -Verb PrintTo -ArgumentList ('\"' + $args[1] + '\"')",
                        str(target),
                        printer,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        result.stderr.strip()
                        or "Windows n’a pas pu transmettre le PDF à l’imprimante."
                    )
            return
        if not shutil.which("lp"):
            raise RuntimeError("Le service d’impression CUPS (commande lp) est indisponible.")
        result = subprocess.run(
            ["lp", "-d", printer, "-n", str(copies), str(target)],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Le service d’impression a refusé le document.")


class RevolutionPreview(tk.Toplevel):
    """Small offline interactive wireframe preview of a turned profile."""

    def __init__(self, parent: tk.Misc, stations: list[tuple[float, float]]) -> None:
        super().__init__(parent, class_="Loucodiworkshop")
        self.title("Vue 3D de la pièce de révolution — Lou Còdi Workshop")
        self.geometry("900x650")
        self.configure(bg="#DCE4ED")
        self.stations = stations
        self.yaw = -0.65
        self.pitch = 0.45
        self._drag_start: tuple[int, int, float, float] | None = None
        header = tk.Frame(self, bg=NAVY, padx=18, pady=10)
        header.pack(fill="x")
        tk.Label(
            header,
            text="Vue 3D — pièce de révolution",
            bg=NAVY,
            fg="white",
            font=("Sans", 16, "bold"),
        ).pack(side="left")
        tk.Label(
            header,
            text="Glissez avec la souris pour faire tourner la pièce",
            bg=NAVY,
            fg="#CBDFF5",
        ).pack(side="right")
        controls = ttk.Frame(self, padding=(14, 8))
        controls.pack(fill="x")
        ttk.Label(controls, text="Matériau :").pack(side="left")
        self.material_var = tk.StringVar(value="Aluminium")
        material = ttk.Combobox(
            controls,
            textvariable=self.material_var,
            values=("Aluminium", "Acier", "Bronze", "Plastique bleu"),
            state="readonly",
            width=16,
        )
        material.pack(side="left", padx=(6, 18))
        material.bind("<<ComboboxSelected>>", lambda _event: self._draw())
        self.wireframe_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            controls,
            text="Afficher le maillage",
            variable=self.wireframe_var,
            command=self._draw,
        ).pack(side="left")
        ttk.Label(
            controls,
            text="Rendu local léger — éclairage simulé",
        ).pack(side="right")
        self.canvas = tk.Canvas(self, bg="#F7FAFD", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=12, pady=12)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Escape>", lambda _event: self.destroy())
        self.after_idle(self._draw)

    def _press(self, event: tk.Event[tk.Misc]) -> None:
        self._drag_start = (event.x, event.y, self.yaw, self.pitch)

    def _drag(self, event: tk.Event[tk.Misc]) -> None:
        if self._drag_start is None:
            return
        start_x, start_y, yaw, pitch = self._drag_start
        self.yaw = yaw + (event.x - start_x) * 0.01
        self.pitch = max(-1.45, min(1.45, pitch + (event.y - start_y) * 0.01))
        self._draw()

    def _project(self, point: tuple[float, float, float], scale: float) -> tuple[float, float, float]:
        x, y, z = point
        cosine_yaw, sine_yaw = math.cos(self.yaw), math.sin(self.yaw)
        x1 = cosine_yaw * x + sine_yaw * z
        z1 = -sine_yaw * x + cosine_yaw * z
        cosine_pitch, sine_pitch = math.cos(self.pitch), math.sin(self.pitch)
        y1 = cosine_pitch * y - sine_pitch * z1
        depth = sine_pitch * y + cosine_pitch * z1
        return (
            self.canvas.winfo_width() / 2 + x1 * scale,
            self.canvas.winfo_height() / 2 - y1 * scale,
            depth,
        )

    def _draw(self) -> None:
        self.canvas.delete("all")
        if self.canvas.winfo_width() < 10:
            return
        minimum_x = min(x for x, _radius in self.stations)
        maximum_x = max(x for x, _radius in self.stations)
        center_x = (minimum_x + maximum_x) / 2
        maximum_radius = max(radius for _x, radius in self.stations)
        extent = max(maximum_x - minimum_x, maximum_radius * 2, 1)
        scale = min(self.canvas.winfo_width(), self.canvas.winfo_height()) * 0.72 / extent
        rings: list[list[tuple[float, float, float]]] = []
        divisions = 32
        for x, radius in self.stations:
            rings.append(
                [
                    self._project(
                        (
                            x - center_x,
                            radius * math.cos(2 * math.pi * index / divisions),
                            radius * math.sin(2 * math.pi * index / divisions),
                        ),
                        scale,
                    )
                    for index in range(divisions)
                ]
            )
        materials = {
            "Aluminium": (184, 194, 204),
            "Acier": (105, 120, 132),
            "Bronze": (181, 118, 55),
            "Plastique bleu": (43, 116, 181),
        }
        base_color = materials.get(self.material_var.get(), materials["Aluminium"])
        facets: list[tuple[float, list[float], str]] = []
        cosine_yaw, sine_yaw = math.cos(self.yaw), math.sin(self.yaw)
        cosine_pitch, sine_pitch = math.cos(self.pitch), math.sin(self.pitch)
        light = (-0.35, 0.55, 0.75)
        for ring_index in range(len(rings) - 1):
            first, second = rings[ring_index], rings[ring_index + 1]
            for index in range(divisions):
                following = (index + 1) % divisions
                points = (first[index], second[index], second[following], first[following])
                theta = 2 * math.pi * (index + 0.5) / divisions
                normal_y, normal_z = math.cos(theta), math.sin(theta)
                normal_x_view = sine_yaw * normal_z
                normal_z_view = cosine_yaw * normal_z
                normal_y_view = cosine_pitch * normal_y - sine_pitch * normal_z_view
                normal_depth = sine_pitch * normal_y + cosine_pitch * normal_z_view
                diffuse = max(
                    0.0,
                    normal_x_view * light[0]
                    + normal_y_view * light[1]
                    + normal_depth * light[2],
                )
                highlight = max(0.0, normal_depth) ** 12 * 0.35
                brightness = min(1.25, 0.38 + diffuse * 0.62 + highlight)
                color = "#{:02x}{:02x}{:02x}".format(
                    *(min(255, round(channel * brightness)) for channel in base_color)
                )
                facets.append(
                    (
                        sum(point[2] for point in points) / 4,
                        [coordinate for point in points for coordinate in point[:2]],
                        color,
                    )
                )
        for _depth, coordinates, color in sorted(facets, key=lambda facet: facet[0]):
            self.canvas.create_polygon(
                *coordinates,
                fill=color,
                outline="#698096" if self.wireframe_var.get() else color,
                width=1,
            )
        if self.wireframe_var.get():
            for ring in rings:
                coordinates = [coordinate for point in ring + [ring[0]] for coordinate in point[:2]]
                self.canvas.create_line(*coordinates, fill="#405E78", width=1)
        self.canvas.create_text(
            18,
            18,
            text=f"Longueur : {(maximum_x - minimum_x) * 25.4 / 72:.1f} mm   •   Ø maxi : {maximum_radius * 2 * 25.4 / 72:.1f} mm",
            anchor="nw",
            fill=NAVY,
            font=("Sans", 11, "bold"),
        )
