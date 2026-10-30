import copy
import math
import re
import zipfile
from itertools import pairwise
from pathlib import Path

import pytest
import pymupdf
from pypdf import PdfReader
from PIL import Image, ImageDraw

from lou_codi_pdf_converter.services.canvas_document import (
    FLOW_BREAK_TOKEN,
    CanvasDocument,
    PageObject,
    append_canvas_document,
    export_canvas_pdf,
    flowed_text_context,
    flowed_text_for_object,
    pages_for_object,
    resolve_dynamic_text,
    table_cell_colors,
    text_frame_line_capacity,
    _text_flow_style_lookup,
    wrapped_text_lines,
    wrapped_text_ranges,
)
from lou_codi_pdf_converter.services.geometry import Segment, angle_at_vertex
from lou_codi_pdf_converter.ui.document_editor import (
    DocumentEditorWindow,
    _replace_text_ranges,
    _slice_text_ranges,
    aligned_text_x,
    dimension_label_layout,
    dimension_line_geometry,
    driving_dimension_translation,
    draw_styled_rectangle,
    edge_coincidence_translation,
    clipboard_html_image_sources,
    compact_text_style_runs,
    constrained_right_triangle_vertices,
    extract_clipboard_html,
    fitted_table_cell_text,
    expanded_group_indices,
    editor_text_style_runs,
    inline_editor_font_size,
    inline_editor_padding,
    merge_editor_text_styles,
    merge_mirrored_outlines,
    normalize_external_text,
    normalize_plain_paste,
    normalize_rich_plain_fallback,
    objects_bounds,
    object_rotation_snap_points,
    paragraph_alignment_at,
    parse_tabular_clipboard,
    parse_tabular_clipboard_html,
    parse_rich_clipboard_html,
    parse_rich_clipboard_html_outside_tables,
    parse_rich_clipboard_rtf,
    proportional_resize,
    remap_text_ranges_after_edit,
    point_hits_rotation_handle,
    nearest_rotation_snap_point,
    polygon_area,
    revolution_axis_target,
    revolution_stations,
    resolved_text_styles,
    resized_circle_diameter,
    rich_text_fragment_boundaries,
    rich_clipboard_matches_plain,
    safe_pillow_color,
    slope_angle_and_percent,
    rotated_rectangle_points,
    rotation_step_for_objects,
    snapped_rotation_delta,
    stable_table_height_after_cell_edit,
    table_cell_editor_size,
    text_style_at,
    transform_object_assembly,
    union_axis_aligned_rectangles,
    available_font_families,
)


def test_append_canvas_document_remaps_pages_and_relationships() -> None:
    first = CanvasDocument(page_count=2)
    root = PageObject("text", 0, 10, 10, 100, 30, text="A", group="g")
    child = PageObject(
        "text", 1, 10, 10, 100, 30, text="B", group="g", source_id=root.object_id
    )
    root.flow_next_id = child.object_id
    second = CanvasDocument(page_count=2, objects=[root, child])

    append_canvas_document(first, second)

    assert first.page_count == 4
    assert [item.page for item in first.objects] == [2, 3]
    assert first.objects[0].object_id != root.object_id
    assert first.objects[0].flow_next_id == first.objects[1].object_id
    assert first.objects[1].source_id == first.objects[0].object_id
    assert first.objects[0].group == first.objects[1].group != "g"


def test_document_tabs_keep_independent_documents_and_history() -> None:
    editor = DocumentEditorWindow.__new__(DocumentEditorWindow)
    first = CanvasDocument(objects=[PageObject("text", 0, 1, 2, 3, 4, text="Premier")])
    second = CanvasDocument(objects=[PageObject("text", 0, 1, 2, 3, 4, text="Second")])
    editor.document = first
    editor._saved_document = copy.deepcopy(first)
    editor.project_path = Path("premier.cod")
    editor.last_export = None
    editor.current_page = 0
    editor.zoom = 1.15
    editor.undo_stack = []
    editor.redo_stack = []
    editor.selected = None
    editor.selected_indices = set()
    editor._document_tabs = [{}, {"document": second}]
    editor._active_document_tab = 0

    editor._store_active_document_tab("Premier")
    editor._document_tabs[1].update(
        saved_document=copy.deepcopy(second), project_path=None, last_export=None,
        current_page=0, zoom=0.8, undo_stack=[], redo_stack=[], title="Second",
    )
    editor._restore_document_tab(1)

    assert editor.document.objects[0].text == "Second"
    assert editor.zoom == 0.8
    assert editor.project_path is None


def test_menu_cleanup_ignores_descendant_destroy_events() -> None:
    editor = DocumentEditorWindow.__new__(DocumentEditorWindow)
    calls: list[str] = []
    editor._dismiss_main_menus = lambda: calls.append("dismiss")  # type: ignore[method-assign]

    editor._dismiss_main_menus_on_window_event(type("Event", (), {"widget": object()})())
    assert calls == []

    editor._dismiss_main_menus_on_window_event(type("Event", (), {"widget": editor})())
    assert calls == ["dismiss"]


def test_close_from_menu_unposts_before_deferred_window_close() -> None:
    editor = DocumentEditorWindow.__new__(DocumentEditorWindow)
    calls: list[str] = []
    editor._dismiss_main_menus = lambda: calls.append("dismiss")  # type: ignore[method-assign]
    editor._request_close = lambda: calls.append("close")  # type: ignore[method-assign]
    editor.after_idle = lambda callback: (calls.append("defer"), callback())  # type: ignore[method-assign]

    editor._request_close_from_menu()

    assert calls == ["dismiss", "defer", "close"]


def test_available_font_families_includes_local_fonts_in_alphabetic_order(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "lou_codi_pdf_converter.ui.document_editor.installed_families",
        lambda: ("Zeta", "Fira Sans", "Arimo"),
    )

    families = available_font_families()

    assert "Fira Sans" in families
    assert families == tuple(sorted(families, key=str.casefold))


def test_slope_angle_and_percent_handles_inclines_and_verticals() -> None:
    angle, percent = slope_angle_and_percent((0, 0), (100, -25))
    vertical_angle, vertical_percent = slope_angle_and_percent((4, 2), (4, 40))

    assert angle == pytest.approx(14.036243)
    assert percent == pytest.approx(25.0)
    assert vertical_angle == 90.0
    assert math.isinf(vertical_percent)


@pytest.mark.parametrize(
    ("point_index", "target"),
    ((0, (20.0, 15.0)), (1, (130.0, 45.0)), (2, (-20.0, 95.0)), (3, (5.0, 7.0))),
)
def test_right_triangle_handle_drag_keeps_angle_a_locked(
    point_index: int, target: tuple[float, float]
) -> None:
    original = [(0.0, 0.0), (100.0, 0.0), (0.0, 60.0), (0.0, 0.0)]

    moved = constrained_right_triangle_vertices(original, point_index, target)

    assert moved[-1] == moved[0]
    assert angle_at_vertex(moved[1], moved[0], moved[2]) == pytest.approx(90.0)


def test_linked_frame_text_metadata_can_be_edited_in_local_coordinates() -> None:
    ranges = [
        {"start": 0, "end": 5, "bold": True},
        {"start": 6, "end": 11, "italic": True},
        {"start": 12, "end": 18, "underline": True},
    ]

    assert _slice_text_ranges(ranges, 6, 5) == [
        {"start": 0, "end": 5, "italic": True}
    ]
    replaced = _replace_text_ranges(
        ranges,
        6,
        5,
        [{"start": 0, "end": 8, "italic": True, "color": "#FF0000"}],
        8,
    )

    assert replaced == [
        {"start": 0, "end": 5, "bold": True},
        {"start": 6, "end": 14, "italic": True, "color": "#FF0000"},
        {"start": 15, "end": 21, "underline": True},
    ]


def test_inline_editor_uses_canvas_pixel_metrics_and_insets() -> None:
    assert inline_editor_font_size(12, 1.0) == -12
    assert inline_editor_font_size(12, 1.15) == -14
    assert inline_editor_font_size("invalid", 1.0) == -12
    assert inline_editor_padding(1.0) == (14, 6)
    assert inline_editor_padding(1.15) == (16, 7)
    assert DocumentEditorWindow._tk_font_family("Sans-serif") == "DejaVu Sans"
    assert DocumentEditorWindow._tk_font_family("Serif") == "DejaVu Serif"


def test_rich_text_fragment_boundaries_only_keep_visible_style_changes() -> None:
    normal = {"bold": False, "color": "#000000"}
    strong = {"bold": True, "color": "#000000"}
    lookup = [normal] * 5 + [strong] * 4 + [normal] * 6
    links = [
        {"start": 1, "end": 3, "hyperlink": "https://before.example"},
        {"start": 7, "end": 12, "hyperlink": "https://visible.example"},
        {"start": 14, "end": 18, "hyperlink": "https://after.example"},
    ]

    assert rich_text_fragment_boundaries(lookup, links, 4, 13) == [4, 5, 7, 9, 12, 13]


def test_compact_text_style_runs_flattens_nested_browser_spans() -> None:
    item = PageObject(
        "text",
        0,
        0,
        0,
        100,
        50,
        text="abcdefghij",
        text_styles=[
            {"start": 0, "end": 10, "font_family": "Sans-serif", "color": "#333333"},
            {"start": 2, "end": 8, "bold": True},
            {"start": 4, "end": 6, "color": "#CC0000"},
            {"start": 6, "end": 8, "bold": True},
        ],
    )

    compacted = compact_text_style_runs(item, len(item.text))
    normalized = copy.copy(item)
    normalized.text_styles = compacted

    assert len(compacted) == 5
    assert resolved_text_styles(normalized, len(item.text)) == resolved_text_styles(
        item, len(item.text)
    )
    assert all(
        compacted[index]["end"] <= compacted[index + 1]["start"]
        for index in range(len(compacted) - 1)
    )


