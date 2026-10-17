from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise

EPSILON = 1e-8


@dataclass(frozen=True)
class Segment:
    x1: float
    y1: float
    x2: float
    y2: float


def point_to_segment_distance(x: float, y: float, segment: Segment) -> float:
    """Return the shortest distance between a point and a finite segment."""
    dx, dy = segment.x2 - segment.x1, segment.y2 - segment.y1
    squared_length = dx * dx + dy * dy
    if squared_length < EPSILON:
        return math.hypot(x - segment.x1, y - segment.y1)
    position = ((x - segment.x1) * dx + (y - segment.y1) * dy) / squared_length
    position = max(0.0, min(1.0, position))
    projection_x = segment.x1 + position * dx
    projection_y = segment.y1 + position * dy
    return math.hypot(x - projection_x, y - projection_y)


def closest_point_on_segment(x: float, y: float, segment: Segment) -> tuple[float, float]:
    """Return the closest point on a finite segment."""
    dx, dy = segment.x2 - segment.x1, segment.y2 - segment.y1
    squared_length = dx * dx + dy * dy
    if squared_length < EPSILON:
        return segment.x1, segment.y1
    position = ((x - segment.x1) * dx + (y - segment.y1) * dy) / squared_length
    position = max(0.0, min(1.0, position))
    return segment.x1 + position * dx, segment.y1 + position * dy


def angle_between_segments(first: Segment, second: Segment) -> float:
    """Return the smallest, unsigned angle between two undirected segments."""
    first_angle = math.atan2(first.y2 - first.y1, first.x2 - first.x1)
    second_angle = math.atan2(second.y2 - second.y1, second.x2 - second.x1)
    difference = abs(math.degrees(second_angle - first_angle)) % 180
    return min(difference, 180 - difference)


def angle_at_vertex(
    first: tuple[float, float],
    vertex: tuple[float, float],
    second: tuple[float, float],
) -> float:
    """Return the internal angle formed by three points, from 0 to 180 degrees."""
    first_vector = (first[0] - vertex[0], first[1] - vertex[1])
    second_vector = (second[0] - vertex[0], second[1] - vertex[1])
    first_length = math.hypot(*first_vector)
    second_length = math.hypot(*second_vector)
    if first_length < EPSILON or second_length < EPSILON:
        raise ValueError("Les points de l’angle doivent être distincts.")
    cosine = (
        first_vector[0] * second_vector[0] + first_vector[1] * second_vector[1]
    ) / (first_length * second_length)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def reflect_point_across_line(x: float, y: float, axis: Segment) -> tuple[float, float]:
    """Reflect a point across the infinite line defined by an axis segment."""
    dx, dy = axis.x2 - axis.x1, axis.y2 - axis.y1
    squared_length = dx * dx + dy * dy
    if squared_length < EPSILON:
        raise ValueError("L’axe de symétrie doit avoir une longueur non nulle.")
    position = ((x - axis.x1) * dx + (y - axis.y1) * dy) / squared_length
    projection_x = axis.x1 + position * dx
    projection_y = axis.y1 + position * dy
    return 2 * projection_x - x, 2 * projection_y - y


def project_point_onto_line(x: float, y: float, axis: Segment) -> tuple[float, float]:
    """Project a point perpendicularly onto the infinite axis line."""
    dx, dy = axis.x2 - axis.x1, axis.y2 - axis.y1
    squared_length = dx * dx + dy * dy
    if squared_length < EPSILON:
        raise ValueError("L’axe doit avoir une longueur non nulle.")
    position = ((x - axis.x1) * dx + (y - axis.y1) * dy) / squared_length
    return axis.x1 + position * dx, axis.y1 + position * dy


def segment_intersection(first: Segment, second: Segment) -> tuple[float, float] | None:
    """Return the strict intersection of two finite, non-parallel segments."""
    dx1, dy1 = first.x2 - first.x1, first.y2 - first.y1
    dx2, dy2 = second.x2 - second.x1, second.y2 - second.y1
    denominator = dx1 * dy2 - dy1 * dx2
    if abs(denominator) < EPSILON:
        return None
    offset_x, offset_y = second.x1 - first.x1, second.y1 - first.y1
    along_first = (offset_x * dy2 - offset_y * dx2) / denominator
    along_second = (offset_x * dy1 - offset_y * dx1) / denominator
    if not (EPSILON < along_first < 1 - EPSILON and EPSILON < along_second < 1 - EPSILON):
        return None
    return first.x1 + along_first * dx1, first.y1 + along_first * dy1


