"""Typed schemas for the zone system and traffic rules engine."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from apps.api.app.db.enums import ViolationSeverity, ViolationType, ZoneType
from services.signals.schemas import SignalPhase
from services.tracking.schemas import CardinalDirection, LineCrossingDirection, Point2D
from services.vision.schemas import ObjectCategory

# ---------------------------------------------------------------------------
# Rule type enum
# ---------------------------------------------------------------------------


class RuleType(StrEnum):
    """Every distinct rule the engine can evaluate."""

    LINE_CROSSING = "line_crossing"
    STOP_LINE_CROSSING = "stop_line_crossing"
    ZONE_ENTRY = "zone_entry"
    ZONE_DWELL_TIME = "zone_dwell_time"
    WRONG_DIRECTION = "wrong_direction"
    RED_LIGHT = "red_light"
    PEDESTRIAN_ON_RED = "pedestrian_on_red"
    ILLEGAL_PARKING = "illegal_parking"
    NO_STOPPING = "no_stopping"
    BUS_STOP_OCCUPATION = "bus_stop_occupation"
    STALLED_VEHICLE = "stalled_vehicle"


class TrafficLightState(StrEnum):
    """Possible traffic signal states."""

    RED = "red"
    YELLOW = "yellow"
    GREEN = "green"
    UNKNOWN = "unknown"


class SignalStateSourceKind(StrEnum):
    """Where a rules-facing signal state came from."""

    VISION = "vision"
    CONTROLLER = "controller"
    RESOLVED = "resolved"


class SignalIntegrationMode(StrEnum):
    """How controller-fed and vision-derived signal states are combined."""

    VISION_ONLY = "vision_only"
    CONTROLLER_ONLY = "controller_only"
    HYBRID = "hybrid"


# ---------------------------------------------------------------------------
# Geometry helpers (parsed from Zone.geometry JSON)
# ---------------------------------------------------------------------------


class LineGeometry(BaseModel):
    """Two-point line geometry (stop-lines, counting lines)."""

    model_config = ConfigDict(frozen=True)

    start: Point2D
    end: Point2D


class PolygonGeometry(BaseModel):
    """Polygon geometry (zones, crosswalks, lanes)."""

    model_config = ConfigDict(frozen=True)

    points: list[Point2D] = Field(min_length=3)


# ---------------------------------------------------------------------------
# Rule configurations — one concrete class per rule type
# ---------------------------------------------------------------------------


class _RuleConfigBase(BaseModel):
    """Shared fields for every rule configuration."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    severity: ViolationSeverity = ViolationSeverity.MEDIUM
    cooldown_seconds: float = Field(default=30.0, ge=0.0)


class LineCrossingRuleConfig(_RuleConfigBase):
    rule_type: Literal["line_crossing"] = "line_crossing"
    violation_type: ViolationType = ViolationType.STOP_LINE
    forbidden_direction: LineCrossingDirection | None = None


class StopLineCrossingRuleConfig(_RuleConfigBase):
    rule_type: Literal["stop_line_crossing"] = "stop_line_crossing"
    violation_type: ViolationType = ViolationType.STOP_LINE
    requires_red_light: bool = True
    confirmation_frames: int = Field(default=1, ge=1)
    min_post_crossing_seconds: float = Field(default=0.05, ge=0.0)
    min_post_crossing_distance_px: float = Field(default=8.0, ge=0.0)


class ZoneEntryRuleConfig(_RuleConfigBase):
    rule_type: Literal["zone_entry"] = "zone_entry"
    violation_type: ViolationType = ViolationType.WRONG_WAY
    restricted_categories: list[ObjectCategory] = Field(default_factory=list)


class ZoneDwellTimeRuleConfig(_RuleConfigBase):
    rule_type: Literal["zone_dwell_time"] = "zone_dwell_time"
    violation_type: ViolationType = ViolationType.ILLEGAL_PARKING
    max_dwell_seconds: float = Field(default=30.0, gt=0.0)
    applicable_categories: list[ObjectCategory] = Field(
        default_factory=lambda: [ObjectCategory.VEHICLE],
    )