def test_text_chain_redraw_keeps_previous_raster_until_replacement_is_ready() -> None:
    events: list[tuple[str, object]] = []

    class CanvasRecorder:
        def find_withtag(self, tag: str) -> tuple[int, ...]:
            return {
                "object:0": (10,),
                "resize-start:0": (11,),
                "resize-end:0": (12,),
            }.get(tag, ())

        def delete(self, item: object) -> None:
            events.append(("delete", item))

    item = PageObject("text", 0, 0, 0, 100, 50, text="Texte")
    editor = DocumentEditorWindow.__new__(DocumentEditorWindow)
    editor.document = CanvasDocument(objects=[item])
    editor.current_page = 0
    editor.canvas = CanvasRecorder()
    editor._editing_object_id = ""
    editor._editing_widget = None
    editor._editing_dialog = None
    editor._draw_object = lambda index, candidate: events.append(("draw", index))

    editor._redraw_text_chain(item)

    assert events == [
        ("draw", 0),
        ("delete", 10),
        ("delete", 11),
        ("delete", 12),
    ]


def test_text_flow_style_lookup_preserves_overlapping_partial_styles() -> None:
    frame = PageObject(
        "text",
        0,
        0,
        0,
        100,
        50,
        text="abcd",
        text_styles=[
            {"start": 0, "end": 4, "bold": True},
            {"start": 1, "end": 3, "italic": True},
        ],
    )

    lookup = _text_flow_style_lookup(frame, len(frame.text))

    assert lookup[0] == ("Sans-serif", 12, True, False)
    assert lookup[1] == ("Sans-serif", 12, True, True)
    assert lookup[3] == ("Sans-serif", 12, True, False)


def test_preview_style_lookup_preserves_overlapping_partial_styles() -> None:
    frame = PageObject(
        "text",
        0,
        0,
        0,
        100,
        50,
        text="abcd",
        text_styles=[
            {"start": 0, "end": 4, "bold": True, "color": "#CC0000"},
            {"start": 1, "end": 3, "italic": True},
        ],
    )

    lookup = resolved_text_styles(frame, len(frame.text))

    assert lookup[0]["bold"] is True
    assert lookup[0]["italic"] is False
    assert lookup[1]["bold"] is True
    assert lookup[1]["italic"] is True
    assert lookup[1]["color"] == "#CC0000"


def test_control_diagonal_resize_preserves_original_proportions() -> None:
    assert proportional_resize(200, 100, 300, 120) == (300, 150)
    assert proportional_resize(200, 100, 210, 180) == (360, 180)


def test_linked_frame_can_copy_previous_frame_appearance_independently() -> None:
    first = PageObject(
        "text", 0, 10, 10, 200, 80,
        fill="#FFF9C4", border_color="#7B2CBF", border_width=5,
        border_style="dotted",
    )
    second = PageObject(
        "text", 0, 10, 110, 140, 60,
        fill="transparent", border_color="#000000", border_width=0.5,
        border_style="solid", rotation=25,
    )
    first.flow_next_id = second.object_id
    editor = DocumentEditorWindow.__new__(DocumentEditorWindow)
    editor.document = CanvasDocument(objects=[first, second])
    editor.selected = 1
    editor.selected_indices = {1}
    editor._checkpoint = lambda: None
    editor._render = lambda: None
    editor.status = _StatusRecorder()

    editor._copy_previous_text_frame_appearance()

    assert (second.fill, second.border_color, second.border_width, second.border_style) == (
        first.fill, first.border_color, first.border_width, first.border_style
    )
    assert (second.width, second.height, second.rotation) == (140, 60, 25)


def test_office_html_clipboard_keeps_styles_and_lists() -> None:
    html = (
        '<p><span style="font-family:Times New Roman;font-size:14pt;color:#123456">'
        '<b>Titre</b></span></p><ul><li><i>Premier point</i></li>'
        '<li>Second point</li></ul>'
    )

    text, styles = parse_rich_clipboard_html(html)

    assert text == "Titre\n• Premier point\n• Second point"
    assert any(run.get("bold") and run["start"] == 0 for run in styles)
    assert any(run.get("italic") and text[run["start"] : run["end"]] == "Premier point" for run in styles)
    assert any(run.get("font_family") == "Serif" and run.get("font_size") == 14 for run in styles)
    assert rich_clipboard_matches_plain(text, "Titre\n· Premier point\n· Second point")


def test_mixed_office_html_keeps_text_around_table_and_shape_images() -> None:
    html = (
        '<style>.important{font-weight:bold}</style>'
        '<p class="important">Texte avant</p>'
        '<table><tr><td>A</td><td>B</td></tr></table>'
        '<img src="data:image/png;base64,AAAA">'
        '<p>Texte après</p>'
    )

    text, styles = parse_rich_clipboard_html_outside_tables(html)

    assert text == "Texte avant\nTexte après"
    assert any(run.get("bold") and text[run["start"] : run["end"]] == "Texte avant" for run in styles)
    assert clipboard_html_image_sources(html) == ["data:image/png;base64,AAAA"]


def test_office_rtf_clipboard_keeps_common_character_styles() -> None:
    rtf = (
        r"{\rtf1\ansi{\fonttbl{\f0 Arial;}{\f1 Times New Roman;}}"
        r"{\colortbl;\red18\green52\blue86;\red255\green241\blue118;}"
        r"\f1\fs28\cf1\b Titre\b0\par "
        r"\f0\fs22 texte \i italique\i0  et \ul souligne\ulnone  "
        r"\highlight2 marque\highlight0.}"
    )

    text, styles = parse_rich_clipboard_rtf(rtf)

    assert text == "Titre\ntexte italique et souligne marque."
    assert any(run.get("bold") and text[run["start"] : run["end"]] == "Titre" for run in styles)
    assert any(run.get("italic") and "italique" in text[run["start"] : run["end"]] for run in styles)
    assert any(run.get("underline") and "souligne" in text[run["start"] : run["end"]] for run in styles)
    assert any(run.get("highlight") == "#FFF176" and "marque" in text[run["start"] : run["end"]] for run in styles)
    assert any(run.get("font_size") == 14 and run.get("color") == "#123456" for run in styles)


def test_office_cf_html_header_does_not_disable_rich_paste() -> None:
    html = '<html><body><p><b>Saisie Word</b> <u>soulignée</u></p></body></html>'
    header = (
        "Version:1.0\r\n"
        "StartHTML:0000000105\r\n"
        "EndHTML:0000000178\r\n"
        "StartFragment:0000000117\r\n"
        "EndFragment:0000000164\r\n"
    )
    payload = header + html
    start = len(header)
    payload = re.sub(
        r"StartHTML:\d+",
        f"StartHTML:{start:010d}",
        payload,
    )
    payload = re.sub(
        r"EndHTML:\d+",
        f"EndHTML:{len(payload):010d}",
        payload,
    )

    extracted = extract_clipboard_html(payload)
    text, styles = parse_rich_clipboard_html(payload)

    assert extracted == html
    assert text == "Saisie Word soulignée"
    assert any(run.get("bold") for run in styles)
    assert any(run.get("underline") for run in styles)


def test_office_html_clipboard_reads_css_classes_and_ignores_list_marker_glyphs() -> None:
    html = """
    <html><head><style>
      .titre { font-weight: 700; font-style: italic; text-decoration: underline; }
      .rouge { color: #cc0000; }
    </style></head><body>
      <p class="titre">Titre important</p>
      <ul><li><span style="mso-list:Ignore">\uf0b7<span>&nbsp;</span></span>
      <span class="rouge"><b>Premier point</b></span></li></ul>
    </body></html>
    """

    text, styles = parse_rich_clipboard_html(html)

    assert text == "Titre important\n• Premier point"
    title = next(run for run in styles if text[run["start"] : run["end"]] == "Titre important")
    point = next(run for run in styles if "Premier point" in text[run["start"] : run["end"]])
    assert title["bold"] is True
    assert title["italic"] is True
    assert title["underline"] is True
    assert point["bold"] is True
    assert point["color"] == "#CC0000"
    assert "\uf0b7" not in text


def test_rich_clipboard_matching_tolerates_office_list_markers() -> None:
    rich = "Titre\n• Premier point\n• Deuxième point"
    plain = "Titre\n\uf0b7 Premier point\n□ Deuxième point"

    assert rich_clipboard_matches_plain(rich, plain)


def test_plain_paste_removes_office_bullets_symbol_font_and_indentation() -> None:
    source = "\t\uf0b7\tPremier point\n    • Deuxième point\n\tTexte ordinaire"

    assert normalize_plain_paste(source) == "Premier point\nDeuxième point\nTexte ordinaire"


def test_rich_paste_fallback_replaces_office_symbol_bullets_without_squares() -> None:
    source = "·\uf0b7« Premier point »\n\uf0a7 Deuxième point"

    assert normalize_rich_plain_fallback(source) == (
        "• « Premier point »\n• Deuxième point"
    )


def test_imported_table_cell_editor_is_readable_without_exceeding_the_page() -> None:
    assert table_cell_editor_size(55, 28, 650, 900) == (60, 35)
    assert table_cell_editor_size(800, 700, 650, 900) == (650, 405)


def test_editing_a_verbose_cell_does_not_expand_every_table_row() -> None:
    assert stable_table_height_after_cell_edit(310, 13) == 312
    assert stable_table_height_after_cell_edit(600, 13) == 600


def test_styled_rectangle_draws_real_gaps_for_dashed_and_dotted_borders() -> None:
    for style in ("dashed", "dotted"):
        image = Image.new("RGB", (80, 40), "white")
        draw_styled_rectangle(
            ImageDraw.Draw(image), (2, 2, 77, 37), color="black", width=2, style=style
        )
        top_edge = [image.getpixel((x, 2)) for x in range(3, 77)]
        assert (0, 0, 0) in top_edge
        assert (255, 255, 255) in top_edge


