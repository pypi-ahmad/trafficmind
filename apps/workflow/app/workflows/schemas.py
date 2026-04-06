"""Typed schemas for LangGraph-based TrafficMind workflows."""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any, Literal, TypeAlias

import uuid

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from apps.api.app.db.enums import (
    CameraStatus,
    DetectionEventStatus,
    DetectionEventType,
    PlateReadStatus,
    ViolationSeverity,
    ViolationStatus,
    ViolationType,
    ZoneType,
)
from packages.shared_types.enums import WorkflowStatus, WorkflowType


class WorkflowName(StrEnum):
    INCIDENT_TRIAGE = "incident_triage"
    VIOLATION_REVIEW = "violation_review"
    MULTIMODAL_REVIEW = "multimodal_review"
    DAILY_SUMMARY = "daily_summary"
    WEEKLY_SUMMARY = "weekly_summary"
    HOTSPOT_REPORT = "hotspot_report"
    OPERATOR_ASSIST = "operator_assist"


class IncidentPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ReviewDisposition(StrEnum):
    CONFIRM_VIOLATION = "confirm_violation"
    DISMISS_FALSE_POSITIVE = "dismiss_false_positive"
    NEED_MORE_EVIDENCE = "need_more_evidence"
    ESCALATE_SUPERVISOR = "escalate_supervisor"


class StoredCameraRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    camera_code: str
    name: str
    location_name: str
    approach: str | None = None
    status: CameraStatus
    latitude: float | None = None
    longitude: float | None = None
    timezone: str = "UTC"


class StoredDetectionEventRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    event_type: DetectionEventType
    occurred_at: datetime
    frame_index: int | None = None
    track_id: str | None = None
    object_class: str
    confidence: float
    bbox: dict[str, Any]
    event_payload: dict[str, Any] = Field(default_factory=dict)
    image_uri: str | None = None
    video_uri: str | None = None


class StoredPlateReadRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    status: PlateReadStatus
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


class StoredViolationEventRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    violation_type: ViolationType
    severity: ViolationSeverity
    status: ViolationStatus
    occurred_at: datetime
    summary: str | None = None
    evidence_image_uri: str | None = None
    evidence_video_uri: str | None = None
    assigned_to: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None
    rule_metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    source: str
    uri: str | None = None
    available: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReviewContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    requested_by: str | None = None
    operator_notes: str | None = None
    existing_review_note: str | None = None
    assigned_to: str | None = None
    reviewed_by: str | None = None


class IncidentTriageContext(BaseModel):
    source_kind: Literal["violation", "detection"]
    camera: StoredCameraRecord
    detection_event: StoredDetectionEventRecord | None = None
    violation_event: StoredViolationEventRecord | None = None
    plate_read: StoredPlateReadRecord | None = None
    evidence: list[EvidenceReference] = Field(default_factory=list)
    review_context: ReviewContext = Field(default_factory=ReviewContext)


class ViolationReviewContext(BaseModel):
    camera: StoredCameraRecord
    violation_event: StoredViolationEventRecord
    detection_event: StoredDetectionEventRecord | None = None
    plate_read: StoredPlateReadRecord | None = None
    evidence: list[EvidenceReference] = Field(default_factory=list)
    review_context: ReviewContext = Field(default_factory=ReviewContext)


class MultimodalGroundingReferenceKind(StrEnum):
    METADATA = "metadata"
    IMAGE = "image"
    CLIP = "clip"
    MANIFEST = "manifest"


class MultimodalGroundingReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: MultimodalGroundingReferenceKind
    label: str
    source: str
    uri: str | None = None
    available: bool = False
    reference_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MultimodalRuleExplanation(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_type: str | None = None
    reason: str | None = None
    frame_index: int | None = None
    conditions_satisfied: list[str] = Field(default_factory=list)
    salient_details: dict[str, Any] = Field(default_factory=dict)


class PriorReviewRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: Literal["violation_event", "workflow_run"]
    recorded_at: datetime
    recorded_by: str | None = None
    workflow_name: WorkflowName | None = None
    workflow_type: WorkflowType | None = None
    summary: str
    disposition: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MultimodalReviewContext(BaseModel):
    camera: StoredCameraRecord
    violation_event: StoredViolationEventRecord
    detection_event: StoredDetectionEventRecord | None = None
    plate_read: StoredPlateReadRecord | None = None
    review_context: ReviewContext = Field(default_factory=ReviewContext)
    rule_explanation: MultimodalRuleExplanation = Field(default_factory=MultimodalRuleExplanation)
    metadata_references: list[MultimodalGroundingReference] = Field(default_factory=list)
    image_references: list[MultimodalGroundingReference] = Field(default_factory=list)
    clip_references: list[MultimodalGroundingReference] = Field(default_factory=list)
    manifest_references: list[MultimodalGroundingReference] = Field(default_factory=list)
    prior_review_history: list[PriorReviewRecord] = Field(default_factory=list)


class MultimodalReviewGrounding(BaseModel):
    metadata_reference_count: int = 0
    image_reference_count: int = 0
    clip_reference_count: int = 0
    manifest_reference_count: int = 0
    attached_image_labels: list[str] = Field(default_factory=list)
    attached_clip_labels: list[str] = Field(default_factory=list)
    manifest_image_labels: list[str] = Field(default_factory=list)
    manifest_clip_labels: list[str] = Field(default_factory=list)
    available_image_labels: list[str] = Field(default_factory=list)
    available_clip_labels: list[str] = Field(default_factory=list)
    planned_media_labels: list[str] = Field(default_factory=list)
    prior_review_count: int = 0
    grounding_notes: list[str] = Field(default_factory=list)


class CameraDailySummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    camera_id: uuid.UUID
    camera_name: str
    location_name: str
    detection_count: int = 0
    violation_count: int = 0
    open_violation_count: int = 0
    top_violation_types: dict[str, int] = Field(default_factory=dict)
    last_incident_at: datetime | None = None


class DailySummaryContext(BaseModel):
    report_date: date
    camera_scope: uuid.UUID | None = None
    cameras: list[CameraDailySummary] = Field(default_factory=list)
    total_detections: int = 0
    total_violations: int = 0
    total_open_violations: int = 0
    top_violation_types: dict[str, int] = Field(default_factory=dict)
    open_violation_examples: list[StoredViolationEventRecord] = Field(default_factory=list)
    review_backlog: ReviewBacklog = Field(default_factory=lambda: ReviewBacklog())
    watchlist: WatchlistSection = Field(default_factory=lambda: WatchlistSection())
    camera_health_concerns: list[CameraHealthConcern] = Field(default_factory=list)
    requested_by: str | None = None


class HumanReviewPrompt(BaseModel):
    review_kind: str
    title: str
    prompt: str
    options: list[str] = Field(default_factory=list)
    context_excerpt: dict[str, Any] = Field(default_factory=dict)


class HumanReviewDecision(BaseModel):
    approved: bool
    reviewer: str | None = None
    note: str | None = None
    overrides: dict[str, Any] = Field(default_factory=dict)


class WorkflowTraceEntry(BaseModel):
    node: str
    message: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)


class IncidentTriageRequest(BaseModel):
    violation_event_id: uuid.UUID | None = None
    detection_event_id: uuid.UUID | None = None
    requested_by: str | None = None
    operator_notes: str | None = None
    require_human_review: bool = True

    @model_validator(mode="after")
    def validate_identifiers(self) -> IncidentTriageRequest:
        if self.violation_event_id is None and self.detection_event_id is None:
            msg = "Provide violation_event_id or detection_event_id."
            raise ValueError(msg)
        return self


class ViolationReviewRequest(BaseModel):
    violation_event_id: uuid.UUID
    requested_by: str | None = None
    operator_notes: str | None = None
    require_human_approval: bool = True


class MultimodalReviewRequest(BaseModel):
    violation_event_id: uuid.UUID
    requested_by: str | None = None
    operator_notes: str | None = None
    include_prior_review_history: bool = True
    prior_review_limit: int = Field(default=5, ge=0, le=10)


