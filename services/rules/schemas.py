"""Typed schemas for the zone system and traffic rules engine."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from apps.api.app.db.enums import ViolationSeverity, ViolationType, ZoneType
from packages.shared_types.enums import (  # noqa: F401 — re-exported
    RuleType,
    ViolationLifecycleStage,
)
from packages.shared_types.events import (  # noqa: F401 — re-exported
    Explanation,
    PreViolationRecord,
    RuleEvaluationResult,
    ViolationRecord,
)
from packages.shared_types.geometry import ObjectCategory, Point2D
from packages.shared_types.scene import (
    SceneContext,
    SceneSignalState,
    SignalConflict,
    SignalIntegrationMode,
    SignalPhase,
    SignalStateSourceKind,
    TrafficLightState,
)
from services.tracking.schemas import CardinalDirection, LineCrossingDirection

__all__ = [
    # re-export shared types for backward compatibility
    "SceneContext",
    "SceneSignalState",
    "SignalConflict",
    "SignalIntegrationMode",
    "SignalPhase",
    "SignalStateSourceKind",
    "TrafficLightState",
    # re-export shared enums and event contracts
    "RuleType",
    "ViolationLifecycleStage",
    "Explanation",
    "PreViolationRecord",
    "ViolationRecord",
    "RuleEvaluationResult",
]


# TrafficLightState, SignalStateSourceKind, SignalIntegrationMode imported
# from packages.shared_types — do NOT redefine here.


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


# ViolationLifecycleStage, Explanation, PreViolationRecord,
# ViolationRecord, RuleEvaluationResult — canonical definitions live in
# packages.shared_types.events; re-exported via __all__ above.


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
