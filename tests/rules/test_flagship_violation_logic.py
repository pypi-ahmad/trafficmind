from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.rules.config import RulesSettings
from services.rules.engine import RulesEngine
from services.rules.schemas import (
    LineGeometry,
    PedestrianOnRedRuleConfig,
    PolygonGeometry,
    RedLightRuleConfig,
    RuleType,
    SceneContext,
    SceneSignalState,
    StopLineCrossingRuleConfig,
    TrafficLightState,
    ZoneConfig,
)
from services.signals.schemas import SignalPhase
from services.tracking.schemas import Point2D, TrackedObject, TrackingResult, TrajectoryPoint
from services.vision.schemas import BBox, ObjectCategory

NOW = datetime(2026, 4, 5, 12, 0, 0, tzinfo=timezone.utc)


def _make_track(
    track_id: str,
    pts: list[tuple[float, float]],
    *,
    category: ObjectCategory = ObjectCategory.VEHICLE,
    class_name: str = "car",
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
        last_seen_at=timestamp + timedelta(milliseconds=(len(pts) - 1) * 33),
        first_seen_frame=0,
        last_seen_frame=len(pts) - 1,
        frame_count=len(pts),
        trajectory=traj,
    )


def _stop_line_zone(*, rules: list) -> ZoneConfig:
    return ZoneConfig(
        zone_id="stop-line-1",
        name="StopLineA",
        zone_type="stop_line",
        geometry=LineGeometry(
            start=Point2D(x=100.0, y=300.0),
            end=Point2D(x=500.0, y=300.0),
        ),
        rules=rules,
    )


def _crosswalk_zone(*, rules: list | None = None) -> ZoneConfig:
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
        rules=rules or [],
    )


def _vehicle_red_scene(*, stop_line_id: str = "stop-line-1") -> SceneContext:
    return SceneContext(
        signal_states=[
            SceneSignalState(
                head_id="veh-main",
                phase=SignalPhase.VEHICLE,
                state=TrafficLightState.RED,
                stop_line_id=stop_line_id,
                confidence=0.95,
            )
        ]
    )


def _pedestrian_scene(state: TrafficLightState, *, crosswalk_id: str = "crosswalk-1") -> SceneContext:
    return SceneContext(
        signal_states=[
            SceneSignalState(
                head_id="ped-main",
                phase=SignalPhase.PEDESTRIAN,
                state=state,
                crosswalk_id=crosswalk_id,
                confidence=0.92,
            )
        ]
    )


def test_stop_line_crossing_on_red_uses_pre_violation_then_confirmation() -> None:
    rule = StopLineCrossingRuleConfig(
        cooldown_seconds=0,
        confirmation_frames=1,
        min_post_crossing_seconds=0.05,
        min_post_crossing_distance_px=8.0,
    )
    zone = _stop_line_zone(rules=[rule])
    engine = RulesEngine([zone], settings=RulesSettings(candidate_timeout_seconds=1.0))

    t0 = NOW
    frame0 = TrackingResult(
        tracks=[_make_track("veh-1", [(300.0, 290.0), (300.0, 304.0)], timestamp=t0)],
        frame_index=10,
        timestamp=t0,
    )
    result0 = engine.evaluate_detailed(frame0, scene=_vehicle_red_scene(stop_line_id=zone.zone_id))

    assert result0.violations == []
    assert len(result0.pre_violations) == 1
    assert result0.pre_violations[0].rule_type == RuleType.STOP_LINE_CROSSING
    assert "signal_red_at_detection" in result0.pre_violations[0].explanation.conditions_satisfied

    t1 = t0 + timedelta(milliseconds=100)
    frame1 = TrackingResult(
        tracks=[_make_track("veh-1", [(300.0, 290.0), (300.0, 304.0), (300.0, 320.0)], timestamp=t0)],
        frame_index=11,
        timestamp=t1,
    )
    result1 = engine.evaluate_detailed(frame1, scene=_vehicle_red_scene(stop_line_id=zone.zone_id))

    assert result1.pre_violations == []
    assert len(result1.violations) == 1
    violation = result1.violations[0]
    assert violation.rule_type == RuleType.STOP_LINE_CROSSING
    assert violation.explanation.details["signal_state_at_decision"] == "red"
    assert violation.explanation.details["confirmation_frames_elapsed"] >= 1
    assert violation.explanation.details["post_crossing_distance_px"] >= 8.0