class WrongDirectionRuleConfig(_RuleConfigBase):
    rule_type: Literal["wrong_direction"] = "wrong_direction"
    violation_type: ViolationType = ViolationType.WRONG_WAY
    expected_direction: CardinalDirection


class RedLightRuleConfig(_RuleConfigBase):
    rule_type: Literal["red_light"] = "red_light"
    violation_type: ViolationType = ViolationType.RED_LIGHT
    stop_line_zone_name: str | None = None
    crosswalk_zone_name: str | None = None
    confirmation_frames: int = Field(default=2, ge=1)
    min_post_crossing_seconds: float = Field(default=0.15, ge=0.0)
    min_post_crossing_distance_px: float = Field(default=20.0, ge=0.0)


class PedestrianOnRedRuleConfig(_RuleConfigBase):
    rule_type: Literal["pedestrian_on_red"] = "pedestrian_on_red"
    violation_type: ViolationType = ViolationType.PEDESTRIAN_CONFLICT
    crosswalk_zone_name: str | None = None
    confirmation_frames: int = Field(default=2, ge=1)
    min_inside_seconds: float = Field(default=0.25, ge=0.0)
    require_entry_on_red: bool = True


class IllegalParkingRuleConfig(_RuleConfigBase):
    rule_type: Literal["illegal_parking"] = "illegal_parking"
    violation_type: ViolationType = ViolationType.ILLEGAL_PARKING
    max_stationary_seconds: float = Field(default=60.0, gt=0.0)
    grace_period_seconds: float = Field(default=10.0, ge=0.0)
    min_stationary_ratio: float = Field(default=0.7, ge=0.0, le=1.0)
    stationary_speed_px: float = Field(default=2.0, gt=0.0)
    max_stationary_displacement_px: float = Field(default=10.0, gt=0.0)
    min_stationary_streak_seconds: float = Field(default=5.0, ge=0.0)
    included_class_names: list[str] = Field(default_factory=list)
    excluded_class_names: list[str] = Field(default_factory=list)


class NoStoppingRuleConfig(_RuleConfigBase):
    rule_type: Literal["no_stopping"] = "no_stopping"
    violation_type: ViolationType = ViolationType.NO_STOPPING
    max_stationary_seconds: float = Field(default=30.0, gt=0.0)
    grace_period_seconds: float = Field(default=5.0, ge=0.0)
    min_stationary_ratio: float = Field(default=0.6, ge=0.0, le=1.0)
    stationary_speed_px: float = Field(default=2.0, gt=0.0)
    max_stationary_displacement_px: float = Field(default=10.0, gt=0.0)
    min_stationary_streak_seconds: float = Field(default=3.0, ge=0.0)
    included_class_names: list[str] = Field(default_factory=list)
    excluded_class_names: list[str] = Field(default_factory=list)


class BusStopOccupationRuleConfig(_RuleConfigBase):
    rule_type: Literal["bus_stop_occupation"] = "bus_stop_occupation"
    violation_type: ViolationType = ViolationType.BUS_STOP_VIOLATION
    max_stationary_seconds: float = Field(default=90.0, gt=0.0)
    grace_period_seconds: float = Field(default=20.0, ge=0.0)
    min_stationary_ratio: float = Field(default=0.65, ge=0.0, le=1.0)
    stationary_speed_px: float = Field(default=2.0, gt=0.0)
    max_stationary_displacement_px: float = Field(default=10.0, gt=0.0)
    min_stationary_streak_seconds: float = Field(default=5.0, ge=0.0)
    applicable_categories: list[ObjectCategory] = Field(
        default_factory=lambda: [ObjectCategory.VEHICLE],
    )
    included_class_names: list[str] = Field(default_factory=list)
    excluded_class_names: list[str] = Field(default_factory=lambda: ["bus"])


