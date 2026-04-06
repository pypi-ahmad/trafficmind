"""Typed schemas for stream-processing jobs."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.shared_types.enums import SourceKind  # noqa: F401 — re-exported


class JobStatus(StrEnum):
    """Lifecycle states for a stream-processing job."""

    PENDING = "pending"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
    COMPLETED = "completed"


# SourceKind is canonical in packages.shared_types.enums — imported above.


# ── Valid transitions ───────────────────────────────────────────────────────

_VALID_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.PENDING: frozenset({JobStatus.STARTING, JobStatus.STOPPED}),
    JobStatus.STARTING: frozenset({JobStatus.RUNNING, JobStatus.FAILED, JobStatus.STOPPED}),
    JobStatus.RUNNING: frozenset({JobStatus.PAUSED, JobStatus.STOPPING, JobStatus.FAILED, JobStatus.COMPLETED}),
    JobStatus.PAUSED: frozenset({JobStatus.RUNNING, JobStatus.STOPPING, JobStatus.STOPPED}),
    JobStatus.STOPPING: frozenset({JobStatus.STOPPED, JobStatus.FAILED}),
    JobStatus.STOPPED: frozenset(),
    JobStatus.FAILED: frozenset(),
    JobStatus.COMPLETED: frozenset(),
}


def is_valid_transition(current: JobStatus, target: JobStatus) -> bool:
    return target in _VALID_TRANSITIONS.get(current, frozenset())


def is_terminal(status: JobStatus) -> bool:
    return status in {JobStatus.STOPPED, JobStatus.FAILED, JobStatus.COMPLETED}


# ── Job specification ───────────────────────────────────────────────────────


class PipelineFlags(BaseModel):
    """Which pipeline stages to enable for this job."""

    model_config = ConfigDict(frozen=True)

    detection: bool = True
    tracking: bool = True
    signals: bool = True
    ocr: bool = False
    rules: bool = True


class JobSpec(BaseModel):
    """Immutable specification for a stream-processing job.

    Created once when a job is requested.  Not modified during execution.
    """

    model_config = ConfigDict(frozen=True)

    job_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    stream_id: uuid.UUID | None = Field(
        default=None,
        description="CameraStream id from the platform DB, if applicable.",
    )
    camera_id: uuid.UUID | None = None
    source_kind: SourceKind
    source_uri: str
    source_config: dict[str, Any] = Field(default_factory=dict)
    frame_step: int = Field(default=1, ge=1)
    max_processing_fps: float | None = Field(default=None, gt=0.0)
    max_frames: int | None = Field(
        default=None,
        description="Stop after processing this many frames.  None = run until stopped or source ends.",
    )
    pipeline: PipelineFlags = Field(default_factory=PipelineFlags)
    requested_by: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def source_id(self) -> str:
        return str(self.stream_id) if self.stream_id is not None else self.source_uri


# ── Runtime metrics ─────────────────────────────────────────────────────────


class JobMetrics(BaseModel):
    """Mutable counters and timing snapshots for a running job."""

    frames_read: int = 0
    frames_processed: int = 0
    frames_skipped: int = 0
    frames_skipped_cadence: int = 0
    frames_dropped_backpressure: int = 0
    frames_failed: int = 0
    stream_read_failures: int = 0
    detections_total: int = 0
    tracks_active: int = 0
    violations_total: int = 0
    events_emitted: int = 0
    avg_inference_ms: float = 0.0
    avg_fps: float = 0.0
    last_processing_latency_ms: float = 0.0
    last_frame_at: datetime | None = None
    last_successful_inference_at: datetime | None = None
    reconnect_count: int = 0


# ── Job state ───────────────────────────────────────────────────────────────


class JobState(BaseModel):
    """Full observable state for a single stream-processing job."""

    spec: JobSpec
    status: JobStatus = JobStatus.PENDING
    metrics: JobMetrics = Field(default_factory=JobMetrics)
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    error_message: str | None = None

    @property
    def job_id(self) -> uuid.UUID:
        return self.spec.job_id

    @property
    def is_active(self) -> bool:
        return self.status in {JobStatus.PENDING, JobStatus.STARTING, JobStatus.RUNNING, JobStatus.PAUSED}


# ── API request / response schemas ─────────────────────────────────────────


class StartJobRequest(BaseModel):
    """API request to start a stream-processing job."""

    model_config = ConfigDict(extra="forbid")

    stream_id: uuid.UUID | None = None
    source_kind: SourceKind | None = None
    source_uri: str | None = None
    source_config: dict[str, Any] = Field(default_factory=dict)
    frame_step: int = Field(default=1, ge=1)
    max_processing_fps: float | None = Field(default=None, gt=0.0)
    max_frames: int | None = None
    pipeline: PipelineFlags = Field(default_factory=PipelineFlags)
    requested_by: str | None = None

    @model_validator(mode="after")
    def validate_source_selector(self) -> StartJobRequest:
        has_stream_ref = self.stream_id is not None
        has_direct_source = self.source_kind is not None or self.source_uri is not None or bool(self.source_config)

        if has_stream_ref and has_direct_source:
            msg = "Provide either stream_id or direct source fields, not both."
            raise ValueError(msg)

        if not has_stream_ref and (self.source_kind is None or self.source_uri is None):
            msg = "Direct job starts require both source_kind and source_uri."
            raise ValueError(msg)

        return self


class JobResponse(BaseModel):
    """API response for a single job."""

    job_id: uuid.UUID
    stream_id: uuid.UUID | None
    camera_id: uuid.UUID | None
    source_kind: SourceKind
    source_uri: str
    frame_step: int
    max_processing_fps: float | None
    status: JobStatus
    metrics: JobMetrics
    started_at: datetime | None
    stopped_at: datetime | None
    last_heartbeat_at: datetime | None
    error_message: str | None
    created_at: datetime
    pipeline: PipelineFlags


class JobListResponse(BaseModel):
    items: list[JobResponse]
    total: int
    active: int


def job_state_to_response(state: JobState) -> JobResponse:
    return JobResponse(
        job_id=state.spec.job_id,
        stream_id=state.spec.stream_id,
        camera_id=state.spec.camera_id,
        source_kind=state.spec.source_kind,
        source_uri=state.spec.source_uri,
        frame_step=state.spec.frame_step,
        max_processing_fps=state.spec.max_processing_fps,
        status=state.status,
        metrics=state.metrics,
        started_at=state.started_at,
        stopped_at=state.stopped_at,
        last_heartbeat_at=state.last_heartbeat_at,
        error_message=state.error_message,
        created_at=state.spec.created_at,
        pipeline=state.spec.pipeline,
    )
