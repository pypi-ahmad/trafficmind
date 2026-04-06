"""TrafficMind database models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from apps.api.app.db.enums import (
    AlertAuditEventType,
    AlertDeliveryState,
    AlertRoutingChannel,
    CameraStatus,
    CaseExportAuditEventType,
    CaseExportFormat,
    CaseExportStatus,
    CaseSubjectKind,
    DetectionEventStatus,
    DetectionEventType,
    EvidenceSubjectKind,
    ModelRegistryTaskType,
    OperationalAlertSeverity,
    OperationalAlertSourceKind,
    OperationalAlertStatus,
    PlateReadStatus,
    ReIdMatchStatus,
    ReIdSubjectType,
    SourceType,
    StreamKind,
    StreamStatus,
    WatchlistAlertStatus,
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


def enum_type(enum_cls: type, name: str) -> SAEnum:
    """Return a portable SQLAlchemy enum column type."""

    return SAEnum(enum_cls, name=name, native_enum=False, validate_strings=True)


class Camera(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Physical traffic camera device managed by the platform."""

    __tablename__ = "cameras"
    __table_args__ = (
        Index("ix_cameras_status_created_at", "status", "created_at"),
        Index("ix_cameras_location_name", "location_name"),
    )

    camera_code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    location_name: Mapped[str] = mapped_column(String(160), nullable=False)
    approach: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC", server_default="UTC")
    status: Mapped[CameraStatus] = mapped_column(
        enum_type(CameraStatus, "camera_status"),
        nullable=False,
        default=CameraStatus.PROVISIONING,
        server_default=CameraStatus.PROVISIONING.value,
    )
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    calibration_config: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )
    calibration_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    streams: Mapped[list["CameraStream"]] = relationship(
        back_populates="camera",
        cascade="all, delete-orphan",
    )

    @property
    def stream_count(self) -> int:
        """Number of streams attached to this camera (requires eager load)."""
        loaded = self.__dict__.get("streams")
        return len(loaded) if loaded is not None else 0

    zones: Mapped[list["Zone"]] = relationship(
        back_populates="camera",
        cascade="all, delete-orphan",
    )
    detection_events: Mapped[list["DetectionEvent"]] = relationship(back_populates="camera")
    evidence_manifests: Mapped[list["EvidenceManifest"]] = relationship(back_populates="camera")
    violation_events: Mapped[list["ViolationEvent"]] = relationship(back_populates="camera")
    plate_reads: Mapped[list["PlateRead"]] = relationship(back_populates="camera")
    watchlist_alerts: Mapped[list["WatchlistAlert"]] = relationship(back_populates="camera")
    workflow_runs: Mapped[list["WorkflowRun"]] = relationship(back_populates="camera")
    operational_alerts: Mapped[list["OperationalAlert"]] = relationship(back_populates="camera")
    reid_sightings: Mapped[list["ReIdSighting"]] = relationship(back_populates="camera")


