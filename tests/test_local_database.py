import math
import sqlite3
from pathlib import Path
from unittest.mock import patch

from lou_codi_pdf_converter.paths import application_data_directory
from lou_codi_pdf_converter.services.canvas_document import PageObject
from lou_codi_pdf_converter.services.geometry import (
    Segment,
    angle_at_vertex,
    angle_between_segments,
    chamfer_segments,
    closest_point_on_segment,
    hatch_segments,
    join_segments,
    point_to_segment_distance,
    project_point_onto_line,
    reflect_point_across_line,
    split_at_intersection,
    split_closed_polyline_by_polyline,
    split_closed_polyline_by_segment,
    split_segment_by_closed_polyline,
)
from lou_codi_pdf_converter.services.local_database import (
    SCHEMA_VERSION,
    add_stock_sheet,
    initialize_database,
    list_stock_sheets,
    set_stock_sheet_status,
)
from lou_codi_pdf_converter.ui.document_editor import DocumentEditorWindow


def test_closest_point_on_segment_is_clamped_to_the_finite_edge() -> None:
    segment = Segment(10, 20, 30, 20)

    assert closest_point_on_segment(18, 27, segment) == (18, 20)
    assert closest_point_on_segment(42, 20, segment) == (30, 20)


def test_angle_between_segments_uses_the_smallest_undirected_angle() -> None:
    horizontal = Segment(0, 0, 10, 0)
    diagonal = Segment(0, 0, -10, -10)

    assert math.isclose(angle_between_segments(horizontal, diagonal), 45.0)


def test_angle_at_vertex_is_independent_of_click_direction() -> None:
    first = (10.0, 0.0)
    vertex = (0.0, 0.0)
    second = (0.0, 10.0)

    assert math.isclose(angle_at_vertex(first, vertex, second), 90.0)
    assert math.isclose(angle_at_vertex(second, vertex, first), 90.0)


def test_database_initialization_creates_business_schema(tmp_path: Path) -> None:
    target = initialize_database(tmp_path / "loucodi.db")

    with sqlite3.connect(target) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        version = connection.execute("SELECT version FROM schema_info").fetchone()[0]

    assert {"sheet_stock", "cutting_project", "cutting_part", "stock_remnant"} <= tables
    assert version == SCHEMA_VERSION


def test_stock_sheet_lifecycle_is_persisted_locally(tmp_path: Path) -> None:
    target = tmp_path / "loucodi.db"
    sheet_id = add_stock_sheet("MDF", "Bois", 2500, 1250, 18, 2, path=target)

    stock = list_stock_sheets(path=target, available_only=True)
    assert stock[0].id == sheet_id
    assert stock[0].quantity == 2

    set_stock_sheet_status(sheet_id, "scrap", path=target)
    assert list_stock_sheets(path=target, available_only=True) == []
    assert list_stock_sheets(path=target)[0].status == "scrap"


def test_application_data_directory_is_platform_specific(tmp_path: Path) -> None:
    with (
        patch("lou_codi_pdf_converter.paths.sys.platform", "win32"),
        patch.dict("os.environ", {"LOCALAPPDATA": str(tmp_path)}, clear=False),
    ):
        assert application_data_directory(create=False) == tmp_path / "LouCodi" / "PDFConverter"

    with (
        patch("lou_codi_pdf_converter.paths.sys.platform", "darwin"),
        patch.object(Path, "home", return_value=tmp_path),
    ):
        assert application_data_directory(create=False) == (
            tmp_path / "Library" / "Application Support" / "LouCodi" / "PDFConverter"
        )


def test_crossing_segments_are_split_into_four_independent_segments() -> None:
    segments = split_at_intersection(Segment(0, 5, 10, 5), Segment(4, 0, 4, 10))

    assert len(segments) == 4
    assert all((4, 5) in {(part.x1, part.y1), (part.x2, part.y2)} for part in segments)


def test_parallel_segments_are_not_split() -> None:
    assert split_at_intersection(Segment(0, 0, 10, 0), Segment(0, 2, 10, 2)) == []


def test_closed_outline_can_be_cut_into_two_open_profiles() -> None:
    square = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]

    profiles = split_closed_polyline_by_segment(square, Segment(-5, 5, 15, 5))

    assert len(profiles) == 2
    assert profiles[0][0] in {(0, 5), (10, 5)}
    assert profiles[0][-1] in {(0, 5), (10, 5)}
    assert all(len(profile) >= 3 for profile in profiles)


def test_ellipse_outline_can_be_cut_through_its_middle() -> None:
    ellipse = PageObject("shape", 0, 10, 20, 100, 60, shape="ellipse")
    outline = DocumentEditorWindow._closed_outline(ellipse)

    profiles = split_closed_polyline_by_segment(outline, Segment(0, 50, 130, 50))

    assert len(profiles) == 2


