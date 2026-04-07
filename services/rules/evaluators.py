"""Pure, deterministic rule evaluator functions.

Each function:
  - receives a TrackedObject, a ZoneConfig, a specific rule config,
    and optional extra state (timestamps, scene context)
  - returns ``ViolationRecord | None``
  - has **no** side-effects
  - is fully testable in isolation
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from services.dwell.analyzer import analyze_dwell
from services.dwell.schemas import DwellOutcome, DwellScenario, DwellThresholds
from services.rules.schemas import (
    BusStopOccupationRuleConfig,
    Explanation,
    IllegalParkingRuleConfig,
    LineCrossingRuleConfig,
    LineGeometry,
    NoStoppingRuleConfig,
    PedestrianOnRedRuleConfig,
    PolygonGeometry,
    RedLightRuleConfig,
    RuleType,
    SceneContext,
    StalledVehicleRuleConfig,
    StopLineCrossingRuleConfig,
    TrafficLightState,
    ViolationRecord,
    WrongDirectionRuleConfig,
    ZoneConfig,
    ZoneDwellTimeRuleConfig,
    ZoneEntryRuleConfig,
)
from services.tracking.schemas import (
    CardinalDirection,
    LineSegment,
    Point2D,
    PolygonZone,
    TrackedObject,
    ZoneTransitionType,
)
from services.tracking.utils import (
    check_line_crossing,
    detect_zone_transition,
    point_in_polygon,
)
from services.vision.schemas import ObjectCategory

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _build_explanation(
    rule_type: RuleType,
    rule_config: Any,
    reason: str,
    track: TrackedObject,
    zone: ZoneConfig,
    *,
    details: dict[str, Any] | None = None,
) -> Explanation:
    return Explanation(
        rule_type=rule_type,
        rule_config=rule_config.model_dump(mode="json"),
        reason=reason,
        details=details or {},
        track_snapshot=track.to_event_dict(),
        zone_info={
            "zone_id": zone.zone_id,
            "zone_name": zone.name,
            "zone_type": zone.zone_type.value,
            "geometry": zone.geometry_as_dict(),
        },
    )


def _build_violation(
    rule_type: RuleType,
    rule_config: Any,
    zone: ZoneConfig,
    track: TrackedObject,
    timestamp: datetime,
    reason: str,
    *,
    details: dict[str, Any] | None = None,
) -> ViolationRecord:
    return ViolationRecord(
        rule_type=rule_type,
        violation_type=rule_config.violation_type,
        severity=rule_config.severity,
        zone_id=zone.zone_id,
        zone_name=zone.name,
        track_id=track.track_id,
        occurred_at=timestamp,
        explanation=_build_explanation(
            rule_type, rule_config, reason, track, zone, details=details,
        ),
    )


def _to_line_segment(geo: LineGeometry) -> LineSegment:
    return LineSegment(start=geo.start, end=geo.end)


def _to_polygon_zone(geo: PolygonGeometry) -> PolygonZone:
    return PolygonZone(points=geo.points)


def _latest_segment(track: TrackedObject) -> tuple[Point2D, Point2D] | None:
    """Return the (previous, current) trajectory points for the latest frame.

    Evaluators that detect one-shot events (crossings, entries) must use
    only the latest segment so old events still in the trajectory buffer
    do not re-fire.
    """
    if len(track.trajectory) < 2:
        return None
    return (track.trajectory[-2].point, track.trajectory[-1].point)


# ---------------------------------------------------------------------------
# 1. Line crossing
# ---------------------------------------------------------------------------


def evaluate_line_crossing(
    track: TrackedObject,
    zone: ZoneConfig,
    rule: LineCrossingRuleConfig,
    timestamp: datetime,
) -> ViolationRecord | None:
    """Fire when a track crosses a line (optionally in a forbidden direction)."""
    if not isinstance(zone.geometry, LineGeometry):
        return None

    segment = _latest_segment(track)
    if segment is None:
        return None
    prev, cur = segment

    crossing = check_line_crossing(prev, cur, _to_line_segment(zone.geometry))
    if not crossing.crossed:
        return None

    if rule.forbidden_direction and crossing.direction != rule.forbidden_direction:
        return None

    direction_str = crossing.direction.value if crossing.direction else "unknown"
    return _build_violation(
        RuleType.LINE_CROSSING, rule, zone, track, timestamp,
        reason=(
            f"Track {track.track_id} crossed line '{zone.name}'"
            f" ({direction_str})."
        ),
        details={"crossing_direction": direction_str},
    )


# ---------------------------------------------------------------------------
# 2. Stop-line crossing
# ---------------------------------------------------------------------------


def evaluate_stop_line_crossing(
    track: TrackedObject,
    zone: ZoneConfig,
    rule: StopLineCrossingRuleConfig,
    timestamp: datetime,
    scene: SceneContext | None = None,
) -> ViolationRecord | None:
    """Fire on stop-line crossing; optionally require red light."""
    if not isinstance(zone.geometry, LineGeometry):
        return None

    light_state = (
        scene.vehicle_signal_state_for_stop_line(zone.zone_id)
        if scene is not None
        else TrafficLightState.UNKNOWN
    )
    if rule.requires_red_light:
        if light_state != TrafficLightState.RED:
            return None

    segment = _latest_segment(track)
    if segment is None:
        return None
    prev, cur = segment

    crossing = check_line_crossing(prev, cur, _to_line_segment(zone.geometry))
    if not crossing.crossed:
        return None

    light_str = light_state.value
    direction_str = crossing.direction.value if crossing.direction else "unknown"
    return _build_violation(
        RuleType.STOP_LINE_CROSSING, rule, zone, track, timestamp,
        reason=(
            f"Track {track.track_id} crossed stop-line '{zone.name}'"
            f" (light: {light_str})."
        ),
        details={
            "crossing_direction": direction_str,
            "traffic_light_state": light_str,
        },
    )


# ---------------------------------------------------------------------------
# 3. Zone entry
# ---------------------------------------------------------------------------


def evaluate_zone_entry(
    track: TrackedObject,
    zone: ZoneConfig,
    rule: ZoneEntryRuleConfig,
    timestamp: datetime,
) -> ViolationRecord | None:
    """Fire when a track enters a restricted polygon zone."""
    if not isinstance(zone.geometry, PolygonGeometry):
        return None

    if rule.restricted_categories and track.category not in rule.restricted_categories:
        return None

    segment = _latest_segment(track)
    if segment is None:
        return None
    prev, cur = segment

    zt = detect_zone_transition(prev, cur, _to_polygon_zone(zone.geometry))
    if zt is None or zt.transition != ZoneTransitionType.ENTERED:
        return None

    return _build_violation(
        RuleType.ZONE_ENTRY, rule, zone, track, timestamp,
        reason=(
            f"Track {track.track_id} ({track.class_name}) entered"
            f" restricted zone '{zone.name}'."
        ),
        details={"category": track.category.value},
    )


# ---------------------------------------------------------------------------
# 4. Zone dwell time
# ---------------------------------------------------------------------------


def evaluate_zone_dwell_time(
    track: TrackedObject,
    zone: ZoneConfig,
    rule: ZoneDwellTimeRuleConfig,
    timestamp: datetime,
    entered_at: datetime | None,
) -> ViolationRecord | None:
    """Fire when a track has been inside a zone longer than allowed."""
    if not isinstance(zone.geometry, PolygonGeometry):
        return None

    if rule.applicable_categories and track.category not in rule.applicable_categories:
        return None

    if entered_at is None:
        return None

    dwell = (timestamp - entered_at).total_seconds()
    if dwell < rule.max_dwell_seconds:
        return None

    return _build_violation(
        RuleType.ZONE_DWELL_TIME, rule, zone, track, timestamp,
        reason=(
            f"Track {track.track_id} dwelled in zone '{zone.name}'"
            f" for {dwell:.1f}s (limit: {rule.max_dwell_seconds}s)."
        ),
        details={
            "dwell_seconds": round(dwell, 2),
            "max_dwell_seconds": rule.max_dwell_seconds,
        },
    )


# ---------------------------------------------------------------------------
# 5. Wrong direction
# ---------------------------------------------------------------------------


def evaluate_wrong_direction(
    track: TrackedObject,
    zone: ZoneConfig,
    rule: WrongDirectionRuleConfig,
    timestamp: datetime,
) -> ViolationRecord | None:
    """Fire when a track is moving opposite to the expected direction."""
    if track.direction is None:
        return None
    if track.direction.direction == CardinalDirection.STATIONARY:
        return None
    if track.direction.direction == rule.expected_direction:
        return None

    # Only check tracks that are inside the zone polygon
    if isinstance(zone.geometry, PolygonGeometry):
        poly = PolygonZone(points=zone.geometry.points)
        if not point_in_polygon(track.centroid, poly):
            return None

    return _build_violation(
        RuleType.WRONG_DIRECTION, rule, zone, track, timestamp,
        reason=(
            f"Track {track.track_id} travelling"
            f" {track.direction.direction.value}"
            f" in zone '{zone.name}'"
            f" (expected: {rule.expected_direction.value})."
        ),
        details={
            "actual_direction": track.direction.direction.value,
            "expected_direction": rule.expected_direction.value,
            "speed_px_per_frame": track.speed_px_per_frame,
        },
    )


# ---------------------------------------------------------------------------
# 6. Red-light violation (foundation)
# ---------------------------------------------------------------------------


def evaluate_red_light(
    track: TrackedObject,
    zone: ZoneConfig,
    rule: RedLightRuleConfig,
    timestamp: datetime,
    scene: SceneContext | None = None,
) -> ViolationRecord | None:
    """Foundation one-shot evaluator — **superseded** by ``RulesEngine._handle_red_light_rule``.

    This function fires on a single-frame crossing check with no temporal
    confirmation.  It exists for backward-compatible unit tests and simple
    demos.  Production callers should use ``RulesEngine.evaluate()`` or
    ``RulesEngine.evaluate_detailed()`` which apply candidate detection,
    temporal/spatial confirmation, and evidence-rich metadata.
    """
    light_state = (
        scene.vehicle_signal_state_for_stop_line(zone.zone_id)
        if scene is not None
        else TrafficLightState.UNKNOWN
    )
    if light_state != TrafficLightState.RED:
        return None
    if track.category != ObjectCategory.VEHICLE:
        return None
    if not isinstance(zone.geometry, LineGeometry):
        return None

    segment = _latest_segment(track)
    if segment is None:
        return None
    prev, cur = segment

    crossing = check_line_crossing(prev, cur, _to_line_segment(zone.geometry))
    if not crossing.crossed:
        return None

    direction_str = crossing.direction.value if crossing.direction else "unknown"
    return _build_violation(
        RuleType.RED_LIGHT, rule, zone, track, timestamp,
        reason=f"Vehicle {track.track_id} ran red light at '{zone.name}'.",
        details={
            "crossing_direction": direction_str,
            "traffic_light_state": light_state.value,
        },
    )


# ---------------------------------------------------------------------------
# 7. Pedestrian-on-red (foundation)
# ---------------------------------------------------------------------------


def evaluate_pedestrian_on_red(
    track: TrackedObject,
    zone: ZoneConfig,
    rule: PedestrianOnRedRuleConfig,
    timestamp: datetime,
    scene: SceneContext | None = None,
) -> ViolationRecord | None:
    """Foundation one-shot evaluator — **superseded** by ``RulesEngine._handle_pedestrian_on_red_rule``.

    This function fires on a single-frame presence check with no temporal
    confirmation or entry-timing logic.  It exists for backward-compatible
    unit tests and simple demos.  Production callers should use
    ``RulesEngine.evaluate()`` or ``RulesEngine.evaluate_detailed()``.
    """
    light_state = (
        scene.pedestrian_signal_state_for_crosswalk(zone.zone_id)
        if scene is not None
        else TrafficLightState.UNKNOWN
    )
    if light_state != TrafficLightState.RED:
        return None
    if track.category != ObjectCategory.PERSON:
        return None
    if not isinstance(zone.geometry, PolygonGeometry):
        return None

    is_inside = point_in_polygon(track.centroid, _to_polygon_zone(zone.geometry))
    if not is_inside:
        return None

    return _build_violation(
        RuleType.PEDESTRIAN_ON_RED, rule, zone, track, timestamp,
        reason=(
            f"Pedestrian {track.track_id} in crosswalk"
            f" '{zone.name}' during red."
        ),
        details={
            "traffic_light_state": light_state.value,
            "pedestrian_signal_state": light_state.value,
        },
    )


# ---------------------------------------------------------------------------
# 8. Illegal parking — dwell-analyzer-backed
# ---------------------------------------------------------------------------


def _thresholds_from_parking_rule(rule: IllegalParkingRuleConfig) -> DwellThresholds:
    """Build a DwellThresholds from the rule's configurable fields."""
    return DwellThresholds(
        scenario=DwellScenario.ILLEGAL_PARKING,
        max_dwell_seconds=rule.max_stationary_seconds,
        grace_period_seconds=rule.grace_period_seconds,
        min_stationary_ratio=rule.min_stationary_ratio,
        stationary_speed_px=rule.stationary_speed_px,
        max_stationary_displacement_px=rule.max_stationary_displacement_px,
        min_stationary_streak_seconds=rule.min_stationary_streak_seconds,
        applicable_categories=[ObjectCategory.VEHICLE],
        included_class_names=rule.included_class_names,
        excluded_class_names=rule.excluded_class_names,
        cooldown_seconds=rule.cooldown_seconds,
    )


