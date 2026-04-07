"""Typed schemas for stationary-object and dwell-time analysis."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from services.vision.schemas import ObjectCategory

# ---------------------------------------------------------------------------
# Dwell scenario taxonomy
# ---------------------------------------------------------------------------


class DwellScenario(StrEnum):
    """Distinct operational scenarios where stationary/dwell analysis applies."""

    ILLEGAL_PARKING = "illegal_parking"
    NO_STOPPING = "no_stopping"
    BUS_STOP_OCCUPATION = "bus_stop_occupation"
    STALLED_VEHICLE = "stalled_vehicle"


class DwellOutcome(StrEnum):
    """Outcome of a single dwell analysis evaluation."""

    BELOW_THRESHOLD = "below_threshold"
    GRACE_PERIOD = "grace_period"
    CANDIDATE = "candidate"
    VIOLATION = "violation"


# ---------------------------------------------------------------------------
# Configurable thresholds — one per camera/zone/scenario
# ---------------------------------------------------------------------------


class DwellThresholds(BaseModel):
    """Per-scenario thresholds that control when a stationary dwell triggers.

    These are intentionally tunable per deployment/camera/zone so that
    operators can distinguish true violations from brief legitimate stops.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario: DwellScenario

    max_dwell_seconds: float = Field(
        default=60.0,
        gt=0.0,
        description="Dwell duration that constitutes a violation.",
    )
    grace_period_seconds: float = Field(
        default=10.0,
        ge=0.0,
        description="Initial dwell window that is always tolerated (e.g. loading/unloading).",
    )
    min_stationary_ratio: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description=(
            "Min fraction of the lookback window that must be stationary "
            "to qualify as a true dwell rather than a brief pause."
        ),
    )
    stationary_speed_px: float = Field(
        default=2.0,
        gt=0.0,
        description="Per-segment pixel displacement below which the object is 'stopped'.",
    )
    max_stationary_displacement_px: float = Field(
        default=10.0,
        gt=0.0,
        description=(
            "Maximum start-to-end drift allowed within the analysis window; "
            "prevents slow creeping motion from being treated as stationary."
        ),
    )
    min_stationary_streak_seconds: float = Field(
        default=5.0,
        ge=0.0,
        description="Min continuous stationary duration to count as genuinely stopped.",
    )
    applicable_categories: list[ObjectCategory] = Field(
        default_factory=lambda: [ObjectCategory.VEHICLE],
        description="Object classes this scenario applies to.",
    )
    included_class_names: list[str] = Field(
        default_factory=list,
        description="If set, only these detector class names are eligible for the scenario.",
    )
    excluded_class_names: list[str] = Field(
        default_factory=list,
        description="Detector class names that are explicitly exempt from the scenario.",
    )
    cooldown_seconds: float = Field(
        default=60.0,
        ge=0.0,
        description="Suppress repeated violations for the same track within this window.",
    )

    # Scenario-specific presets ------------------------------------------------

    @classmethod
    def illegal_parking(cls, **overrides: Any) -> DwellThresholds:
        defaults = dict(
            scenario=DwellScenario.ILLEGAL_PARKING,
            max_dwell_seconds=120.0,
            grace_period_seconds=15.0,
            min_stationary_ratio=0.75,
        )
        return cls(**(defaults | overrides))

    @classmethod
    def no_stopping(cls, **overrides: Any) -> DwellThresholds:
        defaults = dict(
            scenario=DwellScenario.NO_STOPPING,
            max_dwell_seconds=30.0,
            grace_period_seconds=5.0,
            min_stationary_ratio=0.6,
            min_stationary_streak_seconds=3.0,
        )
        return cls(**(defaults | overrides))

    @classmethod
    def bus_stop_occupation(cls, **overrides: Any) -> DwellThresholds:
        defaults = dict(
            scenario=DwellScenario.BUS_STOP_OCCUPATION,
            max_dwell_seconds=90.0,
            grace_period_seconds=20.0,
            min_stationary_ratio=0.65,
            applicable_categories=[ObjectCategory.VEHICLE],
            excluded_class_names=["bus"],
        )
        return cls(**(defaults | overrides))

    @classmethod
    def stalled_vehicle(cls, **overrides: Any) -> DwellThresholds:
        defaults = dict(
            scenario=DwellScenario.STALLED_VEHICLE,
            max_dwell_seconds=45.0,
            grace_period_seconds=10.0,
            min_stationary_ratio=0.85,
            min_stationary_streak_seconds=8.0,
        )
        return cls(**(defaults | overrides))