def test_paragraph_alignment_uses_local_run_without_changing_other_text() -> None:
    item = PageObject(
        "text",
        0,
        0,
        0,
        200,
        80,
        text="Première ligne\nDeuxième ligne",
        align="left",
        paragraph_alignments=[{"start": 15, "end": 29, "align": "center"}],
    )

    assert paragraph_alignment_at(item, 3) == "left"
    assert paragraph_alignment_at(item, 18) == "center"


def test_polygon_area_accepts_open_and_closed_contours() -> None:
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    assert polygon_area(square) == 100.0
    assert polygon_area([*square, square[0]]) == 100.0
    assert polygon_area(square[:2]) == 0.0


def test_dimension_line_geometry_places_parallel_extension_line() -> None:
    assert dimension_line_geometry((0.0, 0.0), (100.0, 0.0), (20.0, 30.0)) == (
        (0.0, 30.0),
        (100.0, 30.0),
    )
    inclined = dimension_line_geometry((0.0, 0.0), (30.0, 40.0), (10.0, 20.0))
    assert inclined is not None
    start, end = inclined
    assert math.isclose(end[0] - start[0], 30.0)
    assert math.isclose(end[1] - start[1], 40.0)
    assert dimension_line_geometry((1.0, 1.0), (1.0, 1.0), (2.0, 3.0)) is None


def test_dimension_label_follows_line_and_stays_above_it() -> None:
    x, y, angle = dimension_label_layout((0.0, 50.0), (100.0, 50.0))
    assert (x, y, angle) == (50.0, 38.0, 0.0)
    x, y, angle = dimension_label_layout((0.0, 0.0), (100.0, 100.0))
    assert y < 50.0
    assert math.isclose(angle, -45.0)


def test_circle_resize_uses_the_dominant_pointer_axis() -> None:
    assert resized_circle_diameter(100.0, 30.0, 5.0) == 130.0
    assert resized_circle_diameter(100.0, 3.0, -25.0) == 75.0
    assert resized_circle_diameter(25.0, -40.0, 0.0) == 20.0


def test_associative_dimension_follows_its_referenced_objects() -> None:
    first = PageObject("line", 0, 10, 20, 0, 100)
    second = PageObject("line", 0, 110, 20, 0, 100)
    dimension = PageObject(
        "dimension", 0, 10, 0, 100, 0, text="35.28",
        points=[[10, 20], [110, 20]],
        dimension_refs=[
            {"object_id": first.object_id, "edge": 0, "t": 0.0},
            {"object_id": second.object_id, "edge": 0, "t": 0.0},
        ],
    )
    editor = DocumentEditorWindow.__new__(DocumentEditorWindow)
    editor.document = CanvasDocument(objects=[first, second, dimension])

    second.x = 160
    editor._update_associative_dimensions()

    assert dimension.points == [[10.0, 20.0], [160.0, 20.0]]
    assert (dimension.x, dimension.y, dimension.width, dimension.height) == (10.0, 0.0, 150.0, 0.0)
    assert dimension.text == "52.92"


def test_dimension_snap_detects_circle_center_midpoint_and_intersection() -> None:
    circle = PageObject("shape", 0, 100, 100, 80, 80, shape="circle")
    midpoint_line = PageObject("line", 0, 20, 250, 80, 0)
    horizontal = PageObject("line", 0, 100, 320, 120, 0)
    vertical = PageObject("line", 0, 160, 280, 0, 80)
    editor = DocumentEditorWindow.__new__(DocumentEditorWindow)
    editor.document = CanvasDocument(objects=[circle, midpoint_line, horizontal, vertical])
    editor.current_page = 0
    editor.zoom = 1.0

    point, label, reference = editor._dimension_reference_at(140, 140)
    assert point == (140.0, 140.0)
    assert label == "centre"
    assert reference["kind"] == "center"

    point, label, reference = editor._dimension_reference_at(60, 250)
    assert point == (60.0, 250.0)
    assert label == "milieu"
    point, label, reference = editor._dimension_reference_at(160, 320)
    assert point == (160.0, 320.0)
    assert label == "intersection"
    assert reference["kind"] == "intersection"


class _StatusRecorder:
    def __init__(self) -> None:
        self.text = ""

    def configure(self, *, text: str) -> None:
        self.text = text


class _BooleanValue:
    def __init__(self, value: bool) -> None:
        self.value = value

    def get(self) -> bool:
        return self.value


def test_measurement_label_contains_only_requested_fields() -> None:
    editor = DocumentEditorWindow.__new__(DocumentEditorWindow)
    editor.document = CanvasDocument()
    editor.measurement_label_vars = {
        key: _BooleanValue(key == "area")
        for key in ("distance", "angle", "perimeter", "area", "segments")
    }
    rectangle = PageObject(
        "polyline", 0, 0, 0, 100, 50,
        points=[[0, 0], [100, 0], [100, 50], [0, 50], [0, 0]],
    )

    label = editor._measurement_label_for_item(rectangle)

    assert label.startswith("A = ")
    assert "segment" not in label
    assert "P =" not in label


def test_canvas_document_round_trip_and_pdf_export(tmp_path: Path) -> None:
    project = tmp_path / "modele.loucodi-document"
    target = tmp_path / "resultat.pdf"
    document = CanvasDocument(
        objects=[
            PageObject("mask", 0, 20, 20, 120, 30),
            PageObject("text", 0, 35, 28, 300, 50, text="Bonjour Lou Còdi", bold=True),
            PageObject(
                "polyline", 0, 40, 90, 100, 80,
                points=[[0, 0], [100, 0], [0, 80], [0, 0]],
                shape="right_triangle_geometry",
                show_dimensions=True,
                show_angles=True,
                show_slope=True,
            ),
        ]
    )
    document.save(project)
    restored = CanvasDocument.load(project)
    export_canvas_pdf(restored, target)

    assert restored.objects[1].text == "Bonjour Lou Còdi"
    assert restored.objects[2].show_dimensions is True
    assert restored.objects[2].show_angles is True
    assert restored.objects[2].show_slope is True
    assert len(PdfReader(target).pages) == 1
    assert zipfile.is_zipfile(project)


def test_cod_embeds_images_and_survives_removal_of_the_source(tmp_path: Path) -> None:
    image_path = tmp_path / "illustration.png"
    Image.new("RGB", (40, 30), "red").save(image_path)
    project = tmp_path / "autonome.cod"
    document = CanvasDocument(
        objects=[
            PageObject(
                "image", 0, 20, 20, 120, 90, image_path=str(image_path)
            )
        ]
    )

    document.save(project)
    image_path.unlink()
    restored = CanvasDocument.load(project)

    restored_image = Path(restored.objects[0].image_path)
    assert restored_image.is_file()
    assert Image.open(restored_image).size == (40, 30)
    with zipfile.ZipFile(project) as archive:
        assert "document.json" in archive.namelist()
        assert any(name.startswith("assets/images/") for name in archive.namelist())


def test_template_flag_round_trip(tmp_path: Path) -> None:
    target = tmp_path / "courrier.cod"
    CanvasDocument(is_template=True).save(target)

    assert CanvasDocument.load(target).is_template is True


def test_save_as_template_keeps_current_document_independent(
    tmp_path: Path, monkeypatch
) -> None:
    current = tmp_path / "travail.cod"
    target = tmp_path / "modele_courrier.cod"
    editor = DocumentEditorWindow.__new__(DocumentEditorWindow)
    editor.document = CanvasDocument(
        objects=[PageObject("text", 0, 10, 10, 100, 30, text="Courrier")]
    )
    editor.project_path = current
    editor.status = _StatusRecorder()
    editor._commit_inline_editor = lambda **_kwargs: None
    monkeypatch.setattr(
        "lou_codi_pdf_converter.ui.document_editor.settings_path",
        lambda: tmp_path / "configuration.json",
    )
    monkeypatch.setattr(
        "lou_codi_pdf_converter.ui.document_editor.choose_save_path",
        lambda *_args, **_kwargs: target,
    )

    assert editor._save_as_template() is True

    assert CanvasDocument.load(target).is_template is True
    assert editor.project_path == current
    assert editor.document.is_template is False


def test_save_as_creates_an_independent_project_without_overwriting_current(
    tmp_path: Path, monkeypatch
) -> None:
    original = tmp_path / "essai.loucodi-document"
    original_document = CanvasDocument(objects=[PageObject("text", 0, 10, 10, 100, 30, text="Original")])
    original_document.save(original)

    editor = DocumentEditorWindow.__new__(DocumentEditorWindow)
    editor.document = CanvasDocument(objects=[PageObject("text", 0, 10, 10, 100, 30, text="Copie modifiée")])
    editor.project_path = original
    editor.status = _StatusRecorder()
    editor._commit_inline_editor = lambda **_kwargs: None
    editor._project_directory = lambda: tmp_path
    monkeypatch.setattr(
        "lou_codi_pdf_converter.ui.document_editor.choose_save_path",
        lambda *_args, **_kwargs: tmp_path / "essai-conserve.loucodi-document",
    )

    editor._save_as()

    copied = tmp_path / "essai-conserve.loucodi-document"
    assert editor.project_path == copied
    assert CanvasDocument.load(original).objects[0].text == "Original"
    assert CanvasDocument.load(copied).objects[0].text == "Copie modifiée"
    assert editor.status.text == "Projet enregistré : essai-conserve.loucodi-document"


def test_unsaved_change_detection_compares_with_last_saved_document() -> None:
    editor = DocumentEditorWindow.__new__(DocumentEditorWindow)
    editor.document = CanvasDocument()
    editor._saved_document = copy.deepcopy(editor.document)
    editor._editing_widget = None

    assert editor._has_unsaved_changes() is False

    editor.document.objects.append(PageObject("text", 0, 10, 10, 100, 30, text="Nouveau"))

    assert editor._has_unsaved_changes() is True