class DailySummaryRequest(BaseModel):
    report_date: date = Field(default_factory=lambda: datetime.now(timezone.utc).date())
    camera_id: uuid.UUID | None = None
    requested_by: str | None = None
    include_open_violation_examples: int = Field(default=5, ge=0, le=20)
    require_human_approval: bool = False


class IncidentTriageOutput(BaseModel):
    workflow: Literal["incident_triage"] = "incident_triage"
    priority: IncidentPriority
    summary: str
    rationale: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    operator_brief: str
    requires_human_review: bool
    escalation_target: str | None = None


class ViolationReviewOutput(BaseModel):
    workflow: Literal["violation_review"] = "violation_review"
    disposition: ReviewDisposition
    summary: str
    rationale: list[str] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    requires_human_approval: bool


class MultimodalReviewOutput(BaseModel):
    workflow: Literal["multimodal_review"] = "multimodal_review"
    review_summary: str
    likely_cause: str
    confidence_caveats: list[str] = Field(default_factory=list)
    recommended_operator_action: str
    escalation_suggestion: str | None = None
    metadata_references: list[MultimodalGroundingReference] = Field(default_factory=list)
    image_references: list[MultimodalGroundingReference] = Field(default_factory=list)
    clip_references: list[MultimodalGroundingReference] = Field(default_factory=list)
    manifest_references: list[MultimodalGroundingReference] = Field(default_factory=list)
    prior_review_history: list[PriorReviewRecord] = Field(default_factory=list)
    audit_notes: list[str] = Field(default_factory=list)


class DailySummaryOutput(BaseModel):
    workflow: Literal["daily_summary"] = "daily_summary"
    report_date: date
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    headline: str
    narrative: str
    markdown: str = ""
    total_detections: int
    total_violations: int
    total_open_violations: int
    top_violation_types: dict[str, int] = Field(default_factory=dict)
    location_summaries: list[CameraDailySummary] = Field(default_factory=list)
    review_backlog: ReviewBacklog = Field(default_factory=lambda: ReviewBacklog())
    watchlist: WatchlistSection = Field(default_factory=lambda: WatchlistSection())
    camera_health_concerns: list[CameraHealthConcern] = Field(default_factory=list)
    recommended_follow_ups: list[str] = Field(default_factory=list)
    scope_notes: list[str] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)


# ── Weekly Summary ──────────────────────────────────────────────────────────


class WeeklySummaryRequest(BaseModel):
    week_ending: date = Field(
        default_factory=lambda: datetime.now(timezone.utc).date(),
        description="The last day of the 7-day window (inclusive).",
    )
    camera_id: uuid.UUID | None = None
    requested_by: str | None = None
    require_human_approval: bool = False


class ReviewBacklog(BaseModel):
    model_config = ConfigDict(frozen=True)

    open_violations: int = 0
    under_review_violations: int = 0
    oldest_open_at: datetime | None = None
    avg_review_hours: float | None = None


class WatchlistSection(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_alerts: int = 0
    open_alerts: int = 0
    top_reasons: dict[str, int] = Field(default_factory=dict)
    data_available: bool = True


class CameraHealthConcern(BaseModel):
    model_config = ConfigDict(frozen=True)

    camera_id: uuid.UUID
    camera_name: str
    concern: str
    detail: str | None = None


class WeeklySummaryContext(BaseModel):
    week_ending: date
    week_start: date
    camera_scope: uuid.UUID | None = None
    daily_breakdowns: list[CameraDailySummary] = Field(default_factory=list)
    total_detections: int = 0
    total_violations: int = 0
    total_open_violations: int = 0
    top_violation_types: dict[str, int] = Field(default_factory=dict)
    review_backlog: ReviewBacklog = Field(default_factory=ReviewBacklog)
    watchlist: WatchlistSection = Field(default_factory=WatchlistSection)
    camera_health_concerns: list[CameraHealthConcern] = Field(default_factory=list)
    requested_by: str | None = None


class WeeklySummaryOutput(BaseModel):
    workflow: Literal["weekly_summary"] = "weekly_summary"
    week_ending: date
    week_start: date
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    headline: str
    narrative: str
    markdown: str = ""
    total_detections: int
    total_violations: int
    total_open_violations: int
    top_violation_types: dict[str, int] = Field(default_factory=dict)
    location_summaries: list[CameraDailySummary] = Field(default_factory=list)
    review_backlog: ReviewBacklog = Field(default_factory=ReviewBacklog)
    watchlist: WatchlistSection = Field(default_factory=WatchlistSection)
    camera_health_concerns: list[CameraHealthConcern] = Field(default_factory=list)
    recommended_follow_ups: list[str] = Field(default_factory=list)
    scope_notes: list[str] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)