def evaluate_illegal_parking(
    track: TrackedObject,
    zone: ZoneConfig,
    rule: IllegalParkingRuleConfig,
    timestamp: datetime,
    entered_at: datetime | None,
) -> ViolationRecord | None:
    """Fire when a stationary vehicle dwells in a restricted zone.

    Uses the dwell analyzer for robust stationarity assessment —
    checks stationary ratio, streak duration, and grace period to
    distinguish true parking from brief temporary stops.
    """
    if not isinstance(zone.geometry, PolygonGeometry):
        return None

    thresholds = _thresholds_from_parking_rule(rule)
    analysis = analyze_dwell(
        track,
        thresholds=thresholds,
        entered_at=entered_at,
        timestamp=timestamp,
        zone_id=zone.zone_id,
        zone_name=zone.name,
        zone_type=zone.zone_type.value,
        allow_track_lifetime_fallback=False,
    )

    if analysis.outcome is not DwellOutcome.VIOLATION:
        return None

    return _build_violation(
        RuleType.ILLEGAL_PARKING, rule, zone, track, timestamp,
        reason=analysis.reason,
        details=analysis.to_detail_dict(),
    )


# ---------------------------------------------------------------------------
# 9. No-stopping zone
# ---------------------------------------------------------------------------


def evaluate_no_stopping(
    track: TrackedObject,
    zone: ZoneConfig,
    rule: NoStoppingRuleConfig,
    timestamp: datetime,
    entered_at: datetime | None,
) -> ViolationRecord | None:
    """Fire when a vehicle stops in a no-stopping zone."""
    if not isinstance(zone.geometry, PolygonGeometry):
        return None

    thresholds = DwellThresholds(
        scenario=DwellScenario.NO_STOPPING,
        max_dwell_seconds=rule.max_stationary_seconds,
        grace_period_seconds=rule.grace_period_seconds,
        min_stationary_ratio=rule.min_stationary_ratio,
        stationary_speed_px=rule.stationary_speed_px,
        max_stationary_displacement_px=rule.max_stationary_displacement_px,
        min_stationary_streak_seconds=rule.min_stationary_streak_seconds,
        applicable_categories=[ObjectCategory.VEHICLE],
        included_class_names=rule.included_class_names,
        excluded_class_names=rule.excluded_class_names,
        cooldown_seconds=rule.cooldown_seconds,
    )
    analysis = analyze_dwell(
        track,
        thresholds=thresholds,
        entered_at=entered_at,
        timestamp=timestamp,
        zone_id=zone.zone_id,
        zone_name=zone.name,
        zone_type=zone.zone_type.value,
        allow_track_lifetime_fallback=False,
    )

    if analysis.outcome is not DwellOutcome.VIOLATION:
        return None

    return _build_violation(
        RuleType.NO_STOPPING, rule, zone, track, timestamp,
        reason=analysis.reason,
        details=analysis.to_detail_dict(),
    )