def test_measurement_scale_survives_project_roundtrip(tmp_path: Path) -> None:
    target = tmp_path / "plan.loucodi-document"
    document = CanvasDocument(measurement_scale=25.0)

    document.save(target)

    assert CanvasDocument.load(target).measurement_scale == 25.0


def test_object_level_survives_project_roundtrip(tmp_path: Path) -> None:
    target = tmp_path / "plans.loucodi-document"
    document = CanvasDocument(
        objects=[PageObject("shape", 0, 10, 10, 20, 20, level=1000)]
    )

    document.save(target)

    assert CanvasDocument.load(target).objects[0].level == 1000


def test_legacy_transparent_mask_exports_as_visible_white_mask(tmp_path: Path) -> None:
    target = tmp_path / "masque.pdf"
    document = CanvasDocument(
        objects=[PageObject("mask", 0, 10, 10, 80, 40, fill="transparent")]
    )

    export_canvas_pdf(document, target)

    assert target.is_file()
    assert target.stat().st_size > 0


def test_table_cells_keep_multiline_text_links_and_images(tmp_path: Path) -> None:
    target = tmp_path / "tableau.loucodi-document"
    source_image = tmp_path / "exemple.png"
    Image.new("RGB", (12, 10), "blue").save(source_image)
    document = CanvasDocument(
        objects=[
            PageObject(
                "table", 0, 10, 10, 200, 100,
                table_cells=[[{
                    "text": "Première ligne\nDeuxième ligne",
                    "hyperlink": "https://example.com",
                    "image_path": str(source_image),
                }]],
            )
        ]
    )

    document.save(target)

    cell = CanvasDocument.load(target).objects[0].table_cells[0][0]
    assert cell["text"] == "Première ligne\nDeuxième ligne"
    assert cell["hyperlink"] == "https://example.com"
    assert Path(cell["image_path"]).is_file()


def test_project_with_pdf_background_loads_before_archive_closes(tmp_path: Path) -> None:
    background = tmp_path / "fond.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((72, 72), "Document source")
        pdf.save(background)
    project = tmp_path / "avec-fond.loucodi-document"

    CanvasDocument(source_pdf=str(background)).save(project)
    restored = CanvasDocument.load(project)

    assert Path(restored.source_pdf).is_file()
    with pymupdf.open(restored.source_pdf) as pdf:
        assert "Document source" in pdf[0].get_text()


def test_table_border_settings_survive_project_roundtrip(tmp_path: Path) -> None:
    target = tmp_path / "bordures.loucodi-document"
    table = PageObject(
        "table", 0, 10, 10, 200, 100,
        table_outer_border_width=3.0,
        table_inner_border_width=0.5,
        table_row_border_widths={"1": 2.5},
        table_border_ranges=[{"top": 0.0, "left": 0.0, "bottom": 1.0, "right": 2.0, "width": 3.0}],
    )

    CanvasDocument(objects=[table]).save(target)
    restored = CanvasDocument.load(target).objects[0]

    assert restored.table_outer_border_width == 3.0
    assert restored.table_inner_border_width == 0.5
    assert restored.table_row_border_widths == {"1": 2.5}
    assert restored.table_border_ranges == [
        {"top": 0.0, "left": 0.0, "bottom": 1.0, "right": 2.0, "width": 3.0}
    ]


def test_table_visual_style_survives_roundtrip_and_alternates_rows(tmp_path: Path) -> None:
    target = tmp_path / "tableau-style.cod"
    table = PageObject("table", 0, 10, 10, 200, 100, table_style="blue")

    CanvasDocument(objects=[table]).save(target)
    restored = CanvasDocument.load(target).objects[0]

    assert restored.table_style == "blue"
    assert table_cell_colors("blue", 0) == ("#193F6A", "#FFFFFF")
    assert table_cell_colors("blue", 1)[0] != table_cell_colors("blue", 2)[0]
    assert table_cell_colors("green", 0) == ("#087F6A", "#FFFFFF")
    assert table_cell_colors("plain", 3) == ("#FFFFFF", "#000000")


def test_merged_table_cells_and_alignment_survive_roundtrip_and_pdf_export(tmp_path: Path) -> None:
    project = tmp_path / "cellules-fusionnees.loucodi-document"
    target = tmp_path / "cellules-fusionnees.pdf"
    table = PageObject(
        "table", 0, 20, 20, 240, 120,
        table_cells=[
            [
                {"text": "Titre", "horizontal_align": "center", "vertical_align": "middle"},
                {"text": ""},
            ],
            [{"text": "A"}, {"text": "B"}],
        ],
        table_merges=[[0, 0, 1, 2]],
    )

    CanvasDocument(objects=[table]).save(project)
    restored_document = CanvasDocument.load(project)
    restored = restored_document.objects[0]
    export_canvas_pdf(restored_document, target)

    assert restored.table_merges == [[0, 0, 1, 2]]
    assert restored.table_cells[0][0]["horizontal_align"] == "center"
    assert restored.table_cells[0][0]["vertical_align"] == "middle"
    assert target.is_file()


def test_table_rows_and_columns_can_be_inserted_and_deleted() -> None:
    table = PageObject(
        "table",
        0,
        20,
        20,
        200,
        100,
        table_cells=[
            [{"text": "A"}, {"text": "B"}],
            [{"text": "C"}, {"text": "D"}],
        ],
    )
    editor = DocumentEditorWindow.__new__(DocumentEditorWindow)
    editor.document = CanvasDocument(objects=[table])
    editor.selected = 0
    editor.selected_indices = {0}
    editor._active_table_cell = (table.object_id, 0, 0)
    editor._editing_widget = None
    editor._commit_inline_editor = lambda **_kwargs: None
    editor._checkpoint = lambda: None
    editor._render = lambda: None
    editor.status = _StatusRecorder()

    editor._change_table_structure("insert_row_after")
    editor._change_table_structure("insert_column_after")

    assert len(table.table_cells) == 3
    assert all(len(row) == 3 for row in table.table_cells)
    assert table.table_cells[0][0]["text"] == "A"

    editor._change_table_structure("delete_row")
    editor._change_table_structure("delete_column")

    assert len(table.table_cells) == 2
    assert all(len(row) == 2 for row in table.table_cells)


def test_pdf_export_contains_a_standard_clickable_uri_link(tmp_path: Path) -> None:
    target = tmp_path / "lien.pdf"
    document = CanvasDocument(
        objects=[
            PageObject(
                "shape", 0, 20, 20, 180, 40,
                shape="rectangle", hyperlink="https://example.com",
            )
        ]
    )

    export_canvas_pdf(document, target)

    annotation = PdfReader(target).pages[0]["/Annots"][0].get_object()
    assert annotation["/Subtype"] == "/Link"
    assert annotation["/A"]["/S"] == "/URI"
    assert annotation["/A"]["/URI"] == "https://example.com"


def test_pdf_export_ignores_legacy_link_attached_to_an_entire_text_frame(tmp_path: Path) -> None:
    target = tmp_path / "ancien-lien-zone.pdf"
    document = CanvasDocument(
        objects=[
            PageObject(
                "text", 0, 20, 20, 180, 40,
                text="Site Lou Còdi", hyperlink="https://example.com",
            )
        ]
    )

    export_canvas_pdf(document, target)

    assert "/Annots" not in PdfReader(target).pages[0]


def test_pdf_export_links_only_the_selected_text_passage(tmp_path: Path) -> None:
    target = tmp_path / "liens-dans-texte.pdf"
    text = "Visiter Google puis Wikipédia"
    document = CanvasDocument(
        objects=[
            PageObject(
                "text", 0, 20, 20, 260, 50, text=text,
                text_links=[
                    {"start": 8, "end": 14, "hyperlink": "https://google.com"},
                    {"start": 20, "end": 29, "hyperlink": "https://wikipedia.org"},
                ],
            )
        ]
    )

    export_canvas_pdf(document, target)

    annotations = [annotation.get_object() for annotation in PdfReader(target).pages[0]["/Annots"]]
    assert {annotation["/A"]["/URI"] for annotation in annotations} == {
        "https://google.com", "https://wikipedia.org"
    }


def test_object_assembly_uses_a_bounding_rectangle_and_moves_as_one() -> None:
    first = PageObject("line", 0, 40, 20, -20, 40)
    second = PageObject("shape", 0, 80, 50, 30, 20, shape="rectangle")

    assert objects_bounds([first, second]) == (20, 20, 90, 50)

    transform_object_assembly([first, second], 100, 200, 180, 100)

    assert objects_bounds([first, second]) == (100, 200, 180, 100)
    assert first.width == -40
    assert second.x == 220


def test_selecting_one_member_expands_symmetry_to_the_whole_assembly() -> None:
    group = "assembly-1"
    objects = [
        PageObject("shape", 0, 0, 0, 20, 20, group=group),
        PageObject("shape", 0, 30, 0, 20, 20, group=group),
        PageObject("line", 0, 60, 0, 0, 100, shape="axis"),
    ]

    assert expanded_group_indices(objects, {0, 2}) == {0, 1, 2}


def test_guided_edge_coincidence_only_requires_a_perpendicular_move() -> None:
    fixed = Segment(10, 50, 110, 50)
    moving = Segment(60, 20, 90, 20)

    assert edge_coincidence_translation(fixed, moving) == (0, 30)


def test_driving_dimension_keeps_the_moving_object_on_its_current_side() -> None:
    fixed = Segment(10, 50, 110, 50)
    moving = Segment(60, 20, 90, 20)

    dx, dy, start, end = driving_dimension_translation(
        fixed, moving, (75, 5), 20
    )

    assert (dx, dy) == (0, 10)
    assert start == (75, 50)
    assert end == (75, 30)