# ── Hotspot Report ──────────────────────────────────────────────────────────


class HotspotGroupBy(StrEnum):
    CAMERA = "camera"
    ZONE = "zone"


class HotspotReportRequest(BaseModel):
    report_date: date = Field(default_factory=lambda: datetime.now(timezone.utc).date())
    lookback_days: int = Field(default=7, ge=1, le=90)
    top_n: int = Field(default=5, ge=1, le=20)
    group_by: HotspotGroupBy = HotspotGroupBy.CAMERA
    requested_by: str | None = None
    require_human_approval: bool = False


class HotspotEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    camera_id: uuid.UUID
    camera_name: str
    location_name: str
    zone_id: uuid.UUID | None = None
    zone_name: str | None = None
    zone_type: str | None = None
    violation_count: int
    open_count: int = 0
    top_violation_types: dict[str, int] = Field(default_factory=dict)
    last_violation_at: datetime | None = None


class HotspotReportContext(BaseModel):
    report_date: date
    lookback_days: int
    top_n: int
    group_by: HotspotGroupBy = HotspotGroupBy.CAMERA
    hotspots: list[HotspotEntry] = Field(default_factory=list)
    total_violations_in_window: int = 0
    total_groups_with_violations: int = 0
    total_cameras_with_violations: int = 0
    unassigned_violations: int = 0
    requested_by: str | None = None


class HotspotReportOutput(BaseModel):
    workflow: Literal["hotspot_report"] = "hotspot_report"
    report_date: date
    lookback_days: int
    group_by: HotspotGroupBy = HotspotGroupBy.CAMERA
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    headline: str
    narrative: str
    markdown: str = ""
    hotspots: list[HotspotEntry] = Field(default_factory=list)
    total_violations_in_window: int = 0
    total_groups_with_violations: int = 0
    total_cameras_with_violations: int = 0
    unassigned_violations: int = 0
    recommended_follow_ups: list[str] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)


class OperatorAssistIntent(StrEnum):
    SEARCH_EVENTS = "search_events"
    SEARCH_PLATES = "search_plates"
    SEARCH_VIOLATIONS = "search_violations"
    EXPLAIN_VIOLATION = "explain_violation"
    SUMMARIZE_REPEATED_INCIDENTS = "summarize_repeated_incidents"
    UNKNOWN = "unknown"


class OperatorAssistRequest(BaseModel):
    query: str = Field(min_length=3, max_length=1000)
    requested_by: str | None = None
    camera_id: uuid.UUID | None = None
    violation_event_id: uuid.UUID | None = None
    detection_event_id: uuid.UUID | None = None
    max_results: int = Field(default=10, ge=1, le=50)
    require_human_review: bool = False


class OperatorAssistPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    intent: OperatorAssistIntent
    raw_query: str
    normalized_query: str
    camera_hint: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    event_type: DetectionEventType | None = None
    event_status: DetectionEventStatus | None = None
    violation_type: ViolationType | None = None
    violation_types: list[ViolationType] = Field(default_factory=list)
    violation_status: ViolationStatus | None = None
    plate_status: PlateReadStatus | None = None
    object_class: str | None = None
    zone_type: ZoneType | None = None
    plate_text: str | None = None
    partial_plate: bool = False
    explicit_violation_event_id: uuid.UUID | None = None
    max_results: int = Field(default=10, ge=1, le=50)
    rationale: list[str] = Field(default_factory=list)


