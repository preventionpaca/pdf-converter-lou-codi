from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pymupdf

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


@dataclass
class CanvasDocument:
    source_pdf: str = ""
    page_count: int = 1
    objects: list[PageObject] = field(default_factory=list)

    def save(self, path: Path) -> None:
        path.write_text(
            json.dumps(
                {
                    "format": 2,
                    "source_pdf": self.source_pdf,
                    "page_count": self.page_count,
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
            objects=[PageObject(**item) for item in data.get("objects", [])],
        )


def export_canvas_pdf(document: CanvasDocument, target: Path) -> None:
    source = Path(document.source_pdf) if document.source_pdf else None
    if source and source.is_file():
        pdf = pymupdf.open(source)
    else:
        pdf = pymupdf.open()

    while pdf.page_count < document.page_count:
        pdf.new_page(width=A4_WIDTH, height=A4_HEIGHT)
    if pdf.page_count == 0:
        pdf.new_page(width=A4_WIDTH, height=A4_HEIGHT)

    for item in document.objects:
        for page_number in pages_for_object(item, pdf.page_count):
            page = pdf[page_number]
            _draw_object(page, item)
    target.parent.mkdir(parents=True, exist_ok=True)
    pdf.save(target, garbage=4, deflate=True)
    pdf.close()


def _draw_object(page: pymupdf.Page, item: PageObject) -> None:
    rectangle = pymupdf.Rect(item.x, item.y, item.x + item.width, item.y + item.height)
    if item.kind == "mask":
        page.draw_rect(rectangle, color=_rgb(item.fill), fill=_rgb(item.fill), overlay=True)
    elif item.kind == "image" and Path(item.image_path).is_file():
        page.insert_image(rectangle, filename=item.image_path, keep_proportion=True, overlay=True)
    elif item.kind in {"text", "table"}:
        if item.kind == "table":
            _draw_table(page, rectangle, item)
        else:
            font_name = "hebi" if item.bold and item.italic else "hebo" if item.bold else "heit" if item.italic else "helv"
            page.insert_textbox(
                rectangle,
                item.text,
                fontsize=max(6, item.font_size),
                fontname=font_name,
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


def _draw_table(page: pymupdf.Page, rectangle: pymupdf.Rect, item: PageObject) -> None:
    rows = [row.split("\t") for row in item.text.splitlines() if row]
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


def _rgb(value: str) -> tuple[float, float, float]:
    clean = value.lstrip("#")
    if len(clean) != 6:
        return (0, 0, 0)
    try:
        return tuple(int(clean[index : index + 2], 16) / 255 for index in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return (0, 0, 0)