def test_two_touching_rectangles_become_one_shoulder_profile() -> None:
    contour = union_axis_aligned_rectangles(
        [(0, 20, 100, 100), (30, 0, 70, 20)]
    )

    assert contour[0] == contour[-1]
    assert set(contour[:-1]) == {
        (30, 0),
        (70, 0),
        (70, 20),
        (100, 20),
        (100, 100),
        (0, 100),
        (0, 20),
        (30, 20),
    }


def test_revolution_stations_use_the_largest_radius_at_each_abscissa() -> None:
    outline = [(0, 50), (0, 10), (40, 20), (40, 50), (0, 50)]

    assert revolution_stations(outline, 50) == [
        (0, 0),
        (0, 40),
        (40, 30),
        (40, 0),
    ]


def test_revolution_axis_guard_uses_symmetry_for_full_profile_and_edge_for_half() -> None:
    full = [[(0, 10), (40, 10), (40, 90), (0, 90), (0, 10)]]
    half = [[(0, 10), (40, 20), (40, 50), (0, 50), (0, 10)]]

    assert revolution_axis_target(full, full_profile=True, current_axis_y=35) == (
        50,
        "plan de symétrie",
    )
    assert revolution_axis_target(half, full_profile=False, current_axis_y=47) == (
        50,
        "bord de fermeture",
    )


def test_mirrored_profiles_merge_without_the_internal_axis_line() -> None:
    upper = [(0, 50), (0, 10), (40, 20), (40, 50), (0, 50)]
    lower = [(0, 50), (40, 50), (40, 80), (0, 90), (0, 50)]

    contour = merge_mirrored_outlines([upper, lower], 50)

    assert contour[0] == contour[-1]
    assert all(
        not (start[1] == end[1] == 50)
        for start, end in pairwise(contour)
    )


def test_mirrored_profile_merge_is_stable_with_reversed_points_and_rounding() -> None:
    upper = [(0, 50), (0, 10), (20, 10), (40, 30), (40, 50), (0, 50)]
    lower = list(
        reversed([(0, 50.0000001), (0, 90), (20, 90), (40, 70), (40, 50.0000001), (0, 50.0000001)])
    )

    contour = merge_mirrored_outlines([lower, upper], 50)

    assert (20, 10) in contour
    assert (20, 90) in contour
    assert contour[0] == contour[-1]


def test_mirrored_profile_merge_reconciles_duplicate_edges_and_axial_limits() -> None:
    upper = [(0, 50), (0, 10), (40, 20), (40, 50), (0, 50), (40, 50), (0, 50)]
    lower = [(0.02, 50), (40.03, 50), (40.03, 80), (0.02, 90), (0.02, 50)]

    contour = merge_mirrored_outlines([upper, lower], 50)

    assert contour[0] == contour[-1]
    assert contour[0][1] == 50


def test_page_scope_supports_all_and_ranges() -> None:
    item = PageObject("text", 0, 0, 0, 100, 30, text="Entête", pages="all")
    assert pages_for_object(item, 4) == [0, 1, 2, 3]

    item.pages = "1,3-4"
    assert pages_for_object(item, 5) == [0, 2, 3]


def test_dynamic_page_fields_are_resolved() -> None:
    assert resolve_dynamic_text("Page {{PAGE}} / {{PAGES}}", 1, 4) == "Page 2 / 4"


def test_text_can_flow_between_linked_frames() -> None:
    first = PageObject("text", 0, 10, 10, 120, 24, text="Un texte assez long pour continuer dans la seconde zone", font_size=12)
    second = PageObject("text", 1, 10, 10, 300, 24, font_size=12)
    first.flow_next_id = second.object_id

    first_part = flowed_text_for_object(first, [first, second])
    second_part = flowed_text_for_object(second, [first, second])

    assert first_part
    assert second_part
    assert f"{first_part} {second_part}" == first.text


def test_linked_frame_keeps_the_root_formatting_offset() -> None:
    text = "Début ordinaire puis suite colorée et importante"
    color_start = text.index("suite")
    first = PageObject(
        "text", 0, 10, 10, 120, 24, text=text, font_size=12,
        text_styles=[{
            "start": color_start, "end": len(text),
            "bold": True, "color": "#CC0000",
        }],
    )
    second = PageObject("text", 0, 10, 50, 300, 40, font_size=12)
    first.flow_next_id = second.object_id

    second_text, style_source, offset = flowed_text_context(second, [first, second])

    assert second_text
    assert style_source is first
    assert first.text[offset : offset + len(second_text)] == second_text
    assert offset <= color_start < offset + len(second_text)


def test_text_flow_respects_explicit_line_breaks() -> None:
    first = PageObject("text", 0, 10, 10, 180, 18, text="Première ligne\nDeuxième ligne", font_size=12)
    second = PageObject("text", 0, 10, 40, 180, 40, font_size=12)
    first.flow_next_id = second.object_id

    assert flowed_text_for_object(first, [first, second]) == "Première ligne"
    assert flowed_text_for_object(second, [first, second]) == "Deuxième ligne"

    before_move = flowed_text_for_object(second, [first, second])
    second.x += 75
    second.y += 40
    assert flowed_text_for_object(second, [first, second]) == before_move


def test_text_flow_can_be_forced_to_next_frame() -> None:
    first = PageObject("text", 0, 10, 10, 300, 80, text=f"Premier{FLOW_BREAK_TOKEN}Second")
    second = PageObject("text", 0, 10, 100, 300, 80)
    first.flow_next_id = second.object_id

    assert flowed_text_for_object(first, [first, second]) == "Premier"
    assert flowed_text_for_object(second, [first, second]) == "Second"


def test_linked_text_never_assigns_hidden_lines_to_a_frame() -> None:
    sentence = (
        "je sais pas si tu m'entends bien j'attends Barbara mon épouse qui va rentrer "
        "de la soutenance de thèse jeune femme médecine et moi je regarde la chaîne "
        "l'équipe je regarde des caisses à savon je continue de dicter mon message"
    )
    text = f"{sentence} {sentence}"
    first = PageObject("text", 0, 30, 30, 320, 90, text=text, font_size=12)
    second = PageObject("text", 0, 30, 150, 320, 90, font_size=12)
    first.flow_next_id = second.object_id

    first_part = flowed_text_for_object(first, [first, second])
    second_part = flowed_text_for_object(second, [first, second])

    assert len(wrapped_text_lines(first_part, first)) <= text_frame_line_capacity(first)
    assert len(wrapped_text_lines(second_part, second)) <= text_frame_line_capacity(second)
    assert second_part


def test_text_frame_wraps_between_words_with_an_inner_margin() -> None:
    frame = PageObject("text", 0, 0, 0, 105, 80, font_size=12)

    lines = wrapped_text_lines("bonjour magnifique monde entier", frame)

    assert " ".join(lines) == "bonjour magnifique monde entier"
    assert all(word in {"bonjour", "magnifique", "monde", "entier"} for line in lines for word in line.split())


def test_text_frame_wrap_uses_the_pasted_rich_font_size_and_weight() -> None:
    text = "Organiser une matinée éco-citoyenne à Cannes parcourir la ville jusqu’au littoral"
    plain = PageObject("text", 0, 0, 0, 300, 100, text=text, font_size=12)
    rich = copy.deepcopy(plain)
    rich.text_styles = [{
        "start": 0,
        "end": len(text),
        "font_family": "Serif",
        "font_size": 14,
        "bold": True,
    }]

    def deterministic_measure(
        _family: str, size: float, bold: bool, _italic: bool, value: str
    ) -> float:
        return len(value) * size * (0.62 if bold else 0.52)

    plain_lines = [line for line, _start, _end in wrapped_text_ranges(
        text, plain, measure=deterministic_measure
    )]
    rich_lines = [line for line, _start, _end in wrapped_text_ranges(
        text, rich, measure=deterministic_measure
    )]

    assert len(rich_lines) > len(plain_lines)
    assert "littoral" not in rich_lines[0]


def test_rich_wrapping_keeps_exact_source_offsets_for_preview() -> None:
    text = "Titre en gras\n• Première phrase très longue qui doit revenir à la ligne"
    frame = PageObject(
        "text", 0, 0, 0, 190, 100, text=text, font_size=12,
        text_styles=[{"start": 0, "end": 13, "font_size": 16, "bold": True}],
    )

    ranges = wrapped_text_ranges(text, frame)

    assert len(ranges) >= 3
    assert all(line == text[start:end] for line, start, end in ranges)


def test_preview_wrapping_can_use_the_inline_editors_scaled_metrics() -> None:
    text = "alpha beta gamma"
    frame = PageObject("text", 0, 0, 0, 80, 100, text=text, font_size=10)
    calls: list[tuple[str, float, bool, bool, str]] = []

    def measure(
        family: str, size: float, bold: bool, italic: bool, value: str
    ) -> float:
        calls.append((family, size, bold, italic, value))
        return len(value) * size

    ranges = wrapped_text_ranges(
        text, frame, measure=measure, measurement_scale=2.0
    )

    assert [line for line, _start, _end in ranges] == ["alpha", "beta", "gamma"]
    assert calls
    assert all(call[1] == 20 for call in calls)


def test_landscape_document_and_linked_charts_export(tmp_path: Path) -> None:
    table = PageObject("table", 0, 30, 30, 250, 100, text="Janvier\t10\nFévrier\t20")
    bars = PageObject("chart", 0, 30, 160, 250, 160, source_id=table.object_id, fill="bar")
    pie = PageObject("chart", 0, 310, 160, 250, 160, source_id=table.object_id, fill="pie")
    line = PageObject("chart", 0, 580, 160, 110, 160, source_id=table.object_id, fill="line")
    horizontal = PageObject(
        "chart", 0, 700, 160, 110, 160,
        source_id=table.object_id, fill="hbar", chart_data_orientation="rows",
    )
    document = CanvasDocument(
        objects=[table, bars, pie, line, horizontal],
        page_width=841.89,
        page_height=595.28,
    )
    target = tmp_path / "graphiques.pdf"

    export_canvas_pdf(document, target)

    page = PdfReader(target).pages[0]
    assert float(page.mediabox.width) > float(page.mediabox.height)