class OperatorAssistReferenceKind(StrEnum):
    CAMERA = "camera"
    VIOLATION_EVENT = "violation_event"
    DETECTION_EVENT = "detection_event"
    PLATE_READ = "plate_read"


class OperatorAssistReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: OperatorAssistReferenceKind
    reference_id: uuid.UUID
    label: str
    occurred_at: datetime | None = None
    camera_id: uuid.UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class OperatorAssistViolationHit(BaseModel):
    model_config = ConfigDict(frozen=True)

    camera: StoredCameraRecord
    violation_event: StoredViolationEventRecord
    detection_event: StoredDetectionEventRecord | None = None
    plate_read: StoredPlateReadRecord | None = None


class OperatorAssistEventHit(BaseModel):
    model_config = ConfigDict(frozen=True)

    camera: StoredCameraRecord
    detection_event: StoredDetectionEventRecord
    zone_name: str | None = None
    zone_type: str | None = None


class OperatorAssistPlateHit(BaseModel):
    model_config = ConfigDict(frozen=True)

    camera: StoredCameraRecord
    plate_read: StoredPlateReadRecord
    detection_event: StoredDetectionEventRecord | None = None


class RepeatedIncidentSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    camera: StoredCameraRecord
    violation_type: ViolationType
    incident_count: int
    open_count: int = 0
    last_occurred_at: datetime | None = None
    sample_violation_event_ids: list[uuid.UUID] = Field(default_factory=list)


class OperatorAssistGrounding(BaseModel):
    plan: OperatorAssistPlan
    camera_matches: list[StoredCameraRecord] = Field(default_factory=list)
    event_hits: list[OperatorAssistEventHit] = Field(default_factory=list)
    violation_hits: list[OperatorAssistViolationHit] = Field(default_factory=list)
    plate_hits: list[OperatorAssistPlateHit] = Field(default_factory=list)
    incident_summaries: list[RepeatedIncidentSummary] = Field(default_factory=list)
    total_matches: int = 0
    supporting_evidence: list[EvidenceReference] = Field(default_factory=list)
    references: list[OperatorAssistReference] = Field(default_factory=list)
    grounding_notes: list[str] = Field(default_factory=list)


class OperatorAssistOutput(BaseModel):
    workflow: Literal["operator_assist"] = "operator_assist"
    intent: OperatorAssistIntent
    answer: str
    grounded: bool
    matched_record_count: int = 0
    filters_applied: dict[str, Any] = Field(default_factory=dict)
    interpretation_notes: list[str] = Field(default_factory=list)
    references: list[OperatorAssistReference] = Field(default_factory=list)
    supporting_evidence: list[EvidenceReference] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    requires_human_review: bool = False
    escalation_reason: str | None = None


WorkflowOutput: TypeAlias = (
    IncidentTriageOutput
    | ViolationReviewOutput
    | MultimodalReviewOutput
    | DailySummaryOutput
    | WeeklySummaryOutput
    | HotspotReportOutput
    | OperatorAssistOutput
)
WORKFLOW_OUTPUT_ADAPTER = TypeAdapter(WorkflowOutput)


class StoredWorkflowRun(BaseModel):
    id: uuid.UUID
    workflow_type: WorkflowType
    status: WorkflowStatus
    priority: int
    requested_by: str | None = None
    camera_id: uuid.UUID | None = None
    detection_event_id: uuid.UUID | None = None
    violation_event_id: uuid.UUID | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    input_payload: dict[str, Any] = Field(default_factory=dict)
    result_payload: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class WorkflowRunResponse(BaseModel):
    run_id: uuid.UUID
    workflow_name: WorkflowName
    workflow_type: WorkflowType
    status: WorkflowStatus
    interrupted: bool = False
    checkpoint_backend: str
    durability_note: str
    interrupt_request: HumanReviewPrompt | None = None
    output: WorkflowOutput | None = None
    trace: list[WorkflowTraceEntry] = Field(default_factory=list)
    error_message: str | None = None


class WorkflowResumeRequest(BaseModel):
    approved: bool
    reviewer: str | None = None
    note: str | None = None
    overrides: dict[str, Any] = Field(default_factory=dict)