def test_red_light_jump_requires_protected_area_progression() -> None:
    rule = RedLightRuleConfig(
        cooldown_seconds=0,
        confirmation_frames=1,
        min_post_crossing_seconds=0.05,
        min_post_crossing_distance_px=20.0,
    )
    zone = _stop_line_zone(rules=[rule])
    engine = RulesEngine([zone], settings=RulesSettings(candidate_timeout_seconds=1.0))

    t0 = NOW
    result0 = engine.evaluate_detailed(
        TrackingResult(
            tracks=[_make_track("veh-1", [(300.0, 290.0), (300.0, 304.0)], timestamp=t0)],
            frame_index=0,
            timestamp=t0,
        ),
        scene=_vehicle_red_scene(stop_line_id=zone.zone_id),
    )
    assert result0.violations == []
    assert len(result0.pre_violations) == 1

    t1 = t0 + timedelta(milliseconds=100)
    result1 = engine.evaluate_detailed(
        TrackingResult(
            tracks=[_make_track("veh-1", [(300.0, 290.0), (300.0, 304.0), (300.0, 328.0)], timestamp=t0)],
            frame_index=1,
            timestamp=t1,
        ),
        scene=_vehicle_red_scene(stop_line_id=zone.zone_id),
    )
    assert len(result1.violations) == 1
    assert result1.violations[0].rule_type == RuleType.RED_LIGHT


def test_red_light_jump_uses_linked_crosswalk_when_configured() -> None:
    rule = RedLightRuleConfig(
        cooldown_seconds=0,
        crosswalk_zone_name="CrosswalkA",
        confirmation_frames=1,
        min_post_crossing_seconds=0.05,
    )
    stop_line = _stop_line_zone(rules=[rule])
    crosswalk = _crosswalk_zone()
    engine = RulesEngine([stop_line, crosswalk], settings=RulesSettings(candidate_timeout_seconds=1.0))

    t0 = NOW
    first = engine.evaluate_detailed(
        TrackingResult(
            tracks=[_make_track("veh-1", [(300.0, 290.0), (300.0, 304.0)], timestamp=t0)],
            frame_index=0,
            timestamp=t0,
        ),
        scene=_vehicle_red_scene(stop_line_id=stop_line.zone_id),
    )
    assert first.violations == []
    assert len(first.pre_violations) == 1

    t1 = t0 + timedelta(milliseconds=100)
    second = engine.evaluate_detailed(
        TrackingResult(
            tracks=[_make_track("veh-1", [(300.0, 290.0), (300.0, 304.0), (300.0, 330.0)], timestamp=t0)],
            frame_index=1,
            timestamp=t1,
        ),
        scene=_vehicle_red_scene(stop_line_id=stop_line.zone_id),
    )
    assert len(second.violations) == 1
    details = second.violations[0].explanation.details
    assert details["entered_linked_crosswalk"] is True
    assert crosswalk.zone_id in details["relevant_zone_ids"]