def test_technical_shapes_are_saved_and_exported(tmp_path: Path) -> None:
    project = tmp_path / "schema.loucodi-document"
    target = tmp_path / "schema.pdf"
    document = CanvasDocument(
        objects=[
            PageObject("shape", 0, 40, 40, 120, 70, shape="rectangle", fill="#DCEBFA"),
            PageObject("shape", 0, 190, 40, 100, 70, shape="ellipse", border_style="dashed"),
            PageObject("shape", 0, 320, 40, 140, 70, shape="arrow", fill="#F9E8C8"),
            PageObject("polyline", 0, 40, 150, 180, 80, points=[[0, 70], [40, 10], [120, 10], [180, 70]], border_width=1.5),
            PageObject("dimension", 0, 40, 260, 0, 45, text="15.88", border_width=1),
            PageObject("origin", 0, 40, 305, 0, 0),
            PageObject("line", 0, 40, 330, 180, 0, shape="axis", locked=True),
        ]
    )

    document.save(project)
    restored = CanvasDocument.load(project)
    export_canvas_pdf(restored, target)

    assert [item.shape for item in restored.objects[:3]] == ["rectangle", "ellipse", "arrow"]
    assert restored.objects[3].points[2] == [120, 10]
    assert restored.objects[-1].locked is True
    assert len(PdfReader(target).pages) == 1


def test_remove_hatches_keeps_their_source_shape() -> None:
    group = "hachures-1"
    source = PageObject(
        "polyline", 0, 10, 10, 100, 100,
        points=[[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]],
        shape="square_geometry", group=group,
    )
    hatches = [
        PageObject(
            "line", 0, 20 + offset, 20, 30, 30,
            group=group, source_id=source.object_id, shape="hatch",
        )
        for offset in range(4)
    ]
    editor = DocumentEditorWindow.__new__(DocumentEditorWindow)
    editor.document = CanvasDocument(objects=[source, *hatches])
    editor.selected_indices = set(range(5))
    editor.selected = 1
    editor.status = _StatusRecorder()
    editor._checkpoint = lambda: None
    editor._render = lambda: None

    editor._remove_selected_hatches()

    assert editor.document.objects == [source]
    assert source.group == ""
    assert "4 hachure(s) supprimée(s)" in editor.status.text


def test_remove_legacy_line_only_hatch_group() -> None:
    group = "anciennes-hachures"
    hatches = [
        PageObject("line", 0, 20 + offset, 20, 30, 30, group=group)
        for offset in range(8)
    ]
    unrelated = PageObject("line", 0, 200, 200, 50, 0)
    editor = DocumentEditorWindow.__new__(DocumentEditorWindow)
    editor.document = CanvasDocument(objects=[*hatches, unrelated])
    editor.selected_indices = set(range(8))
    editor.selected = 0
    editor.status = _StatusRecorder()
    editor._checkpoint = lambda: None
    editor._render = lambda: None

    editor._remove_selected_hatches()

    assert editor.document.objects == [unrelated]
    assert "8 hachure(s) supprimée(s)" in editor.status.text


def test_rotating_hatched_polyline_rotates_hatches_about_the_same_pivot() -> None:
    group = "hachures-tournees"
    source = PageObject(
        "polyline", 0, 10, 20, 100, 60,
        points=[[0, 0], [100, 0], [100, 60], [0, 60], [0, 0]],
        group=group,
    )
    hatch = PageObject(
        "line", 0, 30, 30, 40, 20,
        group=group, source_id=source.object_id, shape="hatch",
    )
    editor = DocumentEditorWindow.__new__(DocumentEditorWindow)
    editor.document = CanvasDocument(objects=[source, hatch])
    editor.selected_indices = {0}
    editor.selected = 0
    editor._checkpoint = lambda: None
    editor._render = lambda: None

    editor._rotate_selected_degrees(90)

    assert editor.selected_indices == {0, 1}
    assert math.isclose(hatch.x, 80.0, abs_tol=1e-6)
    assert math.isclose(hatch.y, 20.0, abs_tol=1e-6)
    assert math.isclose(hatch.width, -20.0, abs_tol=1e-6)
    assert math.isclose(hatch.height, 40.0, abs_tol=1e-6)


def test_close_contour_closes_one_selected_polyline_without_tolerance_dialog() -> None:
    polyline = PageObject(
        "polyline", 0, 10, 20, 100, 60,
        points=[[0, 0], [100, 0], [80, 60]],
    )
    editor = DocumentEditorWindow.__new__(DocumentEditorWindow)
    editor.document = CanvasDocument(objects=[polyline])
    editor.selected_indices = {0}
    editor.selected = 0
    editor.status = _StatusRecorder()
    editor._checkpoint = lambda: None
    editor._render = lambda: None

    editor._close_contour()

    assert polyline.points == [[0, 0], [100, 0], [80, 60], [0, 0]]
    assert DocumentEditorWindow._closed_outline(polyline)
    assert "Polyligne fermée" in editor.status.text


def test_horizontal_mirror_moves_hatches_with_their_polyline() -> None:
    group = "hachures-symetrie"
    source = PageObject(
        "polyline", 0, 10, 20, 100, 60,
        points=[[0, 0], [100, 0], [100, 60], [0, 60], [0, 0]],
        group=group,
    )
    hatch = PageObject(
        "line", 0, 30, 30, 40, 20,
        group=group, source_id=source.object_id, shape="hatch",
    )
    editor = DocumentEditorWindow.__new__(DocumentEditorWindow)
    editor.document = CanvasDocument(objects=[source, hatch])
    editor.selected_indices = {0}
    editor.selected = 0
    editor._checkpoint = lambda: None
    editor._render = lambda: None

    editor._mirror_selected("horizontal")

    assert math.isclose(hatch.x, 90.0, abs_tol=1e-6)
    assert math.isclose(hatch.y, 30.0, abs_tol=1e-6)
    assert math.isclose(hatch.width, -40.0, abs_tol=1e-6)
    assert math.isclose(hatch.height, 20.0, abs_tol=1e-6)


def test_rotation_handle_uses_shortest_delta_and_configured_step() -> None:
    assert snapped_rotation_delta(-90, -52, 15) == 45
    assert snapped_rotation_delta(170, -170, 5) == 20
    assert snapped_rotation_delta(-170, 170, 10) == -20


def test_rotation_pivot_snap_points_cover_line_ends_and_middle() -> None:
    item = PageObject("line", 0, 10, 20, 40, 20)

    assert object_rotation_snap_points(item) == [
        ("extrémité", 10, 20),
        ("milieu", 30, 30),
        ("extrémité", 50, 40),
    ]


def test_rotation_pivot_prefers_nearest_point_and_respects_tolerance() -> None:
    item = PageObject("shape", 0, 10, 20, 100, 40)

    assert nearest_rotation_snap_point([item], (61, 41), 4) == ("centre", 60, 40)
    assert nearest_rotation_snap_point([item], (80, 80), 4) is None


def test_rotation_pivot_is_persisted_in_document_archive(tmp_path: Path) -> None:
    path = tmp_path / "pivot.loucodi-document"
    document = CanvasDocument(objects=[PageObject(
        "shape", 0, 10, 20, 100, 40,
        rotation_pivot_x=25.5, rotation_pivot_y=30.25,
    )])

    document.save(path)
    loaded = CanvasDocument.load(path)

    assert loaded.objects[0].rotation_pivot_x == 25.5
    assert loaded.objects[0].rotation_pivot_y == 30.25


def test_rotated_text_frame_keeps_all_corners_around_the_same_centre() -> None:
    item = PageObject("text", 0, 10, 20, 100, 40, rotation=90)

    points = rotated_rectangle_points(item)

    expected = [(80.0, -10.0), (80.0, 90.0), (40.0, 90.0), (40.0, -10.0)]
    for point, expected_point in zip(points, expected, strict=True):
        assert point == pytest.approx(expected_point)


def test_text_preview_rotates_the_rendered_pixels_not_only_the_selection_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    editor = object.__new__(DocumentEditorWindow)
    editor.zoom = 1.0
    item = PageObject(
        "text", 0, 0, 0, 100, 40,
        text="Texte tourné", rotation=90,
        border_width=1.5, border_style="dotted",
    )
    monkeypatch.setattr(
        "lou_codi_pdf_converter.ui.document_editor.ImageTk.PhotoImage",
        lambda image: image,
    )

    rendered = editor._text_preview(item, item.text, 100, 40)

    assert rendered.size == (40, 100)
    assert rendered.getbbox() is not None


def test_text_preview_tolerates_malformed_imported_formatting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    editor = object.__new__(DocumentEditorWindow)
    editor.zoom = 1.0
    item = PageObject(
        "text", 0, 0, 0, 100, 40,
        text="Texte importé", rotation=90,
        fill="couleur inconnue", border_color="",
        text_styles=[{
            "start": "début", "end": None, "font_size": "grand",
            "color": "pas-une-couleur", "highlight": "invalide",
        }],
    )
    monkeypatch.setattr(
        "lou_codi_pdf_converter.ui.document_editor.ImageTk.PhotoImage",
        lambda image: image,
    )

    rendered = editor._text_preview(item, item.text, 100, 40)

    assert rendered.size == (40, 100)
    assert rendered.getbbox() is not None


def test_emergency_text_preview_still_clips_and_rotates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    editor = object.__new__(DocumentEditorWindow)
    editor.zoom = 1.0
    item = PageObject(
        "text", 0, 0, 0, 120, 35,
        text="Première ligne\nDeuxième ligne\nTexte qui ne doit pas déborder",
        rotation=90,
    )
    monkeypatch.setattr(
        "lou_codi_pdf_converter.ui.document_editor.ImageTk.PhotoImage",
        lambda image: image,
    )

    rendered = editor._basic_text_preview(item, item.text, 120, 35)

    assert rendered.size == (35, 120)
    assert rendered.getbbox() is not None


