from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

from services.tracking.config import TrackingSettings
from services.tracking.interface import MatchedDetection, StatefulTracker, TrackerRegistry
from services.tracking.schemas import (
    CardinalDirection,
    LineCrossingDirection,
    LineSegment,
    MotionVector,
    Point2D,
    PolygonZone,
    TrackLifecycleStatus,
    TrackedObject,
    TrajectoryPoint,
    ZoneTransitionType,
)
from services.tracking.utils import (
    centroid_from_bbox,
    check_line_crossing,
    check_track_line_crossing,
    check_track_line_crossings,
    check_track_zone_transitions,
    detect_zone_transition,
    estimate_direction,
)
from services.vision.schemas import BBox, Detection, DetectionResult, ObjectCategory


def _make_detection_result(
    *,
    frame_index: int,
    timestamp: datetime,
    x1: float,
    y1: float = 20,
    width: float = 16,
    height: float = 12,
) -> DetectionResult:
    detection = Detection(
        class_name="car",
        category=ObjectCategory.VEHICLE,
        class_id=2,
        confidence=0.95,
        bbox=BBox(x1=x1, y1=y1, x2=x1 + width, y2=y1 + height),
        frame_index=frame_index,
        timestamp=timestamp,
    )
    return DetectionResult(
        detections=[detection],
        frame_index=frame_index,
        timestamp=timestamp,
        source_width=640,
        source_height=480,
    )


def test_centroid_extraction_from_bbox() -> None:
    centroid = centroid_from_bbox(BBox(x1=10, y1=20, x2=30, y2=60))
    assert centroid == Point2D(x=20, y=40)


def test_direction_estimation_from_trajectory() -> None:
    motion = estimate_direction(
        [
            TrajectoryPoint(point=Point2D(x=10, y=20)),
            TrajectoryPoint(point=Point2D(x=30, y=20)),
        ]
    )
    assert motion is not None
    assert motion.direction == CardinalDirection.EAST


def test_line_crossing_foundation() -> None:
    previous = Point2D(x=10, y=40)
    current = Point2D(x=70, y=40)
    line = LineSegment(start=Point2D(x=50, y=0), end=Point2D(x=50, y=100))
    result = check_line_crossing(previous, current, line)
    assert result.crossed is True
    assert result.direction == LineCrossingDirection.POSITIVE_TO_NEGATIVE


def test_zone_entry_exit_foundation() -> None:
    zone = PolygonZone(
        points=[
            Point2D(x=0, y=0),
            Point2D(x=20, y=0),
            Point2D(x=20, y=20),
            Point2D(x=0, y=20),
        ]
    )
    entered = detect_zone_transition(Point2D(x=-5, y=10), Point2D(x=10, y=10), zone)
    exited = detect_zone_transition(Point2D(x=10, y=10), Point2D(x=30, y=10), zone)
    assert entered is not None and entered.transition == ZoneTransitionType.ENTERED
    assert exited is not None and exited.transition == ZoneTransitionType.EXITED


def test_tracker_registry_advertises_bytetrack_without_import_side_effect() -> None:
    sys.modules.pop("services.tracking.backends.bytetrack_tracker", None)
    assert "bytetrack" in TrackerRegistry.available()