class CameraStream(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Concrete ingest stream attached to a camera."""

    __tablename__ = "camera_streams"
    __table_args__ = (
        UniqueConstraint("camera_id", "name"),
        Index("ix_camera_streams_status_enabled", "status", "is_enabled"),
        Index("ix_camera_streams_camera_source_type", "camera_id", "source_type"),
    )

    camera_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cameras.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    stream_kind: Mapped[StreamKind] = mapped_column(
        enum_type(StreamKind, "stream_kind"),
        nullable=False,
        default=StreamKind.PRIMARY,
        server_default=StreamKind.PRIMARY.value,
    )
    source_type: Mapped[SourceType] = mapped_column(
        enum_type(SourceType, "source_type"),
        nullable=False,
    )
    source_uri: Mapped[str] = mapped_column(Text, nullable=False)
    source_config: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )
    status: Mapped[StreamStatus] = mapped_column(
        enum_type(StreamStatus, "stream_status"),
        nullable=False,
        default=StreamStatus.OFFLINE,
        server_default=StreamStatus.OFFLINE.value,
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    resolution_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolution_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fps_hint: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    camera: Mapped[Camera] = relationship(back_populates="streams")
    detection_events: Mapped[list["DetectionEvent"]] = relationship(back_populates="stream")
    evidence_manifests: Mapped[list["EvidenceManifest"]] = relationship(back_populates="stream")
    violation_events: Mapped[list["ViolationEvent"]] = relationship(back_populates="stream")
    plate_reads: Mapped[list["PlateRead"]] = relationship(back_populates="stream")
    operational_alerts: Mapped[list["OperationalAlert"]] = relationship(back_populates="stream")


class Zone(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Zone or line definition for rule evaluation on a camera feed."""

    __tablename__ = "zones"
    __table_args__ = (
        UniqueConstraint("camera_id", "name"),
        Index("ix_zones_camera_status_zone_type", "camera_id", "status", "zone_type"),
    )

    camera_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cameras.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    zone_type: Mapped[ZoneType] = mapped_column(
        enum_type(ZoneType, "zone_type"),
        nullable=False,
    )
    status: Mapped[ZoneStatus] = mapped_column(
        enum_type(ZoneStatus, "zone_status"),
        nullable=False,
        default=ZoneStatus.DRAFT,
        server_default=ZoneStatus.DRAFT.value,
    )
    geometry: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    rules_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    camera: Mapped[Camera] = relationship(back_populates="zones")
    detection_events: Mapped[list["DetectionEvent"]] = relationship(back_populates="zone")
    evidence_manifests: Mapped[list["EvidenceManifest"]] = relationship(back_populates="zone")
    violation_events: Mapped[list["ViolationEvent"]] = relationship(back_populates="zone")


class ModelRegistryEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable registry row describing one model or configuration bundle."""

    __tablename__ = "model_registry_entries"
    __table_args__ = (
        UniqueConstraint("config_hash", name="uq_model_registry_entries_config_hash"),
        Index("ix_model_registry_entries_task_type_active", "task_type", "is_active"),
        Index("ix_model_registry_entries_family_version", "model_family", "version_name"),
    )

    task_type: Mapped[ModelRegistryTaskType] = mapped_column(
        enum_type(ModelRegistryTaskType, "model_registry_task_type"),
        nullable=False,
    )
    model_family: Mapped[str] = mapped_column(String(120), nullable=False)
    version_name: Mapped[str] = mapped_column(String(160), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    config_bundle: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    entry_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )

    detection_events_as_detector: Mapped[list["DetectionEvent"]] = relationship(
        back_populates="detector_registry",
        foreign_keys="DetectionEvent.detector_registry_id",
    )
    detection_events_as_tracker: Mapped[list["DetectionEvent"]] = relationship(
        back_populates="tracker_registry",
        foreign_keys="DetectionEvent.tracker_registry_id",
    )
    plate_reads_as_ocr: Mapped[list["PlateRead"]] = relationship(
        back_populates="ocr_registry",
        foreign_keys="PlateRead.ocr_registry_id",
    )
    violation_events_as_rules: Mapped[list["ViolationEvent"]] = relationship(
        back_populates="rules_registry",
        foreign_keys="ViolationEvent.rules_registry_id",
    )
    evidence_manifests: Mapped[list["EvidenceManifest"]] = relationship(
        back_populates="evidence_registry",
        foreign_keys="EvidenceManifest.evidence_registry_id",
    )


class DetectionEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Stored detection or scene event emitted by the deterministic pipeline."""

    __tablename__ = "detection_events"
    __table_args__ = (
        Index("ix_detection_events_camera_occurred_at", "camera_id", "occurred_at"),
        Index("ix_detection_events_status_occurred_at", "status", "occurred_at"),
        Index("ix_detection_events_object_class_occurred_at", "object_class", "occurred_at"),
        Index("ix_detection_events_track_id", "track_id"),
        Index("ix_detection_events_detector_registry_id", "detector_registry_id"),
        Index("ix_detection_events_tracker_registry_id", "tracker_registry_id"),
    )

    camera_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cameras.id", ondelete="RESTRICT"),
        nullable=False,
    )
    stream_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("camera_streams.id", ondelete="SET NULL"),
        nullable=True,
    )
    zone_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("zones.id", ondelete="SET NULL"),
        nullable=True,
    )
    detector_registry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("model_registry_entries.id", ondelete="SET NULL"),
        nullable=True,
    )
    tracker_registry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("model_registry_entries.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[DetectionEventType] = mapped_column(
        enum_type(DetectionEventType, "detection_event_type"),
        nullable=False,
        default=DetectionEventType.DETECTION,
        server_default=DetectionEventType.DETECTION.value,
    )
    status: Mapped[DetectionEventStatus] = mapped_column(
        enum_type(DetectionEventStatus, "detection_event_status"),
        nullable=False,
        default=DetectionEventStatus.NEW,
        server_default=DetectionEventStatus.NEW.value,
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    frame_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    track_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    object_class: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    bbox: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    event_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    image_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_uri: Mapped[str | None] = mapped_column(Text, nullable=True)

    camera: Mapped[Camera] = relationship(back_populates="detection_events")
    stream: Mapped[CameraStream | None] = relationship(back_populates="detection_events")
    zone: Mapped[Zone | None] = relationship(back_populates="detection_events")
    detector_registry: Mapped[ModelRegistryEntry | None] = relationship(
        back_populates="detection_events_as_detector",
        foreign_keys=[detector_registry_id],
    )
    tracker_registry: Mapped[ModelRegistryEntry | None] = relationship(
        back_populates="detection_events_as_tracker",
        foreign_keys=[tracker_registry_id],
    )
    evidence_manifests: Mapped[list["EvidenceManifest"]] = relationship(back_populates="detection_event")
    plate_reads: Mapped[list["PlateRead"]] = relationship(back_populates="detection_event")
    reid_sightings: Mapped[list["ReIdSighting"]] = relationship(back_populates="detection_event")
    violation_events: Mapped[list["ViolationEvent"]] = relationship(back_populates="detection_event")
    workflow_runs: Mapped[list["WorkflowRun"]] = relationship(back_populates="detection_event")
    operational_alerts: Mapped[list["OperationalAlert"]] = relationship(back_populates="detection_event")


class PlateRead(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """OCR plate read attached to a detection event."""

    __tablename__ = "plate_reads"
    __table_args__ = (
        Index("ix_plate_reads_camera_occurred_at", "camera_id", "occurred_at"),
        Index("ix_plate_reads_plate_text_occurred_at", "plate_text", "occurred_at"),
        Index("ix_plate_reads_status_occurred_at", "status", "occurred_at"),
        Index("ix_plate_reads_normalized_plate_text_occurred_at", "normalized_plate_text", "occurred_at"),
        Index("ix_plate_reads_ocr_registry_id", "ocr_registry_id"),
    )

    camera_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cameras.id", ondelete="RESTRICT"),
        nullable=False,
    )
    stream_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("camera_streams.id", ondelete="SET NULL"),
        nullable=True,
    )
    detection_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("detection_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    ocr_registry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("model_registry_entries.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[PlateReadStatus] = mapped_column(
        enum_type(PlateReadStatus, "plate_read_status"),
        nullable=False,
        default=PlateReadStatus.OBSERVED,
        server_default=PlateReadStatus.OBSERVED.value,
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    plate_text: Mapped[str] = mapped_column(String(32), nullable=False)
    normalized_plate_text: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    region_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    bbox: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    crop_image_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_frame_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )

    camera: Mapped[Camera] = relationship(back_populates="plate_reads")
    stream: Mapped[CameraStream | None] = relationship(back_populates="plate_reads")
    detection_event: Mapped[DetectionEvent | None] = relationship(back_populates="plate_reads")
    ocr_registry: Mapped[ModelRegistryEntry | None] = relationship(
        back_populates="plate_reads_as_ocr",
        foreign_keys=[ocr_registry_id],
    )
    evidence_manifests: Mapped[list["EvidenceManifest"]] = relationship(back_populates="plate_read")
    watchlist_alerts: Mapped[list["WatchlistAlert"]] = relationship(back_populates="plate_read")
    violation_events: Mapped[list["ViolationEvent"]] = relationship(back_populates="plate_read")


class ViolationEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Reviewable violation emitted by deterministic rules."""

    __tablename__ = "violation_events"
    __table_args__ = (
        Index("ix_violation_events_camera_occurred_at", "camera_id", "occurred_at"),
        Index(
            "ix_violation_events_status_assigned_to_occurred_at",
            "status",
            "assigned_to",
            "occurred_at",
        ),
        Index("ix_violation_events_status_occurred_at", "status", "occurred_at"),
        Index("ix_violation_events_violation_type_occurred_at", "violation_type", "occurred_at"),
        Index("ix_violation_events_plate_read_id", "plate_read_id"),
        Index("ix_violation_events_rules_registry_id", "rules_registry_id"),
    )

    camera_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cameras.id", ondelete="RESTRICT"),
        nullable=False,
    )
    stream_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("camera_streams.id", ondelete="SET NULL"),
        nullable=True,
    )
    zone_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("zones.id", ondelete="SET NULL"),
        nullable=True,
    )
    detection_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("detection_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    plate_read_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("plate_reads.id", ondelete="SET NULL"),
        nullable=True,
    )
    rules_registry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("model_registry_entries.id", ondelete="SET NULL"),
        nullable=True,
    )
    violation_type: Mapped[ViolationType] = mapped_column(
        enum_type(ViolationType, "violation_type"),
        nullable=False,
    )
    severity: Mapped[ViolationSeverity] = mapped_column(
        enum_type(ViolationSeverity, "violation_severity"),
        nullable=False,
        default=ViolationSeverity.MEDIUM,
        server_default=ViolationSeverity.MEDIUM.value,
    )
    status: Mapped[ViolationStatus] = mapped_column(
        enum_type(ViolationStatus, "violation_status"),
        nullable=False,
        default=ViolationStatus.OPEN,
        server_default=ViolationStatus.OPEN.value,
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_image_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_video_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_to: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    rule_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )

    camera: Mapped[Camera] = relationship(back_populates="violation_events")
    stream: Mapped[CameraStream | None] = relationship(back_populates="violation_events")
    zone: Mapped[Zone | None] = relationship(back_populates="violation_events")
    detection_event: Mapped[DetectionEvent | None] = relationship(back_populates="violation_events")
    plate_read: Mapped[PlateRead | None] = relationship(back_populates="violation_events")
    rules_registry: Mapped[ModelRegistryEntry | None] = relationship(
        back_populates="violation_events_as_rules",
        foreign_keys=[rules_registry_id],
    )
    evidence_manifests: Mapped[list["EvidenceManifest"]] = relationship(back_populates="violation_event")
    workflow_runs: Mapped[list["WorkflowRun"]] = relationship(back_populates="violation_event")
    operational_alerts: Mapped[list["OperationalAlert"]] = relationship(back_populates="violation_event")


class EvidenceManifest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Structured evidence package linked to a persisted event or violation."""

    __tablename__ = "evidence_manifests"
    __table_args__ = (
        UniqueConstraint("subject_kind", "subject_id", name="uq_evidence_manifests_subject"),
        Index("ix_evidence_manifests_camera_occurred_at", "camera_id", "occurred_at"),
        Index("ix_evidence_manifests_manifest_key", "manifest_key"),
        Index("ix_evidence_manifests_detection_event_id", "detection_event_id"),
        Index("ix_evidence_manifests_violation_event_id", "violation_event_id"),
        Index("ix_evidence_manifests_evidence_registry_id", "evidence_registry_id"),
    )

    subject_kind: Mapped[EvidenceSubjectKind] = mapped_column(
        enum_type(EvidenceSubjectKind, "evidence_subject_kind"),
        nullable=False,
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    manifest_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    build_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    camera_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cameras.id", ondelete="RESTRICT"),
        nullable=False,
    )
    stream_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("camera_streams.id", ondelete="SET NULL"),
        nullable=True,
    )
    zone_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("zones.id", ondelete="SET NULL"),
        nullable=True,
    )
    detection_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("detection_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    violation_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("violation_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    plate_read_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("plate_reads.id", ondelete="SET NULL"),
        nullable=True,
    )
    evidence_registry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("model_registry_entries.id", ondelete="SET NULL"),
        nullable=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_frame_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    storage_namespace: Mapped[str] = mapped_column(String(64), nullable=False, default="evidence", server_default="evidence")
    manifest_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    manifest_data: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )

    camera: Mapped[Camera] = relationship(back_populates="evidence_manifests")
    stream: Mapped[CameraStream | None] = relationship(back_populates="evidence_manifests")
    zone: Mapped[Zone | None] = relationship(back_populates="evidence_manifests")
    detection_event: Mapped[DetectionEvent | None] = relationship(back_populates="evidence_manifests")
    violation_event: Mapped[ViolationEvent | None] = relationship(back_populates="evidence_manifests")
    plate_read: Mapped[PlateRead | None] = relationship(back_populates="evidence_manifests")
    evidence_registry: Mapped[ModelRegistryEntry | None] = relationship(
        back_populates="evidence_manifests",
        foreign_keys=[evidence_registry_id],
    )


class WorkflowRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Cold-path workflow execution record."""

    __tablename__ = "workflow_runs"
    __table_args__ = (
        Index("ix_workflow_runs_status_created_at", "status", "created_at"),
        Index("ix_workflow_runs_status_priority_created_at", "status", "priority", "created_at"),
        Index("ix_workflow_runs_workflow_type_created_at", "workflow_type", "created_at"),
        Index("ix_workflow_runs_violation_event_id", "violation_event_id"),
        Index("ix_workflow_runs_detection_event_id", "detection_event_id"),
    )

    camera_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cameras.id", ondelete="SET NULL"),
        nullable=True,
    )
    detection_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("detection_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    violation_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("violation_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    workflow_type: Mapped[WorkflowType] = mapped_column(
        enum_type(WorkflowType, "workflow_type"),
        nullable=False,
    )
    status: Mapped[WorkflowStatus] = mapped_column(
        enum_type(WorkflowStatus, "workflow_status"),
        nullable=False,
        default=WorkflowStatus.QUEUED,
        server_default=WorkflowStatus.QUEUED.value,
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=5, server_default="5")
    requested_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    camera: Mapped[Camera | None] = relationship(back_populates="workflow_runs")
    detection_event: Mapped[DetectionEvent | None] = relationship(back_populates="workflow_runs")
    violation_event: Mapped[ViolationEvent | None] = relationship(back_populates="workflow_runs")
    operational_alerts: Mapped[list["OperationalAlert"]] = relationship(back_populates="workflow_run")


class WatchlistEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Plate number flagged for operational interest."""

    __tablename__ = "watchlist_entries"
    __table_args__ = (
        Index("ix_watchlist_entries_normalized_plate_text", "normalized_plate_text"),
        Index("ix_watchlist_entries_status_reason", "status", "reason"),
        UniqueConstraint("normalized_plate_text", "reason", name="uq_watchlist_plate_reason"),
    )

    normalized_plate_text: Mapped[str] = mapped_column(String(32), nullable=False)
    plate_text_display: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[WatchlistReason] = mapped_column(
        enum_type(WatchlistReason, "watchlist_reason"),
        nullable=False,
    )
    status: Mapped[WatchlistEntryStatus] = mapped_column(
        enum_type(WatchlistEntryStatus, "watchlist_entry_status"),
        nullable=False,
        default=WatchlistEntryStatus.ACTIVE,
        server_default=WatchlistEntryStatus.ACTIVE.value,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    added_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    alert_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true(),
    )
    country_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    watchlist_alerts: Mapped[list["WatchlistAlert"]] = relationship(back_populates="watchlist_entry")