# ---------------------------------------------------------------------------
# 10. Bus-stop occupation
# ---------------------------------------------------------------------------


def evaluate_bus_stop_occupation(
    track: TrackedObject,
    zone: ZoneConfig,
    rule: BusStopOccupationRuleConfig,
    timestamp: datetime,
    entered_at: datetime | None,
) -> ViolationRecord | None:
    """Fire when a non-bus vehicle occupies a bus stop zone too long."""
    if not isinstance(zone.geometry, PolygonGeometry):
        return None

    thresholds = DwellThresholds(
        scenario=DwellScenario.BUS_STOP_OCCUPATION,
        max_dwell_seconds=rule.max_stationary_seconds,
        grace_period_seconds=rule.grace_period_seconds,
        min_stationary_ratio=rule.min_stationary_ratio,
        stationary_speed_px=rule.stationary_speed_px,
        max_stationary_displacement_px=rule.max_stationary_displacement_px,
        min_stationary_streak_seconds=rule.min_stationary_streak_seconds,
        applicable_categories=rule.applicable_categories,
        included_class_names=rule.included_class_names,
        excluded_class_names=rule.excluded_class_names,
        cooldown_seconds=rule.cooldown_seconds,
    )
    analysis = analyze_dwell(
        track,
        thresholds=thresholds,
        entered_at=entered_at,
        timestamp=timestamp,
        zone_id=zone.zone_id,
        zone_name=zone.name,
        zone_type=zone.zone_type.value,
        allow_track_lifetime_fallback=False,
    )

    if analysis.outcome is not DwellOutcome.VIOLATION:
        return None

    return _build_violation(
        RuleType.BUS_STOP_OCCUPATION, rule, zone, track, timestamp,
        reason=analysis.reason,
        details=analysis.to_detail_dict(),
    )


