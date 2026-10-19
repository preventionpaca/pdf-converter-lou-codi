from __future__ import annotations

import math
import tempfile
import uuid
from collections import defaultdict, deque
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

from .canvas_document import (
    A4_HEIGHT,
    A4_WIDTH,
    CanvasDocument,
    PageObject,
    text_frame_line_capacity,
    wrapped_text_lines,
)


def _font_family(name: str | None) -> str:
    lowered = (name or "").lower()
    if "courier" in lowered or "mono" in lowered:
        return "Monospace"
    if "times" in lowered or "serif" in lowered or "cambria" in lowered:
        return "Serif"
    return "Sans-serif"


def _inherited(run: object, paragraph: object, attribute: str, fallback: object) -> object:
    value = getattr(run, attribute, None)
    if value is None:
        value = getattr(getattr(run, "font", None), attribute, None)
    if value is not None:
        return value
    run_style = getattr(run, "style", None)
    value = getattr(getattr(run_style, "font", None), attribute, None)
    if value is not None:
        return value
    paragraph_style = getattr(paragraph, "style", None)
    value = getattr(getattr(paragraph_style, "font", None), attribute, None)
    return fallback if value is None else value


def _run_style(run: object, paragraph: object) -> dict[str, object]:
    size = _inherited(run, paragraph, "size", None)
    name = _inherited(run, paragraph, "name", None)
    color = getattr(getattr(getattr(run, "font", None), "color", None), "rgb", None)
    highlight = getattr(getattr(run, "font", None), "highlight_color", None)
    highlight_names = {
        "YELLOW": "#FFF176",
        "BRIGHT_GREEN": "#A7F3A1",
        "TURQUOISE": "#8BE9FD",
        "PINK": "#F8BBD0",
        "BLUE": "#90CAF9",
        "RED": "#EF9A9A",
        "DARK_BLUE": "#5C6BC0",
        "TEAL": "#80CBC4",
        "GREEN": "#81C784",
        "VIOLET": "#D8B4FE",
        "DARK_RED": "#C62828",
        "DARK_YELLOW": "#F9A825",
        "GRAY_50": "#9E9E9E",
        "GRAY_25": "#D6D6D6",
        "BLACK": "#000000",
    }
    return {
        "bold": bool(_inherited(run, paragraph, "bold", False)),
        "italic": bool(_inherited(run, paragraph, "italic", False)),
        "underline": bool(_inherited(run, paragraph, "underline", False)),
        "strikethrough": bool(_inherited(run, paragraph, "strike", False)),
        "font_family": _font_family(str(name) if name else None),
        "font_size": float(size.pt) if size is not None else 12.0,
        "color": f"#{color}" if color is not None else "#000000",
        "highlight": highlight_names.get(getattr(highlight, "name", ""), ""),
    }


def _paragraph_prefix(paragraph: object, counters: dict[str, int]) -> str:
    properties = getattr(getattr(paragraph, "_p", None), "pPr", None)
    numbered = properties is not None and properties.numPr is not None
    style_name = str(getattr(getattr(paragraph, "style", None), "name", "") or "")
    if not numbered and "list" not in style_name.lower():
        return ""
    if "number" in style_name.lower():
        counters[style_name] = counters.get(style_name, 0) + 1
        return f"{counters[style_name]}. "
    return "• "


def _embedded_image_queues(source: object) -> dict[str, deque[dict[str, object]]]:
    """Extract inline or floating pictures, preserving their Word display size."""
    directory = Path(tempfile.mkdtemp(prefix="lou-codi-docx-import-"))
    images: dict[str, deque[dict[str, object]]] = defaultdict(deque)
    body = getattr(getattr(source, "element", None), "body", None)
    for blip in body.xpath(".//a:blip") if body is not None else ():
        try:
            relationship_id = blip.get(qn("r:embed"))
            part = source.part.related_parts[relationship_id]
            container = blip.getparent()
            while container is not None and container.tag not in {
                qn("wp:inline"), qn("wp:anchor")
            }:
                container = container.getparent()
            extents = container.xpath("./wp:extent") if container is not None else []
            extent = extents[0] if extents else None
            width = float(extent.get("cx")) / 12700.0 if extent is not None else 144.0
            height = float(extent.get("cy")) / 12700.0 if extent is not None else 96.0
            suffix = Path(str(getattr(part, "filename", ""))).suffix.lower()
            if not suffix:
                suffix = {
                    "image/jpeg": ".jpg",
                    "image/png": ".png",
                    "image/gif": ".gif",
                    "image/tiff": ".tiff",
                    "image/bmp": ".bmp",
                    "image/webp": ".webp",
                }.get(str(getattr(part, "content_type", "")).lower(), ".bin")
            target = directory / f"{uuid.uuid4().hex}{suffix}"
            target.write_bytes(part.blob)
            images[relationship_id].append(
                {
                    "path": str(target),
                    "width": max(1.0, width),
                    "height": max(1.0, height),
                }
            )
        except (AttributeError, KeyError, OSError, TypeError, ValueError):
            continue
    return images


