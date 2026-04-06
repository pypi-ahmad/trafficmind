"""Traffic rules engine — orchestrates rule evaluation for one camera's zones.

Create one ``RulesEngine`` per camera.  Call ``evaluate()`` once per frame
with the ``TrackingResult`` and optional ``SceneContext``.  The engine
maintains per-track state (zone entry times), per-violation cooldowns,
and pre-violation candidates across frames.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from apps.api.app.db.enums import ViolationType
from services.rules.config import RulesSettings, get_rules_settings
from services.rules.evaluators import (
    evaluate_bus_stop_occupation,
    evaluate_illegal_parking,
    evaluate_line_crossing,
    evaluate_no_stopping,
    evaluate_stalled_vehicle,
    evaluate_wrong_direction,
    evaluate_zone_dwell_time,
    evaluate_zone_entry,
)
from services.rules.schemas import (
    BusStopOccupationRuleConfig,
    Explanation,
    IllegalParkingRuleConfig,
    LineCrossingRuleConfig,
    LineGeometry,
    NoStoppingRuleConfig,
    PedestrianOnRedRuleConfig,
    PolygonGeometry,
    PreViolationRecord,
    RedLightRuleConfig,
    RuleConfig,
    RuleEvaluationResult,
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
from services.signals.schemas import SignalPhase
from services.tracking.schemas import (
    LineCrossingDirection,
    LineSegment,
    Point2D,
    PolygonZone,
    TrackedObject,
    TrackingResult,
    ZoneTransitionType,
)
from services.tracking.utils import check_line_crossing, detect_zone_transition, point_in_polygon

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _CandidateState:
    rule_type: RuleType
    violation_type: ViolationType
    zone_id: str
    zone_name: str
    track_id: str
    candidate_started_at: datetime
    candidate_frame_index: int | None
    signal_state_at_detection: TrafficLightState
    signal_phase: SignalPhase
    signal_head_id: str | None = None
    signal_confidence: float | None = None
    crossing_direction: str | None = None
    post_cross_sign: float | None = None
    linked_zone_id: str | None = None
    linked_zone_name: str | None = None
    conditions_satisfied: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def age_seconds(self, now: datetime) -> float:
        return max(0.0, (now - self.candidate_started_at).total_seconds())

    def age_frames(self, current_frame: int | None) -> int:
        if current_frame is None or self.candidate_frame_index is None:
            return 0
        return max(0, current_frame - self.candidate_frame_index)


class RulesEngine:
    """Evaluate traffic rules for one camera's zone configuration.

    Serious traffic rules are handled in three steps:
    1. candidate behavior detection
    2. temporal/spatial confirmation
    3. confirmed violation emission
    """

    def __init__(
        self,
        zones: list[ZoneConfig],
        settings: RulesSettings | None = None,
    ) -> None:
        self._zones = list(zones)
        self._settings = settings or get_rules_settings()
        self._zone_entries: dict[tuple[str, str], datetime] = {}
        self._cooldowns: dict[tuple[str, str, str], datetime] = {}
        self._violation_counts: dict[str, int] = {}
        self._candidate_states: dict[tuple[RuleType, str, str], _CandidateState] = {}

        self._zone_polygons: dict[str, PolygonZone] = {}
        self._zone_by_id: dict[str, ZoneConfig] = {}
        self._zone_by_name: dict[str, ZoneConfig] = {}
        self._line_segments: dict[str, LineSegment] = {}
        for zone in self._zones:
            self._zone_by_id[zone.zone_id] = zone
            self._zone_by_name[zone.name] = zone
            if isinstance(zone.geometry, PolygonGeometry):
                self._zone_polygons[zone.zone_id] = PolygonZone(points=zone.geometry.points)
            elif isinstance(zone.geometry, LineGeometry):
                self._line_segments[zone.zone_id] = LineSegment(
                    start=zone.geometry.start,
                    end=zone.geometry.end,
                    name=zone.name,
                )

    @property
    def zones(self) -> list[ZoneConfig]:
        return list(self._zones)

    def reset(self) -> None:
        self._zone_entries.clear()
        self._cooldowns.clear()
        self._violation_counts.clear()
        self._candidate_states.clear()

    def evaluate(
        self,
        tracking_result: TrackingResult,
        scene: SceneContext | None = None,
    ) -> list[ViolationRecord]:
        return self.evaluate_detailed(tracking_result, scene=scene).violations

    def evaluate_detailed(
        self,
        tracking_result: TrackingResult,
        scene: SceneContext | None = None,
    ) -> RuleEvaluationResult:
        timestamp = tracking_result.timestamp or datetime.now(UTC)
        frame_index = tracking_result.frame_index
        pre_violations: list[PreViolationRecord] = []
        violations: list[ViolationRecord] = []

        self._cleanup_expired_candidates(timestamp)

        for track in tracking_result.tracks:
            self._update_zone_occupancy(track, timestamp)

            for zone in self._zones:
                for rule in zone.rules:
                    if not rule.enabled:
                        continue
                    if (
                        self._violation_counts.get(track.track_id, 0)
                        >= self._settings.max_violations_per_track
                    ):
                        continue

                    if isinstance(rule, StopLineCrossingRuleConfig):
                        pre, violation = self._handle_stop_line_crossing_rule(
                            track,
                            zone,
                            rule,
                            timestamp,
                            frame_index,
                            scene,
                        )
                    elif isinstance(rule, RedLightRuleConfig):
                        pre, violation = self._handle_red_light_rule(
                            track,
                            zone,
                            rule,
                            timestamp,
                            frame_index,
                            scene,
                        )
                    elif isinstance(rule, PedestrianOnRedRuleConfig):
                        pre, violation = self._handle_pedestrian_on_red_rule(
                            track,
                            zone,
                            rule,
                            timestamp,
                            frame_index,
                            scene,
                        )
                    else:
                        pre = None
                        violation = self._evaluate_stateless_rule(
                            track, zone, rule, timestamp, scene
                        )

                    if pre is not None:
                        pre.frame_index = frame_index
                        pre.explanation.frame_index = frame_index
                        pre_violations.append(pre)

                    if violation is not None and not self._is_cooled_down(violation, rule):
                        violation.frame_index = frame_index
                        violation.explanation.frame_index = frame_index
                        self._record_cooldown(violation)
                        self._violation_counts[track.track_id] = (
                            self._violation_counts.get(track.track_id, 0) + 1
                        )
                        violations.append(violation)

        for track in tracking_result.removed_tracks:
            self._cleanup_track(track.track_id)

        return RuleEvaluationResult(pre_violations=pre_violations, violations=violations)

    def _evaluate_stateless_rule(
        self,
        track: TrackedObject,
        zone: ZoneConfig,
        rule: RuleConfig,
        timestamp: datetime,
        scene: SceneContext | None,
    ) -> ViolationRecord | None:
        entry_time = self._zone_entries.get((track.track_id, zone.zone_id))

        if isinstance(rule, LineCrossingRuleConfig):
            return evaluate_line_crossing(track, zone, rule, timestamp)
        if isinstance(rule, ZoneEntryRuleConfig):
            return evaluate_zone_entry(track, zone, rule, timestamp)
        if isinstance(rule, ZoneDwellTimeRuleConfig):
            return evaluate_zone_dwell_time(track, zone, rule, timestamp, entry_time)
        if isinstance(rule, WrongDirectionRuleConfig):
            return evaluate_wrong_direction(track, zone, rule, timestamp)
        if isinstance(rule, IllegalParkingRuleConfig):
            return evaluate_illegal_parking(track, zone, rule, timestamp, entry_time)
        if isinstance(rule, NoStoppingRuleConfig):
            return evaluate_no_stopping(track, zone, rule, timestamp, entry_time)
        if isinstance(rule, BusStopOccupationRuleConfig):
            return evaluate_bus_stop_occupation(track, zone, rule, timestamp, entry_time)
        if isinstance(rule, StalledVehicleRuleConfig):
            return evaluate_stalled_vehicle(track, zone, rule, timestamp, entry_time)

        logger.warning("Unhandled rule config type: %s", type(rule).__name__)
        return None

    def _handle_stop_line_crossing_rule(
        self,
        track: TrackedObject,
        zone: ZoneConfig,
        rule: StopLineCrossingRuleConfig,
        timestamp: datetime,
        frame_index: int | None,
        scene: SceneContext | None,
    ) -> tuple[PreViolationRecord | None, ViolationRecord | None]:
        if track.category != track.category.VEHICLE:
            return None, None

        key = self._candidate_key(RuleType.STOP_LINE_CROSSING, track.track_id, zone.zone_id)
        candidate = self._candidate_states.get(key)
        line = self._line_segments.get(zone.zone_id)
        if line is None:
            return None, None

        if candidate is not None and self._candidate_invalidated_for_line(candidate, track, line):
            self._candidate_states.pop(key, None)
            candidate = None

        if candidate is None and not self._is_rule_cooling(
            RuleType.STOP_LINE_CROSSING,
            track.track_id,
            zone.zone_id,
            timestamp,
            rule.cooldown_seconds,
        ):
            candidate = self._detect_vehicle_line_candidate(
                rule_type=RuleType.STOP_LINE_CROSSING,
                violation_type=rule.violation_type,
                track=track,
                zone=zone,
                line=line,
                timestamp=timestamp,
                frame_index=frame_index,
                scene=scene,
                require_red=rule.requires_red_light,
                candidate_reason="Stop-line crossing on red candidate detected.",
            )
            if candidate is not None:
                self._candidate_states[key] = candidate

        if candidate is None:
            return None, None

        if self._line_candidate_confirmed(
            candidate,
            track,
            line,
            timestamp,
            frame_index,
            required_frames=rule.confirmation_frames,
            min_seconds=rule.min_post_crossing_seconds,
            min_distance_px=rule.min_post_crossing_distance_px,
        ):
            self._candidate_states.pop(key, None)
            return None, self._build_confirmed_violation(
                candidate,
                zone,
                rule,
                track,
                timestamp,
                reason=(
                    f"Vehicle {track.track_id} crossed stop-line '{zone.name}' on red and"
                    f" remained beyond the line long enough to confirm the violation."
                ),
                extra_conditions=[
                    "post_crossing_temporal_confirmation_met",
                    "post_crossing_distance_threshold_met",
                ],
                extra_details={
                    "signal_state_at_decision": candidate.signal_state_at_detection.value,
                    "relevant_zone_ids": [zone.zone_id],
                    "crossing_direction": candidate.crossing_direction,
                    "confirmation_seconds_elapsed": round(candidate.age_seconds(timestamp), 3),
                    "confirmation_frames_elapsed": candidate.age_frames(frame_index),
                    "post_crossing_distance_px": round(
                        abs(self._signed_line_distance(track.centroid, line)), 2
                    ),
                    "rule_conditions_satisfied": [
                        *candidate.conditions_satisfied,
                        "post_crossing_temporal_confirmation_met",
                        "post_crossing_distance_threshold_met",
                    ],
                },
            )

        return self._build_pre_violation(
            candidate,
            zone,
            rule,
            track,
            timestamp,
            reason=(
                f"Vehicle {track.track_id} crossed stop-line '{zone.name}' under the configured"
                " signal condition; awaiting temporal confirmation."
            ),
            extra_details={
                "signal_state_at_decision": candidate.signal_state_at_detection.value,
                "relevant_zone_ids": [zone.zone_id],
                "crossing_direction": candidate.crossing_direction,
                "confirmation_seconds_elapsed": round(candidate.age_seconds(timestamp), 3),
                "confirmation_frames_elapsed": candidate.age_frames(frame_index),
                "post_crossing_distance_px": round(
                    abs(self._signed_line_distance(track.centroid, line)), 2
                ),
                "confirmation_threshold_seconds": rule.min_post_crossing_seconds,
                "confirmation_threshold_frames": rule.confirmation_frames,
                "confirmation_threshold_distance_px": rule.min_post_crossing_distance_px,
            },
        ), None

    def _handle_red_light_rule(
        self,
        track: TrackedObject,
        zone: ZoneConfig,
        rule: RedLightRuleConfig,
        timestamp: datetime,
        frame_index: int | None,
        scene: SceneContext | None,
    ) -> tuple[PreViolationRecord | None, ViolationRecord | None]:
        if track.category != track.category.VEHICLE:
            return None, None
        if (
            rule.stop_line_zone_name
            and zone.name != rule.stop_line_zone_name
            and zone.zone_id != rule.stop_line_zone_name
        ):
            return None, None

        key = self._candidate_key(RuleType.RED_LIGHT, track.track_id, zone.zone_id)
        candidate = self._candidate_states.get(key)
        line = self._line_segments.get(zone.zone_id)
        if line is None:
            return None, None

        if candidate is not None and self._candidate_invalidated_for_line(candidate, track, line):
            self._candidate_states.pop(key, None)
            candidate = None

        if candidate is None and not self._is_rule_cooling(
            RuleType.RED_LIGHT, track.track_id, zone.zone_id, timestamp, rule.cooldown_seconds
        ):
            candidate = self._detect_vehicle_line_candidate(
                rule_type=RuleType.RED_LIGHT,
                violation_type=rule.violation_type,
                track=track,
                zone=zone,
                line=line,
                timestamp=timestamp,
                frame_index=frame_index,
                scene=scene,
                require_red=True,
                candidate_reason="Red-light jump candidate detected.",
            )
            if candidate is not None:
                linked_crosswalk = self._resolve_zone_reference(rule.crosswalk_zone_name)
                if linked_crosswalk is not None:
                    candidate.linked_zone_id = linked_crosswalk.zone_id
                    candidate.linked_zone_name = linked_crosswalk.name
                self._candidate_states[key] = candidate

        if candidate is None:
            return None, None

        linked_crosswalk = self._resolve_zone_reference(rule.crosswalk_zone_name)
        entered_linked_crosswalk = False
        if linked_crosswalk is not None:
            poly = self._zone_polygons.get(linked_crosswalk.zone_id)
            entered_linked_crosswalk = poly is not None and point_in_polygon(track.centroid, poly)

        if self._red_light_candidate_confirmed(
            candidate,
            track,
            line,
            timestamp,
            frame_index,
            required_frames=rule.confirmation_frames,
            min_seconds=rule.min_post_crossing_seconds,
            min_distance_px=rule.min_post_crossing_distance_px,
            linked_crosswalk_present=linked_crosswalk is not None,
            entered_linked_crosswalk=entered_linked_crosswalk,
        ):
            self._candidate_states.pop(key, None)
            return None, self._build_confirmed_violation(
                candidate,
                zone,
                rule,
                track,
                timestamp,
                reason=(
                    f"Vehicle {track.track_id} crossed stop-line '{zone.name}' on red and"
                    f" continued into the protected area."
                ),
                extra_conditions=[
                    "post_crossing_temporal_confirmation_met",
                    "protected_area_progression_confirmed",
                ],
                extra_details={
                    "signal_state_at_decision": candidate.signal_state_at_detection.value,
                    "relevant_zone_ids": [zone.zone_id]
                    + ([linked_crosswalk.zone_id] if linked_crosswalk is not None else []),
                    "relevant_zone_names": [zone.name]
                    + ([linked_crosswalk.name] if linked_crosswalk is not None else []),
                    "crossing_direction": candidate.crossing_direction,
                    "confirmation_seconds_elapsed": round(candidate.age_seconds(timestamp), 3),
                    "confirmation_frames_elapsed": candidate.age_frames(frame_index),
                    "post_crossing_distance_px": round(
                        abs(self._signed_line_distance(track.centroid, line)), 2
                    ),
                    "entered_linked_crosswalk": entered_linked_crosswalk,
                    "rule_conditions_satisfied": [
                        *candidate.conditions_satisfied,
                        "post_crossing_temporal_confirmation_met",
                        "protected_area_progression_confirmed",
                    ],
                },
            )

        return self._build_pre_violation(
            candidate,
            zone,
            rule,
            track,
            timestamp,
            reason=(
                f"Vehicle {track.track_id} crossed stop-line '{zone.name}' on red; awaiting"
                " confirmation that the vehicle committed to the protected area."
            ),
            extra_details={
                "signal_state_at_decision": candidate.signal_state_at_detection.value,
                "relevant_zone_ids": [zone.zone_id]
                + ([linked_crosswalk.zone_id] if linked_crosswalk is not None else []),
                "relevant_zone_names": [zone.name]
                + ([linked_crosswalk.name] if linked_crosswalk is not None else []),
                "crossing_direction": candidate.crossing_direction,
                "confirmation_seconds_elapsed": round(candidate.age_seconds(timestamp), 3),
                "confirmation_frames_elapsed": candidate.age_frames(frame_index),
                "post_crossing_distance_px": round(
                    abs(self._signed_line_distance(track.centroid, line)), 2
                ),
                "entered_linked_crosswalk": entered_linked_crosswalk,
                "confirmation_threshold_seconds": rule.min_post_crossing_seconds,
                "confirmation_threshold_frames": rule.confirmation_frames,
                "confirmation_threshold_distance_px": rule.min_post_crossing_distance_px,
                "linked_crosswalk_required": linked_crosswalk is not None,
            },
        ), None

    def _handle_pedestrian_on_red_rule(
        self,
        track: TrackedObject,
        zone: ZoneConfig,
        rule: PedestrianOnRedRuleConfig,
        timestamp: datetime,
        frame_index: int | None,
        scene: SceneContext | None,
    ) -> tuple[PreViolationRecord | None, ViolationRecord | None]:
        if track.category != track.category.PERSON:
            return None, None
        if not isinstance(zone.geometry, PolygonGeometry):
            return None, None
        if (
            rule.crosswalk_zone_name
            and zone.name != rule.crosswalk_zone_name
            and zone.zone_id != rule.crosswalk_zone_name
        ):
            return None, None

        key = self._candidate_key(RuleType.PEDESTRIAN_ON_RED, track.track_id, zone.zone_id)
        candidate = self._candidate_states.get(key)
        polygon = self._zone_polygons.get(zone.zone_id)
        if polygon is None:
            return None, None

        if candidate is not None and not point_in_polygon(track.centroid, polygon):
            self._candidate_states.pop(key, None)
            candidate = None

        if candidate is None and not self._is_rule_cooling(
            RuleType.PEDESTRIAN_ON_RED,
            track.track_id,
            zone.zone_id,
            timestamp,
            rule.cooldown_seconds,
        ):
            candidate = self._detect_pedestrian_crosswalk_candidate(
                track=track,
                zone=zone,
                polygon=polygon,
                rule=rule,
                timestamp=timestamp,
                frame_index=frame_index,
                scene=scene,
            )
            if candidate is not None:
                self._candidate_states[key] = candidate

        if candidate is None:
            return None, None

        if self._pedestrian_candidate_confirmed(
            candidate,
            track,
            polygon,
            timestamp,
            frame_index,
            required_frames=rule.confirmation_frames,
            min_inside_seconds=rule.min_inside_seconds,
        ):
            self._candidate_states.pop(key, None)
            return None, self._build_confirmed_violation(
                candidate,
                zone,
                rule,
                track,
                timestamp,
                reason=(
                    f"Pedestrian {track.track_id} entered crosswalk '{zone.name}' on red and"
                    f" remained inside long enough to confirm the violation."
                ),
                extra_conditions=[
                    "crosswalk_entry_detected_under_red",
                    "crosswalk_temporal_confirmation_met",
                ],
                extra_details={
                    "signal_state_at_decision": candidate.signal_state_at_detection.value,
                    "relevant_zone_ids": [zone.zone_id],
                    "relevant_zone_names": [zone.name],
                    "crosswalk_entry_at": candidate.candidate_started_at,
                    "confirmation_seconds_elapsed": round(candidate.age_seconds(timestamp), 3),
                    "confirmation_frames_elapsed": candidate.age_frames(frame_index),
                    "rule_conditions_satisfied": [
                        *candidate.conditions_satisfied,
                        "crosswalk_temporal_confirmation_met",
                    ],
                },
            )

        return self._build_pre_violation(
            candidate,
            zone,
            rule,
            track,
            timestamp,
            reason=(
                f"Pedestrian {track.track_id} entered crosswalk '{zone.name}' on red; awaiting"
                " confirmation that the crossing is sustained."
            ),
            extra_details={
                "signal_state_at_decision": candidate.signal_state_at_detection.value,
                "relevant_zone_ids": [zone.zone_id],
                "relevant_zone_names": [zone.name],
                "crosswalk_entry_at": candidate.candidate_started_at,
                "confirmation_seconds_elapsed": round(candidate.age_seconds(timestamp), 3),
                "confirmation_frames_elapsed": candidate.age_frames(frame_index),
                "confirmation_threshold_seconds": rule.min_inside_seconds,
                "confirmation_threshold_frames": rule.confirmation_frames,
            },
        ), None

    def _detect_vehicle_line_candidate(
        self,
        *,
        rule_type: RuleType,
        violation_type: ViolationType,
        track: TrackedObject,
        zone: ZoneConfig,
        line: LineSegment,
        timestamp: datetime,
        frame_index: int | None,
        scene: SceneContext | None,
        require_red: bool,
        candidate_reason: str,
    ) -> _CandidateState | None:
        segment = self._latest_segment(track)
        if segment is None:
            return None
        prev, cur = segment
        crossing = check_line_crossing(prev, cur, line)
        if not crossing.crossed:
            return None

        signal_state = (
            scene.vehicle_signal_state_for_stop_line(
                zone.zone_id,
                min_confidence=self._settings.min_signal_confidence,
            )
            if scene is not None
            else TrafficLightState.UNKNOWN
        )
        signal = (
            scene.signal_for_stop_line(zone.zone_id, phase=SignalPhase.VEHICLE)
            if scene is not None
            else None
        )
        if require_red and signal_state != TrafficLightState.RED:
            return None

        signed_distance = self._signed_line_distance(track.centroid, line)
        if signed_distance > 0:
            post_sign = 1.0
        elif signed_distance < 0:
            post_sign = -1.0
        elif crossing.direction == LineCrossingDirection.NEGATIVE_TO_POSITIVE:
            post_sign = 1.0
        elif crossing.direction == LineCrossingDirection.POSITIVE_TO_NEGATIVE:
            post_sign = -1.0
        else:
            post_sign = None

        conditions = ["latest_segment_crossed_line", "track_category_vehicle"]
        if require_red:
            conditions.append("signal_red_at_detection")

        return _CandidateState(
            rule_type=rule_type,
            violation_type=violation_type,
            zone_id=zone.zone_id,
            zone_name=zone.name,
            track_id=track.track_id,
            candidate_started_at=timestamp,
            candidate_frame_index=frame_index,
            signal_state_at_detection=signal_state,
            signal_phase=SignalPhase.VEHICLE,
            signal_head_id=signal.head_id if signal is not None else None,
            signal_confidence=signal.confidence if signal is not None else None,
            crossing_direction=crossing.direction.value
            if crossing.direction is not None
            else None,
            post_cross_sign=post_sign,
            conditions_satisfied=conditions,
            metadata={
                "candidate_reason": candidate_reason,
                "detection_centroid": {"x": track.centroid.x, "y": track.centroid.y},
                "detection_bbox": track.bbox.to_dict(),
                "signal_source_kind": signal.source_kind.value if signal is not None else None,
                "signal_observed_sources": (
                    [source.value for source in signal.observed_sources]
                    if signal is not None
                    else []
                ),
                "signal_conflict_reason": signal.conflict_reason if signal is not None else None,
                "signal_controller_id": signal.controller_id if signal is not None else None,
                "signal_junction_id": signal.junction_id if signal is not None else None,
                "signal_phase_id": signal.phase_id if signal is not None else None,
                "signal_integration_mode": scene.integration_mode.value
                if scene is not None
                else None,
            },
        )

    def _detect_pedestrian_crosswalk_candidate(
        self,
        *,
        track: TrackedObject,
        zone: ZoneConfig,
        polygon: PolygonZone,
        rule: PedestrianOnRedRuleConfig,
        timestamp: datetime,
        frame_index: int | None,
        scene: SceneContext | None,
    ) -> _CandidateState | None:
        segment = self._latest_segment(track)
        if segment is None:
            return None
        prev, cur = segment
        transition = detect_zone_transition(prev, cur, polygon)
        if transition is None:
            return None
        if rule.require_entry_on_red and transition.transition != ZoneTransitionType.ENTERED:
            return None

        signal_state = (
            scene.pedestrian_signal_state_for_crosswalk(
                zone.zone_id,
                min_confidence=self._settings.min_signal_confidence,
            )
            if scene is not None
            else TrafficLightState.UNKNOWN
        )
        signal = (
            scene.signal_for_crosswalk(zone.zone_id, phase=SignalPhase.PEDESTRIAN)
            if scene is not None
            else None
        )
        if signal_state != TrafficLightState.RED:
            return None

        return _CandidateState(
            rule_type=RuleType.PEDESTRIAN_ON_RED,
            violation_type=rule.violation_type,
            zone_id=zone.zone_id,
            zone_name=zone.name,
            track_id=track.track_id,
            candidate_started_at=timestamp,
            candidate_frame_index=frame_index,
            signal_state_at_detection=signal_state,
            signal_phase=SignalPhase.PEDESTRIAN,
            signal_head_id=signal.head_id if signal is not None else None,
            signal_confidence=signal.confidence if signal is not None else None,
            conditions_satisfied=[
                "track_category_person",
                "crosswalk_entry_detected",
                "pedestrian_signal_red_at_entry",
            ],
            metadata={
                "entry_transition": transition.transition.value,
                "entry_centroid": {"x": track.centroid.x, "y": track.centroid.y},
                "entry_bbox": track.bbox.to_dict(),
                "signal_source_kind": signal.source_kind.value if signal is not None else None,
                "signal_observed_sources": (
                    [source.value for source in signal.observed_sources]
                    if signal is not None
                    else []
                ),
                "signal_conflict_reason": signal.conflict_reason if signal is not None else None,
                "signal_controller_id": signal.controller_id if signal is not None else None,
                "signal_junction_id": signal.junction_id if signal is not None else None,
                "signal_phase_id": signal.phase_id if signal is not None else None,
                "signal_integration_mode": scene.integration_mode.value
                if scene is not None
                else None,
            },
        )

    def _line_candidate_confirmed(
        self,
        candidate: _CandidateState,
        track: TrackedObject,
        line: LineSegment,
        timestamp: datetime,
        frame_index: int | None,
        *,
        required_frames: int,
        min_seconds: float,
        min_distance_px: float,
    ) -> bool:
        signed_distance = self._signed_line_distance(track.centroid, line)
        if (
            candidate.post_cross_sign is not None
            and signed_distance * candidate.post_cross_sign <= 0
        ):
            return False
        return (
            candidate.age_frames(frame_index) >= required_frames
            and candidate.age_seconds(timestamp) >= min_seconds
            and abs(signed_distance) >= min_distance_px
        )

    def _red_light_candidate_confirmed(
        self,
        candidate: _CandidateState,
        track: TrackedObject,
        line: LineSegment,
        timestamp: datetime,
        frame_index: int | None,
        *,
        required_frames: int,
        min_seconds: float,
        min_distance_px: float,
        linked_crosswalk_present: bool,
        entered_linked_crosswalk: bool,
    ) -> bool:
        temporal_ok = (
            candidate.age_frames(frame_index) >= required_frames
            and candidate.age_seconds(timestamp) >= min_seconds
        )
        if not temporal_ok:
            return False
        if linked_crosswalk_present:
            return entered_linked_crosswalk

        signed_distance = self._signed_line_distance(track.centroid, line)
        if (
            candidate.post_cross_sign is not None
            and signed_distance * candidate.post_cross_sign <= 0
        ):
            return False
        return abs(signed_distance) >= min_distance_px

    def _pedestrian_candidate_confirmed(
        self,
        candidate: _CandidateState,
        track: TrackedObject,
        polygon: PolygonZone,
        timestamp: datetime,
        frame_index: int | None,
        *,
        required_frames: int,
        min_inside_seconds: float,
    ) -> bool:
        if not point_in_polygon(track.centroid, polygon):
            return False
        return (
            candidate.age_frames(frame_index) >= required_frames
            and candidate.age_seconds(timestamp) >= min_inside_seconds
        )

    def _candidate_invalidated_for_line(
        self,
        candidate: _CandidateState,
        track: TrackedObject,
        line: LineSegment,
    ) -> bool:
        signed_distance = self._signed_line_distance(track.centroid, line)
        if candidate.post_cross_sign is None:
            return False
        return signed_distance * candidate.post_cross_sign < 0

    def _build_pre_violation(
        self,
        candidate: _CandidateState,
        zone: ZoneConfig,
        rule: RuleConfig,
        track: TrackedObject,
        observed_at: datetime,
        *,
        reason: str,
        extra_details: dict[str, Any] | None = None,
    ) -> PreViolationRecord:
        return PreViolationRecord(
            rule_type=candidate.rule_type,
            violation_type=candidate.violation_type,
            zone_id=zone.zone_id,
            zone_name=zone.name,
            track_id=track.track_id,
            observed_at=observed_at,
            candidate_started_at=candidate.candidate_started_at,
            certainty=0.5,
            explanation=self._build_explanation(
                candidate.rule_type,
                rule,
                reason,
                track,
                zone,
                conditions_satisfied=candidate.conditions_satisfied,
                details={
                    "stage": "pre_violation",
                    "signal_state_at_detection": candidate.signal_state_at_detection.value,
                    "signal_phase": candidate.signal_phase.value,
                    "signal_head_id": candidate.signal_head_id,
                    "signal_confidence": candidate.signal_confidence,
                    "candidate_started_at": candidate.candidate_started_at,
                    **candidate.metadata,
                    **(extra_details or {}),
                },
            ),
        )

    def _build_confirmed_violation(
        self,
        candidate: _CandidateState,
        zone: ZoneConfig,
        rule: RuleConfig,
        track: TrackedObject,
        occurred_at: datetime,
        *,
        reason: str,
        extra_conditions: list[str] | None = None,
        extra_details: dict[str, Any] | None = None,
    ) -> ViolationRecord:
        confirmed_conditions = candidate.conditions_satisfied + list(extra_conditions or [])
        return ViolationRecord(
            rule_type=candidate.rule_type,
            violation_type=candidate.violation_type,
            severity=rule.severity,
            zone_id=zone.zone_id,
            zone_name=zone.name,
            track_id=track.track_id,
            occurred_at=occurred_at,
            certainty=1.0,
            explanation=self._build_explanation(
                candidate.rule_type,
                rule,
                reason,
                track,
                zone,
                conditions_satisfied=confirmed_conditions,
                details={
                    "stage": "confirmed",
                    "signal_state_at_detection": candidate.signal_state_at_detection.value,
                    "signal_phase": candidate.signal_phase.value,
                    "signal_head_id": candidate.signal_head_id,
                    "signal_confidence": candidate.signal_confidence,
                    "candidate_started_at": candidate.candidate_started_at,
                    **candidate.metadata,
                    **(extra_details or {}),
                },
            ),
        )

    def _build_explanation(
        self,
        rule_type: RuleType,
        rule_config: RuleConfig,
        reason: str,
        track: TrackedObject,
        zone: ZoneConfig,
        *,
        conditions_satisfied: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> Explanation:
        return Explanation(
            rule_type=rule_type,
            rule_config=rule_config.model_dump(mode="json"),
            reason=reason,
            conditions_satisfied=list(conditions_satisfied or []),
            details=details or {},
            track_snapshot=track.to_event_dict(),
            zone_info={
                "zone_id": zone.zone_id,
                "zone_name": zone.name,
                "zone_type": zone.zone_type.value,
                "geometry": zone.geometry_as_dict(),
            },
        )

    def _candidate_key(
        self, rule_type: RuleType, track_id: str, zone_id: str
    ) -> tuple[RuleType, str, str]:
        return (rule_type, track_id, zone_id)

    def _cleanup_expired_candidates(self, timestamp: datetime) -> None:
        expired_keys = [
            key
            for key, candidate in self._candidate_states.items()
            if candidate.age_seconds(timestamp) > self._settings.candidate_timeout_seconds
        ]
        for key in expired_keys:
            del self._candidate_states[key]

    def _cleanup_track(self, track_id: str) -> None:
        keys_entries = [key for key in self._zone_entries if key[0] == track_id]
        for key in keys_entries:
            del self._zone_entries[key]

        keys_cd = [key for key in self._cooldowns if key[1] == track_id]
        for key in keys_cd:
            del self._cooldowns[key]

        candidate_keys = [key for key in self._candidate_states if key[1] == track_id]
        for key in candidate_keys:
            del self._candidate_states[key]

        self._violation_counts.pop(track_id, None)

    def _update_zone_occupancy(self, track: TrackedObject, timestamp: datetime) -> None:
        for zone in self._zones:
            poly = self._zone_polygons.get(zone.zone_id)
            if poly is None:
                continue
            key = (track.track_id, zone.zone_id)
            inside = point_in_polygon(track.centroid, poly)
            if inside and key not in self._zone_entries:
                self._zone_entries[key] = timestamp
            elif not inside and key in self._zone_entries:
                del self._zone_entries[key]

    def _is_cooled_down(self, violation: ViolationRecord, rule: RuleConfig) -> bool:
        key = (violation.rule_type.value, violation.track_id, violation.zone_id)
        last = self._cooldowns.get(key)
        if last is None:
            return False
        return (violation.occurred_at - last).total_seconds() < rule.cooldown_seconds

    def _is_rule_cooling(
        self,
        rule_type: RuleType,
        track_id: str,
        zone_id: str,
        timestamp: datetime,
        cooldown_seconds: float,
    ) -> bool:
        last = self._cooldowns.get((rule_type.value, track_id, zone_id))
        if last is None:
            return False
        return (timestamp - last).total_seconds() < cooldown_seconds

    def _record_cooldown(self, violation: ViolationRecord) -> None:
        self._cooldowns[(violation.rule_type.value, violation.track_id, violation.zone_id)] = (
            violation.occurred_at
        )

    def _resolve_zone_reference(self, zone_ref: str | None) -> ZoneConfig | None:
        if zone_ref is None:
            return None
        return self._zone_by_id.get(zone_ref) or self._zone_by_name.get(zone_ref)

    def _latest_segment(self, track: TrackedObject) -> tuple[Point2D, Point2D] | None:
        if len(track.trajectory) < 2:
            return None
        return track.trajectory[-2].point, track.trajectory[-1].point

    def _signed_line_distance(self, point: Point2D, line: LineSegment) -> float:
        dx = line.end.x - line.start.x
        dy = line.end.y - line.start.y
        norm = math.hypot(dx, dy)
        if norm <= 1e-9:
            return 0.0
        return ((dx * (point.y - line.start.y)) - (dy * (point.x - line.start.x))) / norm
