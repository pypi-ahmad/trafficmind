"""Health and observability schemas.

All health signals are **derived** from data that already exists in
``CameraStream`` (DB) and ``JobState``/``JobMetrics`` (in-memory).
Nothing here invents counters that lack a real source.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

# ── Enumerations ────────────────────────────────────────────────────────────


class AlertSeverity(StrEnum):
    """Operational severity of a health alert."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class HealthStateBasis(StrEnum):
    """What real signal the current stream health state is based on."""

    ACTIVE_JOB = "active_job"
    RECENT_HEARTBEAT = "recent_heartbeat"
    NO_RUNTIME_SIGNAL = "no_runtime_signal"
    DISABLED = "disabled"


class HealthSignal(StrEnum):
    """Named health condition that can affect a stream or camera."""

    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"

    # Stream-level conditions
    STALE_STREAM = "stale_stream"
    LOW_FPS = "low_fps"
    HIGH_FRAME_DROP_RATE = "high_frame_drop_rate"
    HIGH_DECODE_FAILURE_RATE = "high_decode_failure_rate"
    RECONNECTING = "reconnecting"
    STREAM_ERROR = "stream_error"

    # Placeholders — wired when real sources exist
    OCR_FAILURE_RATE_HIGH = "ocr_failure_rate_high"
    DETECTOR_NO_OUTPUT = "detector_no_output"


# ── Thresholds (configurable) ──────────────────────────────────────────────


class HealthThresholds(BaseModel):
    """Tuneable thresholds for health signal evaluation.

    Defaults are conservative starting points.  Override via the
    ``HealthAssessor`` constructor.
    """

    model_config = ConfigDict(frozen=True)

    stale_heartbeat_seconds: float = Field(
        default=30.0,
        description="Seconds since last heartbeat before a stream is considered stale.",
    )
    low_fps_ratio: float = Field(
        default=0.5,
        description="If avg_fps < fps_hint * this ratio, signal LOW_FPS.",
    )
    high_drop_rate_percent: float = Field(
        default=20.0,
        description="Frame drop rate percentage to trigger HIGH_FRAME_DROP_RATE.",
    )
    high_decode_failure_rate_percent: float = Field(
        default=5.0,
        description="Frame decode failure rate percentage to trigger HIGH_DECODE_FAILURE_RATE.",
    )
    min_frames_for_rate: int = Field(
        default=10,
        description="Minimum frames_read before rate-based checks activate.",
    )
    detector_no_output_frames: int = Field(
        default=200,
        description="If frames_processed > this and detections_total == 0, flag DETECTOR_NO_OUTPUT.",
    )


# ── Alert ───────────────────────────────────────────────────────────────────


class HealthAlert(BaseModel):
    """A single health condition detected for a stream or camera."""

    model_config = ConfigDict(frozen=True)

    signal: HealthSignal
    severity: AlertSeverity
    message: str
    detail: dict[str, object] | None = None


# ── Metric snapshot ─────────────────────────────────────────────────────────


class JobMetricsSnapshot(BaseModel):
    """Operator-friendly projection of ``JobMetrics`` with computed rates."""

    model_config = ConfigDict(frozen=True)

    read_attempts: int = 0
    stream_read_failures: int = 0
    frames_processed: int = 0
    frames_dropped: int = 0
    frames_skipped_cadence: int = 0
    frames_failed: int = 0
    frames_read: int = 0
    drop_rate_percent: float = 0.0
    decode_failure_rate_percent: float = 0.0
    avg_inference_ms: float = 0.0
    processing_fps: float = 0.0
    last_successful_inference_at: datetime | None = None
    reconnect_count: int = 0


# ── Stream health ──────────────────────────────────────────────────────────


class StreamHealthReport(BaseModel):
    """Health assessment for a single ``CameraStream``."""

    stream_id: uuid.UUID
    stream_name: str
    camera_id: uuid.UUID
    source_type: str
    db_status: str
    is_enabled: bool
    is_online: bool
    state_basis: HealthStateBasis
    last_heartbeat_at: datetime | None = None
    last_heartbeat_age_seconds: float | None = None
    last_error: str | None = None
    alerts: list[HealthAlert] = Field(default_factory=list)
    active_job_id: uuid.UUID | None = None
    latest_job_id: uuid.UUID | None = None
    latest_job_status: str | None = None
    latest_job_error_message: str | None = None
    latest_job_started_at: datetime | None = None
    latest_job_stopped_at: datetime | None = None
    metrics: JobMetricsSnapshot | None = None


# ── Camera health ──────────────────────────────────────────────────────────


class CameraHealthReport(BaseModel):
    """Health assessment for a camera and all its streams."""

    camera_id: uuid.UUID
    camera_code: str
    camera_name: str
    camera_status: str
    overall_health: HealthSignal
    alerts: list[HealthAlert] = Field(default_factory=list)
    streams: list[StreamHealthReport] = Field(default_factory=list)


# ── Dashboard ──────────────────────────────────────────────────────────────


class HealthDashboard(BaseModel):
    """Aggregate observability summary for all cameras — dashboard-ready."""

    assessed_at: datetime
    total_cameras: int = 0
    cameras_online: int = 0
    cameras_offline: int = 0
    cameras_degraded: int = 0
    total_streams: int = 0
    streams_online: int = 0
    active_jobs: int = 0
    critical_alerts: int = 0
    warning_alerts: int = 0
    cameras: list[CameraHealthReport] = Field(default_factory=list)
