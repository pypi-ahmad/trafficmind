"""Small local demo for the tracking foundation.

This demo creates a short synthetic detection sequence, feeds it into the
tracking service, and prints persistent track ids, motion, and rule-ready
line/zone checks. It is intentionally simple but exercises the real tracking
contract that production detection backends will emit.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.tracking.config import TrackingSettings
from services.tracking.interface import TrackerRegistry
from services.tracking.schemas import LineSegment, Point2D, PolygonZone
from services.tracking.utils import (
    check_line_crossing,
    check_track_line_crossing,
    check_track_zone_transitions,
    detect_zone_transition,
)
from services.vision.schemas import BBox, Detection, DetectionResult, ObjectCategory


def _synthetic_frames() -> list[DetectionResult]:
    start = datetime(2026, 4, 4, 12, 0, 0, tzinfo=timezone.utc)
    positions = list(range(10, 59, 3))
    frames: list[DetectionResult] = []

    for frame_index, x1 in enumerate(positions):
        timestamp = start + timedelta(milliseconds=frame_index * 100)
        detection = Detection(
            class_name="car",
            category=ObjectCategory.VEHICLE,
            class_id=2,
            confidence=0.93,
            bbox=BBox(x1=x1, y1=40, x2=x1 + 18, y2=58),
            frame_index=frame_index,
            timestamp=timestamp,
        )
        frames.append(
            DetectionResult(
                detections=[detection],
                frame_index=frame_index,
                timestamp=timestamp,
                source_width=160,
                source_height=120,
            )
        )
    return frames


def main() -> None:
    tracker = TrackerRegistry.create(
        "bytetrack",
        TrackingSettings(
            minimum_matching_threshold=0.7,
            minimum_consecutive_frames=1,
        ),
    )
    line = LineSegment(start=Point2D(x=50, y=0), end=Point2D(x=50, y=120), name="count-line")
    zone = PolygonZone(
        name="intersection-core",
        points=[
            Point2D(x=55, y=20),
            Point2D(x=120, y=20),
            Point2D(x=120, y=90),
            Point2D(x=55, y=90),
        ],
    )

    previous_centroid: Point2D | None = None
    for frame in _synthetic_frames():
        result = tracker.update(frame)
        if not result.tracks:
            continue

        track = result.tracks[0]
        current_centroid = track.centroid
        crossing = check_line_crossing(previous_centroid, current_centroid, line)
        zone_transition = detect_zone_transition(previous_centroid, current_centroid, zone)
        direction = track.direction.direction.value if track.direction else "unknown"

        print(
            f"frame={frame.frame_index} track={track.track_id} class={track.class_name} "
            f"frames_seen={track.frame_count} direction={direction} centroid={current_centroid.as_tuple()}"
        )
        if crossing.crossed:
            print(f"  line_crossing={crossing.direction.value if crossing.direction else 'undirected'}")
        if zone_transition and zone_transition.transition.value in {"entered", "exited"}:
            print(f"  zone_transition={zone_transition.transition.value}")

        previous_centroid = current_centroid

    # Demonstrate track-level utilities and analytics helpers
    print("\n--- Track-level summary ---")
    final = result  # noqa: F821 — last frame from loop
    for track in final.tracks:
        lc = check_track_line_crossing(track, line)
        zt_list = check_track_zone_transitions(track, zone)
        dur = track.duration
        print(
            f"track={track.track_id}: duration={dur}, speed={track.speed_px_per_frame:.1f}px/f, "
            f"line_crossed={'yes' if lc else 'no'}, zone_transitions={len(zt_list)}"
        )
        print(f"  event_dict keys: {sorted(track.to_event_dict().keys())}")
    print(f"summary: {final.to_summary_dict()}")


if __name__ == "__main__":
    main()