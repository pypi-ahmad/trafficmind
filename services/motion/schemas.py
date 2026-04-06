"""Typed schemas for speed estimation and motion analytics."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.tracking.schemas import CardinalDirection, MotionVector


class CalibrationMode(StrEnum):
    NONE = "none"
    SCALE_APPROXIMATION = "scale_approximation"
    PLANAR_HOMOGRAPHY = "planar_homography"


class EstimateQuality(StrEnum):
    ROUGH = "rough"
    APPROXIMATE = "approximate"
    CALIBRATED = "calibrated"


class ReliabilityBand(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SpeedUnit(StrEnum):
    PX_PER_FRAME = "px/frame"
    PX_PER_SECOND = "px/s"
    M_PER_S = "m/s"
    KM_PER_H = "km/h"
    MPH = "mph"


class TimeBasis(StrEnum):
    TIMESTAMP = "timestamp"
    FPS_HINT = "fps_hint"
    FRAME_ONLY = "frame_only"


class FlowDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    CROSSING = "crossing"
    UNKNOWN = "unknown"


class LaneRelativeDirection(StrEnum):
    WITH_FLOW = "with_flow"
    AGAINST_FLOW = "against_flow"
    CROSS_TRAFFIC = "cross_traffic"
    UNKNOWN = "unknown"


class Vector2D(BaseModel):
    """Reference vector used for scene semantics such as inbound or lane flow."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dx: float
    dy: float

    @property
    def magnitude(self) -> float:
        return (self.dx**2 + self.dy**2) ** 0.5


class ScaleApproximation(BaseModel):
    """Approximate linear scale used when full calibration is unavailable."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    meters_per_pixel: float = Field(gt=0.0)
    source_note: str | None = None


class HomographyCalibration(BaseModel):
    """Ground-plane mapping for calibrated distance estimation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    homography_matrix: list[list[float]] = Field(min_length=3, max_length=3)
    meters_per_world_unit: float = Field(default=1.0, gt=0.0)
    source_note: str | None = None

    @model_validator(mode="after")
    def _validate_shape(self) -> HomographyCalibration:
        if any(len(row) != 3 for row in self.homography_matrix):
            msg = "homography_matrix must be a 3x3 matrix"
            raise ValueError(msg)
        return self


class DirectionSemantics(BaseModel):
    """Optional scene-specific labels and reference vectors."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scene_direction_map: dict[str, str] = Field(default_factory=dict)
    inbound_vector: Vector2D | None = None
    lane_direction_vector: Vector2D | None = None
    lane_name: str | None = None


class MotionCalibrationProfile(BaseModel):
    """Typed calibration profile derived from camera calibration JSON."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: CalibrationMode = CalibrationMode.NONE
    scale: ScaleApproximation | None = None
    homography: HomographyCalibration | None = None
    direction: DirectionSemantics = Field(default_factory=DirectionSemantics)
    enforcement_validated: bool = False
    notes: str | None = None

    @model_validator(mode="after")
    def _validate_mode_payload(self) -> MotionCalibrationProfile:
        if self.mode is CalibrationMode.SCALE_APPROXIMATION and self.scale is None:
            msg = "scale calibration data is required when mode=scale_approximation"
            raise ValueError(msg)
        if self.mode is CalibrationMode.PLANAR_HOMOGRAPHY and self.homography is None:
            msg = "homography calibration data is required when mode=planar_homography"
            raise ValueError(msg)
        return self

    @property
    def calibration_aware(self) -> bool:
        return self.mode is not CalibrationMode.NONE


class MotionAnalytics(BaseModel):
    """Calibration-aware motion estimate derived from one tracked object."""

    model_config = ConfigDict(extra="forbid")

    track_id: str
    estimated_speed: float = 0.0
    speed_unit: SpeedUnit = SpeedUnit.PX_PER_SECOND
    estimate_quality: EstimateQuality = EstimateQuality.ROUGH
    calibration_mode: CalibrationMode = CalibrationMode.NONE
    time_basis: TimeBasis = TimeBasis.FRAME_ONLY
    reliability: ReliabilityBand = ReliabilityBand.LOW
    reliability_score: float = Field(default=0.0, ge=0.0, le=1.0)
    enforcement_grade: bool = False
    heading: MotionVector | None = None
    cardinal_direction: CardinalDirection = CardinalDirection.STATIONARY
    scene_direction_label: str | None = None
    inbound_outbound: FlowDirection = FlowDirection.UNKNOWN
    lane_relative_direction: LaneRelativeDirection = LaneRelativeDirection.UNKNOWN
    distance_px: float = 0.0
    distance_m: float | None = None
    elapsed_seconds: float | None = None
    frame_delta: int | None = None
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "estimated_speed": self.estimated_speed,
            "speed_unit": self.speed_unit.value,
            "estimate_quality": self.estimate_quality.value,
            "calibration_mode": self.calibration_mode.value,
            "time_basis": self.time_basis.value,
            "reliability": self.reliability.value,
            "reliability_score": self.reliability_score,
            "enforcement_grade": self.enforcement_grade,
            "cardinal_direction": self.cardinal_direction.value,
            "scene_direction_label": self.scene_direction_label,
            "inbound_outbound": self.inbound_outbound.value,
            "lane_relative_direction": self.lane_relative_direction.value,
            "distance_px": self.distance_px,
            "distance_m": self.distance_m,
            "elapsed_seconds": self.elapsed_seconds,
            "frame_delta": self.frame_delta,
            "warnings": list(self.warnings),
        }


class OverspeedCandidate(BaseModel):
    """Analytics / enforcement-support output for overspeed screening."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    is_candidate: bool = False
    estimated_speed: float | None = None
    estimated_speed_unit: SpeedUnit | None = None
    speed_limit: float | None = None
    speed_limit_unit: SpeedUnit | None = None
    excess_speed: float | None = None
    reliability: ReliabilityBand = ReliabilityBand.LOW
    enforcement_grade: bool = False
    requires_manual_review: bool = True
    reason: str


class WrongWayCandidate(BaseModel):
    """Analytics / enforcement-support output for wrong-way screening."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    is_candidate: bool = False
    lane_relative_direction: LaneRelativeDirection = LaneRelativeDirection.UNKNOWN
    scene_direction_label: str | None = None
    reliability: ReliabilityBand = ReliabilityBand.LOW
    requires_manual_review: bool = True
    reason: str