"""Tests for the CentroidTracker backend.

Validates that the centroid-distance tracker:
- conforms to the StatefulTracker / Tracker ABC,
- correctly creates, associates, loses, and removes tracks,
- handles multi-object scenarios,
- is discoverable through the TrackerRegistry.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

from services.tracking.config import TrackingSettings
from services.tracking.interface import TrackerRegistry
from services.tracking.schemas import CardinalDirection, TrackLifecycleStatus
from services.vision.schemas import BBox, Detection, DetectionResult, ObjectCategory


def _make_result(
    *,
    frame_index: int,
    timestamp: datetime,
    x1: float,
    y1: float = 20,
    width: float = 16,
    height: float = 12,
) -> DetectionResult:
    return DetectionResult(
        detections=[
            Detection(
                class_name="car",
                category=ObjectCategory.VEHICLE,
                class_id=2,
                confidence=0.95,
                bbox=BBox(x1=x1, y1=y1, x2=x1 + width, y2=y1 + height),
                frame_index=frame_index,
                timestamp=timestamp,
            )
        ],
        frame_index=frame_index,
        timestamp=timestamp,
        source_width=640,
        source_height=480,
    )


def _empty_result(frame_index: int, timestamp: datetime) -> DetectionResult:
    return DetectionResult(
        detections=[],
        frame_index=frame_index,
        timestamp=timestamp,
        source_width=640,
        source_height=480,
    )


_SETTINGS = TrackingSettings(
    trajectory_history_size=8,
    lost_track_buffer=1,
    minimum_matching_threshold=0.8,
)


def test_centroid_registry_advertised() -> None:
    sys.modules.pop("services.tracking.backends.centroid_tracker", None)
    assert "centroid" in TrackerRegistry.available()


def test_centroid_registry_create() -> None:
    tracker = TrackerRegistry.create("centroid", _SETTINGS)
    from services.tracking.interface import Tracker

    assert isinstance(tracker, Tracker)


def test_centroid_creates_tracks() -> None:
    tracker = TrackerRegistry.create("centroid", _SETTINGS)
    base = datetime(2026, 4, 6, 12, 0, 0, tzinfo=timezone.utc)
    r = tracker.update(_make_result(frame_index=0, timestamp=base, x1=20))
    assert r.active_count == 1
    assert len(r.new_track_ids) == 1
    assert r.tracks[0].frame_count == 1
    assert r.tracks[0].status == TrackLifecycleStatus.ACTIVE


def test_centroid_associates_nearby_detections() -> None:
    tracker = TrackerRegistry.create("centroid", _SETTINGS)
    base = datetime(2026, 4, 6, 12, 0, 0, tzinfo=timezone.utc)

    r1 = tracker.update(_make_result(frame_index=0, timestamp=base, x1=100))
    tid = r1.tracks[0].track_id

    # Small shift — centroid moves ~4 pixels, well within threshold.
    r2 = tracker.update(
        _make_result(frame_index=1, timestamp=base + timedelta(milliseconds=100), x1=104)
    )
    assert r2.active_count == 1
    assert r2.tracks[0].track_id == tid
    assert r2.tracks[0].frame_count == 2


def test_centroid_new_track_for_distant_detection() -> None:
    tracker = TrackerRegistry.create("centroid", _SETTINGS)
    base = datetime(2026, 4, 6, 12, 0, 0, tzinfo=timezone.utc)

    r1 = tracker.update(_make_result(frame_index=0, timestamp=base, x1=20))
    first_tid = r1.tracks[0].track_id

    # Far away — distance >> max_dist → new track.
    r2 = tracker.update(
        _make_result(frame_index=1, timestamp=base + timedelta(milliseconds=100), x1=500)
    )
    assert r2.active_count == 1
    assert r2.tracks[0].track_id != first_tid
    assert first_tid in r2.lost_track_ids


def test_centroid_lifecycle_active_lost_removed() -> None:
    tracker = TrackerRegistry.create("centroid", _SETTINGS)
    base = datetime(2026, 4, 6, 12, 0, 0, tzinfo=timezone.utc)

    r1 = tracker.update(_make_result(frame_index=0, timestamp=base, x1=100))
    tid = r1.tracks[0].track_id

    r2 = tracker.update(_empty_result(1, base + timedelta(milliseconds=100)))
    assert tid in r2.lost_track_ids
    assert tracker.get_active_tracks() == []

    r3 = tracker.update(_empty_result(2, base + timedelta(milliseconds=200)))
    assert tid in r3.removed_track_ids
    assert r3.removed_tracks[0].status == TrackLifecycleStatus.REMOVED
    assert tracker.snapshot(include_inactive=True) == []


def test_centroid_multiple_simultaneous_objects() -> None:
    tracker = TrackerRegistry.create(
        "centroid",
        TrackingSettings(trajectory_history_size=8, lost_track_buffer=2, minimum_matching_threshold=0.8),
    )
    base = datetime(2026, 4, 6, 12, 0, 0, tzinfo=timezone.utc)

    two_dets = DetectionResult(
        detections=[
            Detection(
                class_name="car", category=ObjectCategory.VEHICLE, class_id=2,
                confidence=0.9, bbox=BBox(x1=10, y1=20, x2=30, y2=40),
                frame_index=0, timestamp=base,
            ),
            Detection(
                class_name="person", category=ObjectCategory.PERSON, class_id=0,
                confidence=0.8, bbox=BBox(x1=300, y1=300, x2=320, y2=360),
                frame_index=0, timestamp=base,
            ),
        ],
        frame_index=0, timestamp=base, source_width=640, source_height=480,
    )
    r1 = tracker.update(two_dets)
    assert r1.active_count == 2
    assert len(r1.new_track_ids) == 2

    ids = {t.track_id for t in r1.tracks}

    # Both objects shift slightly.
    shifted = DetectionResult(
        detections=[
            Detection(
                class_name="car", category=ObjectCategory.VEHICLE, class_id=2,
                confidence=0.9, bbox=BBox(x1=14, y1=22, x2=34, y2=42),
                frame_index=1, timestamp=base + timedelta(milliseconds=100),
            ),
            Detection(
                class_name="person", category=ObjectCategory.PERSON, class_id=0,
                confidence=0.8, bbox=BBox(x1=304, y1=302, x2=324, y2=362),
                frame_index=1, timestamp=base + timedelta(milliseconds=100),
            ),
        ],
        frame_index=1, timestamp=base + timedelta(milliseconds=100),
        source_width=640, source_height=480,
    )
    r2 = tracker.update(shifted)
    assert r2.active_count == 2
    assert len(r2.new_track_ids) == 0
    for t in r2.tracks:
        assert t.track_id in ids
        assert t.frame_count == 2


def test_centroid_reset_clears_state() -> None:
    tracker = TrackerRegistry.create("centroid", _SETTINGS)
    base = datetime(2026, 4, 6, 12, 0, 0, tzinfo=timezone.utc)
    tracker.update(_make_result(frame_index=0, timestamp=base, x1=100))
    assert len(tracker.get_active_tracks()) == 1
    tracker.reset()
    assert tracker.get_active_tracks() == []
    assert tracker.snapshot(include_inactive=True) == []


def test_centroid_direction_estimation() -> None:
    tracker = TrackerRegistry.create(
        "centroid",
        TrackingSettings(trajectory_history_size=8, lost_track_buffer=2, minimum_matching_threshold=0.8),
    )
    base = datetime(2026, 4, 6, 12, 0, 0, tzinfo=timezone.utc)

    for i in range(5):
        tracker.update(
            _make_result(
                frame_index=i,
                timestamp=base + timedelta(milliseconds=100 * i),
                x1=50 + i * 6,
            )
        )

    tracks = tracker.get_active_tracks()
    assert len(tracks) == 1
    assert tracks[0].direction is not None
    assert tracks[0].direction.direction in {
        CardinalDirection.EAST,
        CardinalDirection.NORTH_EAST,
        CardinalDirection.SOUTH_EAST,
    }