# ---------------------------------------------------------------------------
# 11. Stalled vehicle in roadway
# ---------------------------------------------------------------------------


def evaluate_stalled_vehicle(
    track: TrackedObject,
    zone: ZoneConfig,
    rule: StalledVehicleRuleConfig,
    timestamp: datetime,
    entered_at: datetime | None,
) -> ViolationRecord | None:
    """Fire when a vehicle is stalled in an active roadway zone."""
    if not isinstance(zone.geometry, PolygonGeometry):
        return None

    thresholds = DwellThresholds(
        scenario=DwellScenario.STALLED_VEHICLE,
        max_dwell_seconds=rule.max_stationary_seconds,
        grace_period_seconds=rule.grace_period_seconds,
        min_stationary_ratio=rule.min_stationary_ratio,
        stationary_speed_px=rule.stationary_speed_px,
        max_stationary_displacement_px=rule.max_stationary_displacement_px,
        min_stationary_streak_seconds=rule.min_stationary_streak_seconds,
        applicable_categories=[ObjectCategory.VEHICLE],
        included_class_names=rule.included_class_names,
        excluded_class_names=rule.excluded_class_names,
        cooldown_seconds=rule.cooldown_seconds,
    )
    analysis = analyze_dwell(
        track,
        thresholds=thresholds,
        entered_at=entered_at,
        timestamp=timestamp,
        zone_id=zone.zone_id,
        zone_name=zone.name,
        zone_type=zone.zone_type.value,
        allow_track_lifetime_fallback=False,
    )

    if analysis.outcome is not DwellOutcome.VIOLATION:
        return None

    return _build_violation(
        RuleType.STALLED_VEHICLE, rule, zone, track, timestamp,
        reason=analysis.reason,
        details=analysis.to_detail_dict(),
    )
