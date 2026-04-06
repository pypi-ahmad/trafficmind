"""Typed schemas for lane occupancy and queue analytics."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.tracking.schemas import LineSegment, Point2D, PolygonZone
from services.vision.schemas import ObjectCategory


class QueueAnchorSource(StrEnum):
    NONE = "none"
    STOP_LINE = "stop_line"
    REFERENCE_POINT = "reference_point"


class CongestionLevel(StrEnum):
    FREE_FLOW = "free_flow"
    HEAVY = "heavy"
    QUEUED = "queued"
    CONGESTED = "congested"


class LaneAnalyticsTuning(BaseModel):
    """Configurable thresholds for one camera/lane analytics profile."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    window_seconds: float = Field(default=60.0, gt=0.0)
    stationarity_lookback_points: int = Field(default=8, ge=2)
    stationary_speed_px: float = Field(default=2.0, gt=0.0)
    min_stationary_ratio: float = Field(default=0.75, ge=0.0, le=1.0)
    queue_anchor_radius_px: float = Field(default=120.0, gt=0.0)
    max_queue_gap_px: float = Field(default=90.0, gt=0.0)
    min_queue_count: int = Field(default=2, ge=1)
    nominal_capacity_count: int | None = Field(default=None, ge=1)
    heavy_occupancy_ratio: float = Field(default=0.4, ge=0.0, le=1.0)
    congestion_occupancy_ratio: float = Field(default=0.65, ge=0.0, le=1.0)
    congestion_queue_duration_seconds: float = Field(default=15.0, ge=0.0)
    saturation_queue_count: int = Field(default=5, ge=1)
    included_categories: list[ObjectCategory] = Field(
        default_factory=lambda: [ObjectCategory.VEHICLE],
    )
    notes: str | None = None

    @model_validator(mode="after")
    def _validate_threshold_ordering(self) -> LaneAnalyticsTuning:
        if self.congestion_occupancy_ratio < self.heavy_occupancy_ratio:
            msg = "congestion_occupancy_ratio must be >= heavy_occupancy_ratio"
            raise ValueError(msg)
        if self.saturation_queue_count < self.min_queue_count:
            msg = "saturation_queue_count must be >= min_queue_count"
            raise ValueError(msg)
        return self


class LaneAnalyticsLaneConfig(LaneAnalyticsTuning):
    """Resolved analytics config for one lane."""

    lane_id: str
    lane_name: str
    lane_polygon: PolygonZone
    stop_line: LineSegment | None = None
    queue_reference_point: Point2D | None = None
    queue_reference_label: str | None = None


class QueuedTrack(BaseModel):
    """One queued track in the current lane snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    track_id: str
    class_name: str
    anchor_distance_px: float
    stationary_ratio: float
    current_speed_px: float


class LaneObservation(BaseModel):
    """One per-lane observation captured for a time window."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    observed_at: datetime
    active_track_count: int = 0
    occupied: bool = False
    queue_detected: bool = False
    queue_track_count: int = 0
    queue_extent_px: float = 0.0


class LaneOccupancyMetrics(BaseModel):
    """Current and windowed occupancy metrics for one lane."""

    model_config = ConfigDict(extra="forbid")

    active_track_count: int = 0
    active_track_ids: list[str] = Field(default_factory=list)
    occupied: bool = False
    occupancy_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    average_active_track_count: float = 0.0
    peak_active_track_count: int = 0
    utilization_ratio: float | None = Field(default=None, ge=0.0)
    window_seconds: float = 0.0


class LaneQueueMetrics(BaseModel):
    """Current and persistence-aware queue metrics for one lane."""

    model_config = ConfigDict(extra="forbid")

    anchor_source: QueueAnchorSource = QueueAnchorSource.NONE
    queue_detected: bool = False
    queue_track_count: int = 0
    queue_extent_px: float = 0.0
    queue_duration_seconds: float = 0.0
    average_queue_track_count: float = 0.0
    peak_queue_track_count: int = 0
    queued_track_ids: list[str] = Field(default_factory=list)
    queued_tracks: list[QueuedTrack] = Field(default_factory=list)


class LaneAnalytics(BaseModel):
    """Practical lane analytics output for dashboards and correlation."""

    model_config = ConfigDict(extra="forbid")

    lane_id: str
    lane_name: str
    observed_at: datetime
    congestion_level: CongestionLevel = CongestionLevel.FREE_FLOW
    occupancy: LaneOccupancyMetrics
    queue: LaneQueueMetrics
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def to_dashboard_dict(self) -> dict[str, Any]:
        return {
            "lane_id": self.lane_id,
            "lane_name": self.lane_name,
            "observed_at": self.observed_at.isoformat(),
            "congestion_level": self.congestion_level.value,
            "active_track_count": self.occupancy.active_track_count,
            "peak_active_track_count": self.occupancy.peak_active_track_count,
            "occupancy_ratio": self.occupancy.occupancy_ratio,
            "average_active_track_count": self.occupancy.average_active_track_count,
            "utilization_ratio": self.occupancy.utilization_ratio,
            "window_seconds": self.occupancy.window_seconds,
            "queue_anchor_source": self.queue.anchor_source.value,
            "queue_detected": self.queue.queue_detected,
            "queue_track_count": self.queue.queue_track_count,
            "average_queue_track_count": self.queue.average_queue_track_count,
            "peak_queue_track_count": self.queue.peak_queue_track_count,
            "queue_extent_px": self.queue.queue_extent_px,
            "queue_duration_seconds": self.queue.queue_duration_seconds,
            "assumptions": list(self.assumptions),
            "warnings": list(self.warnings),
        }

    def to_hotspot_dict(self) -> dict[str, Any]:
        return {
            "lane_id": self.lane_id,
            "lane_name": self.lane_name,
            "observed_at": self.observed_at.isoformat(),
            "congestion_level": self.congestion_level.value,
            "occupancy_ratio": self.occupancy.occupancy_ratio,
            "window_seconds": self.occupancy.window_seconds,
            "peak_active_track_count": self.occupancy.peak_active_track_count,
            "queue_anchor_source": self.queue.anchor_source.value,
            "average_queue_track_count": self.queue.average_queue_track_count,
            "peak_queue_track_count": self.queue.peak_queue_track_count,
            "queue_duration_seconds": self.queue.queue_duration_seconds,
        }

    def to_incident_dict(self) -> dict[str, Any]:
        return {
            "lane_id": self.lane_id,
            "lane_name": self.lane_name,
            "observed_at": self.observed_at.isoformat(),
            "queue_detected": self.queue.queue_detected,
            "queue_duration_seconds": self.queue.queue_duration_seconds,
            "queue_track_count": self.queue.queue_track_count,
            "queue_anchor_source": self.queue.anchor_source.value,
            "queue_extent_px": self.queue.queue_extent_px,
            "congestion_level": self.congestion_level.value,
        }