def test_line_is_split_on_both_sides_and_inside_a_closed_shape() -> None:
    square = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]

    segments = split_segment_by_closed_polyline(Segment(-5, 5, 15, 5), square)

    assert len(segments) == 3
    assert segments[1] == Segment(0, 5, 10, 5)


def test_two_closed_shapes_are_split_at_their_crossings() -> None:
    horizontal = [(0, 2), (12, 2), (12, 8), (0, 8), (0, 2)]
    vertical = [(4, 0), (8, 0), (8, 10), (4, 10), (4, 0)]

    paths = split_closed_polyline_by_polyline(horizontal, vertical)

    assert len(paths) == 4
    assert all(len(path) >= 2 for path in paths)


def test_thin_line_has_a_geometric_selection_tolerance() -> None:
    horizontal = Segment(10, 20, 110, 20)

    assert point_to_segment_distance(60, 25, horizontal) == 5
    assert point_to_segment_distance(5, 20, horizontal) == 5


def test_point_reflection_uses_the_real_inclined_axis() -> None:
    reflected = reflect_point_across_line(10, 0, Segment(0, 0, 20, 20))

    assert abs(reflected[0]) < 1e-8
    assert abs(reflected[1] - 10) < 1e-8


def test_profile_endpoint_can_be_projected_exactly_onto_axis() -> None:
    projected = project_point_onto_line(8, 3, Segment(0, 0, 20, 0))

    assert projected == (8, 0)


def test_line_can_rotate_freely_back_to_horizontal() -> None:
    line = PageObject("line", 0, 20, 20, 0, 180)

    DocumentEditorWindow._rotate_line(line, -90)

    assert abs(line.height) < 1e-8
    assert line.width > 0


def test_polyline_keyboard_constraints_are_geometrically_exact() -> None:
    editor = DocumentEditorWindow.__new__(DocumentEditorWindow)
    editor._polyline_points = [(10.0, 10.0)]
    editor._modifier_keys = set()
    editor._polyline_axis_index = None

    assert editor._constrained_polyline_point(25, 13, 0x0004) == (25, 10)
    diagonal = editor._constrained_polyline_point(20, 17, 0x0001)
    thirty_degrees = editor._constrained_polyline_point(20, 17, 0x0008)

    assert abs(abs(diagonal[0] - 10) - abs(diagonal[1] - 10)) < 1e-8
    assert abs(math.degrees(math.atan2(thirty_degrees[1] - 10, thirty_degrees[0] - 10)) - 30) < 1e-8


def test_unordered_segments_are_recognized_as_a_closed_contour() -> None:
    points, gap, closed = join_segments(
        [
            Segment(0, 0, 10, 0),
            Segment(0, 10, 0, 0),
            Segment(10, 10, 0, 10),
            Segment(10, 0, 10, 10),
        ],
        tolerance=0.01,
    )

    assert len(points) == 5
    assert gap == 0
    assert closed is True


def test_chamfer_trims_two_lines_and_adds_connector() -> None:
    result = chamfer_segments(
        Segment(0, 0, 10, 0), Segment(10, 0, 10, 10), distance=2
    )

    assert result is not None
    first, second, connector = result
    assert {(first.x1, first.y1), (first.x2, first.y2)} == {(0, 0), (8, 0)}
    assert {(second.x1, second.y1), (second.x2, second.y2)} == {(10, 2), (10, 10)}
    assert {(connector.x1, connector.y1), (connector.x2, connector.y2)} == {
        (8, 0),
        (10, 2),
    }


def test_hatches_are_clipped_inside_a_closed_square() -> None:
    segments = hatch_segments(
        [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)], spacing=2, angle_degrees=45
    )

    assert segments
    assert all(
        -1e-8 <= coordinate <= 10 + 1e-8
        for segment in segments
        for coordinate in (segment.x1, segment.y1, segment.x2, segment.y2)
    )


def test_aluminium_hatches_can_be_generated_as_close_pairs() -> None:
    outline = [(0, 0), (30, 0), (30, 30), (0, 30), (0, 0)]
    first = hatch_segments(outline, spacing=10, angle_degrees=45, offset_shift=0)
    second = hatch_segments(outline, spacing=10, angle_degrees=45, offset_shift=2)

    assert first and second
    # Les deux familles ont le même pas long, avec seulement un petit décalage
    # entre les deux traits de chaque paire.
    first_offsets = sorted({round((segment.y1 - segment.x1) / 2**0.5, 6) for segment in first})
    second_offsets = sorted({round((segment.y1 - segment.x1) / 2**0.5, 6) for segment in second})
    assert min(abs(a - b) for a in first_offsets for b in second_offsets) <= 2.000001
