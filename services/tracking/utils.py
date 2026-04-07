"""Deterministic tracking utility functions for motion and rule foundations."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import TYPE_CHECKING

from services.tracking.schemas import (
    CardinalDirection,
    LineCrossingCheck,
    LineCrossingDirection,
    LineSegment,
    MotionVector,
    Point2D,
    PolygonZone,
    TrajectoryPoint,
    ZoneTransition,
    ZoneTransitionType,
)
from services.vision.schemas import BBox, Detection

if TYPE_CHECKING:
    from services.tracking.schemas import TrackedObject


def centroid_from_bbox(bbox: BBox) -> Point2D:
    """Return the centroid of a bounding box."""
    x, y = bbox.center
    return Point2D(x=x, y=y)


def centroid_from_detection(detection: Detection) -> Point2D:
    """Return the centroid of a detection's box."""
    return centroid_from_bbox(detection.bbox)


def estimate_direction(
    trajectory: Sequence[TrajectoryPoint],
    *,
    lookback: int = 5,
    stationary_epsilon: float = 1.0,
) -> MotionVector | None:
    """Estimate motion from recent trajectory points."""
    if len(trajectory) < 2:
        return None

    recent = list(trajectory[-lookback:])
    start = recent[0].point
    end = recent[-1].point
    dx = end.x - start.x
    dy = end.y - start.y
    magnitude = math.hypot(dx, dy)

    if magnitude <= stationary_epsilon:
        return MotionVector(
            dx=dx,
            dy=dy,
            magnitude=magnitude,
            bearing_degrees=None,
            direction=CardinalDirection.STATIONARY,
        )

    bearing = (math.degrees(math.atan2(-dy, dx)) + 360.0) % 360.0
    direction = _bearing_to_cardinal(bearing)
    return MotionVector(
        dx=dx,
        dy=dy,
        magnitude=magnitude,
        bearing_degrees=round(bearing, 2),
        direction=direction,
    )


def check_line_crossing(
    previous: Point2D | None,
    current: Point2D | None,
    line: LineSegment,
    *,
    epsilon: float = 1e-6,
) -> LineCrossingCheck:
    """Check whether motion between two points crosses a line segment."""
    if previous is None or current is None:
        return LineCrossingCheck(crossed=False)

    if not _segments_intersect(previous, current, line.start, line.end, epsilon=epsilon):
        return LineCrossingCheck(crossed=False)

    previous_side = _orientation(line.start, line.end, previous)
    current_side = _orientation(line.start, line.end, current)

    if previous_side < -epsilon and current_side > epsilon:
        direction = LineCrossingDirection.NEGATIVE_TO_POSITIVE
    elif previous_side > epsilon and current_side < -epsilon:
        direction = LineCrossingDirection.POSITIVE_TO_NEGATIVE
    else:
        direction = None

    return LineCrossingCheck(crossed=True, direction=direction)


def point_in_polygon(point: Point2D, zone: PolygonZone) -> bool:
    """Return True when the point lies inside the polygon zone."""
    inside = False
    points = zone.points
    j = len(points) - 1

    for i, current in enumerate(points):
        previous = points[j]
        intersects = ((current.y > point.y) != (previous.y > point.y)) and (
            point.x
            < (previous.x - current.x) * (point.y - current.y) / ((previous.y - current.y) or 1e-9)
            + current.x
        )
        if intersects:
            inside = not inside
        j = i

    return inside


def detect_zone_transition(
    previous: Point2D | None,
    current: Point2D | None,
    zone: PolygonZone,
) -> ZoneTransition | None:
    """Determine entry/exit state between two trajectory points and a polygon zone."""
    if current is None:
        return None

    was_inside = point_in_polygon(previous, zone) if previous is not None else False
    is_inside = point_in_polygon(current, zone)

    if not was_inside and is_inside:
        transition = ZoneTransitionType.ENTERED
    elif was_inside and not is_inside:
        transition = ZoneTransitionType.EXITED
    elif is_inside:
        transition = ZoneTransitionType.INSIDE
    else:
        transition = ZoneTransitionType.OUTSIDE

    return ZoneTransition(
        transition=transition,
        was_inside=was_inside,
        is_inside=is_inside,
    )