def test_pedestrian_on_red_uses_crosswalk_entry_timing() -> None:
    rule = PedestrianOnRedRuleConfig(
        cooldown_seconds=0,
        confirmation_frames=1,
        min_inside_seconds=0.1,
    )
    crosswalk = _crosswalk_zone(rules=[rule])
    engine = RulesEngine([crosswalk], settings=RulesSettings(candidate_timeout_seconds=1.0))

    t0 = NOW
    # Enter on green -> no candidate.
    green_enter = engine.evaluate_detailed(
        TrackingResult(
            tracks=[
                _make_track(
                    "ped-1",
                    [(150.0, 340.0), (250.0, 340.0)],
                    category=ObjectCategory.PERSON,
                    class_name="person",
                    timestamp=t0,
                )
            ],
            frame_index=0,
            timestamp=t0,
        ),
        scene=_pedestrian_scene(TrafficLightState.GREEN, crosswalk_id=crosswalk.zone_id),
    )
    assert green_enter.pre_violations == []
    assert green_enter.violations == []

    # Still inside after the signal turns red -> still no candidate because entry was not on red.
    t1 = t0 + timedelta(milliseconds=150)
    red_while_inside = engine.evaluate_detailed(
        TrackingResult(
            tracks=[
                _make_track(
                    "ped-1",
                    [(250.0, 340.0), (270.0, 340.0)],
                    category=ObjectCategory.PERSON,
                    class_name="person",
                    timestamp=t0,
                )
            ],
            frame_index=1,
            timestamp=t1,
        ),
        scene=_pedestrian_scene(TrafficLightState.RED, crosswalk_id=crosswalk.zone_id),
    )
    assert red_while_inside.pre_violations == []
    assert red_while_inside.violations == []


def test_pedestrian_on_red_pre_violation_then_confirmation() -> None:
    rule = PedestrianOnRedRuleConfig(
        cooldown_seconds=0,
        confirmation_frames=1,
        min_inside_seconds=0.1,
    )
    crosswalk = _crosswalk_zone(rules=[rule])
    engine = RulesEngine([crosswalk], settings=RulesSettings(candidate_timeout_seconds=1.0))

    t0 = NOW
    first = engine.evaluate_detailed(
        TrackingResult(
            tracks=[
                _make_track(
                    "ped-2",
                    [(150.0, 340.0), (250.0, 340.0)],
                    category=ObjectCategory.PERSON,
                    class_name="person",
                    timestamp=t0,
                )
            ],
            frame_index=0,
            timestamp=t0,
        ),
        scene=_pedestrian_scene(TrafficLightState.RED, crosswalk_id=crosswalk.zone_id),
    )
    assert first.violations == []
    assert len(first.pre_violations) == 1

    t1 = t0 + timedelta(milliseconds=150)
    second = engine.evaluate_detailed(
        TrackingResult(
            tracks=[
                _make_track(
                    "ped-2",
                    [(150.0, 340.0), (250.0, 340.0), (290.0, 340.0)],
                    category=ObjectCategory.PERSON,
                    class_name="person",
                    timestamp=t0,
                )
            ],
            frame_index=1,
            timestamp=t1,
        ),
        scene=_pedestrian_scene(TrafficLightState.RED, crosswalk_id=crosswalk.zone_id),
    )
    assert len(second.violations) == 1
    assert second.violations[0].rule_type == RuleType.PEDESTRIAN_ON_RED
    assert second.violations[0].explanation.details["crosswalk_entry_at"] == t0


def test_unknown_signal_state_is_conservative_for_flagship_rules() -> None:
    rule = StopLineCrossingRuleConfig(cooldown_seconds=0)
    zone = _stop_line_zone(rules=[rule])
    engine = RulesEngine([zone], settings=RulesSettings(candidate_timeout_seconds=1.0))

    result = engine.evaluate_detailed(
        TrackingResult(
            tracks=[_make_track("veh-1", [(300.0, 290.0), (300.0, 304.0)], timestamp=NOW)],
            frame_index=0,
            timestamp=NOW,
        ),
        scene=SceneContext(),
    )
    assert result.pre_violations == []
    assert result.violations == []


def test_evaluate_returns_confirmed_only_while_detailed_exposes_pre_violations() -> None:
    rule = StopLineCrossingRuleConfig(
        cooldown_seconds=0,
        confirmation_frames=1,
        min_post_crossing_seconds=0.05,
        min_post_crossing_distance_px=8.0,
    )
    zone = _stop_line_zone(rules=[rule])
    engine = RulesEngine([zone], settings=RulesSettings(candidate_timeout_seconds=1.0))

    t0 = NOW
    confirmed_only = engine.evaluate(
        TrackingResult(
            tracks=[_make_track("veh-1", [(300.0, 290.0), (300.0, 304.0)], timestamp=t0)],
            frame_index=0,
            timestamp=t0,
        ),
        scene=_vehicle_red_scene(stop_line_id=zone.zone_id),
    )
    assert confirmed_only == []