def import_docx_as_canvas(path: Path) -> CanvasDocument:
    """Import DOCX text, pictures, lists and formatting into editable objects."""
    source = Document(path)
    section = source.sections[0] if source.sections else None
    page_width = float(section.page_width.pt) if section and section.page_width else A4_WIDTH
    page_height = float(section.page_height.pt) if section and section.page_height else A4_HEIGHT
    margin_left = float(section.left_margin.pt) if section and section.left_margin else 42.0
    margin_right = float(section.right_margin.pt) if section and section.right_margin else 42.0
    margin_top = float(section.top_margin.pt) if section and section.top_margin else 42.0
    margin_bottom = float(section.bottom_margin.pt) if section and section.bottom_margin else 42.0
    width = max(120.0, page_width - margin_left - margin_right)
    height = max(100.0, page_height - margin_top - margin_bottom)

    parts: list[str] = []
    styles: list[dict[str, object]] = []
    alignments: list[dict[str, object]] = []
    image_placements: list[dict[str, object]] = []
    image_queues = _embedded_image_queues(source)
    counters: dict[str, int] = {}
    alignment_names = {0: "left", 1: "center", 2: "right", 3: "justify", 4: "justify"}
    for paragraph in source.paragraphs:
        if parts:
            parts.append("\n")
        paragraph_start = sum(len(part) for part in parts)
        prefix = _paragraph_prefix(paragraph, counters)
        parts.append(prefix)
        for run in paragraph.runs:
            value = run.text.replace("\v", "\n").replace("\f", "\n")
            if value:
                start = sum(len(part) for part in parts)
                parts.append(value)
                end = start + len(value)
                styles.append({"start": start, "end": end, **_run_style(run, paragraph)})
            for blip in run._r.xpath(".//a:blip"):
                relationship_id = blip.get(qn("r:embed"))
                if not relationship_id or not image_queues[relationship_id]:
                    continue
                image = image_queues[relationship_id].popleft()
                display_width = min(width, float(image["width"]))
                display_height = float(image["height"]) * display_width / float(image["width"])
                image_placements.append(
                    {
                        **image,
                        "width": display_width,
                        "height": display_height,
                        "position": sum(len(part) for part in parts),
                    }
                )
                # Reserve the picture's vertical space in the linked text flow.
                parts.append("\n" * max(1, math.ceil(display_height / 15.0)))
        paragraph_end = sum(len(part) for part in parts)
        alignment = alignment_names.get(int(paragraph.alignment), "left") if paragraph.alignment is not None else "left"
        if alignment != "left" and paragraph_end > paragraph_start:
            alignments.append(
                {"start": paragraph_start, "end": paragraph_end, "align": alignment}
            )

    text = "".join(parts)
    prototype = PageObject(
        "text", 0, margin_left, margin_top, width, height,
        text=text, fill="transparent", border_width=0,
        text_styles=styles, paragraph_alignments=alignments,
    )
    line_count = max(1, len(wrapped_text_lines(text, prototype)))
    capacity = max(1, text_frame_line_capacity(prototype))
    page_count = max(1, math.ceil(line_count / capacity))
    frames = [prototype]
    for page in range(1, page_count):
        frames.append(PageObject(
            "text", page, margin_left, margin_top, width, height,
            fill="transparent", border_width=0,
        ))
        frames[-2].flow_next_id = frames[-1].object_id
    image_objects: list[PageObject] = []
    for image in image_placements:
        preceding_lines = max(
            0,
            len(wrapped_text_lines(text[: int(image["position"])], prototype)) - 1,
        )
        page = min(page_count - 1, preceding_lines // capacity)
        line_on_page = preceding_lines % capacity
        image_objects.append(
            PageObject(
                "image",
                page,
                margin_left,
                margin_top + line_on_page * 15.0,
                float(image["width"]),
                float(image["height"]),
                image_path=str(image["path"]),
            )
        )
    return CanvasDocument(
        page_width=page_width,
        page_height=page_height,
        page_count=page_count,
        objects=frames + image_objects,
    )
