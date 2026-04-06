"""Comprehensive tests for the zone system and traffic rules engine."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from apps.api.app.db.enums import ViolationSeverity, ViolationType, ZoneType
from services.rules.config import RulesSettings
from services.rules.engine import RulesEngine
from services.rules.evaluators import (
    evaluate_illegal_parking,
    evaluate_line_crossing,
    evaluate_pedestrian_on_red,
    evaluate_red_light,
    evaluate_stop_line_crossing,
    evaluate_wrong_direction,
    evaluate_zone_dwell_time,
    evaluate_zone_entry,
)
from services.rules.persistence import pre_violation_to_event_dict, violation_to_orm_kwargs
from services.rules.schemas import (
    Explanation,
    IllegalParkingRuleConfig,
    LineCrossingRuleConfig,
    LineGeometry,
    PedestrianOnRedRuleConfig,
    PolygonGeometry,
    PreViolationRecord,
    RedLightRuleConfig,
    RuleType,
    SceneContext,
    SceneSignalState,
    StopLineCrossingRuleConfig,
    TrafficLightState,
    ViolationLifecycleStage,
    ViolationRecord,
    WrongDirectionRuleConfig,
    ZoneConfig,
    ZoneDwellTimeRuleConfig,
    ZoneEntryRuleConfig,
    parse_zone_config,
)
from services.signals.schemas import SignalPhase
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

NOW = datetime(2026, 4, 4, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_track(
    track_id: str,
    pts: list[tuple[float, float]],
    *,
    category: ObjectCategory = ObjectCategory.VEHICLE,
    class_name: str = "car",
    direction: MotionVector | None = None,
    timestamp: datetime = NOW,
) -> TrackedObject:
    traj = [
        TrajectoryPoint(
            point=Point2D(x=x, y=y),
            frame_index=i,
            timestamp=timestamp + timedelta(milliseconds=i * 33),
        )
        for i, (x, y) in enumerate(pts)
    ]
    last = pts[-1]
    return TrackedObject(
        track_id=track_id,
        class_name=class_name,
        category=category,
        bbox=BBox(x1=last[0] - 10, y1=last[1] - 10, x2=last[0] + 10, y2=last[1] + 10),
        confidence=0.9,
        first_seen_at=timestamp,
        last_seen_at=timestamp + timedelta(seconds=len(pts) * 0.033),
        first_seen_frame=0,
        last_seen_frame=len(pts) - 1,
        frame_count=len(pts),
        trajectory=traj,
        direction=direction,
    )


def _line_zone(
    zone_id: str = "z1",
    name: str = "Stop Line",
    zone_type: str = "stop_line",
    start: tuple[float, float] = (100.0, 300.0),
    end: tuple[float, float] = (500.0, 300.0),
    rules: list | None = None,
) -> ZoneConfig:
    return ZoneConfig(
        zone_id=zone_id,
        name=name,
        zone_type=zone_type,
        geometry=LineGeometry(
            start=Point2D(x=start[0], y=start[1]),
            end=Point2D(x=end[0], y=end[1]),
        ),
        rules=rules or [],
    )


def _polygon_zone(
    zone_id: str = "z2",
    name: str = "Restricted Area",
    zone_type: str = "restricted",
    points: list[tuple[float, float]] | None = None,
    rules: list | None = None,
) -> ZoneConfig:
    pts = points or [(200, 200), (400, 200), (400, 400), (200, 400)]
    return ZoneConfig(
        zone_id=zone_id,
        name=name,
        zone_type=zone_type,
        geometry=PolygonGeometry(points=[Point2D(x=x, y=y) for x, y in pts]),
        rules=rules or [],
    )


# ===================================================================
# Schema tests
# ===================================================================


def test_rule_type_enum_values():
    assert RuleType.LINE_CROSSING == "line_crossing"
    assert RuleType.ILLEGAL_PARKING == "illegal_parking"
    assert len(RuleType) == 11


def test_line_geometry_frozen():
    g = LineGeometry(start=Point2D(x=0, y=0), end=Point2D(x=1, y=1))
    with pytest.raises(ValidationError):
        g.start = Point2D(x=2, y=2)  # type: ignore[misc]


def test_polygon_geometry_min_points():
    with pytest.raises(ValidationError):
        PolygonGeometry(points=[Point2D(x=0, y=0), Point2D(x=1, y=1)])


def test_zone_config_geometry_as_dict():
    zone = _line_zone()
    d = zone.geometry_as_dict()
    assert "start" in d and "end" in d


def test_parse_zone_config_line():
    zc = parse_zone_config(
        zone_id="abc",
        name="SL",
        zone_type="stop_line",
        geometry={"start": {"x": 0, "y": 0}, "end": {"x": 10, "y": 10}},
        rules_config={"rules": [{"rule_type": "line_crossing", "severity": "high"}]},
    )
    assert zc.zone_type == ZoneType.STOP_LINE
    assert isinstance(zc.geometry, LineGeometry)
    assert len(zc.rules) == 1
    assert isinstance(zc.rules[0], LineCrossingRuleConfig)


def test_parse_zone_config_polygon():
    zc = parse_zone_config(
        zone_id="xyz",
        name="RZ",
        zone_type="restricted",
        geometry={"points": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}]},
        rules_config={"rules": []},
    )
    assert zc.zone_type == ZoneType.RESTRICTED
    assert isinstance(zc.geometry, PolygonGeometry)


def test_parse_zone_config_no_rules():
    zc = parse_zone_config(
        zone_id="a",
        name="A",
        zone_type="line",
        geometry={"start": {"x": 0, "y": 0}, "end": {"x": 10, "y": 10}},
        rules_config={},
    )
    assert zc.rules == []


def test_violation_record_to_orm_kwargs():
    vr = ViolationRecord(
        rule_type=RuleType.LINE_CROSSING,
        violation_type=ViolationType.STOP_LINE,
        severity=ViolationSeverity.HIGH,
        zone_id="z1",
        zone_name="SL",
        track_id="T1",
        occurred_at=NOW,
        explanation=Explanation(
            rule_type=RuleType.LINE_CROSSING,
            reason="crossed",
        ),
    )
    d = vr.to_orm_kwargs()
    assert d["violation_type"] == ViolationType.STOP_LINE
    assert d["severity"] == ViolationSeverity.HIGH
    assert d["occurred_at"] == NOW
    assert "rule_metadata" in d
    assert d["rule_metadata"]["rule_type"] == "line_crossing"


def test_scene_context_defaults():
    sc = SceneContext()
    assert sc.traffic_light_state == TrafficLightState.UNKNOWN
    assert sc.vehicle_signal_state == TrafficLightState.UNKNOWN
    assert sc.pedestrian_signal_state == TrafficLightState.UNKNOWN
    assert sc.signal_states == []
    assert sc.frame_index is None


def test_scene_context_stop_line_signal_resolution():
    sc = SceneContext(
        signal_states=[
            SceneSignalState(
                head_id="veh-sl1",
                phase=SignalPhase.VEHICLE,
                state=TrafficLightState.RED,
                stop_line_id="sl1",
            ),
            SceneSignalState(
                head_id="veh-sl2",
                phase=SignalPhase.VEHICLE,
                state=TrafficLightState.GREEN,
                stop_line_id="sl2",
            ),
        ]
    )
    assert sc.vehicle_signal_state_for_stop_line("sl1") == TrafficLightState.RED
    assert sc.vehicle_signal_state_for_stop_line("sl2") == TrafficLightState.GREEN


def test_scene_context_does_not_fallback_to_unrelated_stop_line_signal():
    sc = SceneContext(
        signal_states=[
            SceneSignalState(
                head_id="veh-other",
                phase=SignalPhase.VEHICLE,
                state=TrafficLightState.GREEN,
                stop_line_id="sl-other",
            )
        ]
    )
    assert sc.signal_for_stop_line("sl-target", phase=SignalPhase.VEHICLE) is None
    assert sc.vehicle_signal_state_for_stop_line("sl-target") == TrafficLightState.UNKNOWN


def test_scene_context_crosswalk_signal_resolution_requires_pedestrian_phase():
    sc = SceneContext(
        traffic_light_state=TrafficLightState.RED,
        signal_states=[
            SceneSignalState(
                head_id="veh-main",
                phase=SignalPhase.VEHICLE,
                state=TrafficLightState.RED,
                stop_line_id="sl1",
            )
        ],
    )
    assert sc.pedestrian_signal_state_for_crosswalk("cw1") == TrafficLightState.UNKNOWN


def test_scene_context_primary_signal_is_unknown_when_phase_is_ambiguous():
    sc = SceneContext(
        signal_states=[
            SceneSignalState(
                head_id="veh-a",
                phase=SignalPhase.VEHICLE,
                state=TrafficLightState.RED,
            ),
            SceneSignalState(
                head_id="veh-b",
                phase=SignalPhase.VEHICLE,
                state=TrafficLightState.GREEN,
            ),
        ]
    )
    assert sc.primary_signal(phase=SignalPhase.VEHICLE) is None
    assert sc.vehicle_signal_state_for_stop_line(None) == TrafficLightState.UNKNOWN


def test_discriminated_union_resolves():
    # Use the parse_zone_config path for full integration
    zc = parse_zone_config(
        zone_id="d",
        name="D",
        zone_type="polygon",
        geometry={"points": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}]},
        rules_config={
            "rules": [
                {"rule_type": "zone_entry", "severity": "low"},
                {"rule_type": "zone_dwell_time", "max_dwell_seconds": 10},
            ]
        },
    )
    assert isinstance(zc.rules[0], ZoneEntryRuleConfig)
    assert isinstance(zc.rules[1], ZoneDwellTimeRuleConfig)
    assert zc.rules[1].max_dwell_seconds == 10.0


# ===================================================================
# Evaluator tests
# ===================================================================


def test_evaluate_line_crossing_fires():
    zone = _line_zone(rules=[LineCrossingRuleConfig()])
    # Trajectory crosses y=300 line
    track = _make_track("T1", [(300, 290), (300, 310)])
    v = evaluate_line_crossing(track, zone, zone.rules[0], NOW)
    assert v is not None
    assert v.rule_type == RuleType.LINE_CROSSING
    assert v.track_id == "T1"
    assert v.explanation.reason.startswith("Track T1")


def test_evaluate_line_crossing_no_crossing():
    zone = _line_zone(rules=[LineCrossingRuleConfig()])
    track = _make_track("T1", [(300, 280), (300, 290)])
    v = evaluate_line_crossing(track, zone, zone.rules[0], NOW)
    assert v is None


def test_evaluate_line_crossing_forbidden_direction_blocks():
    zone = _line_zone(
        rules=[
            LineCrossingRuleConfig(
                forbidden_direction=LineCrossingDirection.POSITIVE_TO_NEGATIVE,
            ),
        ]
    )
    # neg-to-pos crossing (y goes from 290 to 310 across y=300 line)
    track = _make_track("T1", [(300, 290), (300, 310)])
    v = evaluate_line_crossing(track, zone, zone.rules[0], NOW)
    # Direction doesn't match forbidden → should NOT fire
    assert v is None


def test_evaluate_line_crossing_forbidden_direction_matches():
    zone = _line_zone(
        rules=[
            LineCrossingRuleConfig(
                forbidden_direction=LineCrossingDirection.NEGATIVE_TO_POSITIVE,
            ),
        ]
    )
    track = _make_track("T1", [(300, 290), (300, 310)])
    v = evaluate_line_crossing(track, zone, zone.rules[0], NOW)
    # The crossing is neg-to-pos, forbidden is neg-to-pos → fire
    # Wait — need to check what direction this crossing actually is.
    # Line from (100,300) to (500,300) is horizontal.
    # Point goes from y=290 (above) to y=310 (below).
    # Previous side: 400 * (290 - 300) = -4000, so it starts negative.
    # Current side: 400 * (310 - 300) = 4000, so it moves to positive.
    # The crossing is negative-to-positive, which matches the forbidden direction.
    assert v is not None


def test_evaluate_line_crossing_wrong_geometry_type():
    zone = _polygon_zone(rules=[LineCrossingRuleConfig()])
    track = _make_track("T1", [(300, 290), (300, 310)])
    v = evaluate_line_crossing(track, zone, zone.rules[0], NOW)
    assert v is None


def test_evaluate_stop_line_crossing_requires_red():
    zone = _line_zone(rules=[StopLineCrossingRuleConfig(requires_red_light=True)])
    track = _make_track("T1", [(300, 290), (300, 310)])

    # No scene → no violation
    v = evaluate_stop_line_crossing(track, zone, zone.rules[0], NOW, scene=None)
    assert v is None

    # Green → no violation
    v = evaluate_stop_line_crossing(
        track,
        zone,
        zone.rules[0],
        NOW,
        scene=SceneContext(traffic_light_state=TrafficLightState.GREEN),
    )
    assert v is None

    # Red → fires
    v = evaluate_stop_line_crossing(
        track,
        zone,
        zone.rules[0],
        NOW,
        scene=SceneContext(traffic_light_state=TrafficLightState.RED),
    )
    assert v is not None
    assert v.rule_type == RuleType.STOP_LINE_CROSSING


def test_evaluate_stop_line_no_red_required():
    rule = StopLineCrossingRuleConfig(requires_red_light=False)
    zone = _line_zone(rules=[rule])
    track = _make_track("T1", [(300, 290), (300, 310)])
    v = evaluate_stop_line_crossing(track, zone, rule, NOW, scene=None)
    assert v is not None


def test_evaluate_zone_entry_fires():
    rule = ZoneEntryRuleConfig(restricted_categories=[ObjectCategory.VEHICLE])
    zone = _polygon_zone(rules=[rule])
    # Trajectory goes from outside (150,300) to inside (250,300) the polygon
    track = _make_track("T1", [(150, 300), (250, 300)])
    v = evaluate_zone_entry(track, zone, rule, NOW)
    assert v is not None
    assert v.rule_type == RuleType.ZONE_ENTRY


def test_evaluate_zone_entry_wrong_category():
    rule = ZoneEntryRuleConfig(restricted_categories=[ObjectCategory.VEHICLE])
    zone = _polygon_zone(rules=[rule])
    track = _make_track(
        "T1", [(150, 300), (250, 300)], category=ObjectCategory.PERSON, class_name="person"
    )
    v = evaluate_zone_entry(track, zone, rule, NOW)
    assert v is None


def test_evaluate_zone_entry_no_entry():
    rule = ZoneEntryRuleConfig()
    zone = _polygon_zone(rules=[rule])
    # Both points inside → no ENTERED transition
    track = _make_track("T1", [(250, 300), (260, 300)])
    v = evaluate_zone_entry(track, zone, rule, NOW)
    assert v is None


def test_evaluate_zone_dwell_time_fires():
    rule = ZoneDwellTimeRuleConfig(max_dwell_seconds=5.0)
    zone = _polygon_zone(rules=[rule])
    track = _make_track("T1", [(250, 300), (260, 300)])
    entered_at = NOW - timedelta(seconds=10)
    v = evaluate_zone_dwell_time(track, zone, rule, NOW, entered_at)
    assert v is not None
    assert v.explanation.details["dwell_seconds"] == 10.0


def test_evaluate_zone_dwell_time_under_limit():
    rule = ZoneDwellTimeRuleConfig(max_dwell_seconds=30.0)
    zone = _polygon_zone(rules=[rule])
    track = _make_track("T1", [(250, 300)])
    entered_at = NOW - timedelta(seconds=5)
    v = evaluate_zone_dwell_time(track, zone, rule, NOW, entered_at)
    assert v is None


def test_evaluate_zone_dwell_time_no_entry():
    rule = ZoneDwellTimeRuleConfig(max_dwell_seconds=5.0)
    zone = _polygon_zone(rules=[rule])
    track = _make_track("T1", [(250, 300)])
    v = evaluate_zone_dwell_time(track, zone, rule, NOW, entered_at=None)
    assert v is None


def test_evaluate_wrong_direction_fires():
    rule = WrongDirectionRuleConfig(expected_direction=CardinalDirection.EAST)
    zone = _polygon_zone(
        zone_id="lane1",
        name="Eastbound",
        zone_type="lane",
        points=[(0, 250), (600, 250), (600, 350), (0, 350)],
        rules=[rule],
    )
    west = MotionVector(
        dx=-10,
        dy=0,
        magnitude=10,
        bearing_degrees=180.0,
        direction=CardinalDirection.WEST,
    )
    # Track at (300,300) is inside the lane polygon
    track = _make_track("T1", [(350, 300), (300, 300)], direction=west)
    v = evaluate_wrong_direction(track, zone, rule, NOW)
    assert v is not None
    assert v.rule_type == RuleType.WRONG_DIRECTION
    assert v.explanation.details["actual_direction"] == "west"


def test_evaluate_wrong_direction_correct():
    rule = WrongDirectionRuleConfig(expected_direction=CardinalDirection.EAST)
    zone = _polygon_zone(
        zone_id="lane1",
        name="Eastbound",
        zone_type="lane",
        points=[(0, 250), (600, 250), (600, 350), (0, 350)],
        rules=[rule],
    )
    east = MotionVector(
        dx=10,
        dy=0,
        magnitude=10,
        bearing_degrees=0.0,
        direction=CardinalDirection.EAST,
    )
    track = _make_track("T1", [(300, 300), (350, 300)], direction=east)
    v = evaluate_wrong_direction(track, zone, rule, NOW)
    assert v is None


def test_evaluate_wrong_direction_outside_zone():
    rule = WrongDirectionRuleConfig(expected_direction=CardinalDirection.EAST)
    zone = _polygon_zone(
        zone_id="lane1",
        name="Eastbound",
        zone_type="lane",
        points=[(0, 250), (600, 250), (600, 350), (0, 350)],
        rules=[rule],
    )
    west = MotionVector(
        dx=-10,
        dy=0,
        magnitude=10,
        bearing_degrees=180.0,
        direction=CardinalDirection.WEST,
    )
    # Track at (300,100) is outside the lane polygon (y=100 not in 250-350)
    track = _make_track("T1", [(350, 100), (300, 100)], direction=west)
    v = evaluate_wrong_direction(track, zone, rule, NOW)
    assert v is None


def test_evaluate_wrong_direction_stationary():
    rule = WrongDirectionRuleConfig(expected_direction=CardinalDirection.EAST)
    zone = _polygon_zone(zone_id="l", name="L", zone_type="lane", rules=[rule])
    stationary = MotionVector(
        dx=0,
        dy=0,
        magnitude=0,
        bearing_degrees=None,
        direction=CardinalDirection.STATIONARY,
    )
    track = _make_track("T1", [(300, 300)], direction=stationary)
    v = evaluate_wrong_direction(track, zone, rule, NOW)
    assert v is None


def test_evaluate_red_light_fires():
    rule = RedLightRuleConfig()
    zone = _line_zone(zone_id="sl", name="SL", rules=[rule])
    track = _make_track("T1", [(300, 290), (300, 310)])
    scene = SceneContext(
        signal_states=[
            SceneSignalState(
                head_id="veh-sl",
                phase=SignalPhase.VEHICLE,
                state=TrafficLightState.RED,
                stop_line_id="sl",
            )
        ]
    )
    v = evaluate_red_light(track, zone, rule, NOW, scene)
    assert v is not None
    assert v.rule_type == RuleType.RED_LIGHT
    assert v.violation_type == ViolationType.RED_LIGHT


def test_evaluate_red_light_uses_stop_line_specific_signal():
    rule = RedLightRuleConfig()
    zone = _line_zone(zone_id="sl2", name="SL2", rules=[rule])
    track = _make_track("T1", [(300, 290), (300, 310)])
    scene = SceneContext(
        signal_states=[
            SceneSignalState(
                head_id="veh-sl1",
                phase=SignalPhase.VEHICLE,
                state=TrafficLightState.RED,
                stop_line_id="sl1",
            ),
            SceneSignalState(
                head_id="veh-sl2",
                phase=SignalPhase.VEHICLE,
                state=TrafficLightState.GREEN,
                stop_line_id="sl2",
            ),
        ]
    )
    v = evaluate_red_light(track, zone, rule, NOW, scene)
    assert v is None


def test_evaluate_red_light_no_red():
    rule = RedLightRuleConfig()
    zone = _line_zone(rules=[rule])
    track = _make_track("T1", [(300, 290), (300, 310)])
    v = evaluate_red_light(track, zone, rule, NOW, scene=None)
    assert v is None


def test_evaluate_red_light_not_vehicle():
    rule = RedLightRuleConfig()
    zone = _line_zone(rules=[rule])
    track = _make_track(
        "T1", [(300, 290), (300, 310)], category=ObjectCategory.PERSON, class_name="person"
    )
    scene = SceneContext(traffic_light_state=TrafficLightState.RED)
    v = evaluate_red_light(track, zone, rule, NOW, scene)
    assert v is None


def test_evaluate_pedestrian_on_red_fires():
    rule = PedestrianOnRedRuleConfig()
    zone = _polygon_zone(zone_id="cw", name="Crosswalk", zone_type="crosswalk", rules=[rule])
    # Pedestrian inside the polygon
    track = _make_track("P1", [(300, 300)], category=ObjectCategory.PERSON, class_name="person")
    scene = SceneContext(
        signal_states=[
            SceneSignalState(
                head_id="ped-cw",
                phase=SignalPhase.PEDESTRIAN,
                state=TrafficLightState.RED,
                crosswalk_id="cw",
            )
        ]
    )
    v = evaluate_pedestrian_on_red(track, zone, rule, NOW, scene)
    assert v is not None
    assert v.rule_type == RuleType.PEDESTRIAN_ON_RED


def test_evaluate_pedestrian_on_red_not_red():
    rule = PedestrianOnRedRuleConfig()
    zone = _polygon_zone(rules=[rule])
    track = _make_track("P1", [(300, 300)], category=ObjectCategory.PERSON, class_name="person")
    v = evaluate_pedestrian_on_red(track, zone, rule, NOW, scene=None)
    assert v is None


def test_evaluate_pedestrian_on_red_not_pedestrian():
    rule = PedestrianOnRedRuleConfig()
    zone = _polygon_zone(rules=[rule])
    track = _make_track("V1", [(300, 300)])
    scene = SceneContext(pedestrian_signal_state=TrafficLightState.RED)
    v = evaluate_pedestrian_on_red(track, zone, rule, NOW, scene)
    assert v is None


def test_evaluate_pedestrian_on_red_does_not_use_vehicle_signal():
    rule = PedestrianOnRedRuleConfig()
    zone = _polygon_zone(zone_id="cw", name="Crosswalk", zone_type="crosswalk", rules=[rule])
    track = _make_track("P1", [(300, 300)], category=ObjectCategory.PERSON, class_name="person")
    scene = SceneContext(traffic_light_state=TrafficLightState.RED)
    v = evaluate_pedestrian_on_red(track, zone, rule, NOW, scene)
    assert v is None


def test_evaluate_illegal_parking_fires():
    rule = IllegalParkingRuleConfig(
        max_stationary_seconds=30.0,
        min_stationary_streak_seconds=0.0,
    )
    zone = _polygon_zone(rules=[rule])
    # Stationary vehicle — enough points to satisfy stationarity ratio
    track = _make_track("V1", [(300, 300)] * 10)
    entered_at = NOW - timedelta(seconds=60)
    v = evaluate_illegal_parking(track, zone, rule, NOW, entered_at)
    assert v is not None
    assert v.rule_type == RuleType.ILLEGAL_PARKING
    assert v.explanation.details["dwell_seconds"] == 60.0


def test_evaluate_illegal_parking_moving():
    rule = IllegalParkingRuleConfig(max_stationary_seconds=30.0)
    zone = _polygon_zone(rules=[rule])
    moving = MotionVector(dx=10, dy=0, magnitude=10, direction=CardinalDirection.EAST)
    track = _make_track("V1", [(300, 300)], direction=moving)
    entered_at = NOW - timedelta(seconds=60)
    v = evaluate_illegal_parking(track, zone, rule, NOW, entered_at)
    assert v is None  # moving → not parked


def test_evaluate_illegal_parking_under_limit():
    rule = IllegalParkingRuleConfig(max_stationary_seconds=120.0)
    zone = _polygon_zone(rules=[rule])
    track = _make_track("V1", [(300, 300)])
    entered_at = NOW - timedelta(seconds=30)
    v = evaluate_illegal_parking(track, zone, rule, NOW, entered_at)
    assert v is None


def test_evaluate_illegal_parking_not_vehicle():
    rule = IllegalParkingRuleConfig(max_stationary_seconds=10.0)
    zone = _polygon_zone(rules=[rule])
    track = _make_track("P1", [(300, 300)], category=ObjectCategory.PERSON, class_name="person")
    entered_at = NOW - timedelta(seconds=60)
    v = evaluate_illegal_parking(track, zone, rule, NOW, entered_at)
    assert v is None


# ===================================================================
# Engine tests
# ===================================================================


def test_engine_empty_zones():
    engine = RulesEngine([], settings=RulesSettings())
    result = TrackingResult(tracks=[], frame_index=0, timestamp=NOW)
    assert engine.evaluate(result) == []


def test_engine_line_crossing_end_to_end():
    rule = LineCrossingRuleConfig(cooldown_seconds=0)
    zone = _line_zone(rules=[rule])
    engine = RulesEngine([zone], settings=RulesSettings())
    track = _make_track("T1", [(300, 290), (300, 310)])
    result = TrackingResult(tracks=[track], frame_index=0, timestamp=NOW)
    violations = engine.evaluate(result)
    assert len(violations) == 1
    assert violations[0].zone_name == "Stop Line"


def test_engine_cooldown_prevents_repeat():
    rule = LineCrossingRuleConfig(cooldown_seconds=60)
    zone = _line_zone(rules=[rule])
    engine = RulesEngine([zone], settings=RulesSettings())
    track = _make_track("T1", [(300, 290), (300, 310)])

    # First evaluation → fires
    r1 = TrackingResult(tracks=[track], frame_index=0, timestamp=NOW)
    v1 = engine.evaluate(r1)
    assert len(v1) == 1

    # Second evaluation 5s later → cooled down (within 60s)
    r2 = TrackingResult(tracks=[track], frame_index=1, timestamp=NOW + timedelta(seconds=5))
    v2 = engine.evaluate(r2)
    assert len(v2) == 0


def test_engine_cooldown_expires():
    rule = LineCrossingRuleConfig(cooldown_seconds=10)
    zone = _line_zone(rules=[rule])
    engine = RulesEngine([zone], settings=RulesSettings())
    track = _make_track("T1", [(300, 290), (300, 310)])

    r1 = TrackingResult(tracks=[track], frame_index=0, timestamp=NOW)
    v1 = engine.evaluate(r1)
    assert len(v1) == 1

    # After cooldown expires → fires again
    r2 = TrackingResult(tracks=[track], frame_index=2, timestamp=NOW + timedelta(seconds=15))
    v2 = engine.evaluate(r2)
    assert len(v2) == 1


def test_engine_disabled_rule_skipped():
    rule = LineCrossingRuleConfig(enabled=False, cooldown_seconds=0)
    zone = _line_zone(rules=[rule])
    engine = RulesEngine([zone], settings=RulesSettings())
    track = _make_track("T1", [(300, 290), (300, 310)])
    result = TrackingResult(tracks=[track], frame_index=0, timestamp=NOW)
    assert engine.evaluate(result) == []


def test_engine_zone_occupancy_tracking():
    rule = ZoneDwellTimeRuleConfig(max_dwell_seconds=5.0, cooldown_seconds=0)
    zone = _polygon_zone(rules=[rule])
    engine = RulesEngine([zone], settings=RulesSettings())

    # Frame 1: track enters zone → entry recorded
    track_in = _make_track("T1", [(150, 300), (250, 300)])
    r1 = TrackingResult(tracks=[track_in], frame_index=0, timestamp=NOW)
    v1 = engine.evaluate(r1)  # no dwell yet
    assert len(v1) == 0

    # Entry should be tracked
    assert ("T1", "z2") in engine._zone_entries

    # Frame 2: track still in zone 10s later → dwell fires
    track_still = _make_track("T1", [(260, 300)])
    r2 = TrackingResult(
        tracks=[track_still],
        frame_index=10,
        timestamp=NOW + timedelta(seconds=10),
    )
    v2 = engine.evaluate(r2)
    assert len(v2) == 1
    assert v2[0].rule_type == RuleType.ZONE_DWELL_TIME


def test_engine_cleanup_on_track_removal():
    rule = ZoneDwellTimeRuleConfig(max_dwell_seconds=5.0, cooldown_seconds=0)
    zone = _polygon_zone(rules=[rule])
    engine = RulesEngine([zone], settings=RulesSettings())

    # Add a track inside the zone
    track = _make_track("T1", [(250, 300)])
    engine.evaluate(TrackingResult(tracks=[track], frame_index=0, timestamp=NOW))
    assert ("T1", "z2") in engine._zone_entries

    # Remove the track
    removed = _make_track("T1", [(250, 300)])
    engine.evaluate(
        TrackingResult(
            tracks=[],
            removed_tracks=[removed],
            frame_index=1,
            timestamp=NOW + timedelta(seconds=1),
        )
    )
    assert ("T1", "z2") not in engine._zone_entries


def test_engine_reset():
    rule = LineCrossingRuleConfig(cooldown_seconds=60)
    zone = _line_zone(rules=[rule])
    engine = RulesEngine([zone], settings=RulesSettings())
    track = _make_track("T1", [(300, 290), (300, 310)])
    engine.evaluate(TrackingResult(tracks=[track], frame_index=0, timestamp=NOW))
    assert len(engine._cooldowns) > 0

    engine.reset()
    assert len(engine._cooldowns) == 0
    assert len(engine._zone_entries) == 0


def test_engine_multiple_rules_same_zone():
    rules = [
        LineCrossingRuleConfig(cooldown_seconds=0),
        RedLightRuleConfig(
            cooldown_seconds=0,
            confirmation_frames=1,
            min_post_crossing_seconds=0.05,
            min_post_crossing_distance_px=8.0,
        ),
    ]
    zone = _line_zone(rules=rules)
    engine = RulesEngine([zone], settings=RulesSettings(candidate_timeout_seconds=1.0))
    scene = SceneContext(traffic_light_state=TrafficLightState.RED)

    first = TrackingResult(
        tracks=[_make_track("T1", [(300, 290), (300, 310)])],
        frame_index=0,
        timestamp=NOW,
    )
    first_result = engine.evaluate_detailed(first, scene=scene)
    assert {v.rule_type for v in first_result.violations} == {RuleType.LINE_CROSSING}
    assert {v.rule_type for v in first_result.pre_violations} == {RuleType.RED_LIGHT}

    second = TrackingResult(
        tracks=[_make_track("T1", [(300, 290), (300, 310), (300, 326)])],
        frame_index=1,
        timestamp=NOW + timedelta(milliseconds=100),
    )
    second_result = engine.evaluate_detailed(second, scene=scene)
    assert {v.rule_type for v in second_result.violations} == {RuleType.RED_LIGHT}
    assert second_result.pre_violations == []


def test_engine_multiple_zones():
    zone1 = _line_zone(
        zone_id="sl1",
        name="StopLine1",
        rules=[LineCrossingRuleConfig(cooldown_seconds=0)],
    )
    zone2 = _line_zone(
        zone_id="sl2",
        name="StopLine2",
        start=(100.0, 300.0),
        end=(500.0, 300.0),
        rules=[LineCrossingRuleConfig(cooldown_seconds=0)],
    )
    engine = RulesEngine([zone1, zone2], settings=RulesSettings())
    track = _make_track("T1", [(300, 290), (300, 310)])
    result = TrackingResult(tracks=[track], frame_index=0, timestamp=NOW)
    violations = engine.evaluate(result)
    assert len(violations) == 2
    zone_ids = {v.zone_id for v in violations}
    assert zone_ids == {"sl1", "sl2"}


def test_engine_zones_property():
    zone = _line_zone()
    engine = RulesEngine([zone], settings=RulesSettings())
    assert len(engine.zones) == 1
    assert engine.zones[0].zone_id == "z1"


# ===================================================================
# Persistence tests
# ===================================================================


def test_violation_to_orm_kwargs():
    vr = ViolationRecord(
        rule_type=RuleType.RED_LIGHT,
        violation_type=ViolationType.RED_LIGHT,
        severity=ViolationSeverity.CRITICAL,
        zone_id=str(uuid.uuid4()),
        zone_name="SL",
        track_id="T1",
        occurred_at=NOW,
        explanation=Explanation(
            rule_type=RuleType.RED_LIGHT,
            reason="Ran red light",
        ),
    )
    cam_id = uuid.uuid4()
    d = violation_to_orm_kwargs(vr, camera_id=cam_id)
    assert d["camera_id"] == cam_id
    assert d["violation_type"] == ViolationType.RED_LIGHT
    assert d["zone_id"] == uuid.UUID(vr.zone_id)
    assert "rule_metadata" in d


def test_violation_to_orm_kwargs_non_uuid_zone():
    vr = ViolationRecord(
        rule_type=RuleType.LINE_CROSSING,
        violation_type=ViolationType.STOP_LINE,
        severity=ViolationSeverity.MEDIUM,
        zone_id="synthetic-zone",
        zone_name="SL",
        track_id="T1",
        occurred_at=NOW,
        explanation=Explanation(
            rule_type=RuleType.LINE_CROSSING,
            reason="crossed",
        ),
    )
    cam_id = uuid.uuid4()
    d = violation_to_orm_kwargs(vr, camera_id=cam_id)
    assert d["zone_id"] is None  # non-UUID zone_id → None


def test_violation_to_orm_kwargs_explicit_ids():
    vr = ViolationRecord(
        rule_type=RuleType.LINE_CROSSING,
        violation_type=ViolationType.STOP_LINE,
        severity=ViolationSeverity.MEDIUM,
        zone_id="x",
        zone_name="SL",
        track_id="T1",
        occurred_at=NOW,
        explanation=Explanation(
            rule_type=RuleType.LINE_CROSSING,
            reason="crossed",
        ),
    )
    cam_id = uuid.uuid4()
    zone_uuid = uuid.uuid4()
    det_id = uuid.uuid4()
    d = violation_to_orm_kwargs(
        vr,
        camera_id=cam_id,
        zone_id=zone_uuid,
        detection_event_id=det_id,
    )
    assert d["zone_id"] == zone_uuid
    assert d["detection_event_id"] == det_id


def test_pre_violation_to_event_dict():
    pv = PreViolationRecord(
        rule_type=RuleType.RED_LIGHT,
        violation_type=ViolationType.RED_LIGHT,
        zone_id="z1",
        zone_name="SL",
        track_id="T1",
        observed_at=NOW,
        candidate_started_at=NOW - timedelta(seconds=1),
        explanation=Explanation(
            rule_type=RuleType.RED_LIGHT,
            reason="candidate",
            conditions_satisfied=["signal_red_at_detection"],
        ),
    )
    assert pv.stage == ViolationLifecycleStage.PRE_VIOLATION
    d = pv.to_event_dict()
    assert d["stage"] == "pre_violation"
    assert d["rule_type"] == "red_light"
    assert d["track_id"] == "T1"
    assert "explanation" in d


def test_pre_violation_to_event_dict_persistence_bridge():
    pv = PreViolationRecord(
        rule_type=RuleType.STOP_LINE_CROSSING,
        violation_type=ViolationType.STOP_LINE,
        zone_id="z1",
        zone_name="SL",
        track_id="T1",
        observed_at=NOW,
        candidate_started_at=NOW,
        explanation=Explanation(
            rule_type=RuleType.STOP_LINE_CROSSING,
            reason="candidate",
        ),
    )
    cam_id = uuid.uuid4()
    stream = uuid.uuid4()
    d = pre_violation_to_event_dict(pv, camera_id=cam_id, stream_id=stream)
    assert d["camera_id"] == cam_id
    assert d["stream_id"] == stream
    assert d["stage"] == "pre_violation"
    assert d["rule_type"] == "stop_line_crossing"
    assert d["track_id"] == "T1"


# ===================================================================
# Config tests
# ===================================================================


def test_rules_settings_defaults():
    s = RulesSettings()
    assert s.default_cooldown_seconds == 30.0
    assert s.max_violations_per_track == 50
    assert s.enable_debug_logging is False


# ===================================================================
# Explanation completeness
# ===================================================================


def test_explanation_contains_all_fields():
    rule = LineCrossingRuleConfig(cooldown_seconds=0)
    zone = _line_zone(rules=[rule])
    track = _make_track("T1", [(300, 290), (300, 310)])
    v = evaluate_line_crossing(track, zone, rule, NOW)
    assert v is not None
    exp = v.explanation
    assert exp.rule_type == RuleType.LINE_CROSSING
    assert "rule_type" in exp.rule_config
    assert len(exp.reason) > 0
    assert "crossing_direction" in exp.details
    assert exp.track_snapshot["track_id"] == "T1"
    assert exp.zone_info["zone_id"] == "z1"
    assert exp.zone_info["zone_name"] == "Stop Line"
    assert "geometry" in exp.zone_info
