"""Demo: exercise the rules engine with synthetic tracked objects."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from services.rules.config import RulesSettings
from services.rules.engine import RulesEngine
from services.rules.schemas import (
    LineCrossingRuleConfig,
    LineGeometry,
    PolygonGeometry,
    RedLightRuleConfig,
    SceneContext,
    TrafficLightState,
    WrongDirectionRuleConfig,
    ZoneConfig,
    ZoneDwellTimeRuleConfig,
    ZoneEntryRuleConfig,
)
from services.tracking.schemas import (
    CardinalDirection,
    LineCrossingDirection,
    MotionVector,
    Point2D,
    TrackedObject,
    TrackingResult,
    TrajectoryPoint,
)
from services.vision.schemas import BBox, ObjectCategory


def _make_track(
    track_id: str,
    trajectory_pts: list[tuple[float, float]],
    *,
    category: ObjectCategory = ObjectCategory.VEHICLE,
    class_name: str = "car",
    timestamp: datetime | None = None,
    direction: MotionVector | None = None,
) -> TrackedObject:
    ts = timestamp or datetime.now(timezone.utc)
    traj = [
        TrajectoryPoint(
            point=Point2D(x=x, y=y),
            frame_index=i,
            timestamp=ts + timedelta(milliseconds=i * 33),
        )
        for i, (x, y) in enumerate(trajectory_pts)
    ]
    last = trajectory_pts[-1]
    return TrackedObject(
        track_id=track_id,
        class_name=class_name,
        category=category,
        bbox=BBox(x1=last[0] - 20, y1=last[1] - 20, x2=last[0] + 20, y2=last[1] + 20),
        confidence=0.9,
        first_seen_at=ts,
        last_seen_at=ts + timedelta(seconds=len(trajectory_pts) * 0.033),
        first_seen_frame=0,
        last_seen_frame=len(trajectory_pts) - 1,
        frame_count=len(trajectory_pts),
        trajectory=traj,
        direction=direction,
    )


def main() -> None:
    print("=" * 60)
    print("TrafficMind Rules Engine Demo")
    print("=" * 60)

    # --- Zone 1: Stop line ---
    stop_line = ZoneConfig(
        zone_id="zone-stop-line-1",
        name="Main Stop Line",
        zone_type="stop_line",
        geometry=LineGeometry(
            start=Point2D(x=100.0, y=300.0),
            end=Point2D(x=500.0, y=300.0),
        ),
        rules=[
            LineCrossingRuleConfig(
                severity="high",
                forbidden_direction=LineCrossingDirection.NEGATIVE_TO_POSITIVE,
                cooldown_seconds=0,
            ),
            RedLightRuleConfig(severity="critical", cooldown_seconds=0),
        ],
    )

    # --- Zone 2: Restricted polygon ---
    restricted = ZoneConfig(
        zone_id="zone-restricted-1",
        name="No Entry Area",
        zone_type="restricted",
        geometry=PolygonGeometry(
            points=[
                Point2D(x=200.0, y=200.0),
                Point2D(x=400.0, y=200.0),
                Point2D(x=400.0, y=400.0),
                Point2D(x=200.0, y=400.0),
            ],
        ),
        rules=[
            ZoneEntryRuleConfig(
                severity="medium",
                restricted_categories=[ObjectCategory.VEHICLE],
                cooldown_seconds=0,
            ),
            ZoneDwellTimeRuleConfig(
                max_dwell_seconds=5.0,
                severity="high",
                cooldown_seconds=0,
            ),
        ],
    )

    # --- Zone 3: Lane with wrong-direction rule ---
    lane = ZoneConfig(
        zone_id="zone-lane-1",
        name="Eastbound Lane",
        zone_type="lane",
        geometry=PolygonGeometry(
            points=[
                Point2D(x=0.0, y=250.0),
                Point2D(x=600.0, y=250.0),
                Point2D(x=600.0, y=350.0),
                Point2D(x=0.0, y=350.0),
            ],
        ),
        rules=[
            WrongDirectionRuleConfig(
                expected_direction=CardinalDirection.EAST,
                severity="critical",
                cooldown_seconds=0,
            ),
        ],
    )

    settings = RulesSettings(default_cooldown_seconds=0)
    engine = RulesEngine([stop_line, restricted, lane], settings=settings)
    now = datetime.now(timezone.utc)

    # --- Frame 1: vehicle approaches stop line (no crossing yet) ---
    track1 = _make_track("T1", [(300.0, 280.0), (300.0, 290.0)], timestamp=now)
    result1 = TrackingResult(tracks=[track1], frame_index=0, timestamp=now)
    v1 = engine.evaluate(result1)
    print(f"\nFrame 1 (approach): {len(v1)} violations")

    # --- Frame 2: vehicle crosses stop line (no red light) ---
    now2 = now + timedelta(seconds=0.033)
    track2 = _make_track("T1", [(300.0, 280.0), (300.0, 290.0), (300.0, 310.0)], timestamp=now)
    result2 = TrackingResult(tracks=[track2], frame_index=1, timestamp=now2)
    v2 = engine.evaluate(result2)
    print(f"Frame 2 (line crossing): {len(v2)} violations")
    for v in v2:
        print(f"  -> {v.rule_type}: {v.explanation.reason}")

    # --- Frame 3: same crossing while RED ---
    now3 = now + timedelta(seconds=0.066)
    scene_red = SceneContext(traffic_light_state=TrafficLightState.RED)
    v3 = engine.evaluate(
        TrackingResult(tracks=[track2], frame_index=2, timestamp=now3),
        scene=scene_red,
    )
    print(f"Frame 3 (red light): {len(v3)} violations")
    for v in v3:
        print(f"  -> {v.rule_type}: {v.explanation.reason}")

    # --- Frame 4: vehicle enters restricted zone ---
    now4 = now + timedelta(seconds=0.1)
    track3 = _make_track("T2", [(150.0, 300.0), (250.0, 300.0)], timestamp=now)
    result4 = TrackingResult(tracks=[track3], frame_index=3, timestamp=now4)
    v4 = engine.evaluate(result4)
    print(f"Frame 4 (zone entry): {len(v4)} violations")
    for v in v4:
        print(f"  -> {v.rule_type}: {v.explanation.reason}")

    # --- Frame 5: vehicle dwells in zone past limit ---
    now5 = now + timedelta(seconds=10.0)
    track4 = _make_track("T2", [(150.0, 300.0), (250.0, 300.0), (260.0, 300.0)], timestamp=now)
    result5 = TrackingResult(tracks=[track4], frame_index=10, timestamp=now5)
    v5 = engine.evaluate(result5)
    print(f"Frame 5 (dwell time): {len(v5)} violations")
    for v in v5:
        print(f"  -> {v.rule_type}: {v.explanation.reason}")

    # --- Frame 6: vehicle going WEST in eastbound lane ---
    now6 = now + timedelta(seconds=0.2)
    west_direction = MotionVector(
        dx=-10.0, dy=0.0, magnitude=10.0,
        bearing_degrees=180.0, direction=CardinalDirection.WEST,
    )
    track5 = _make_track(
        "T3",
        [(400.0, 300.0), (350.0, 300.0)],
        timestamp=now,
        direction=west_direction,
    )
    result6 = TrackingResult(tracks=[track5], frame_index=5, timestamp=now6)
    v6 = engine.evaluate(result6)
    print(f"Frame 6 (wrong direction): {len(v6)} violations")
    for v in v6:
        print(f"  -> {v.rule_type}: {v.explanation.reason}")

    # --- Summary ---
    all_v = v1 + v2 + v3 + v4 + v5 + v6
    if all_v:
        print("\n--- Sample Violation JSON ---")
        sample = all_v[0]
        print(json.dumps(sample.model_dump(mode="json"), indent=2, default=str))
        print("\n--- ORM kwargs ---")
        print(json.dumps(sample.to_orm_kwargs(), indent=2, default=str))

    print(f"\nTotal violations across demo: {len(all_v)}")
    print("Done.")


if __name__ == "__main__":
    main()