class StalledVehicleRuleConfig(_RuleConfigBase):
    rule_type: Literal["stalled_vehicle"] = "stalled_vehicle"
    violation_type: ViolationType = ViolationType.STALLED_VEHICLE
    max_stationary_seconds: float = Field(default=45.0, gt=0.0)
    grace_period_seconds: float = Field(default=10.0, ge=0.0)
    min_stationary_ratio: float = Field(default=0.85, ge=0.0, le=1.0)
    stationary_speed_px: float = Field(default=2.0, gt=0.0)
    max_stationary_displacement_px: float = Field(default=10.0, gt=0.0)
    min_stationary_streak_seconds: float = Field(default=8.0, ge=0.0)
    included_class_names: list[str] = Field(default_factory=list)
    excluded_class_names: list[str] = Field(default_factory=list)


RuleConfig = Annotated[
    LineCrossingRuleConfig
    | StopLineCrossingRuleConfig
    | ZoneEntryRuleConfig
    | ZoneDwellTimeRuleConfig
    | WrongDirectionRuleConfig
    | RedLightRuleConfig
    | PedestrianOnRedRuleConfig
    | IllegalParkingRuleConfig
    | NoStoppingRuleConfig
    | BusStopOccupationRuleConfig
    | StalledVehicleRuleConfig,
    Field(discriminator="rule_type"),
]


# ---------------------------------------------------------------------------
# Zone configuration (all rules for one zone)
# ---------------------------------------------------------------------------


class ZoneConfig(BaseModel):
    """Typed configuration produced from a DB Zone row."""

    zone_id: str
    name: str
    zone_type: ZoneType
    geometry: LineGeometry | PolygonGeometry
    rules: list[RuleConfig] = Field(default_factory=list)

    def geometry_as_dict(self) -> dict[str, Any]:
        """Serialise the geometry for embedding in explanations."""
        return self.geometry.model_dump(mode="json")


class SceneSignalState(BaseModel):
    """Rules-facing signal state for one linked signal head on one frame.

    This is a compact, typed representation extracted from the signal
    perception layer.  It gives the rules engine enough context to resolve
    the correct signal per stop-line or crosswalk without importing the full
    signal-service schemas.
    """

    model_config = ConfigDict(frozen=True)

    head_id: str
    phase: SignalPhase = SignalPhase.UNKNOWN
    state: TrafficLightState = TrafficLightState.UNKNOWN
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    frame_index: int | None = None
    last_seen_at: datetime | None = None
    frames_since_seen: int = 0
    is_stale: bool = False
    source_id: str | None = None
    stream_id: uuid.UUID | None = None
    camera_id: uuid.UUID | None = None
    lane_id: str | None = None
    stop_line_id: str | None = None
    crosswalk_id: str | None = None
    source_kind: SignalStateSourceKind = SignalStateSourceKind.RESOLVED
    observed_sources: list[SignalStateSourceKind] = Field(default_factory=list)
    trust_score: float | None = Field(default=None, ge=0.0, le=1.0)
    junction_id: str | None = None
    controller_id: str | None = None
    phase_id: str | None = None
    conflict_reason: str | None = None


class SignalConflict(BaseModel):
    """Explicit conflict between controller-fed and vision-derived signal state."""

    model_config = ConfigDict(frozen=True)

    phase: SignalPhase = SignalPhase.UNKNOWN
    reason: str
    head_id: str | None = None
    lane_id: str | None = None
    stop_line_id: str | None = None
    crosswalk_id: str | None = None
    phase_id: str | None = None
    junction_id: str | None = None
    controller_id: str | None = None
    vision_state: TrafficLightState = TrafficLightState.UNKNOWN
    controller_state: TrafficLightState = TrafficLightState.UNKNOWN
    vision_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    controller_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Scene context (external signals delivered per-frame)