def test_detector_outputs_flow_into_persistent_tracks() -> None:
    base = datetime(2026, 4, 4, 12, 0, 0, tzinfo=timezone.utc)
    tracker = TrackerRegistry.create(
        "bytetrack",
        TrackingSettings(
            trajectory_history_size=8,
            lost_track_buffer=1,
            minimum_matching_threshold=0.7,
            minimum_consecutive_frames=1,
        ),
    )

    result1 = tracker.update(_make_detection_result(frame_index=0, timestamp=base, x1=20))
    assert result1.active_count == 1
    assert len(result1.new_track_ids) == 1
    first_track = result1.tracks[0]
    assert first_track.frame_count == 1
    assert first_track.status == TrackLifecycleStatus.ACTIVE
    assert len(first_track.trajectory) == 1

    result2 = tracker.update(
        _make_detection_result(frame_index=1, timestamp=base + timedelta(milliseconds=100), x1=26)
    )
    assert result2.active_count == 1
    second_track = result2.tracks[0]
    assert second_track.track_id == first_track.track_id
    assert second_track.frame_count == 2
    assert len(second_track.trajectory) == 2
    assert second_track.direction is not None
    assert second_track.direction.direction in {CardinalDirection.EAST, CardinalDirection.NORTH_EAST, CardinalDirection.SOUTH_EAST}

    lost = tracker.update(
        DetectionResult(
            detections=[],
            frame_index=2,
            timestamp=base + timedelta(milliseconds=200),
            source_width=640,
            source_height=480,
        )
    )
    assert first_track.track_id in lost.lost_track_ids
    assert len(lost.lost_tracks) == 1
    assert lost.lost_tracks[0].track_id == first_track.track_id
    assert tracker.get_active_tracks() == []

    removed = tracker.update(
        DetectionResult(
            detections=[],
            frame_index=3,
            timestamp=base + timedelta(milliseconds=300),
            source_width=640,
            source_height=480,
        )
    )
    assert first_track.track_id in removed.removed_track_ids
    assert tracker.snapshot(include_inactive=True) == []


def test_removed_tracks_carry_final_tracked_object() -> None:
    """Violations engines need the full TrackedObject on removal, not just an ID."""
    base = datetime(2026, 4, 4, 12, 0, 0, tzinfo=timezone.utc)
    tracker = TrackerRegistry.create(
        "bytetrack",
        TrackingSettings(
            trajectory_history_size=8,
            lost_track_buffer=1,
            minimum_matching_threshold=0.7,
            minimum_consecutive_frames=1,
        ),
    )
    tracker.update(_make_detection_result(frame_index=0, timestamp=base, x1=20))
    # Lost
    tracker.update(
        DetectionResult(detections=[], frame_index=1, timestamp=base + timedelta(milliseconds=100), source_width=640, source_height=480)
    )
    # Removed
    removed = tracker.update(
        DetectionResult(detections=[], frame_index=2, timestamp=base + timedelta(milliseconds=200), source_width=640, source_height=480)
    )
    assert len(removed.removed_tracks) == 1
    rt = removed.removed_tracks[0]
    assert rt.track_id == removed.removed_track_ids[0]
    assert rt.status == TrackLifecycleStatus.REMOVED
    assert rt.frame_count == 1
    assert rt.duration is not None or rt.first_seen_at is not None


