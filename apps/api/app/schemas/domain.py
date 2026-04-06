"""Pydantic schemas for the first database-backed TrafficMind entities."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from apps.api.app.db.enums import (
    CameraStatus,
    DetectionEventStatus,
    DetectionEventType,
    ModelRegistryTaskType,
    PlateReadStatus,
    SourceType,
    StreamKind,
    StreamStatus,
    ViolationSeverity,
    ViolationStatus,
    ViolationType,
    WatchlistEntryStatus,
    WatchlistReason,
    WorkflowStatus,
    WorkflowType,
    ZoneStatus,
    ZoneType,
)


class ORMSchema(BaseModel):
    """Base schema with ORM compatibility enabled."""

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Junction
# ---------------------------------------------------------------------------


class JunctionBase(ORMSchema):
    name: str
    description: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class JunctionCreate(JunctionBase):
    pass


class JunctionRead(JunctionBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class JunctionDetail(JunctionRead):
    cameras: list["CameraRead"] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------


class CameraBase(ORMSchema):
    camera_code: str
    name: str
    location_name: str
    approach: str | None = None
    junction_id: uuid.UUID | None = None
    timezone: str = "UTC"
    status: CameraStatus = CameraStatus.PROVISIONING
    latitude: float | None = None
    longitude: float | None = None
    notes: str | None = None
    calibration_config: dict[str, Any] = Field(default_factory=dict)
    calibration_updated_at: datetime | None = None


class CameraCreate(CameraBase):
    pass


class CameraRead(CameraBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    stream_count: int = 0


class CameraStreamBase(ORMSchema):
    name: str
    stream_kind: StreamKind = StreamKind.PRIMARY
    source_type: SourceType
    source_uri: str
    source_config: dict[str, Any] = Field(default_factory=dict)
    status: StreamStatus = StreamStatus.OFFLINE
    is_enabled: bool = True
    resolution_width: int | None = None
    resolution_height: int | None = None
    fps_hint: float | None = None
    last_heartbeat_at: datetime | None = None
    last_error: str | None = None


class CameraStreamCreate(CameraStreamBase):
    camera_id: uuid.UUID


class CameraStreamRead(CameraStreamBase):
    id: uuid.UUID
    camera_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class ZoneBase(ORMSchema):
    name: str
    zone_type: ZoneType
    status: ZoneStatus = ZoneStatus.DRAFT
    geometry: dict[str, Any]
    rules_config: dict[str, Any] = Field(default_factory=dict)
    sort_order: int = 0


class ZoneCreate(ZoneBase):
    camera_id: uuid.UUID


class ZoneRead(ZoneBase):
    id: uuid.UUID
    camera_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class DetectionEventBase(ORMSchema):
    detector_registry_id: uuid.UUID | None = None
    tracker_registry_id: uuid.UUID | None = None
    event_type: DetectionEventType = DetectionEventType.DETECTION
    status: DetectionEventStatus = DetectionEventStatus.NEW
    occurred_at: datetime
    frame_index: int | None = None
    track_id: str | None = None
    object_class: str
    confidence: float
    bbox: dict[str, Any]
    event_payload: dict[str, Any] = Field(default_factory=dict)
    image_uri: str | None = None
    video_uri: str | None = None


class DetectionEventCreate(DetectionEventBase):
    camera_id: uuid.UUID
    stream_id: uuid.UUID | None = None
    zone_id: uuid.UUID | None = None


class DetectionEventRead(DetectionEventBase):
    id: uuid.UUID
    camera_id: uuid.UUID
    stream_id: uuid.UUID | None = None
    zone_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class PlateReadBase(ORMSchema):
    ocr_registry_id: uuid.UUID | None = None
    status: PlateReadStatus = PlateReadStatus.OBSERVED
    occurred_at: datetime
    plate_text: str
    normalized_plate_text: str
    confidence: float
    country_code: str | None = None
    region_code: str | None = None
    bbox: dict[str, Any]
    crop_image_uri: str | None = None
    source_frame_uri: str | None = None
    ocr_metadata: dict[str, Any] = Field(default_factory=dict)


class PlateReadCreate(PlateReadBase):
    camera_id: uuid.UUID
    stream_id: uuid.UUID | None = None
    detection_event_id: uuid.UUID | None = None


class PlateReadRead(PlateReadBase):
    id: uuid.UUID
    camera_id: uuid.UUID
    stream_id: uuid.UUID | None = None
    detection_event_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class ViolationEventBase(ORMSchema):
    rules_registry_id: uuid.UUID | None = None
    violation_type: ViolationType
    severity: ViolationSeverity = ViolationSeverity.MEDIUM
    status: ViolationStatus = ViolationStatus.OPEN
    occurred_at: datetime
    summary: str | None = None
    evidence_image_uri: str | None = None
    evidence_video_uri: str | None = None
    assigned_to: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None
    rule_metadata: dict[str, Any] = Field(default_factory=dict)


class ViolationEventCreate(ViolationEventBase):
    camera_id: uuid.UUID
    stream_id: uuid.UUID | None = None
    zone_id: uuid.UUID | None = None
    detection_event_id: uuid.UUID | None = None
    plate_read_id: uuid.UUID | None = None


class ViolationEventRead(ViolationEventBase):
    id: uuid.UUID
    camera_id: uuid.UUID
    stream_id: uuid.UUID | None = None
    zone_id: uuid.UUID | None = None
    detection_event_id: uuid.UUID | None = None
    plate_read_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class ViolationReviewActionRequest(ORMSchema):
    actor: str = Field(min_length=1, max_length=120)
    action: Literal["approve", "reject"]
    note: str | None = None


class WorkflowRunBase(ORMSchema):
    workflow_type: WorkflowType
    status: WorkflowStatus = WorkflowStatus.QUEUED
    priority: int = 5
    requested_by: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    input_payload: dict[str, Any] = Field(default_factory=dict)
    result_payload: dict[str, Any] | None = None
    error_message: str | None = None


class WorkflowRunCreate(WorkflowRunBase):
    camera_id: uuid.UUID | None = None
    detection_event_id: uuid.UUID | None = None
    violation_event_id: uuid.UUID | None = None


class WorkflowRunRead(WorkflowRunBase):
    id: uuid.UUID
    camera_id: uuid.UUID | None = None
    detection_event_id: uuid.UUID | None = None
    violation_event_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class CameraDetail(CameraRead):
    streams: list[CameraStreamRead] = Field(default_factory=list)
    zones: list[ZoneRead] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Watchlist schemas
# ---------------------------------------------------------------------------


class WatchlistEntryBase(ORMSchema):
    normalized_plate_text: str
    plate_text_display: str
    reason: WatchlistReason
    status: WatchlistEntryStatus = WatchlistEntryStatus.ACTIVE
    description: str | None = None
    added_by: str | None = None
    expires_at: datetime | None = None
    alert_enabled: bool = True
    country_code: str | None = None
    notes: str | None = None


class WatchlistEntryCreate(ORMSchema):
    plate_text: str = Field(max_length=32, description="Raw plate text — will be normalized server-side")
    reason: WatchlistReason
    description: str | None = None
    added_by: str | None = None
    expires_at: datetime | None = None
    alert_enabled: bool = True
    country_code: str | None = None
    notes: str | None = None


class WatchlistEntryUpdate(ORMSchema):
    plate_text: str | None = Field(default=None, max_length=32)
    country_code: str | None = Field(default=None, max_length=8)
    reason: WatchlistReason | None = None
    status: WatchlistEntryStatus | None = None
    description: str | None = None
    expires_at: datetime | None = None
    alert_enabled: bool | None = None
    notes: str | None = None


class WatchlistEntryRead(WatchlistEntryBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Plate search schemas
# ---------------------------------------------------------------------------


class PlateSearchParams(ORMSchema):
    plate_text: str | None = Field(None, description="Exact or partial plate text to search")
    partial: bool = Field(False, description="Use contains-style matching instead of exact matching")
    normalized: bool = Field(True, description="Whether to normalize the query before search")
    camera_id: uuid.UUID | None = None
    camera_query: str | None = Field(None, description="Camera code, name, or location filter")
    stream_id: uuid.UUID | None = None
    detection_event_id: uuid.UUID | None = None
    track_id: str | None = Field(None, max_length=64)
    country_code: str | None = Field(None, max_length=8)
    normalization_country_code: str | None = Field(None, max_length=8)
    region_code: str | None = Field(None, max_length=16)
    status: PlateReadStatus | None = None
    occurred_after: datetime | None = None
    occurred_before: datetime | None = None
    has_evidence: bool | None = None
    min_confidence: float | None = Field(None, ge=0.0, le=1.0)
    limit: int = Field(50, ge=1, le=500)
    offset: int = Field(0, ge=0)


class PlateSearchResult(ORMSchema):
    items: list[PlateReadRead] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0


class DetectionEventSearchParams(ORMSchema):
    camera_id: uuid.UUID | None = None
    camera_query: str | None = Field(None, description="Camera code, name, or location filter")
    stream_id: uuid.UUID | None = None
    zone_id: uuid.UUID | None = None
    event_type: DetectionEventType | None = None
    status: DetectionEventStatus | None = None
    occurred_after: datetime | None = None
    occurred_before: datetime | None = None
    object_class: str | None = Field(None, max_length=64)
    track_id: str | None = Field(None, max_length=64)
    zone_type: ZoneType | None = None
    has_evidence: bool | None = None
    min_confidence: float | None = Field(None, ge=0.0, le=1.0)
    limit: int = Field(50, ge=1, le=500)
    offset: int = Field(0, ge=0)


class DetectionEventSearchResult(ORMSchema):
    items: list[DetectionEventRead] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0


class ViolationSearchParams(ORMSchema):
    camera_id: uuid.UUID | None = None
    camera_query: str | None = Field(None, description="Camera code, name, or location filter")
    stream_id: uuid.UUID | None = None
    zone_id: uuid.UUID | None = None
    detection_event_id: uuid.UUID | None = None
    plate_read_id: uuid.UUID | None = None
    violation_type: ViolationType | None = None
    status: ViolationStatus | None = None
    occurred_after: datetime | None = None
    occurred_before: datetime | None = None
    object_class: str | None = Field(None, max_length=64)
    plate_text: str | None = Field(None, description="Exact or partial related plate text")
    partial_plate: bool = False
    normalization_country_code: str | None = Field(None, max_length=8)
    assigned_to: str | None = Field(None, max_length=120)
    reviewed_by: str | None = Field(None, max_length=120)
    zone_type: ZoneType | None = None
    has_evidence: bool | None = None
    limit: int = Field(50, ge=1, le=500)
    offset: int = Field(0, ge=0)


class ViolationSearchResult(ORMSchema):
    items: list[ViolationEventRead] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0


class CameraEventCountRow(ORMSchema):
    camera_id: str
    camera_name: str
    location_name: str
    event_count: int


class CameraViolationCountRow(ORMSchema):
    camera_id: str
    camera_name: str
    location_name: str
    violation_count: int
    severity_counts: dict[str, int] = Field(default_factory=dict)


class FeedSummaryResponse(ORMSchema):
    event_counts: list[CameraEventCountRow] = Field(default_factory=list)
    violation_counts: list[CameraViolationCountRow] = Field(default_factory=list)
    total_events: int = 0
    total_violations: int = 0


class EventSummaryTotals(ORMSchema):
    """Flat aggregate counts for detection events."""

    total: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    by_type: dict[str, int] = Field(default_factory=dict)


class ViolationSummaryTotals(ORMSchema):
    """Flat aggregate counts for violation events."""

    total: int = 0
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_type: dict[str, int] = Field(default_factory=dict)
    by_status: dict[str, int] = Field(default_factory=dict)


class WatchlistMatchResult(ORMSchema):
    plate_read: PlateReadRead
    watchlist_entry: WatchlistEntryRead


class WatchlistEntryListResult(ORMSchema):
    items: list[WatchlistEntryRead] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0


class WatchlistCheckResult(ORMSchema):
    matched: bool = False
    normalized_plate_text: str = ""
    entries: list[WatchlistEntryRead] = Field(default_factory=list)