def split_at_intersection(first: Segment, second: Segment) -> list[Segment]:
    intersection = segment_intersection(first, second)
    if intersection is None:
        return []
    x, y = intersection
    return [
        Segment(first.x1, first.y1, x, y),
        Segment(x, y, first.x2, first.y2),
        Segment(second.x1, second.y1, x, y),
        Segment(x, y, second.x2, second.y2),
    ]


def split_closed_polyline_by_segment(
    points: list[tuple[float, float]], cutter: Segment
) -> list[list[tuple[float, float]]]:
    """Split a simple closed outline at the two crossings made by a segment."""
    if len(points) < 4:
        return []
    ring = list(points)
    if math.dist(ring[0], ring[-1]) > EPSILON:
        ring.append(ring[0])
    expanded = [ring[0]]
    crossing_indices: list[int] = []
    for start, end in pairwise(ring):
        crossing = segment_intersection(Segment(*start, *end), cutter)
        if crossing is not None:
            expanded.append(crossing)
            crossing_indices.append(len(expanded) - 1)
        expanded.append(end)
    if len(crossing_indices) != 2:
        return []
    first, second = crossing_indices
    forward = expanded[first : second + 1]
    backward = expanded[second:] + expanded[1 : first + 1]
    return [forward, backward]


def split_segment_by_closed_polyline(
    segment: Segment, points: list[tuple[float, float]]
) -> list[Segment]:
    """Split a segment at every distinct crossing of a closed outline."""
    if len(points) < 4:
        return []
    ring = list(points)
    if math.dist(ring[0], ring[-1]) > EPSILON:
        ring.append(ring[0])
    crossings: list[tuple[float, float]] = []
    for start, end in pairwise(ring):
        crossing = segment_intersection(segment, Segment(*start, *end))
        if crossing is not None and not any(math.dist(crossing, item) < 1e-6 for item in crossings):
            crossings.append(crossing)
    if not crossings:
        return []
    length_x, length_y = segment.x2 - segment.x1, segment.y2 - segment.y1
    denominator = length_x * length_x + length_y * length_y
    if denominator < EPSILON:
        return []
    crossings.sort(
        key=lambda point: (
            (point[0] - segment.x1) * length_x + (point[1] - segment.y1) * length_y
        )
        / denominator
    )
    ordered = [(segment.x1, segment.y1), *crossings, (segment.x2, segment.y2)]
    return [Segment(*start, *end) for start, end in pairwise(ordered)]


def split_closed_polyline_by_polyline(
    points: list[tuple[float, float]], cutter: list[tuple[float, float]]
) -> list[list[tuple[float, float]]]:
    """Split a closed outline into paths at its crossings with another outline."""
    if len(points) < 4 or len(cutter) < 2:
        return []
    ring = list(points)
    if math.dist(ring[0], ring[-1]) > EPSILON:
        ring.append(ring[0])
    cutter_ring = list(cutter)
    if math.dist(cutter_ring[0], cutter_ring[-1]) > EPSILON:
        cutter_ring.append(cutter_ring[0])
    expanded = [ring[0]]
    crossing_indices: list[int] = []
    for start, end in pairwise(ring):
        edge = Segment(*start, *end)
        crossings: list[tuple[float, float]] = []
        for cutter_start, cutter_end in pairwise(cutter_ring):
            crossing = segment_intersection(edge, Segment(*cutter_start, *cutter_end))
            if crossing is not None and not any(
                math.dist(crossing, item) < 1e-6 for item in crossings
            ):
                crossings.append(crossing)
        crossings.sort(key=lambda point: math.dist(start, point))
        for crossing in crossings:
            expanded.append(crossing)
            crossing_indices.append(len(expanded) - 1)
        expanded.append(end)
    if len(crossing_indices) < 2:
        return []
    paths: list[list[tuple[float, float]]] = []
    for position, start_index in enumerate(crossing_indices):
        if position + 1 < len(crossing_indices):
            paths.append(expanded[start_index : crossing_indices[position + 1] + 1])
        else:
            paths.append(expanded[start_index:] + expanded[1 : crossing_indices[0] + 1])
    return [path for path in paths if len(path) >= 2]


