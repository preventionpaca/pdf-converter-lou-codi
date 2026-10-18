import copy
import math
import zipfile
from itertools import pairwise
from pathlib import Path

import pytest
from pypdf import PdfReader
from PIL import Image, ImageDraw

from lou_codi_pdf_converter.services.canvas_document import (
    FLOW_BREAK_TOKEN,
    CanvasDocument,
    PageObject,
    export_canvas_pdf,
    flowed_text_for_object,
    pages_for_object,
    resolve_dynamic_text,
    table_cell_colors,
    text_frame_line_capacity,
    wrapped_text_lines,
)
from lou_codi_pdf_converter.services.geometry import Segment
from lou_codi_pdf_converter.ui.document_editor import (
    DocumentEditorWindow,
    aligned_text_x,
    dimension_label_layout,
    dimension_line_geometry,
    driving_dimension_translation,
    draw_styled_rectangle,
    edge_coincidence_translation,
    expanded_group_indices,
    merge_mirrored_outlines,
    normalize_external_text,
    objects_bounds,
    paragraph_alignment_at,
    parse_tabular_clipboard,
    point_hits_rotation_handle,
    polygon_area,
    revolution_axis_target,
    revolution_stations,
    resized_circle_diameter,
    rotated_rectangle_points,
    rotation_step_for_objects,
    snapped_rotation_delta,
    text_style_at,
    transform_object_assembly,
    union_axis_aligned_rectangles,
)


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
        ]
    )
    document.save(project)
    restored = CanvasDocument.load(project)
    export_canvas_pdf(restored, target)

    assert restored.objects[1].text == "Bonjour Lou Còdi"
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


def test_landscape_document_and_linked_charts_export(tmp_path: Path) -> None:
    table = PageObject("table", 0, 30, 30, 250, 100, text="Janvier\t10\nFévrier\t20")
    bars = PageObject("chart", 0, 30, 160, 250, 160, source_id=table.object_id, fill="bar")
    pie = PageObject("chart", 0, 310, 160, 250, 160, source_id=table.object_id, fill="pie")
    document = CanvasDocument(
        objects=[table, bars, pie],
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


def test_rotated_text_frame_keeps_all_corners_around_the_same_centre() -> None:
    item = PageObject("text", 0, 10, 20, 100, 40, rotation=90)

    points = rotated_rectangle_points(item)

    expected = [(80.0, -10.0), (80.0, 90.0), (40.0, 90.0), (40.0, -10.0)]
    for point, expected_point in zip(points, expected, strict=True):
        assert point == pytest.approx(expected_point)


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


def test_text_highlight_only_applies_inside_its_text_range() -> None:
    item = PageObject(
        "text", 0, 0, 0, 200, 50, text="bonjour monde",
        text_styles=[{"start": 8, "end": 13, "highlight": "#FFF176"}],
    )

    assert text_style_at(item, 2)["highlight"] == ""
    assert text_style_at(item, 10)["highlight"] == "#FFF176"


def test_text_alignment_uses_actual_rendered_width() -> None:
    assert aligned_text_x(300, 80, 10, "left") == 10
    assert aligned_text_x(300, 80, 10, "center") == 110
    assert aligned_text_x(300, 80, 10, "right") == 210


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