# ---------------------------------------------------------------------------
# Stationarity assessment — trajectory-derived motion summary
# ---------------------------------------------------------------------------


class StationarityAssessment(BaseModel):
    """Summary of a track's recent motion behaviour.

    Computed from trajectory points; does NOT incorporate zone or dwell
    context.  This lets callers reason about how stopped an object is
    independently of where it is or how long it has been there.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    samples_analyzed: int = 0
    stationary_samples: int = 0
    stationary_ratio: float = 0.0
    longest_stationary_streak_samples: int = 0
    longest_stationary_streak_seconds: float | None = None
    net_displacement_px: float = 0.0
    current_speed_px: float = 0.0
    is_currently_stationary: bool = True
    average_speed_px: float = 0.0
    max_speed_px: float = 0.0


# ---------------------------------------------------------------------------
# Dwell analysis output — the full determination
# ---------------------------------------------------------------------------


class DwellAnalysis(BaseModel):
    """Full dwell-analysis output for one track-in-zone evaluation.

    Carries enough metadata for downstream rules or review UIs to
    understand exactly why a dwell was or was not flagged.
    """

    model_config = ConfigDict(extra="forbid")

    outcome: DwellOutcome = DwellOutcome.BELOW_THRESHOLD
    scenario: DwellScenario
    track_id: str
    zone_id: str | None = None
    zone_name: str | None = None
    zone_type: str | None = None
    object_category: ObjectCategory | None = None
    object_class: str | None = None
    dwell_seconds: float = 0.0
    grace_period_seconds: float = 0.0
    threshold_seconds: float = 0.0
    threshold_exceeded_by: float = 0.0
    stationarity: StationarityAssessment = Field(
        default_factory=StationarityAssessment,
    )
    reason: str = ""
    warnings: list[str] = Field(default_factory=list)

    def to_detail_dict(self) -> dict[str, Any]:
        """Serialisable dict for embedding in violation explanations."""
        return {
            "outcome": self.outcome.value,
            "scenario": self.scenario.value,
            "track_id": self.track_id,
            "zone_id": self.zone_id,
            "zone_name": self.zone_name,
            "zone_type": self.zone_type,
            "object_category": self.object_category.value if self.object_category else None,
            "object_class": self.object_class,
            "dwell_seconds": round(self.dwell_seconds, 2),
            "grace_period_seconds": round(self.grace_period_seconds, 2),
            "threshold_seconds": round(self.threshold_seconds, 2),
            "threshold_exceeded_by": round(self.threshold_exceeded_by, 2),
            "stationary_ratio": round(self.stationarity.stationary_ratio, 3),
            "longest_stationary_streak_seconds": (
                round(self.stationarity.longest_stationary_streak_seconds, 2)
                if self.stationarity.longest_stationary_streak_seconds is not None
                else None
            ),
            "net_displacement_px": round(self.stationarity.net_displacement_px, 2),
            "current_speed_px": round(self.stationarity.current_speed_px, 2),
            "is_currently_stationary": self.stationarity.is_currently_stationary,
            "motion_summary": {
                "samples_analyzed": self.stationarity.samples_analyzed,
                "stationary_samples": self.stationarity.stationary_samples,
                "stationary_ratio": round(self.stationarity.stationary_ratio, 3),
                "longest_stationary_streak_samples": self.stationarity.longest_stationary_streak_samples,
                "longest_stationary_streak_seconds": (
                    round(self.stationarity.longest_stationary_streak_seconds, 2)
                    if self.stationarity.longest_stationary_streak_seconds is not None
                    else None
                ),
                "net_displacement_px": round(self.stationarity.net_displacement_px, 2),
                "current_speed_px": round(self.stationarity.current_speed_px, 2),
                "average_speed_px": round(self.stationarity.average_speed_px, 2),
                "max_speed_px": round(self.stationarity.max_speed_px, 2),
                "is_currently_stationary": self.stationarity.is_currently_stationary,
            },
            "reason": self.reason,
            "warnings": list(self.warnings),
        }