# ---------------------------------------------------------------------------
# Candidate timeout / expiry
# ---------------------------------------------------------------------------


def test_candidate_expires_after_timeout() -> None:
    """Pre-violation candidate should be discarded when it exceeds the timeout
    without being confirmed, and no violation should be emitted."""
    rule = StopLineCrossingRuleConfig(
        cooldown_seconds=0,
        confirmation_frames=1,
        min_post_crossing_seconds=0.05,
        min_post_crossing_distance_px=8.0,
    )
    zone = _stop_line_zone(rules=[rule])
    timeout = 0.5
    engine = RulesEngine([zone], settings=RulesSettings(candidate_timeout_seconds=timeout))

    t0 = NOW
    # Frame 0: crossing detected → pre-violation candidate
    engine.evaluate_detailed(
        TrackingResult(
            tracks=[_make_track("veh-1", [(300.0, 290.0), (300.0, 304.0)], timestamp=t0)],
            frame_index=0,
            timestamp=t0,
        ),
        scene=_vehicle_red_scene(stop_line_id=zone.zone_id),
    )
    assert len(engine._candidate_states) == 1

    # Frame 1: well after timeout — candidate should have been cleaned up
    t_late = t0 + timedelta(seconds=timeout + 1.0)
    result = engine.evaluate_detailed(
        TrackingResult(
            tracks=[_make_track("veh-1", [(300.0, 304.0), (300.0, 320.0)], timestamp=t_late)],
            frame_index=50,
            timestamp=t_late,
        ),
        scene=_vehicle_red_scene(stop_line_id=zone.zone_id),
    )
    # The old candidate timed out; no confirmation, no pre-violation on a new
    # frame that doesn't re-cross the line.
    assert result.violations == []
    assert len(engine._candidate_states) == 0


# ---------------------------------------------------------------------------
# Candidate invalidation (vehicle reverses back across the line)
# ---------------------------------------------------------------------------


def test_candidate_invalidated_when_vehicle_reverses() -> None:
    """If the vehicle moves back to the pre-crossing side, the candidate should
    be discarded — the vehicle did not commit to the crossing."""
    rule = StopLineCrossingRuleConfig(
        cooldown_seconds=0,
        confirmation_frames=2,
        min_post_crossing_seconds=0.5,
        min_post_crossing_distance_px=30.0,
    )
    zone = _stop_line_zone(rules=[rule])
    engine = RulesEngine([zone], settings=RulesSettings(candidate_timeout_seconds=5.0))

    t0 = NOW
    # Frame 0: cross the stop-line going south (y increases)
    r0 = engine.evaluate_detailed(
        TrackingResult(
            tracks=[_make_track("veh-1", [(300.0, 290.0), (300.0, 304.0)], timestamp=t0)],
            frame_index=0,
            timestamp=t0,
        ),
        scene=_vehicle_red_scene(stop_line_id=zone.zone_id),
    )
    assert len(r0.pre_violations) == 1

    # Frame 1: vehicle appears back on the pre-crossing side (single point,
    # no new crossing segment) — the candidate should be invalidated.
    t1 = t0 + timedelta(milliseconds=200)
    r1 = engine.evaluate_detailed(
        TrackingResult(
            tracks=[_make_track("veh-1", [(300.0, 290.0)], timestamp=t1)],
            frame_index=1,
            timestamp=t1,
        ),
        scene=_vehicle_red_scene(stop_line_id=zone.zone_id),
    )
    # Candidate was invalidated; no violation, no new candidate (single-point
    # trajectory has no segment to trigger a fresh crossing)
    assert r1.violations == []
    assert len(engine._candidate_states) == 0


# ---------------------------------------------------------------------------
# Signal change after crossing — confirmation still succeeds
# ---------------------------------------------------------------------------