# ---------------------------------------------------------------------------


class SceneContext(BaseModel):
    """External signals for the current frame (traffic-light state, etc.)."""

    model_config = ConfigDict(frozen=True)

    frame_index: int | None = None
    timestamp: datetime | None = None
    # Backward-compatible vehicle-signal alias used by older callers/tests.
    traffic_light_state: TrafficLightState = TrafficLightState.UNKNOWN
    traffic_light_zone_name: str | None = None
    vehicle_signal_state: TrafficLightState = TrafficLightState.UNKNOWN
    pedestrian_signal_state: TrafficLightState = TrafficLightState.UNKNOWN
    signal_states: list[SceneSignalState] = Field(default_factory=list)
    vision_signal_states: list[SceneSignalState] = Field(default_factory=list)
    controller_signal_states: list[SceneSignalState] = Field(default_factory=list)
    signal_conflicts: list[SignalConflict] = Field(default_factory=list)
    integration_mode: SignalIntegrationMode = SignalIntegrationMode.VISION_ONLY

    def _phase_signals(self, *, phase: SignalPhase) -> list[SceneSignalState]:
        return [signal for signal in self.signal_states if signal.phase == phase]

    def primary_signal(self, *, phase: SignalPhase) -> SceneSignalState | None:
        phase_signals = self._phase_signals(phase=phase)
        if len(phase_signals) != 1:
            return None
        return phase_signals[0]

    def signal_for_stop_line(
        self,
        stop_line_id: str | None,
        *,
        phase: SignalPhase = SignalPhase.VEHICLE,
    ) -> SceneSignalState | None:
        phase_signals = self._phase_signals(phase=phase)
        if stop_line_id is not None:
            linked_signals = [
                signal for signal in phase_signals if signal.stop_line_id is not None
            ]
            for signal in linked_signals:
                if signal.stop_line_id == stop_line_id:
                    return signal
            if linked_signals:
                return None
        return self.primary_signal(phase=phase)

    def signal_for_crosswalk(
        self,
        crosswalk_id: str | None,
        *,
        phase: SignalPhase = SignalPhase.PEDESTRIAN,
    ) -> SceneSignalState | None:
        phase_signals = self._phase_signals(phase=phase)
        if crosswalk_id is not None:
            linked_signals = [
                signal for signal in phase_signals if signal.crosswalk_id is not None
            ]
            for signal in linked_signals:
                if signal.crosswalk_id == crosswalk_id:
                    return signal
            if linked_signals:
                return None
        return self.primary_signal(phase=phase)

    def vehicle_signal_state_for_stop_line(
        self,
        stop_line_id: str | None,
        *,
        min_confidence: float = 0.0,
    ) -> TrafficLightState:
        signal = self.signal_for_stop_line(stop_line_id, phase=SignalPhase.VEHICLE)
        if signal is not None:
            if signal.is_stale or signal.confidence < min_confidence:
                return TrafficLightState.UNKNOWN
            return signal.state
        if self.vehicle_signal_state != TrafficLightState.UNKNOWN:
            return self.vehicle_signal_state
        return self.traffic_light_state

    def pedestrian_signal_state_for_crosswalk(
        self,
        crosswalk_id: str | None,
        *,
        min_confidence: float = 0.0,
    ) -> TrafficLightState:
        signal = self.signal_for_crosswalk(crosswalk_id, phase=SignalPhase.PEDESTRIAN)
        if signal is not None:
            if signal.is_stale or signal.confidence < min_confidence:
                return TrafficLightState.UNKNOWN
            return signal.state
        return self.pedestrian_signal_state


class ViolationLifecycleStage(StrEnum):
    PRE_VIOLATION = "pre_violation"
    CONFIRMED = "confirmed"


# ---------------------------------------------------------------------------
# Violation output (designed for frontend review UI)
# ---------------------------------------------------------------------------