def test_tracked_object_duration() -> None:
    t0 = datetime(2026, 4, 4, 12, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(seconds=3)
    obj = TrackedObject(
        track_id="1",
        class_name="car",
        category=ObjectCategory.VEHICLE,
        bbox=BBox(x1=0, y1=0, x2=10, y2=10),
        confidence=0.9,
        first_seen_at=t0,
        last_seen_at=t1,
        frame_count=90,
    )
    assert obj.duration == timedelta(seconds=3)
    assert obj.duration.total_seconds() == 3.0

    obj_no_ts = TrackedObject(
        track_id="2",
        class_name="car",
        category=ObjectCategory.VEHICLE,
        bbox=BBox(x1=0, y1=0, x2=10, y2=10),
        confidence=0.9,
    )
    assert obj_no_ts.duration is None


def test_tracked_object_speed_px_per_frame() -> None:
    obj = TrackedObject(
        track_id="1",
        class_name="car",
        category=ObjectCategory.VEHICLE,
        bbox=BBox(x1=0, y1=0, x2=10, y2=10),
        confidence=0.9,
        frame_count=5,
        direction=MotionVector(dx=3.0, dy=4.0, magnitude=5.0),
    )
    assert obj.speed_px_per_frame == 5.0

    obj_no_dir = TrackedObject(
        track_id="2",
        class_name="car",
        category=ObjectCategory.VEHICLE,
        bbox=BBox(x1=0, y1=0, x2=10, y2=10),
        confidence=0.9,
    )
    assert obj_no_dir.speed_px_per_frame == 0.0


def test_tracked_object_to_event_dict() -> None:
    t0 = datetime(2026, 4, 4, 12, 0, 0, tzinfo=timezone.utc)
    obj = TrackedObject(
        track_id="7",
        class_name="truck",
        category=ObjectCategory.VEHICLE,
        bbox=BBox(x1=1, y1=2, x2=3, y2=4),
        confidence=0.88,
        first_seen_at=t0,
        last_seen_at=t0 + timedelta(seconds=2),
        frame_count=60,
        direction=MotionVector(dx=1.0, dy=0.0, magnitude=1.0, direction=CardinalDirection.EAST),
    )
    d = obj.to_event_dict()
    assert d["track_id"] == "7"
    assert d["category"] == "vehicle"
    assert d["direction"] == "east"
    assert d["duration_seconds"] == 2.0
    assert d["speed_px_per_frame"] == 1.0
    assert "bbox" in d
    assert d["centroid"] == {"x": 2.0, "y": 3.0}


def test_tracking_result_by_category_and_summary() -> None:
    tracks = [
        TrackedObject(
            track_id="1",
            class_name="car",
            category=ObjectCategory.VEHICLE,
            bbox=BBox(x1=0, y1=0, x2=10, y2=10),
            confidence=0.9,
        ),
        TrackedObject(
            track_id="2",
            class_name="person",
            category=ObjectCategory.PERSON,
            bbox=BBox(x1=20, y1=20, x2=30, y2=30),
            confidence=0.8,
        ),
    ]
    from services.tracking.schemas import TrackingResult

    result = TrackingResult(tracks=tracks, frame_index=5, new_track_ids=["2"])
    assert len(result.by_category(ObjectCategory.VEHICLE)) == 1
    assert len(result.by_category(ObjectCategory.PERSON)) == 1
    assert len(result.by_category(ObjectCategory.TRAFFIC_LIGHT)) == 0

    summary = result.to_summary_dict()
    assert summary["active_count"] == 2
    assert summary["new_count"] == 1
    assert summary["category_counts"]["vehicle"] == 1
    assert summary["category_counts"]["person"] == 1


# ------------------------------------------------------------------
# Track-level line / zone utilities
# ------------------------------------------------------------------


def test_check_track_line_crossing_scans_trajectory() -> None:
    line = LineSegment(start=Point2D(x=50, y=0), end=Point2D(x=50, y=100))
    track = TrackedObject(
        track_id="1",
        class_name="car",
        category=ObjectCategory.VEHICLE,
        bbox=BBox(x1=55, y1=35, x2=65, y2=45),
        confidence=0.9,
        trajectory=[
            TrajectoryPoint(point=Point2D(x=20, y=40)),
            TrajectoryPoint(point=Point2D(x=40, y=40)),
            TrajectoryPoint(point=Point2D(x=60, y=40)),
        ],
    )
    result = check_track_line_crossing(track, line)
    assert result is not None
    assert result.crossed is True
    assert result.direction == LineCrossingDirection.POSITIVE_TO_NEGATIVE


def test_check_track_line_crossing_returns_none_when_no_crossing() -> None:
    line = LineSegment(start=Point2D(x=50, y=0), end=Point2D(x=50, y=100))
    track = TrackedObject(
        track_id="1",
        class_name="car",
        category=ObjectCategory.VEHICLE,
        bbox=BBox(x1=5, y1=35, x2=15, y2=45),
        confidence=0.9,
        trajectory=[
            TrajectoryPoint(point=Point2D(x=10, y=40)),
            TrajectoryPoint(point=Point2D(x=20, y=40)),
            TrajectoryPoint(point=Point2D(x=30, y=40)),
        ],
    )
    assert check_track_line_crossing(track, line) is None


def test_check_track_line_crossings_returns_all_crossings() -> None:
    """A counting-line rule needs all crossings, not just the first."""
    line = LineSegment(start=Point2D(x=50, y=0), end=Point2D(x=50, y=100))
    track = TrackedObject(
        track_id="1",
        class_name="car",
        category=ObjectCategory.VEHICLE,
        bbox=BBox(x1=55, y1=35, x2=65, y2=45),
        confidence=0.9,
        trajectory=[
            TrajectoryPoint(point=Point2D(x=20, y=40)),
            TrajectoryPoint(point=Point2D(x=60, y=40)),  # crossing 1
            TrajectoryPoint(point=Point2D(x=40, y=40)),  # crossing 2 (back)
            TrajectoryPoint(point=Point2D(x=70, y=40)),  # crossing 3
        ],
    )
    crossings = check_track_line_crossings(track, line)
    assert len(crossings) == 3
    assert all(c.crossed for c in crossings)
    # First and third go same direction, second reverses
    assert crossings[0].direction != crossings[1].direction


def test_check_track_zone_transitions_finds_enter_and_exit() -> None:
    zone = PolygonZone(
        points=[
            Point2D(x=40, y=0),
            Point2D(x=60, y=0),
            Point2D(x=60, y=100),
            Point2D(x=40, y=100),
        ]
    )
    track = TrackedObject(
        track_id="1",
        class_name="car",
        category=ObjectCategory.VEHICLE,
        bbox=BBox(x1=75, y1=45, x2=85, y2=55),
        confidence=0.9,
        trajectory=[
            TrajectoryPoint(point=Point2D(x=20, y=50)),
            TrajectoryPoint(point=Point2D(x=50, y=50)),  # entered
            TrajectoryPoint(point=Point2D(x=55, y=50)),  # inside (omitted)
            TrajectoryPoint(point=Point2D(x=80, y=50)),  # exited
        ],
    )
    transitions = check_track_zone_transitions(track, zone)
    assert len(transitions) == 2
    assert transitions[0].transition == ZoneTransitionType.ENTERED
    assert transitions[1].transition == ZoneTransitionType.EXITED


# ------------------------------------------------------------------
# StatefulTracker base is backend-agnostic
# ------------------------------------------------------------------


def test_stateful_tracker_reconcile_is_backend_independent() -> None:
    """A trivial _match implementation should produce full TrackedObjects."""

    class StubTracker(StatefulTracker):
        def _match(self, detections):
            return [
                MatchedDetection(
                    track_id="stub-1",
                    bbox=detections.detections[0].bbox,
                    class_name=detections.detections[0].class_name,
                    category=detections.detections[0].category,
                    class_id=detections.detections[0].class_id,
                    confidence=detections.detections[0].confidence,
                )
            ] if detections.detections else []

    settings = TrackingSettings(trajectory_history_size=4, lost_track_buffer=1)
    tracker = StubTracker(settings)
    base = datetime(2026, 4, 4, 12, 0, 0, tzinfo=timezone.utc)

    r1 = tracker.update(_make_detection_result(frame_index=0, timestamp=base, x1=10))
    assert r1.active_count == 1
    assert r1.new_track_ids == ["stub-1"]
    assert r1.tracks[0].frame_count == 1

    r2 = tracker.update(_make_detection_result(frame_index=1, timestamp=base + timedelta(milliseconds=100), x1=16))
    assert r2.tracks[0].frame_count == 2
    assert r2.tracks[0].direction is not None

    # Empty frame → lost
    r3 = tracker.update(
        DetectionResult(detections=[], frame_index=2, timestamp=base + timedelta(milliseconds=200), source_width=640, source_height=480)
    )
    assert "stub-1" in r3.lost_track_ids

    # Second empty → removed
    r4 = tracker.update(
        DetectionResult(detections=[], frame_index=3, timestamp=base + timedelta(milliseconds=300), source_width=640, source_height=480)
    )
    assert "stub-1" in r4.removed_track_ids
    assert len(r4.removed_tracks) == 1
    assert r4.removed_tracks[0].track_id == "stub-1"
    assert tracker.snapshot(include_inactive=True) == []