def test_pdf_export_rotates_text_and_its_border_without_losing_content(tmp_path: Path) -> None:
    target = tmp_path / "texte-tourne.pdf"
    document = CanvasDocument(objects=[PageObject(
        "text", 0, 100, 100, 240, 100,
        text="Rotation complète", rotation=30,
        border_width=1.5, border_style="dotted",
    )])

    export_canvas_pdf(document, target)

    with pymupdf.open(target) as pdf:
        page = pdf[0]
        assert "Rotation complète" in page.get_text()
        text_line = next(
            line
            for block in page.get_text("dict")["blocks"]
            for line in block.get("lines", [])
        )
        assert text_line["dir"][0] == pytest.approx(math.cos(math.radians(30)), abs=1e-4)
        assert text_line["dir"][1] == pytest.approx(math.sin(math.radians(30)), abs=1e-4)
        assert page.get_drawings()


def test_pdf_export_retries_a_tight_word_text_frame_instead_of_leaving_it_blank(
    tmp_path: Path,
) -> None:
    target = tmp_path / "cadre-serre.pdf"
    document = CanvasDocument(objects=[PageObject(
        "text", 0, 20, 20, 220, 28,
        text="Une première ligne assez longue\nUne deuxième ligne assez longue",
        font_size=12,
        text_line_height=12,
    )])

    export_canvas_pdf(document, target)

    with pymupdf.open(target) as pdf:
        assert "Une première ligne" in pdf[0].get_text()


def test_layout_rich_objects_use_quarter_turns_for_guided_rotation() -> None:
    assert rotation_step_for_objects([PageObject("text", 0, 0, 0, 100, 40)], 15) == 15
    assert rotation_step_for_objects([PageObject("table", 0, 0, 0, 100, 40)], 5) == 90
    assert rotation_step_for_objects([PageObject("polyline", 0, 0, 0, 100, 40)], 15) == 15


def test_character_style_only_applies_inside_its_text_range() -> None:
    item = PageObject(
        "text", 0, 0, 0, 200, 50, text="bonjour monde", color="#000000",
        text_styles=[{"start": 8, "end": 13, "bold": True, "color": "#CC0000"}],
    )

    assert text_style_at(item, 2)["bold"] is False
    assert text_style_at(item, 2)["color"] == "#000000"
    assert text_style_at(item, 10)["bold"] is True
    assert text_style_at(item, 10)["color"] == "#CC0000"


def test_table_cell_character_style_is_resolved_without_formatting_the_whole_cell() -> None:
    table = PageObject(
        "table", 0, 0, 0, 200, 50,
        table_cells=[[{
            "text": "bonjour monde",
            "horizontal_align": "center",
            "bold": False,
            "text_styles": [{"start": 8, "end": 13, "bold": True}],
        }]],
    )
    editor = DocumentEditorWindow.__new__(DocumentEditorWindow)
    editor._editing_table_cell = (0, 0)
    editor._editing_style_tags = {}

    class WidgetWithoutLiveTags:
        @staticmethod
        def tag_names(_index: str) -> tuple[str, ...]:
            return ()

    plain = editor._inline_text_style_at(WidgetWithoutLiveTags(), table, 2)  # type: ignore[arg-type]
    emphasized = editor._inline_text_style_at(WidgetWithoutLiveTags(), table, 10)  # type: ignore[arg-type]

    assert plain["bold"] is False
    assert emphasized["bold"] is True


def test_text_highlight_only_applies_inside_its_text_range() -> None:
    item = PageObject(
        "text", 0, 0, 0, 200, 50, text="bonjour monde",
        text_styles=[{"start": 8, "end": 13, "highlight": "#FFF176"}],
    )

    assert text_style_at(item, 2)["highlight"] == ""
    assert text_style_at(item, 10)["highlight"] == "#FFF176"


def test_editor_preserves_imported_styles_when_a_new_style_is_added() -> None:
    item = PageObject(
        "text", 0, 0, 0, 200, 50, text="Titre important",
        text_styles=[{"start": 0, "end": 5, "bold": True, "color": "#CC0000"}],
    )

    merged = merge_editor_text_styles(
        item,
        item.text,
        item.text,
        item.text_styles,
        [{"start": 6, "end": 15, "italic": True, "highlight": "#FFF176"}],
    )
    result = copy.copy(item)
    result.text_styles = merged

    assert text_style_at(result, 2)["bold"] is True
    assert text_style_at(result, 2)["color"] == "#CC0000"
    assert text_style_at(result, 9)["italic"] is True
    assert text_style_at(result, 9)["highlight"] == "#FFF176"


def test_css_rgb_colours_are_normalised_for_the_tk_editor() -> None:
    html = (
        '<p style="color: rgb(33, 37, 41); '
        'background-color: rgb(255, 255, 255)">Texte Web</p>'
    )

    text, styles = parse_rich_clipboard_html(html)

    assert text == "Texte Web"
    assert styles == [{
        "start": 0,
        "end": 9,
        "color": "#212529",
        "highlight": "#FFFFFF",
    }]
    assert safe_pillow_color("rgb(33, 37, 41)", "#000000") == "#212529"


def test_inline_editor_receives_complete_styles_for_every_character() -> None:
    item = PageObject(
        "text", 0, 0, 0, 200, 50, text="Titre puis suite",
        underline=True,
        color="#123456",
        text_styles=[{"start": 0, "end": 5, "bold": True, "color": "#CC0000"}],
    )

    runs = editor_text_style_runs(item, len(item.text), item.text_styles)

    assert runs[0]["start"] == 0
    assert runs[-1]["end"] == len(item.text)
    assert all(run["underline"] is True for run in runs)
    assert runs[0]["bold"] is True
    assert runs[0]["color"] == "#CC0000"
    assert runs[-1]["color"] == "#123456"


def test_editor_remaps_imported_styles_after_text_edit_before_overlaying_new_style() -> None:
    item = PageObject(
        "text", 0, 0, 0, 200, 50, text="Bonjour monde",
        text_styles=[{"start": 8, "end": 13, "bold": True}],
    )
    new_text = "Bonjour beau monde"

    merged = merge_editor_text_styles(
        item,
        item.text,
        new_text,
        item.text_styles,
        [{"start": 0, "end": 7, "underline": True}],
    )
    result = copy.copy(item)
    result.text = new_text
    result.text_styles = merged

    assert text_style_at(result, 3)["underline"] is True
    assert text_style_at(result, 15)["bold"] is True


def test_editor_can_remove_an_imported_style_without_losing_other_formatting() -> None:
    item = PageObject(
        "text", 0, 0, 0, 200, 50, text="Titre rouge",
        text_styles=[{
            "start": 0, "end": 11, "bold": True, "color": "#CC0000",
        }],
    )

    merged = merge_editor_text_styles(
        item,
        item.text,
        item.text,
        item.text_styles,
        [{"start": 0, "end": 5, "bold": False, "color": "#CC0000"}],
    )
    result = copy.copy(item)
    result.text_styles = merged

    assert text_style_at(result, 2)["bold"] is False
    assert text_style_at(result, 2)["color"] == "#CC0000"
    assert text_style_at(result, 8)["bold"] is True


def test_text_alignment_uses_actual_rendered_width() -> None:
    assert aligned_text_x(300, 80, 10, "left") == 10
    assert aligned_text_x(300, 80, 10, "center") == 110
    assert aligned_text_x(300, 80, 10, "right") == 210


def test_text_frame_border_and_resize_keep_text_inside_safe_insets() -> None:
    text = "Une phrase assez longue pour vérifier la marge intérieure droite"
    wide = PageObject("text", 0, 0, 0, 260, 80, text=text, border_width=4)
    narrow = copy.deepcopy(wide)
    narrow.width = 150

    assert len(wrapped_text_lines(wide.text, wide)) < len(
        wrapped_text_lines(narrow.text, narrow)
    )
    assert text_frame_line_capacity(wide) == 3


def test_partial_style_selection_stays_partial_in_a_right_aligned_paragraph() -> None:
    item = PageObject(
        "text", 0, 0, 0, 240, 60, text="texte aligné à droite", align="right"
    )

    class InlineWidget:
        added: list[tuple[str, str, str]] = []

        @staticmethod
        def tag_names(_index: str) -> tuple[str, ...]:
            return ()

        @staticmethod
        def cget(_name: str) -> str:
            return "#FFFFFF"

        @staticmethod
        def tag_configure(_tag: str, **_options: object) -> None:
            return None

        @classmethod
        def tag_add(cls, tag: str, start: str, end: str) -> None:
            cls.added.append((tag, start, end))

        @staticmethod
        def tag_raise(_tag: str) -> None:
            return None

    editor = DocumentEditorWindow.__new__(DocumentEditorWindow)
    editor._editing_widget = InlineWidget()
    editor._editing_object_id = item.object_id
    editor._editing_selection_range = (6, 12)
    editor._editing_style_tags = {}
    editor._editing_table_cell = None
    editor.zoom = 1.0
    editor.status = _StatusRecorder()

    assert editor._apply_inline_text_style(item, {"bold": True}) is True
    assert InlineWidget.added[-1][1:] == (
        "1.0 + 6 chars",
        "1.0 + 12 chars",
    )


def test_zero_character_offset_from_tk_is_not_treated_as_an_error() -> None:
    class FirstCharacter:
        @staticmethod
        def count(*_args: object) -> None:
            return None

    assert DocumentEditorWindow._text_character_offset(FirstCharacter(), "1.0") == 0  # type: ignore[arg-type]


def test_rotation_handle_has_a_generous_but_bounded_hit_area() -> None:
    assert point_hits_rotation_handle((108, 108), (100, 100))
    assert point_hits_rotation_handle((115, 100), (100, 100))
    assert not point_hits_rotation_handle((116, 100), (100, 100))