class WatchlistAlert(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Operational alert emitted when a persisted plate read hits the watchlist."""

    __tablename__ = "watchlist_alerts"
    __table_args__ = (
        Index("ix_watchlist_alerts_camera_occurred_at", "camera_id", "occurred_at"),
        Index("ix_watchlist_alerts_status_occurred_at", "status", "occurred_at"),
        Index("ix_watchlist_alerts_watchlist_entry_id", "watchlist_entry_id"),
        UniqueConstraint("plate_read_id", "watchlist_entry_id", name="uq_watchlist_alert_plate_read_entry"),
    )

    plate_read_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plate_reads.id", ondelete="CASCADE"),
        nullable=False,
    )
    watchlist_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("watchlist_entries.id", ondelete="SET NULL"),
        nullable=True,
    )
    camera_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cameras.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[WatchlistAlertStatus] = mapped_column(
        enum_type(WatchlistAlertStatus, "watchlist_alert_status"),
        nullable=False,
        default=WatchlistAlertStatus.OPEN,
        server_default=WatchlistAlertStatus.OPEN.value,
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    normalized_plate_text: Mapped[str] = mapped_column(String(32), nullable=False)
    plate_text: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[WatchlistReason] = mapped_column(
        enum_type(WatchlistReason, "watchlist_alert_reason"),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    alert_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )

    plate_read: Mapped[PlateRead] = relationship(back_populates="watchlist_alerts")
    watchlist_entry: Mapped[WatchlistEntry | None] = relationship(back_populates="watchlist_alerts")
    camera: Mapped[Camera] = relationship(back_populates="watchlist_alerts")
    operational_alerts: Mapped[list["OperationalAlert"]] = relationship(back_populates="watchlist_alert")


class AlertRoutingTarget(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Configured destination for routed operational alerts."""

    __tablename__ = "alert_routing_targets"
    __table_args__ = (
        UniqueConstraint("channel", "destination", name="uq_alert_routing_targets_channel_destination"),
        Index("ix_alert_routing_targets_channel_enabled", "channel", "is_enabled"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    channel: Mapped[AlertRoutingChannel] = mapped_column(
        enum_type(AlertRoutingChannel, "alert_routing_channel"),
        nullable=False,
    )
    destination: Mapped[str] = mapped_column(Text, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    target_config: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )

    policy_routes: Mapped[list["AlertPolicyRoute"]] = relationship(back_populates="routing_target")
    delivery_attempts: Mapped[list["AlertDeliveryAttempt"]] = relationship(back_populates="routing_target")


class AlertPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Routing and escalation policy evaluated against normalized alert signals."""

    __tablename__ = "alert_policies"
    __table_args__ = (
        Index("ix_alert_policies_source_condition_enabled", "source_kind", "condition_key", "is_enabled"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_kind: Mapped[OperationalAlertSourceKind] = mapped_column(
        enum_type(OperationalAlertSourceKind, "operational_alert_source_kind"),
        nullable=False,
    )
    condition_key: Mapped[str] = mapped_column(String(80), nullable=False)
    min_severity: Mapped[OperationalAlertSeverity] = mapped_column(
        enum_type(OperationalAlertSeverity, "operational_alert_severity"),
        nullable=False,
        default=OperationalAlertSeverity.MEDIUM,
        server_default=OperationalAlertSeverity.MEDIUM.value,
    )
    cooldown_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300, server_default="300")
    dedup_window_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=900, server_default="900")
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    policy_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )

    routes: Mapped[list["AlertPolicyRoute"]] = relationship(
        back_populates="policy",
        cascade="all, delete-orphan",
        order_by="AlertPolicyRoute.escalation_level",
    )
    alerts: Mapped[list["OperationalAlert"]] = relationship(back_populates="policy")


class AlertPolicyRoute(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One routing destination within an alert policy escalation ladder."""

    __tablename__ = "alert_policy_routes"
    __table_args__ = (
        UniqueConstraint("policy_id", "routing_target_id", "escalation_level", name="uq_alert_policy_routes_step"),
        Index("ix_alert_policy_routes_policy_escalation", "policy_id", "escalation_level", "delay_seconds"),
        Index("ix_alert_policy_routes_target_id", "routing_target_id"),
    )

    policy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("alert_policies.id", ondelete="CASCADE"),
        nullable=False,
    )
    routing_target_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("alert_routing_targets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    escalation_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    delay_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    route_config: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )

    policy: Mapped[AlertPolicy] = relationship(back_populates="routes")
    routing_target: Mapped[AlertRoutingTarget] = relationship(back_populates="policy_routes")


class OperationalAlert(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Persisted operational alert instance created from a normalized source signal."""

    __tablename__ = "operational_alerts"
    __table_args__ = (
        Index("ix_operational_alerts_status_occurred_at", "status", "occurred_at"),
        Index("ix_operational_alerts_policy_status", "policy_id", "status"),
        Index("ix_operational_alerts_camera_status", "camera_id", "status"),
        Index("ix_operational_alerts_dedup_key", "dedup_key"),
        Index("ix_operational_alerts_source_kind_condition", "source_kind", "condition_key"),
    )

    policy_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("alert_policies.id", ondelete="SET NULL"),
        nullable=True,
    )
    camera_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cameras.id", ondelete="SET NULL"),
        nullable=True,
    )
    stream_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("camera_streams.id", ondelete="SET NULL"),
        nullable=True,
    )
    detection_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("detection_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    violation_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("violation_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    watchlist_alert_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("watchlist_alerts.id", ondelete="SET NULL"),
        nullable=True,
    )
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_kind: Mapped[OperationalAlertSourceKind] = mapped_column(
        enum_type(OperationalAlertSourceKind, "operational_alert_instance_source_kind"),
        nullable=False,
    )
    condition_key: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[OperationalAlertSeverity] = mapped_column(
        enum_type(OperationalAlertSeverity, "operational_alert_instance_severity"),
        nullable=False,
    )
    status: Mapped[OperationalAlertStatus] = mapped_column(
        enum_type(OperationalAlertStatus, "operational_alert_status"),
        nullable=False,
        default=OperationalAlertStatus.NEW,
        server_default=OperationalAlertStatus.NEW.value,
    )
    dedup_key: Mapped[str] = mapped_column(String(240), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    escalation_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    escalation_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_routed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    suppressed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suppressed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )
    alert_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )

    policy: Mapped[AlertPolicy | None] = relationship(back_populates="alerts")
    camera: Mapped[Camera | None] = relationship(back_populates="operational_alerts")
    stream: Mapped[CameraStream | None] = relationship(back_populates="operational_alerts")
    detection_event: Mapped[DetectionEvent | None] = relationship(back_populates="operational_alerts")
    violation_event: Mapped[ViolationEvent | None] = relationship(back_populates="operational_alerts")
    watchlist_alert: Mapped[WatchlistAlert | None] = relationship(back_populates="operational_alerts")
    workflow_run: Mapped[WorkflowRun | None] = relationship(back_populates="operational_alerts")
    deliveries: Mapped[list["AlertDeliveryAttempt"]] = relationship(
        back_populates="alert",
        cascade="all, delete-orphan",
        order_by="AlertDeliveryAttempt.created_at",
    )
    audit_events: Mapped[list["AlertAuditEvent"]] = relationship(
        back_populates="alert",
        cascade="all, delete-orphan",
        order_by="AlertAuditEvent.created_at",
    )


class AlertDeliveryAttempt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Auditable routing plan or delivery attempt for one alert target."""

    __tablename__ = "alert_delivery_attempts"
    __table_args__ = (
        Index("ix_alert_delivery_attempts_alert_created_at", "alert_id", "created_at"),
        Index("ix_alert_delivery_attempts_state_created_at", "delivery_state", "created_at"),
        Index("ix_alert_delivery_attempts_target_id", "routing_target_id"),
    )

    alert_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("operational_alerts.id", ondelete="CASCADE"),
        nullable=False,
    )
    policy_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("alert_policies.id", ondelete="SET NULL"),
        nullable=True,
    )
    routing_target_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("alert_routing_targets.id", ondelete="SET NULL"),
        nullable=True,
    )
    escalation_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    delivery_state: Mapped[AlertDeliveryState] = mapped_column(
        enum_type(AlertDeliveryState, "alert_delivery_state"),
        nullable=False,
        default=AlertDeliveryState.PLANNED,
        server_default=AlertDeliveryState.PLANNED.value,
    )
    channel: Mapped[AlertRoutingChannel] = mapped_column(
        enum_type(AlertRoutingChannel, "alert_delivery_channel"),
        nullable=False,
    )
    destination: Mapped[str] = mapped_column(Text, nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivery_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )

    alert: Mapped[OperationalAlert] = relationship(back_populates="deliveries")
    routing_target: Mapped[AlertRoutingTarget | None] = relationship(back_populates="delivery_attempts")


class AlertAuditEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Status and routing audit trail for an operational alert."""

    __tablename__ = "alert_audit_events"
    __table_args__ = (
        Index("ix_alert_audit_events_alert_created_at", "alert_id", "created_at"),
        Index("ix_alert_audit_events_event_type", "event_type"),
    )

    alert_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("operational_alerts.id", ondelete="CASCADE"),
        nullable=False,
    )
    policy_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("alert_policies.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[AlertAuditEventType] = mapped_column(
        enum_type(AlertAuditEventType, "alert_audit_event_type"),
        nullable=False,
    )
    status_after: Mapped[OperationalAlertStatus | None] = mapped_column(
        enum_type(OperationalAlertStatus, "alert_audit_status"),
        nullable=True,
    )
    actor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )

    alert: Mapped[OperationalAlert] = relationship(back_populates="audit_events")


# ===========================================================================
# Multi-camera Re-identification
# ===========================================================================


class CrossCameraEntity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A confirmed cross-camera identity that unifies sightings across cameras."""

    __tablename__ = "cross_camera_entities"
    __table_args__ = (
        Index("ix_cross_camera_entities_subject_type", "subject_type"),
        Index("ix_cross_camera_entities_first_seen_at", "first_seen_at"),
    )

    subject_type: Mapped[ReIdSubjectType] = mapped_column(
        enum_type(ReIdSubjectType, "reid_subject_type"),
        nullable=False,
    )
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    representative_image_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reid_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'"),
    )

    sightings: Mapped[list["ReIdSighting"]] = relationship(back_populates="entity")