def test_signal_change_to_green_after_crossing_still_confirms() -> None:
    """Once a vehicle crosses on red, the violation should still confirm even
    if the signal turns green before the confirmation threshold is met.
    The relevant signal state is at time-of-crossing, not at confirmation."""
    rule = RedLightRuleConfig(
        cooldown_seconds=0,
        confirmation_frames=1,
        min_post_crossing_seconds=0.05,
        min_post_crossing_distance_px=20.0,
    )
    zone = _stop_line_zone(rules=[rule])
    engine = RulesEngine([zone], settings=RulesSettings(candidate_timeout_seconds=2.0))

    t0 = NOW
    # Frame 0: cross on red → candidate
    engine.evaluate_detailed(
        TrackingResult(
            tracks=[_make_track("veh-1", [(300.0, 290.0), (300.0, 304.0)], timestamp=t0)],
            frame_index=0,
            timestamp=t0,
        ),
        scene=_vehicle_red_scene(stop_line_id=zone.zone_id),
    )

    # Frame 1: signal is now GREEN, vehicle progressed far past the line
    t1 = t0 + timedelta(milliseconds=100)
    green_scene = SceneContext(
        signal_states=[
            SceneSignalState(
                head_id="veh-main",
                phase=SignalPhase.VEHICLE,
                state=TrafficLightState.GREEN,
                stop_line_id=zone.zone_id,
                confidence=0.95,
            )
        ]
    )
    result = engine.evaluate_detailed(
        TrackingResult(
            tracks=[_make_track("veh-1", [(300.0, 290.0), (300.0, 304.0), (300.0, 328.0)], timestamp=t0)],
            frame_index=1,
            timestamp=t1,
        ),
        scene=green_scene,
    )
    # The candidate was created on red — it should still confirm
    assert len(result.violations) == 1
    assert result.violations[0].rule_type == RuleType.RED_LIGHT
    assert result.violations[0].explanation.details["signal_state_at_decision"] == "red"


# ---------------------------------------------------------------------------
# Max violations per track cap
# ---------------------------------------------------------------------------


def test_max_violations_per_track_caps_flagship_rules() -> None:
    """Once a track hits the max_violations_per_track limit, no more violations
    are generated for that track even if new qualifying events occur."""
    rule = StopLineCrossingRuleConfig(
        cooldown_seconds=0,
        confirmation_frames=1,
        min_post_crossing_seconds=0.0,
        min_post_crossing_distance_px=1.0,
    )
    zone = _stop_line_zone(rules=[rule])
    engine = RulesEngine(
        [zone],
        settings=RulesSettings(candidate_timeout_seconds=2.0, max_violations_per_track=1),
    )

    t0 = NOW
    scene = _vehicle_red_scene(stop_line_id=zone.zone_id)

    # Frame 0: crossing → candidate
    engine.evaluate_detailed(
        TrackingResult(
            tracks=[_make_track("veh-1", [(300.0, 290.0), (300.0, 304.0)], timestamp=t0)],
            frame_index=0,
            timestamp=t0,
        ),
        scene=scene,
    )
    # Frame 1: confirm
    t1 = t0 + timedelta(milliseconds=100)
    r1 = engine.evaluate_detailed(
        TrackingResult(
            tracks=[_make_track("veh-1", [(300.0, 290.0), (300.0, 304.0), (300.0, 310.0)], timestamp=t0)],
            frame_index=1,
            timestamp=t1,
        ),
        scene=scene,
    )
    assert len(r1.violations) == 1

    # Reset engine state (cooldowns etc.) but violation count persists
    engine._cooldowns.clear()
    engine._candidate_states.clear()

    # Frame 2: another crossing attempt — should be capped
    t2 = t0 + timedelta(seconds=1)
    r2 = engine.evaluate_detailed(
        TrackingResult(
            tracks=[_make_track("veh-1", [(300.0, 290.0), (300.0, 304.0)], timestamp=t2)],
            frame_index=2,
            timestamp=t2,
        ),
        scene=scene,
    )
    assert r2.violations == []
    assert r2.pre_violations == []


# ---------------------------------------------------------------------------
# Explanation metadata richness
# ---------------------------------------------------------------------------