def test_external_office_text_separators_become_line_breaks() -> None:
    assert normalize_external_text("un\vdeux\ftrois\u2028quatre\x00\u200b\u202e") == (
        "un\ndeux\ntrois\nquatre"
    )


def test_clipboard_image_file_uri_is_recognized(tmp_path: Path) -> None:
    image = tmp_path / "une image.png"
    image.write_bytes(b"not-needed-for-path-detection")

    result = DocumentEditorWindow._clipboard_file_from_text(
        f"copy\n{image.as_uri()}\n"
    )

    assert result == image


def test_spreadsheet_clipboard_becomes_an_editable_table() -> None:
    cells = parse_tabular_clipboard("Nom\tQuantité\nVis\t12\nÉcrou\t8")

    assert [[cell["text"] for cell in row] for row in cells] == [
        ["Nom", "Quantité"],
        ["Vis", "12"],
        ["Écrou", "8"],
    ]
    assert parse_tabular_clipboard("Un texte ordinaire") == []


def test_spreadsheet_html_clipboard_keeps_formula_styles_and_dimensions() -> None:
    html = """
    <table><tr style="height:24pt">
      <td style="width:90pt;background-color:#fff2cc;font-weight:bold;border:2px solid #000000">A</td>
      <td style="width:72pt;text-align:right" data-formula="=A1+2">3</td>
    </tr></table>
    """

    cells, widths, heights = parse_tabular_clipboard_html(html)

    assert cells[0][0]["text"] == "A"
    assert cells[0][0]["bold"] is True
    assert str(cells[0][0]["fill"]).upper() == "#FFF2CC"
    assert cells[0][0]["border_width"] == 1.5
    assert cells[0][1]["text"] == "=A1+2"
    assert cells[0][1]["horizontal_align"] == "right"
    assert widths == [90.0, 72.0]
    assert heights == [24.0]


def test_spreadsheet_clipboard_roundtrip_exports_visible_cell_values(tmp_path: Path) -> None:
    html = """
    <table>
      <tr><td>Nom</td><td>Quantité</td></tr>
      <tr><td>Vis</td><td>12</td></tr>
    </table>
    """
    cells, widths, heights = parse_tabular_clipboard_html(html)
    project = tmp_path / "tableau-excel.loucodi-document"
    target = tmp_path / "tableau-excel.pdf"
    document = CanvasDocument(objects=[PageObject(
        "table", 0, 70, 80, 300, 120,
        table_cells=cells,
        table_column_widths=widths,
        table_row_heights=heights,
        font_size=10,
    )])

    document.save(project)
    restored = CanvasDocument.load(project)
    export_canvas_pdf(restored, target)

    with pymupdf.open(target) as pdf:
        exported_text = "\n".join(page.get_text() for page in pdf)
    assert "Nom" in exported_text
    assert "Quantité" in exported_text
    assert "Vis" in exported_text
    assert "12" in exported_text


def test_spreadsheet_html_clipboard_resolves_office_css_classes_and_nested_formatting() -> None:
    html = """
    <style>
      .xlHeader { background-color:#ffe699; font-weight:bold; border:3px solid #203864; }
      .xlFormula { text-align:right; font-style:italic; }
    </style>
    <table><tr>
      <td class="xlHeader"><u>Titre</u></td>
      <td class="xlFormula" data-cell-formula="of:=A1*2">6</td>
    </tr></table>
    """

    cells, _widths, _heights = parse_tabular_clipboard_html(html)

    assert cells[0][0]["text"] == "Titre"
    assert cells[0][0]["bold"] is True
    assert cells[0][0]["underline"] is True
    assert str(cells[0][0]["fill"]).upper() == "#FFE699"
    assert cells[0][0]["border_width"] == 2.25
    assert cells[0][1]["text"] == "=A1*2"
    assert cells[0][1]["italic"] is True
    assert cells[0][1]["horizontal_align"] == "right"


def test_sparse_word_layout_table_remains_rich_flowing_text() -> None:
    html = """
    <table>
      <tr><td>Introduction assez longue pour être un paragraphe.</td><td></td></tr>
      <tr><td></td><td>Premier point</td></tr>
      <tr><td></td><td>Deuxième point</td></tr>
      <tr><td>Conclusion</td><td></td></tr>
      <tr><td></td><td></td></tr>
    </table>
    """

    cells, widths, heights = parse_tabular_clipboard_html(html)
    text, _styles = parse_rich_clipboard_html(html)

    assert cells == []
    assert widths == []
    assert heights == []
    assert "Introduction" in text
    assert "Premier point" in text


def test_html_table_keeps_partial_character_formatting_inside_a_cell() -> None:
    html = """
    <table><tr>
      <td>Texte <b>important</b> puis <span style="color:#ff0000">rouge</span></td>
      <td style="background-color:#00b050">Cellule verte</td>
    </tr></table>
    """

    cells, _widths, _heights = parse_tabular_clipboard_html(html)

    first = cells[0][0]
    assert first["text"] == "Texte important puis rouge"
    assert any(
        run.get("bold") and first["text"][run["start"] : run["end"]] == "important"
        for run in first["text_styles"]
    )
    assert any(
        str(run.get("color", "")).upper() == "#FF0000" and "rouge" in first["text"][run["start"] : run["end"]]
        for run in first["text_styles"]
    )
    assert str(cells[0][1]["fill"]).upper() == "#00B050"


def test_chart_uses_first_column_as_labels_and_selected_numeric_series() -> None:
    header, values = DocumentEditorWindow._chart_values(
        [["Élève", "Notes", "Absences"], ["Alice", "12", "1"], ["Bob", "15", "3"]],
        1,
    )

    assert header == "Notes"
    assert values == [("Alice", 12.0), ("Bob", 15.0)]

    series = DocumentEditorWindow._chart_series(
        [["Élève", "Notes", "Absences"], ["Alice", "12", "1"], ["Bob", "15", "3"]],
        [1, 2],
    )

    assert series == [
        ("Notes", [("Alice", 12.0), ("Bob", 15.0)]),
        ("Absences", [("Alice", 1.0), ("Bob", 3.0)]),
    ]

    oriented = DocumentEditorWindow._chart_oriented_rows(
        [["", "Notes", "Absences"], ["Alice", "12", "1"], ["Bob", "15", "3"]],
        "rows",
    )
    assert oriented == [
        ["", "Alice", "Bob"],
        ["Notes", "12", "15"],
        ["Absences", "1", "3"],
    ]
    assert DocumentEditorWindow._chart_series(oriented, [1, 2]) == [
        ("Alice", [("Notes", 12.0), ("Absences", 1.0)]),
        ("Bob", [("Notes", 15.0), ("Absences", 3.0)]),
    ]


def test_verbose_table_cell_is_fitted_and_clipped_to_its_own_rectangle() -> None:
    text, size = fitted_table_cell_text(
        "Informations financières très longues qui ne doivent pas déborder",
        70,
        18,
        12,
        bold=True,
    )

    assert size == 4
    assert text.endswith("…")
    assert text.count("\n") == 1


def test_image_rotation_and_symmetry_are_baked_into_pixels(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (40, 20), "red").save(source)
    item = PageObject("image", 0, 10, 20, 80, 40, image_path=str(source))
    editor = object.__new__(DocumentEditorWindow)
    editor.document = CanvasDocument(objects=[item])
    editor.selected = 0
    editor.selected_indices = {0}
    editor._checkpoint = lambda: None
    editor._render = lambda: None

    def replace(target: PageObject, image: Image.Image) -> None:
        path = tmp_path / f"edited-{image.width}-{image.height}.png"
        image.save(path)
        target.image_path = str(path)

    editor._replace_image_pixels = replace
    editor._rotate_selected_degrees(90)

    assert Image.open(item.image_path).size == (20, 40)
    assert (item.width, item.height) == (40, 80)
    editor._mirror_selected("horizontal")
    assert Path(item.image_path).is_file()


def test_live_drag_render_is_coalesced_until_the_pending_frame_runs() -> None:
    editor = object.__new__(DocumentEditorWindow)
    editor._live_render_after_id = None
    editor._rendering = False
    scheduled: list[tuple[int, object]] = []
    editor.after = lambda delay, callback: scheduled.append((delay, callback)) or "frame-1"

    editor._schedule_live_render()
    editor._schedule_live_render()
    editor._schedule_live_render()

    assert scheduled == [(33, editor._flush_live_render)]
    assert editor._live_render_after_id == "frame-1"


def test_live_drag_render_allows_next_frame_after_flush() -> None:
    editor = object.__new__(DocumentEditorWindow)
    editor._live_render_after_id = "frame-1"
    editor._rendering = False
    renders: list[bool] = []
    editor._render = lambda: renders.append(True)

    editor._flush_live_render()

    assert editor._live_render_after_id is None
    assert renders == [True]


def test_rich_text_ranges_survive_a_small_plain_text_edit() -> None:
    old_text = "Titre important et suite"
    new_text = "Titre très important et suite"
    ranges = [
        {"start": 0, "end": 5, "bold": True},
        {"start": 6, "end": 15, "italic": True},
    ]

    remapped = remap_text_ranges_after_edit(old_text, new_text, ranges)

    assert {"start": 0, "end": 5, "bold": True} in remapped
    assert any(run.get("italic") is True and run["end"] > run["start"] for run in remapped)


def test_editor_text_measurements_are_cached() -> None:
    editor = object.__new__(DocumentEditorWindow)
    calls: list[str] = []

    class FakeFont:
        def measure(self, value: str) -> int:
            calls.append(value)
            return len(value) * 7

    editor._tk_layout_font = lambda *_args: FakeFont()

    first = editor._measure_editor_text("Inter", 12, False, False, "Même texte")
    second = editor._measure_editor_text("Inter", 12, False, False, "Même texte")

    assert first == second == 70
    assert calls == ["Même texte"]