class ReIdSighting(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single observation of a tracked object on one camera, stored for re-id."""

    __tablename__ = "reid_sightings"
    __table_args__ = (
        UniqueConstraint(
            "camera_id",
            "track_id",
            "first_seen_at",
            name="uq_reid_sightings_camera_track_first_seen",
        ),
        Index("ix_reid_sightings_camera_id", "camera_id"),
        Index("ix_reid_sightings_subject_type", "subject_type"),
        Index("ix_reid_sightings_entity_id", "entity_id"),
        Index("ix_reid_sightings_camera_track", "camera_id", "track_id"),
        Index("ix_reid_sightings_first_seen_at", "first_seen_at"),
        Index("ix_reid_sightings_detection_event_id", "representative_detection_event_id"),
    )

    camera_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cameras.id", ondelete="RESTRICT"),
        nullable=False,
    )
    track_id: Mapped[str] = mapped_column(
        String(128), nullable=False, doc="Local per-camera track identifier."
    )
    subject_type: Mapped[ReIdSubjectType] = mapped_column(
        enum_type(ReIdSubjectType, "reid_sighting_subject_type"),
        nullable=False,
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cross_camera_entities.id", ondelete="SET NULL"),
        nullable=True,
        doc="Set once the sighting is linked to a cross-camera entity.",
    )
    representative_detection_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("detection_events.id", ondelete="SET NULL"),
        nullable=True,
        doc="Representative persisted event used to audit the sighting.",
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    embedding_vector: Mapped[list[float] | None] = mapped_column(
        JSON, nullable=True, doc="Appearance embedding (list of floats)."
    )
    embedding_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bbox_snapshot: Mapped[dict[str, float] | None] = mapped_column(JSON, nullable=True)
    image_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    reid_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'"),
    )

    camera: Mapped[Camera] = relationship(back_populates="reid_sightings")
    detection_event: Mapped[DetectionEvent | None] = relationship(back_populates="reid_sightings")
    entity: Mapped[CrossCameraEntity | None] = relationship(back_populates="sightings")
    matches_as_a: Mapped[list["ReIdMatch"]] = relationship(
        foreign_keys="ReIdMatch.sighting_a_id", back_populates="sighting_a",
    )
    matches_as_b: Mapped[list["ReIdMatch"]] = relationship(
        foreign_keys="ReIdMatch.sighting_b_id", back_populates="sighting_b",
    )


class ReIdMatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A proposed or confirmed match between two sightings."""

    __tablename__ = "reid_matches"
    __table_args__ = (
        Index("ix_reid_matches_status", "status"),
        Index("ix_reid_matches_pair_key", "pair_key"),
        Index("ix_reid_matches_proposed_at", "proposed_at"),
        Index("ix_reid_matches_sighting_a_id", "sighting_a_id"),
        Index("ix_reid_matches_sighting_b_id", "sighting_b_id"),
        UniqueConstraint("pair_key", name="uq_reid_match_pair_key"),
    )

    sighting_a_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reid_sightings.id", ondelete="CASCADE"),
        nullable=False,
    )
    sighting_b_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reid_sightings.id", ondelete="CASCADE"),
        nullable=False,
    )
    pair_key: Mapped[str] = mapped_column(
        String(73),
        nullable=False,
        doc="Canonical sorted key for the sighting pair, e.g. uuid_a:uuid_b.",
    )
    similarity_score: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[ReIdMatchStatus] = mapped_column(
        enum_type(ReIdMatchStatus, "reid_match_status"),
        nullable=False,
        default=ReIdMatchStatus.CANDIDATE,
        server_default=ReIdMatchStatus.CANDIDATE.value,
    )
    proposed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reid_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'"),
    )

    sighting_a: Mapped[ReIdSighting] = relationship(
        foreign_keys=[sighting_a_id], back_populates="matches_as_a",
    )
    sighting_b: Mapped[ReIdSighting] = relationship(
        foreign_keys=[sighting_b_id], back_populates="matches_as_b",
    )


