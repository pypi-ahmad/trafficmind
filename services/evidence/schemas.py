"""Typed schemas for structured incident evidence manifests."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from apps.api.app.db.enums import EvidenceSubjectKind


class EvidenceAssetKind(StrEnum):
    KEY_FRAME_SNAPSHOT = "key_frame_snapshot"
    OBJECT_CROP = "object_crop"
    PLATE_CROP = "plate_crop"
    CLIP_WINDOW = "clip_window"
    TIMELINE_METADATA = "timeline_metadata"


class EvidenceFrameRole(StrEnum):
    PRE_EVENT = "pre_event"
    EVENT = "event"
    POST_EVENT = "post_event"


class EvidenceStorageState(StrEnum):
    AVAILABLE = "available"
    PLANNED = "planned"
    INLINE = "inline"


class EvidenceAccessRole(StrEnum):
    OPERATOR = "operator"
    REVIEWER = "reviewer"
    SUPERVISOR = "supervisor"
    PRIVACY_OFFICER = "privacy_officer"
    EVIDENCE_ADMIN = "evidence_admin"
    EXPORT_SERVICE = "export_service"


class EvidenceAssetView(StrEnum):
    ORIGINAL = "original"
    REDACTED = "redacted"


class EvidenceRedactionStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    PLANNED = "planned"
    AVAILABLE = "available"


class EvidenceRedactionTarget(StrEnum):
    FACE = "face"
    LICENSE_PLATE = "license_plate"
    PERSONALLY_IDENTIFYING_DETAIL = "personally_identifying_detail"


class EvidenceOverlayKind(StrEnum):
    BBOX = "bbox"
    ZONE = "zone"
    TRACK_PATH = "track_path"
    SIGNAL_STATE = "signal_state"


class EvidencePrivacyPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy_name: str = "default_evidence_redaction_v1"
    policy_version: int = 1
    default_api_role: EvidenceAccessRole = EvidenceAccessRole.OPERATOR
    default_asset_view: EvidenceAssetView = EvidenceAssetView.REDACTED
    default_export_view: EvidenceAssetView = EvidenceAssetView.REDACTED
    preserve_original_assets: bool = True
    authorized_original_roles: list[EvidenceAccessRole] = Field(
        default_factory=lambda: [
            EvidenceAccessRole.PRIVACY_OFFICER,
            EvidenceAccessRole.EVIDENCE_ADMIN,
        ]
    )
    mask_by_default_roles: list[EvidenceAccessRole] = Field(
        default_factory=lambda: [
            EvidenceAccessRole.OPERATOR,
            EvidenceAccessRole.REVIEWER,
            EvidenceAccessRole.SUPERVISOR,
            EvidenceAccessRole.EXPORT_SERVICE,
        ]
    )
    redaction_targets: list[EvidenceRedactionTarget] = Field(
        default_factory=lambda: [
            EvidenceRedactionTarget.FACE,
            EvidenceRedactionTarget.LICENSE_PLATE,
            EvidenceRedactionTarget.PERSONALLY_IDENTIFYING_DETAIL,
        ]
    )
    enforcement_notes: list[str] = Field(
        default_factory=lambda: [
            "API responses default to redacted evidence views for non-authorized roles.",
            "Original asset references are preserved for restricted access roles only.",
            "This repo does not yet include a full authentication/session layer; request-declared roles are a policy foundation, not a complete authorization system.",
        ]
    )
    compliance_notes: list[str] = Field(
        default_factory=lambda: [
            "This foundation does not claim jurisdiction-specific privacy compliance by itself.",
            "Redacted asset generation is a foundation: visual redaction targets and access boundaries are explicit, but a production masking pipeline still needs to materialize redacted media.",
        ]
    )


class EvidenceAccessResolution(BaseModel):
    model_config = ConfigDict(frozen=True)

    requested_role: EvidenceAccessRole = EvidenceAccessRole.OPERATOR
    requested_view: EvidenceAssetView | None = None
    resolved_view: EvidenceAssetView = EvidenceAssetView.REDACTED
    original_access_authorized: bool = False
    resolution_notes: list[str] = Field(default_factory=list)


class EvidenceSubjectRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: EvidenceSubjectKind
    subject_id: uuid.UUID
    camera_id: uuid.UUID
    camera_code: str
    stream_id: uuid.UUID | None = None
    zone_id: uuid.UUID | None = None
    detection_event_id: uuid.UUID | None = None
    violation_event_id: uuid.UUID | None = None
    plate_read_id: uuid.UUID | None = None
    track_id: str | None = None
    violation_type: str | None = None
    object_class: str | None = None
    plate_text: str | None = None
    occurred_at: datetime


class EvidenceSelectionPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_frame_index: int | None = None
    pre_event_frame_count: int = 2
    post_event_frame_count: int = 2
    frame_step: int = 1
    clip_lead_frames: int = 12
    clip_tail_frames: int = 12
    fps_hint: float | None = None
    selection_reason: str


class EvidenceTimelineFrame(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: EvidenceFrameRole
    label: str
    frame_index: int | None = None
    relative_frame_offset: int
    timestamp: datetime | None = None


class EvidenceClipWindow(BaseModel):
    model_config = ConfigDict(frozen=True)

    start_frame_index: int | None = None
    end_frame_index: int | None = None
    lead_frames: int = 12
    tail_frames: int = 12
    fps_hint: float | None = None
    approx_duration_ms: int | None = None
    generation_mode: str = "placeholder"


class EvidenceTimeline(BaseModel):
    model_config = ConfigDict(frozen=True)

    occurred_at: datetime
    event_frame_index: int | None = None
    selected_frames: list[EvidenceTimelineFrame] = Field(default_factory=list)
    clip_window: EvidenceClipWindow


class EvidenceAsset(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset_kind: EvidenceAssetKind
    label: str
    asset_key: str
    asset_view: EvidenceAssetView = EvidenceAssetView.ORIGINAL
    uri: str | None = None
    source_uri: str | None = None
    storage_state: EvidenceStorageState = EvidenceStorageState.PLANNED
    available: bool = False
    content_type: str | None = None
    frame_index: int | None = None
    derived_from_asset_key: str | None = None
    redaction_status: EvidenceRedactionStatus = EvidenceRedactionStatus.NOT_REQUIRED
    redaction_targets: list[EvidenceRedactionTarget] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    render_hints: dict[str, Any] = Field(default_factory=dict)


class EvidenceManifestDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    subject: EvidenceSubjectRef
    storage_namespace: str = "evidence"
    selection_policy: EvidenceSelectionPolicy
    timeline: EvidenceTimeline
    assets: list[EvidenceAsset] = Field(default_factory=list)
    redacted_assets: list[EvidenceAsset] = Field(default_factory=list)
    privacy_policy: EvidencePrivacyPolicy = Field(default_factory=EvidencePrivacyPolicy)
    active_asset_view: EvidenceAssetView = EvidenceAssetView.ORIGINAL
    original_asset_count: int = 0
    redacted_asset_count: int = 0
    audit: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_manifest(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        assets = list(data.get("assets") or [])
        redacted_assets = list(data.get("redacted_assets") or [])
        data.setdefault("privacy_policy", EvidencePrivacyPolicy().model_dump(mode="json"))
        data.setdefault("active_asset_view", EvidenceAssetView.ORIGINAL.value)
        data.setdefault("original_asset_count", len(assets))
        data.setdefault("redacted_asset_count", len(redacted_assets))
        return data


class EvidenceManifestRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    subject_kind: EvidenceSubjectKind
    subject_id: uuid.UUID
    manifest_key: str
    build_revision: int
    camera_id: uuid.UUID
    stream_id: uuid.UUID | None = None
    zone_id: uuid.UUID | None = None
    detection_event_id: uuid.UUID | None = None
    violation_event_id: uuid.UUID | None = None
    plate_read_id: uuid.UUID | None = None
    evidence_registry_id: uuid.UUID | None = None
    occurred_at: datetime
    event_frame_index: int | None = None
    storage_namespace: str
    manifest_uri: str | None = None
    manifest: EvidenceManifestDocument
    access: EvidenceAccessResolution = Field(default_factory=EvidenceAccessResolution)
    visible_assets: list[EvidenceAsset] = Field(default_factory=list)
    has_restricted_original_assets: bool = False
    created_at: datetime
    updated_at: datetime