def test_confirmed_violation_explanation_has_evidence_fields() -> None:
    """Confirmed violations must carry full evidence metadata for review."""
    rule = StopLineCrossingRuleConfig(
        cooldown_seconds=0,
        confirmation_frames=1,
        min_post_crossing_seconds=0.05,
        min_post_crossing_distance_px=8.0,
    )
    zone = _stop_line_zone(rules=[rule])
    engine = RulesEngine([zone], settings=RulesSettings(candidate_timeout_seconds=1.0))
    scene = _vehicle_red_scene(stop_line_id=zone.zone_id)

    t0 = NOW
    engine.evaluate_detailed(
        TrackingResult(
            tracks=[_make_track("veh-1", [(300.0, 290.0), (300.0, 304.0)], timestamp=t0)],
            frame_index=0,
            timestamp=t0,
        ),
        scene=scene,
    )

    t1 = t0 + timedelta(milliseconds=100)
    result = engine.evaluate_detailed(
        TrackingResult(
            tracks=[_make_track("veh-1", [(300.0, 290.0), (300.0, 304.0), (300.0, 320.0)], timestamp=t0)],
            frame_index=1,
            timestamp=t1,
        ),
        scene=scene,
    )
    assert len(result.violations) == 1
    v = result.violations[0]
    exp = v.explanation

    # Evidence fields that must be present for review
    assert exp.rule_type == RuleType.STOP_LINE_CROSSING
    assert len(exp.rule_config) > 0
    assert len(exp.reason) > 0
    assert exp.conditions_satisfied
    assert "signal_state_at_decision" in exp.details
    assert "confirmation_frames_elapsed" in exp.details
    assert "post_crossing_distance_px" in exp.details
    assert "rule_conditions_satisfied" in exp.details
    assert "stage" in exp.details
    assert exp.details["stage"] == "confirmed"
    assert exp.track_snapshot["track_id"] == "veh-1"
    assert exp.zone_info["zone_id"] == zone.zone_id
    assert v.certainty == 1.0


def test_pre_violation_explanation_has_pending_evidence() -> None:
    """Pre-violation records must carry enough context for the review queue."""
    rule = RedLightRuleConfig(
        cooldown_seconds=0,
        confirmation_frames=5,
        min_post_crossing_seconds=1.0,
        min_post_crossing_distance_px=50.0,
    )
    zone = _stop_line_zone(rules=[rule])
    engine = RulesEngine([zone], settings=RulesSettings(candidate_timeout_seconds=5.0))

    t0 = NOW
    result = engine.evaluate_detailed(
        TrackingResult(
            tracks=[_make_track("veh-1", [(300.0, 290.0), (300.0, 304.0)], timestamp=t0)],
            frame_index=0,
            timestamp=t0,
        ),
        scene=_vehicle_red_scene(stop_line_id=zone.zone_id),
    )
    assert len(result.pre_violations) == 1
    pv = result.pre_violations[0]

    assert pv.rule_type == RuleType.RED_LIGHT
    assert pv.certainty < 1.0
    assert pv.candidate_started_at == t0
    assert pv.track_id == "veh-1"
    assert pv.zone_id == zone.zone_id
    exp = pv.explanation
    assert "signal_state_at_detection" in exp.details
    assert exp.details["signal_state_at_detection"] == "red"
    assert "confirmation_threshold_frames" in exp.details
    assert "confirmation_threshold_seconds" in exp.details


# ---------------------------------------------------------------------------
# Stale signal guard
# ---------------------------------------------------------------------------