# ===========================================================================
# Case Export
# ===========================================================================


class CaseExport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Persisted audit-ready case export bundle."""

    __tablename__ = "case_exports"
    __table_args__ = (
        Index("ix_case_exports_subject", "subject_kind", "subject_id"),
        Index("ix_case_exports_status_created_at", "status", "created_at"),
    )

    subject_kind: Mapped[CaseSubjectKind] = mapped_column(
        enum_type(CaseSubjectKind, "case_subject_kind"),
        nullable=False,
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    export_format: Mapped[CaseExportFormat] = mapped_column(
        enum_type(CaseExportFormat, "case_export_format"),
        nullable=False,
    )
    status: Mapped[CaseExportStatus] = mapped_column(
        enum_type(CaseExportStatus, "case_export_status"),
        nullable=False,
        default=CaseExportStatus.PENDING,
        server_default=CaseExportStatus.PENDING.value,
    )
    requested_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bundle_version: Mapped[str] = mapped_column(
        String(16), nullable=False, default="1.0", server_default="1.0",
    )
    filename: Mapped[str] = mapped_column(String(260), nullable=False)
    bundle_data: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'"),
    )
    completeness: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'"),
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    audit_events: Mapped[list["CaseExportAuditEvent"]] = relationship(
        back_populates="case_export",
        cascade="all, delete-orphan",
        order_by="CaseExportAuditEvent.created_at",
    )


class CaseExportAuditEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Audit trail entry for a case export."""

    __tablename__ = "case_export_audit_events"
    __table_args__ = (
        Index("ix_case_export_audit_events_export_created", "case_export_id", "created_at"),
    )

    case_export_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("case_exports.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[CaseExportAuditEventType] = mapped_column(
        enum_type(CaseExportAuditEventType, "case_export_audit_event_type"),
        nullable=False,
    )
    actor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'"),
    )

    case_export: Mapped[CaseExport] = relationship(back_populates="audit_events")