def join_segments(
    segments: list[Segment], tolerance: float
) -> tuple[list[tuple[float, float]], float, bool]:
    """Order touching segments into one path and report its final gap.

    Segments may be supplied in any order and direction. ``tolerance`` is used
    only to decide which endpoint is the next one; the returned points retain
    their original coordinates until the caller elects to close the contour.
    """
    if not segments:
        return [], 0.0, False
    remaining = list(segments[1:])
    points = [(segments[0].x1, segments[0].y1), (segments[0].x2, segments[0].y2)]
    while remaining:
        tail = points[-1]
        best: tuple[float, int, bool] | None = None
        for index, segment in enumerate(remaining):
            for reverse, endpoint in (
                (False, (segment.x1, segment.y1)),
                (True, (segment.x2, segment.y2)),
            ):
                distance = math.dist(tail, endpoint)
                if best is None or distance < best[0]:
                    best = distance, index, reverse
        if best is None or best[0] > tolerance:
            return points, best[0] if best else math.inf, False
        _, index, reverse = best
        segment = remaining.pop(index)
        end = (segment.x1, segment.y1) if reverse else (segment.x2, segment.y2)
        points.append(end)
    gap = math.dist(points[-1], points[0])
    return points, gap, gap <= tolerance


def line_intersection(first: Segment, second: Segment) -> tuple[float, float] | None:
    """Return the intersection of the two infinite lines."""
    dx1, dy1 = first.x2 - first.x1, first.y2 - first.y1
    dx2, dy2 = second.x2 - second.x1, second.y2 - second.y1
    denominator = dx1 * dy2 - dy1 * dx2
    if abs(denominator) < EPSILON:
        return None
    offset_x, offset_y = second.x1 - first.x1, second.y1 - first.y1
    position = (offset_x * dy2 - offset_y * dx2) / denominator
    return first.x1 + position * dx1, first.y1 + position * dy1


def chamfer_segments(
    first: Segment, second: Segment, distance: float
) -> tuple[Segment, Segment, Segment] | None:
    """Trim the nearest end of two lines and connect them with a chamfer."""
    crossing = line_intersection(first, second)
    if crossing is None or distance <= 0:
        return None

    def trimmed(segment: Segment) -> tuple[Segment, tuple[float, float]] | None:
        endpoints = [(segment.x1, segment.y1), (segment.x2, segment.y2)]
        near_index = min(range(2), key=lambda index: math.dist(endpoints[index], crossing))
        far = endpoints[1 - near_index]
        length = math.dist(far, crossing)
        if length <= distance + EPSILON:
            return None
        ratio = distance / length
        cut = (
            crossing[0] + (far[0] - crossing[0]) * ratio,
            crossing[1] + (far[1] - crossing[1]) * ratio,
        )
        result = Segment(*far, *cut) if near_index == 1 else Segment(*cut, *far)
        return result, cut

    first_trimmed = trimmed(first)
    second_trimmed = trimmed(second)
    if first_trimmed is None or second_trimmed is None:
        return None
    first_result, first_cut = first_trimmed
    second_result, second_cut = second_trimmed
    return first_result, second_result, Segment(*first_cut, *second_cut)


def hatch_segments(
    points: list[tuple[float, float]],
    spacing: float,
    angle_degrees: float = 45,
    offset_shift: float = 0.0,
) -> list[Segment]:
    """Clip parallel hatch lines to a simple closed polygon."""
    if len(points) < 3 or spacing <= 0:
        return []
    polygon = list(points)
    if math.dist(polygon[0], polygon[-1]) < EPSILON:
        polygon.pop()
    angle = math.radians(angle_degrees)
    direction = (math.cos(angle), math.sin(angle))
    normal = (-direction[1], direction[0])
    projections = [x * normal[0] + y * normal[1] for x, y in polygon]
    minimum, maximum = min(projections), max(projections)
    offset = math.floor((minimum - offset_shift) / spacing) * spacing + offset_shift
    result: list[Segment] = []
    while offset <= maximum + EPSILON:
        crossings: list[float] = []
        for start, end in pairwise([*polygon, polygon[0]]):
            start_projection = start[0] * normal[0] + start[1] * normal[1]
            end_projection = end[0] * normal[0] + end[1] * normal[1]
            delta = end_projection - start_projection
            if abs(delta) < EPSILON:
                continue
            ratio = (offset - start_projection) / delta
            if -EPSILON <= ratio < 1 - EPSILON:
                x = start[0] + ratio * (end[0] - start[0])
                y = start[1] + ratio * (end[1] - start[1])
                crossings.append(x * direction[0] + y * direction[1])
        crossings.sort()
        for start_value, end_value in zip(crossings[::2], crossings[1::2]):
            start = (
                normal[0] * offset + direction[0] * start_value,
                normal[1] * offset + direction[1] * start_value,
            )
            end = (
                normal[0] * offset + direction[0] * end_value,
                normal[1] * offset + direction[1] * end_value,
            )
            if math.dist(start, end) > EPSILON:
                result.append(Segment(*start, *end))
        offset += spacing
    return result