def test_stale_signal_treated_as_unknown_blocks_candidate() -> None:
    """A SceneSignalState with is_stale=True should be treated as UNKNOWN
    even if state=RED, so no candidate is created."""
    rule = RedLightRuleConfig(cooldown_seconds=0)
    zone = _stop_line_zone(rules=[rule])
    engine = RulesEngine([zone], settings=RulesSettings(candidate_timeout_seconds=1.0))

    stale_red_scene = SceneContext(
        signal_states=[
            SceneSignalState(
                head_id="veh-main",
                phase=SignalPhase.VEHICLE,
                state=TrafficLightState.RED,
                stop_line_id=zone.zone_id,
                confidence=0.95,
                is_stale=True,
            )
        ]
    )
    result = engine.evaluate_detailed(
        TrackingResult(
            tracks=[_make_track("veh-1", [(300.0, 290.0), (300.0, 304.0)], timestamp=NOW)],
            frame_index=0,
            timestamp=NOW,
        ),
        scene=stale_red_scene,
    )
    assert result.pre_violations == []
    assert result.violations == []


def test_stale_pedestrian_signal_blocks_candidate() -> None:
    """Stale pedestrian signal should not create a pedestrian-on-red candidate."""
    rule = PedestrianOnRedRuleConfig(cooldown_seconds=0, confirmation_frames=1, min_inside_seconds=0.1)
    crosswalk = ZoneConfig(
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
    engine = RulesEngine([crosswalk], settings=RulesSettings(candidate_timeout_seconds=1.0))

    stale_ped_scene = SceneContext(
        signal_states=[
            SceneSignalState(
                head_id="ped-main",
                phase=SignalPhase.PEDESTRIAN,
                state=TrafficLightState.RED,
                crosswalk_id=crosswalk.zone_id,
                confidence=0.90,
                is_stale=True,
            )
        ]
    )
    result = engine.evaluate_detailed(
        TrackingResult(
            tracks=[
                _make_track(
                    "ped-1",
                    [(150.0, 340.0), (250.0, 340.0)],
                    category=ObjectCategory.PERSON,
                    class_name="person",
                    timestamp=NOW,
                )
            ],
            frame_index=0,
            timestamp=NOW,
        ),
        scene=stale_ped_scene,
    )
    assert result.pre_violations == []
    assert result.violations == []


# ---------------------------------------------------------------------------
# Low-confidence signal guard
# ---------------------------------------------------------------------------


def test_low_confidence_signal_treated_as_unknown() -> None:
    """A signal head below min_signal_confidence should not trigger a
    candidate, even if state=RED."""
    rule = StopLineCrossingRuleConfig(cooldown_seconds=0)
    zone = _stop_line_zone(rules=[rule])
    engine = RulesEngine(
        [zone],
        settings=RulesSettings(candidate_timeout_seconds=1.0, min_signal_confidence=0.5),
    )

    low_conf_scene = SceneContext(
        signal_states=[
            SceneSignalState(
                head_id="veh-main",
                phase=SignalPhase.VEHICLE,
                state=TrafficLightState.RED,
                stop_line_id=zone.zone_id,
                confidence=0.3,
            )
        ]
    )
    result = engine.evaluate_detailed(
        TrackingResult(
            tracks=[_make_track("veh-1", [(300.0, 290.0), (300.0, 304.0)], timestamp=NOW)],
            frame_index=0,
            timestamp=NOW,
        ),
        scene=low_conf_scene,
    )
    assert result.pre_violations == []
    assert result.violations == []


def test_sufficient_confidence_signal_creates_candidate() -> None:
    """A signal head at or above min_signal_confidence should still work."""
    rule = StopLineCrossingRuleConfig(cooldown_seconds=0)
    zone = _stop_line_zone(rules=[rule])
    engine = RulesEngine(
        [zone],
        settings=RulesSettings(candidate_timeout_seconds=1.0, min_signal_confidence=0.5),
    )

    ok_scene = SceneContext(
        signal_states=[
            SceneSignalState(
                head_id="veh-main",
                phase=SignalPhase.VEHICLE,
                state=TrafficLightState.RED,
                stop_line_id=zone.zone_id,
                confidence=0.7,
            )
        ]
    )
    result = engine.evaluate_detailed(
        TrackingResult(
            tracks=[_make_track("veh-1", [(300.0, 290.0), (300.0, 304.0)], timestamp=NOW)],
            frame_index=0,
            timestamp=NOW,
        ),
        scene=ok_scene,
    )
    assert len(result.pre_violations) == 1
