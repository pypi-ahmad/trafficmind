from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.rules.config import RulesSettings
from services.rules.engine import RulesEngine
from services.rules.schemas import (
    LineGeometry,
    PedestrianOnRedRuleConfig,
    RedLightRuleConfig,
    RuleType,
    SceneContext,
    SceneSignalState,
    TrafficLightState,
    ZoneConfig,
    PolygonGeometry,
)
from services.signals.schemas import SignalPhase
from services.tracking.schemas import Point2D, TrackedObject, TrackingResult, TrajectoryPoint
from services.vision.schemas import BBox, ObjectCategory

from tests.fixtures.sample_data import load_json_fixture

NOW = datetime(2026, 4, 5, 12, 0, 0, tzinfo=timezone.utc)


def _make_track(track_id: str, *, points: list[list[float]], category: ObjectCategory, class_name: str) -> TrackedObject:
    trajectory = [
        TrajectoryPoint(
            point=Point2D(x=point[0], y=point[1]),
            frame_index=index,
            timestamp=NOW + timedelta(milliseconds=index * 33),
        )
        for index, point in enumerate(points)
    ]
    last = points[-1]
    return TrackedObject(
        track_id=track_id,
        class_name=class_name,
        category=category,
        bbox=BBox(x1=last[0] - 10, y1=last[1] - 10, x2=last[0] + 10, y2=last[1] + 10),
        confidence=0.9,
        first_seen_at=NOW,
        last_seen_at=NOW + timedelta(milliseconds=(len(points) - 1) * 33),
        first_seen_frame=0,
        last_seen_frame=len(points) - 1,
        frame_count=len(points),
        trajectory=trajectory,
    )


def _stop_line_zone(rule: RedLightRuleConfig) -> ZoneConfig:
    return ZoneConfig(
        zone_id="stop-line-1",
        name="StopLineA",
        zone_type="stop_line",
        geometry=LineGeometry(start=Point2D(x=100.0, y=300.0), end=Point2D(x=500.0, y=300.0)),
        rules=[rule],
    )


def _crosswalk_zone(rule: PedestrianOnRedRuleConfig) -> ZoneConfig:
    return ZoneConfig(
        zone_id="crosswalk-1",
        name="CrosswalkA",
        zone_type="crosswalk",
        geometry=PolygonGeometry(
            points=[
                Point2D(x=220.0, y=315.0),
                Point2D(x=380.0, y=315.0),
                Point2D(x=380.0, y=380.0),
                Point2D(x=220.0, y=380.0),
            ]
        ),
        rules=[rule],
    )


def _vehicle_scene(*, stop_line_id: str, signal_state: str) -> SceneContext:
    return SceneContext(
        signal_states=[
            SceneSignalState(
                head_id="veh-main",
                phase=SignalPhase.VEHICLE,
                state=TrafficLightState(signal_state),
                stop_line_id=stop_line_id,
                confidence=0.95,
            )
        ]
    )


def _pedestrian_scene(*, crosswalk_id: str, signal_state: str) -> SceneContext:
    return SceneContext(
        signal_states=[
            SceneSignalState(
                head_id="ped-main",
                phase=SignalPhase.PEDESTRIAN,
                state=TrafficLightState(signal_state),
                crosswalk_id=crosswalk_id,
                confidence=0.92,
            )
        ]
    )


def test_red_light_fixture_sequence() -> None:
    fixture = load_json_fixture("critical_logic/rules.json")["red_light_progression"]
    rule = RedLightRuleConfig(
        cooldown_seconds=0,
        confirmation_frames=1,
        min_post_crossing_seconds=0.05,
        min_post_crossing_distance_px=20.0,
    )
    zone = _stop_line_zone(rule)
    engine = RulesEngine([zone], settings=RulesSettings(candidate_timeout_seconds=1.0))

    for frame in fixture["frames"]:
        result = engine.evaluate_detailed(
            TrackingResult(
                tracks=[
                    _make_track(
                        frame["track_id"],
                        points=frame["points"],
                        category=ObjectCategory(frame["category"]),
                        class_name=frame["class_name"],
                    )
                ],
                frame_index=frame["frame_index"],
                timestamp=NOW + timedelta(milliseconds=frame["timestamp_offset_ms"]),
            ),
            scene=_vehicle_scene(stop_line_id=zone.zone_id, signal_state=frame["signal_state"]),
        )
        assert len(result.pre_violations) == frame["expected_pre_violations"]
        assert len(result.violations) == frame["expected_violations"]
        if result.violations:
            assert result.violations[0].rule_type == RuleType.RED_LIGHT


def test_pedestrian_on_red_fixture_sequence() -> None:
    fixture = load_json_fixture("critical_logic/rules.json")["pedestrian_on_red_progression"]
    rule = PedestrianOnRedRuleConfig(
        cooldown_seconds=0,
        confirmation_frames=1,
        min_inside_seconds=0.1,
    )
    zone = _crosswalk_zone(rule)
    engine = RulesEngine([zone], settings=RulesSettings(candidate_timeout_seconds=1.0))

    for frame in fixture["frames"]:
        result = engine.evaluate_detailed(
            TrackingResult(
                tracks=[
                    _make_track(
                        frame["track_id"],
                        points=frame["points"],
                        category=ObjectCategory(frame["category"]),
                        class_name=frame["class_name"],
                    )
                ],
                frame_index=frame["frame_index"],
                timestamp=NOW + timedelta(milliseconds=frame["timestamp_offset_ms"]),
            ),
            scene=_pedestrian_scene(crosswalk_id=zone.zone_id, signal_state=frame["signal_state"]),
        )
        assert len(result.pre_violations) == frame["expected_pre_violations"]
        assert len(result.violations) == frame["expected_violations"]
        if result.violations:
            assert result.violations[0].rule_type == RuleType.PEDESTRIAN_ON_RED