def _bearing_to_cardinal(bearing: float) -> CardinalDirection:
    directions = [
        CardinalDirection.EAST,
        CardinalDirection.NORTH_EAST,
        CardinalDirection.NORTH,
        CardinalDirection.NORTH_WEST,
        CardinalDirection.WEST,
        CardinalDirection.SOUTH_WEST,
        CardinalDirection.SOUTH,
        CardinalDirection.SOUTH_EAST,
    ]
    index = int((bearing + 22.5) // 45) % 8
    return directions[index]


def _orientation(a: Point2D, b: Point2D, c: Point2D) -> float:
    return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)


def _on_segment(a: Point2D, b: Point2D, c: Point2D, *, epsilon: float) -> bool:
    return (
        min(a.x, c.x) - epsilon <= b.x <= max(a.x, c.x) + epsilon
        and min(a.y, c.y) - epsilon <= b.y <= max(a.y, c.y) + epsilon
    )


def _segments_intersect(
    p1: Point2D,
    p2: Point2D,
    q1: Point2D,
    q2: Point2D,
    *,
    epsilon: float,
) -> bool:
    o1 = _orientation(p1, p2, q1)
    o2 = _orientation(p1, p2, q2)
    o3 = _orientation(q1, q2, p1)
    o4 = _orientation(q1, q2, p2)

    if ((o1 > epsilon and o2 < -epsilon) or (o1 < -epsilon and o2 > epsilon)) and (
        (o3 > epsilon and o4 < -epsilon) or (o3 < -epsilon and o4 > epsilon)
    ):
        return True

    if abs(o1) <= epsilon and _on_segment(p1, q1, p2, epsilon=epsilon):
        return True
    if abs(o2) <= epsilon and _on_segment(p1, q2, p2, epsilon=epsilon):
        return True
    if abs(o3) <= epsilon and _on_segment(q1, p1, q2, epsilon=epsilon):
        return True
    if abs(o4) <= epsilon and _on_segment(q1, p2, q2, epsilon=epsilon):
        return True
    return False


# ------------------------------------------------------------------
# Track-level convenience utilities (primary API for rules engines)
# ------------------------------------------------------------------


def check_track_line_crossing(
    track: TrackedObject,
    line: LineSegment,
    *,
    epsilon: float = 1e-6,
) -> LineCrossingCheck | None:
    """Scan a track's trajectory for the *first* crossing of *line*.

    Returns the ``LineCrossingCheck`` for the first pair of consecutive
    trajectory points that crosses *line*, or ``None`` if no crossing
    occurred anywhere in the recorded trajectory.
    """
    crossings = check_track_line_crossings(track, line, epsilon=epsilon)
    return crossings[0] if crossings else None


def check_track_line_crossings(
    track: TrackedObject,
    line: LineSegment,
    *,
    epsilon: float = 1e-6,
) -> list[LineCrossingCheck]:
    """Return *every* crossing of *line* found in the track's trajectory.

    Useful for counting-line rules that need a total directional count
    rather than just whether a crossing happened.
    """
    pts = track.trajectory
    crossings: list[LineCrossingCheck] = []
    for i in range(1, len(pts)):
        result = check_line_crossing(pts[i - 1].point, pts[i].point, line, epsilon=epsilon)
        if result.crossed:
            crossings.append(result)
    return crossings


def check_track_zone_transitions(
    track: TrackedObject,
    zone: PolygonZone,
) -> list[ZoneTransition]:
    """Return every enter/exit transition the track made through *zone*.

    Only ``ENTERED`` and ``EXITED`` transitions are included — steady-state
    ``INSIDE`` / ``OUTSIDE`` frames are omitted so callers get a clean
    event sequence.
    """
    transitions: list[ZoneTransition] = []
    pts = track.trajectory
    for i in range(1, len(pts)):
        zt = detect_zone_transition(pts[i - 1].point, pts[i].point, zone)
        if zt is not None and zt.transition in {ZoneTransitionType.ENTERED, ZoneTransitionType.EXITED}:
            transitions.append(zt)
    return transitions