class Explanation(BaseModel):
    """Structured evidence for why a violation fired.

    Every field is serialisable so the value can be stored in JSON and
    rendered by the review UI.
    """

    rule_type: RuleType
    rule_config: dict[str, Any] = Field(default_factory=dict)
    reason: str
    frame_index: int | None = None
    conditions_satisfied: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
    track_snapshot: dict[str, Any] = Field(default_factory=dict)
    zone_info: dict[str, Any] = Field(default_factory=dict)


class PreViolationRecord(BaseModel):
    """One candidate/pre-violation state emitted before confirmation."""

    stage: ViolationLifecycleStage = ViolationLifecycleStage.PRE_VIOLATION
    rule_type: RuleType
    violation_type: ViolationType
    zone_id: str
    zone_name: str
    track_id: str
    observed_at: datetime
    candidate_started_at: datetime
    frame_index: int | None = None
    certainty: float = Field(default=0.5, ge=0.0, le=1.0)
    explanation: Explanation

    def to_event_dict(self) -> dict[str, Any]:
        """Serialisable dict for persistence or downstream consumers."""
        return {
            "stage": self.stage.value,
            "rule_type": self.rule_type.value,
            "violation_type": self.violation_type.value,
            "zone_id": self.zone_id,
            "zone_name": self.zone_name,
            "track_id": self.track_id,
            "observed_at": self.observed_at,
            "candidate_started_at": self.candidate_started_at,
            "frame_index": self.frame_index,
            "certainty": self.certainty,
            "explanation": self.explanation.model_dump(mode="json"),
        }


class ViolationRecord(BaseModel):
    """One emitted violation from the rules engine."""

    rule_type: RuleType
    violation_type: ViolationType
    severity: ViolationSeverity
    zone_id: str
    zone_name: str
    track_id: str
    occurred_at: datetime
    frame_index: int | None = None
    certainty: float = Field(default=1.0, ge=0.0, le=1.0)
    explanation: Explanation

    def to_orm_kwargs(self) -> dict[str, Any]:
        """Dict suitable for creating a ViolationEvent ORM instance."""
        return {
            "violation_type": self.violation_type,
            "severity": self.severity,
            "occurred_at": self.occurred_at,
            "summary": self.explanation.reason,
            "rule_metadata": {
                "rule_type": self.rule_type.value,
                "frame_index": self.frame_index,
                "track_id": self.track_id,
                "certainty": self.certainty,
                "explanation": self.explanation.model_dump(mode="json"),
            },
        }


class RuleEvaluationResult(BaseModel):
    """Full per-frame rules evaluation output, including pre-violations."""

    pre_violations: list[PreViolationRecord] = Field(default_factory=list)
    violations: list[ViolationRecord] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Parsing helper — build ZoneConfig from raw DB fields
# ---------------------------------------------------------------------------

_RULE_LIST_ADAPTER: TypeAdapter[list[RuleConfig]] = TypeAdapter(list[RuleConfig])

_LINE_ZONE_TYPES: frozenset[str] = frozenset({ZoneType.LINE, ZoneType.STOP_LINE})


def parse_zone_config(
    *,
    zone_id: str,
    name: str,
    zone_type: str,
    geometry: dict[str, Any],
    rules_config: dict[str, Any],
) -> ZoneConfig:
    """Build a typed ``ZoneConfig`` from raw DB Zone fields."""
    if zone_type in _LINE_ZONE_TYPES:
        geo: LineGeometry | PolygonGeometry = LineGeometry.model_validate(geometry)
    else:
        geo = PolygonGeometry.model_validate(geometry)

    raw_rules = rules_config.get("rules", [])
    rules = _RULE_LIST_ADAPTER.validate_python(raw_rules) if raw_rules else []

    return ZoneConfig(
        zone_id=zone_id,
        name=name,
        zone_type=ZoneType(zone_type),
        geometry=geo,
        rules=rules,
    )
