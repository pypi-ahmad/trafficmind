from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.db.base import Base
from apps.api.app.db.enums import (
    CameraStatus,
    DetectionEventType,
    PlateReadStatus,
    SourceType,
    StreamKind,
    StreamStatus,
    ViolationSeverity,
    ViolationStatus,
    ViolationType,
    WorkflowStatus,
    WorkflowType,
    ZoneStatus,
    ZoneType,
)
from apps.api.app.db.models import (
    Camera,
    CameraStream,
    DetectionEvent,
    PlateRead,
    ViolationEvent,
    WorkflowRun,
    Zone,
)
from apps.workflow.app.core.config import Settings
from apps.workflow.app.main import create_app
from apps.workflow.app.workflows.repository import SqlAlchemyWorkflowRepository, WorkflowRepository
from apps.workflow.app.workflows.operator_assist import plan_operator_assist_request
from apps.workflow.app.workflows.schemas import (
    CameraDailySummary,
    CameraHealthConcern,
    DailySummaryContext,
    DailySummaryRequest,
    EvidenceReference,
    HotspotEntry,
    HotspotGroupBy,
    HotspotReportContext,
    HotspotReportRequest,
    IncidentTriageContext,
    IncidentTriageRequest,
    MultimodalGroundingReference,
    MultimodalGroundingReferenceKind,
    MultimodalReviewContext,
    MultimodalReviewRequest,
    MultimodalRuleExplanation,
    OperatorAssistEventHit,
    OperatorAssistGrounding,
    OperatorAssistIntent,
    OperatorAssistOutput,
    OperatorAssistPlateHit,
    OperatorAssistPlan,
    OperatorAssistReference,
    OperatorAssistReferenceKind,
    OperatorAssistRequest,
    OperatorAssistViolationHit,
    PriorReviewRecord,
    RepeatedIncidentSummary,
    ReviewBacklog,
    ReviewContext,
    StoredCameraRecord,
    StoredDetectionEventRecord,
    StoredPlateReadRecord,
    StoredViolationEventRecord,
    StoredWorkflowRun,
    ViolationReviewContext,
    ViolationReviewRequest,
    WatchlistSection,
    WeeklySummaryContext,
    WeeklySummaryRequest,
    WorkflowName,
    WorkflowResumeRequest,
)
from apps.workflow.app.workflows.service import WorkflowService
from services.evidence.service import build_violation_evidence_manifest

NOW = datetime(2026, 4, 4, 12, 0, tzinfo=timezone.utc)


def _camera_record() -> StoredCameraRecord:
    return StoredCameraRecord(
        id=uuid.uuid4(),
        camera_code="CAM-001",
        name="Main & 3rd Northbound",
        location_name="Main St & 3rd Ave",
        approach="northbound",
        status=CameraStatus.ACTIVE,
        latitude=24.7136,
        longitude=46.6753,
        timezone="UTC",
    )


def _detection_record(*, confidence: float = 0.94) -> StoredDetectionEventRecord:
    return StoredDetectionEventRecord(
        id=uuid.uuid4(),
        event_type=DetectionEventType.LINE_CROSSING,
        occurred_at=NOW,
        frame_index=101,
        track_id="T-123",
        object_class="car",
        confidence=confidence,
        bbox={"x1": 100, "y1": 150, "x2": 240, "y2": 360},
        event_payload={"direction": "northbound"},
        image_uri="s3://evidence/detection-frame.jpg",
        video_uri="s3://evidence/detection-clip.mp4",
    )


def _plate_record() -> StoredPlateReadRecord:
    return StoredPlateReadRecord(
        id=uuid.uuid4(),
        status=PlateReadStatus.OBSERVED,
        occurred_at=NOW,
        plate_text="ABC1234",
        normalized_plate_text="ABC1234",
        confidence=0.91,
        country_code="SA",
        region_code="RUH",
        bbox={"x1": 120, "y1": 180, "x2": 210, "y2": 220},
        crop_image_uri="s3://evidence/plate-crop.jpg",
        source_frame_uri="s3://evidence/plate-source.jpg",
        ocr_metadata={"engine": "paddleocr"},
    )


def _violation_record(
    *,
    severity: ViolationSeverity = ViolationSeverity.HIGH,
    status: ViolationStatus = ViolationStatus.OPEN,
    evidence: bool = True,
) -> StoredViolationEventRecord:
    return StoredViolationEventRecord(
        id=uuid.uuid4(),
        violation_type=ViolationType.RED_LIGHT,
        severity=severity,
        status=status,
        occurred_at=NOW,
        summary="Vehicle crossed the stop line during red.",
        evidence_image_uri="s3://evidence/violation-image.jpg" if evidence else None,
        evidence_video_uri="s3://evidence/violation-clip.mp4" if evidence else None,
        assigned_to="ops.lead",
        reviewed_by=None,
        reviewed_at=None,
        review_note=None,
        rule_metadata={"rule_type": "red_light", "frame_index": 101},
    )


class FakeWorkflowRepository(WorkflowRepository):
    def __init__(
        self,
        *,
        triage_context: IncidentTriageContext,
        review_context: ViolationReviewContext,
        daily_summary_context: DailySummaryContext,
        multimodal_review_context: MultimodalReviewContext | None = None,
        operator_assist_grounding: OperatorAssistGrounding | None = None,
        weekly_summary_context: WeeklySummaryContext | None = None,
        hotspot_report_context: HotspotReportContext | None = None,
    ) -> None:
        self._triage_context = triage_context
        self._review_context = review_context
        self._daily_summary_context = daily_summary_context
        self._multimodal_review_context = multimodal_review_context
        self._operator_assist_grounding = operator_assist_grounding
        self._weekly_summary_context = weekly_summary_context or WeeklySummaryContext(
            week_ending=date(2026, 4, 4), week_start=date(2026, 3, 29),
        )
        self._hotspot_report_context = hotspot_report_context or HotspotReportContext(
            report_date=date(2026, 4, 4), lookback_days=7, top_n=5,
        )
        self._runs: dict[uuid.UUID, StoredWorkflowRun] = {}

    async def build_incident_triage_context(self, request: IncidentTriageRequest) -> IncidentTriageContext:
        del request
        return self._triage_context

    async def build_violation_review_context(self, request: ViolationReviewRequest) -> ViolationReviewContext:
        del request
        return self._review_context

    async def build_multimodal_review_context(self, request: MultimodalReviewRequest) -> MultimodalReviewContext:
        del request
        if self._multimodal_review_context is not None:
            return self._multimodal_review_context
        return MultimodalReviewContext(
            camera=self._review_context.camera,
            violation_event=self._review_context.violation_event,
            detection_event=self._review_context.detection_event,
            plate_read=self._review_context.plate_read,
            review_context=self._review_context.review_context,
            rule_explanation=MultimodalRuleExplanation(
                rule_type=self._review_context.violation_event.rule_metadata.get("rule_type"),
                reason=self._review_context.violation_event.summary,
                frame_index=self._review_context.violation_event.rule_metadata.get("frame_index"),
            ),
        )

    async def build_daily_summary_context(self, request: DailySummaryRequest) -> DailySummaryContext:
        del request
        return self._daily_summary_context

    async def build_weekly_summary_context(self, request: WeeklySummaryRequest) -> WeeklySummaryContext:
        del request
        return self._weekly_summary_context

    async def build_hotspot_report_context(self, request: HotspotReportRequest) -> HotspotReportContext:
        del request
        return self._hotspot_report_context

    async def build_operator_assist_grounding(
        self,
        request: OperatorAssistRequest,
        plan: OperatorAssistPlan,
    ) -> OperatorAssistGrounding:
        del request
        if self._operator_assist_grounding is not None:
            return self._operator_assist_grounding
        grounding_notes: list[str] = []
        if plan.intent == OperatorAssistIntent.EXPLAIN_VIOLATION and plan.explicit_violation_event_id is None:
            grounding_notes.append("A specific stored violation_event_id is required to explain why an alert fired.")
        if plan.intent == OperatorAssistIntent.SUMMARIZE_REPEATED_INCIDENTS and plan.camera_hint is None:
            grounding_notes.append("Repeated-incident summaries require a specific camera or junction scope.")
        return OperatorAssistGrounding(plan=plan, grounding_notes=grounding_notes)

    async def create_workflow_run(
        self,
        *,
        workflow_name: WorkflowName,
        workflow_type: WorkflowType,
        requested_by: str | None,
        input_payload: dict[str, Any],
        camera_id: uuid.UUID | None = None,
        detection_event_id: uuid.UUID | None = None,
        violation_event_id: uuid.UUID | None = None,
        priority: int = 5,
    ) -> StoredWorkflowRun:
        run_id = uuid.uuid4()
        run = StoredWorkflowRun(
            id=run_id,
            workflow_type=workflow_type,
            status=WorkflowStatus.QUEUED,
            priority=priority,
            requested_by=requested_by,
            camera_id=camera_id,
            detection_event_id=detection_event_id,
            violation_event_id=violation_event_id,
            started_at=None,
            completed_at=None,
            input_payload={**input_payload, "workflow_name": workflow_name.value},
            result_payload=None,
            error_message=None,
            created_at=NOW,
            updated_at=NOW,
        )
        self._runs[run_id] = run
        return run

    async def update_workflow_run(
        self,
        run_id: uuid.UUID,
        *,
        status: WorkflowStatus,
        result_payload: dict[str, Any] | None = None,
        error_message: str | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> StoredWorkflowRun:
        run = self._runs[run_id]
        updated = run.model_copy(
            update={
                "status": status,
                "result_payload": result_payload if result_payload is not None else run.result_payload,
                "error_message": error_message if error_message is not None else run.error_message,
                "started_at": started_at if started_at is not None else run.started_at,
                "completed_at": completed_at if completed_at is not None else run.completed_at,
                "updated_at": NOW,
            }
        )
        self._runs[run_id] = updated
        return updated

    async def get_workflow_run(self, run_id: uuid.UUID) -> StoredWorkflowRun:
        return self._runs[run_id]

    async def apply_violation_disposition(
        self,
        violation_event_id: uuid.UUID,
        *,
        new_status: ViolationStatus,
        reviewed_by: str | None,
        review_note: str | None,
    ) -> None:
        self.last_disposition = {
            "violation_event_id": violation_event_id,
            "new_status": new_status,
            "reviewed_by": reviewed_by,
            "review_note": review_note,
        }


def _build_service(
    *,
    triage_context: IncidentTriageContext,
    review_context: ViolationReviewContext,
    daily_summary_context: DailySummaryContext,
    multimodal_review_context: MultimodalReviewContext | None = None,
    operator_assist_grounding: OperatorAssistGrounding | None = None,
    weekly_summary_context: WeeklySummaryContext | None = None,
    hotspot_report_context: HotspotReportContext | None = None,
) -> tuple[WorkflowService, FakeWorkflowRepository]:
    repository = FakeWorkflowRepository(
        triage_context=triage_context,
        review_context=review_context,
        daily_summary_context=daily_summary_context,
        multimodal_review_context=multimodal_review_context,
        operator_assist_grounding=operator_assist_grounding,
        weekly_summary_context=weekly_summary_context,
        hotspot_report_context=hotspot_report_context,
    )
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        provider_backend="heuristic",
        checkpoint_backend="memory",
        debug=False,
    )
    return WorkflowService(repository=repository, settings=settings), repository


def _operator_assist_hit(
    *,
    camera: StoredCameraRecord,
    violation: StoredViolationEventRecord,
    detection: StoredDetectionEventRecord | None = None,
    plate_read: StoredPlateReadRecord | None = None,
) -> OperatorAssistViolationHit:
    return OperatorAssistViolationHit(
        camera=camera,
        violation_event=violation,
        detection_event=detection,
        plate_read=plate_read,
    )


def _operator_assist_grounding_for_search(
    *,
    camera: StoredCameraRecord,
    violation: StoredViolationEventRecord,
    detection: StoredDetectionEventRecord | None = None,
    plate_read: StoredPlateReadRecord | None = None,
) -> OperatorAssistGrounding:
    hit = _operator_assist_hit(camera=camera, violation=violation, detection=detection, plate_read=plate_read)
    return OperatorAssistGrounding(
        plan=OperatorAssistPlan(
            intent=OperatorAssistIntent.SEARCH_VIOLATIONS,
            raw_query="show all red-light violations from main in the last 2 hours",
            normalized_query="show all red-light violations from main in the last 2 hours",
            camera_hint="main",
            violation_type=ViolationType.RED_LIGHT,
            start_at=NOW - timedelta(hours=2),
            end_at=NOW,
            max_results=10,
            rationale=["test grounding"],
        ),
        camera_matches=[camera],
        violation_hits=[hit],
        total_matches=1,
        references=[
            OperatorAssistReference(
                kind=OperatorAssistReferenceKind.CAMERA,
                reference_id=camera.id,
                label=camera.name,
                camera_id=camera.id,
            ),
            OperatorAssistReference(
                kind=OperatorAssistReferenceKind.VIOLATION_EVENT,
                reference_id=violation.id,
                label=violation.summary or violation.violation_type.value,
                occurred_at=violation.occurred_at,
                camera_id=camera.id,
            ),
        ],
    )


def _operator_assist_event_grounding_for_search(
    *,
    camera: StoredCameraRecord,
    detection: StoredDetectionEventRecord,
) -> OperatorAssistGrounding:
    hit = OperatorAssistEventHit(
        camera=camera,
        detection_event=detection,
        zone_name="restricted-bay-a",
        zone_type=ZoneType.RESTRICTED.value,
    )
    return OperatorAssistGrounding(
        plan=OperatorAssistPlan(
            intent=OperatorAssistIntent.SEARCH_EVENTS,
            raw_query="show line crossing events near junction 4 this morning",
            normalized_query="show line crossing events near junction 4 this morning",
            camera_hint="junction 4",
            start_at=NOW.replace(hour=6, minute=0, second=0, microsecond=0),
            end_at=NOW,
            event_type=detection.event_type,
            object_class=detection.object_class,
            zone_type=ZoneType.RESTRICTED,
            max_results=10,
            rationale=["test event search grounding"],
        ),
        camera_matches=[camera],
        event_hits=[hit],
        total_matches=1,
        supporting_evidence=[
            EvidenceReference(
                label="detection_image",
                source="detection_event",
                uri=detection.image_uri,
                available=True,
            )
        ],
        references=[
            OperatorAssistReference(
                kind=OperatorAssistReferenceKind.CAMERA,
                reference_id=camera.id,
                label=camera.name,
                camera_id=camera.id,
            ),
            OperatorAssistReference(
                kind=OperatorAssistReferenceKind.DETECTION_EVENT,
                reference_id=detection.id,
                label=f"{detection.event_type.value} for {detection.object_class}",
                occurred_at=detection.occurred_at,
                camera_id=camera.id,
                metadata={"zone_type": ZoneType.RESTRICTED.value},
            ),
        ],
    )


def _operator_assist_plate_grounding_for_search(
    *,
    camera: StoredCameraRecord,
    plate_read: StoredPlateReadRecord,
    detection: StoredDetectionEventRecord | None = None,
) -> OperatorAssistGrounding:
    hit = OperatorAssistPlateHit(
        camera=camera,
        plate_read=plate_read,
        detection_event=detection,
    )
    references = [
        OperatorAssistReference(
            kind=OperatorAssistReferenceKind.CAMERA,
            reference_id=camera.id,
            label=camera.name,
            camera_id=camera.id,
        ),
        OperatorAssistReference(
            kind=OperatorAssistReferenceKind.PLATE_READ,
            reference_id=plate_read.id,
            label=f"plate {plate_read.normalized_plate_text}",
            occurred_at=plate_read.occurred_at,
            camera_id=camera.id,
        ),
    ]
    if detection is not None:
        references.append(
            OperatorAssistReference(
                kind=OperatorAssistReferenceKind.DETECTION_EVENT,
                reference_id=detection.id,
                label=f"{detection.event_type.value} for {detection.object_class}",
                occurred_at=detection.occurred_at,
                camera_id=camera.id,
            )
        )
    return OperatorAssistGrounding(
        plan=OperatorAssistPlan(
            intent=OperatorAssistIntent.SEARCH_PLATES,
            raw_query="show plate reads similar to ABC1 in the last 24 hours",
            normalized_query="show plate reads similar to abc1 in the last 24 hours",
            start_at=NOW - timedelta(hours=24),
            end_at=NOW,
            plate_text="ABC1",
            partial_plate=True,
            plate_status=plate_read.status,
            max_results=10,
            rationale=["test plate search grounding"],
        ),
        camera_matches=[camera],
        plate_hits=[hit],
        total_matches=1,
        supporting_evidence=[
            EvidenceReference(
                label="plate_crop",
                source="plate_read",
                uri=plate_read.crop_image_uri,
                available=True,
            )
        ],
        references=references,
    )


def _multimodal_review_context(
    *,
    camera: StoredCameraRecord,
    violation: StoredViolationEventRecord,
    detection: StoredDetectionEventRecord | None = None,
    plate_read: StoredPlateReadRecord | None = None,
    with_media: bool = True,
) -> MultimodalReviewContext:
    image_refs = [
        MultimodalGroundingReference(
            kind=MultimodalGroundingReferenceKind.IMAGE,
            label="violation_image",
            source="violation_event",
            uri=violation.evidence_image_uri,
            available=bool(violation.evidence_image_uri),
            metadata={"role": "key_frame"},
        )
    ] if with_media else []
    clip_refs = [
        MultimodalGroundingReference(
            kind=MultimodalGroundingReferenceKind.CLIP,
            label="violation_clip",
            source="violation_event",
            uri=violation.evidence_video_uri,
            available=bool(violation.evidence_video_uri),
            metadata={"role": "clip_window"},
        )
    ] if with_media else []

    return MultimodalReviewContext(
        camera=camera,
        violation_event=violation,
        detection_event=detection,
        plate_read=plate_read,
        review_context=ReviewContext(
            requested_by="ops.lead",
            operator_notes="Check the signal-state details before closing the case.",
            existing_review_note="Earlier reviewer asked for a wider temporal window.",
            assigned_to="ops.lead",
        ),
        rule_explanation=MultimodalRuleExplanation(
            rule_type="red_light",
            reason="Track T-123 crossed the stop line while the signal state at decision time was red.",
            frame_index=101,
            conditions_satisfied=["track crossed stop line", "signal state was red"],
            salient_details={
                "signal_state_at_decision": "red",
                "track_id": "T-123",
            },
        ),
        metadata_references=[
            MultimodalGroundingReference(
                kind=MultimodalGroundingReferenceKind.METADATA,
                label="violation_metadata",
                source="violation_event",
                available=True,
                metadata={
                    "violation_type": violation.violation_type.value,
                    "severity": violation.severity.value,
                    "status": violation.status.value,
                },
            ),
            MultimodalGroundingReference(
                kind=MultimodalGroundingReferenceKind.METADATA,
                label="rule_explanation",
                source="rule_metadata",
                available=True,
                metadata={"frame_index": 101, "signal_state_at_decision": "red"},
            ),
            MultimodalGroundingReference(
                kind=MultimodalGroundingReferenceKind.METADATA,
                label="operator_notes",
                source="review_context",
                available=True,
                metadata={"text": "Check the signal-state details before closing the case."},
            ),
        ],
        image_references=image_refs,
        clip_references=clip_refs,
        manifest_references=[
            MultimodalGroundingReference(
                kind=MultimodalGroundingReferenceKind.MANIFEST,
                label="violation_manifest",
                source="evidence_manifest",
                uri="evidence-manifest://violation",
                available=True,
                metadata={"asset_count": 4},
            )
        ],
        prior_review_history=[
            PriorReviewRecord(
                source="violation_event",
                recorded_at=NOW - timedelta(minutes=30),
                recorded_by="analyst.a",
                summary="Earlier analyst wanted a wider clip before closing the case.",
                disposition=ViolationStatus.UNDER_REVIEW.value,
                metadata={"status": ViolationStatus.UNDER_REVIEW.value},
            )
        ],
    )


@pytest.mark.asyncio
async def test_incident_triage_workflow_completes_without_interrupt_when_context_is_clear() -> None:
    camera = _camera_record()
    detection = _detection_record(confidence=0.91)
    violation = _violation_record(severity=ViolationSeverity.MEDIUM, evidence=True)
    triage_context = IncidentTriageContext(
        source_kind="violation",
        camera=camera,
        detection_event=detection,
        violation_event=violation,
        plate_read=_plate_record(),
        evidence=[
            EvidenceReference(label="violation_image", source="violation", uri="s3://image.jpg", available=True),
            EvidenceReference(label="violation_clip", source="violation", uri="s3://clip.mp4", available=True),
        ],
    )
    review_context = ViolationReviewContext(
        camera=camera,
        violation_event=violation,
        detection_event=detection,
        plate_read=_plate_record(),
        evidence=triage_context.evidence,
    )
    daily_context = DailySummaryContext(
        report_date=date(2026, 4, 4),
        cameras=[CameraDailySummary(camera_id=camera.id, camera_name=camera.name, location_name=camera.location_name, detection_count=5, violation_count=1, open_violation_count=1)],
        total_detections=5,
        total_violations=1,
        total_open_violations=1,
        top_violation_types={"red_light": 1},
    )
    service, _ = _build_service(
        triage_context=triage_context,
        review_context=review_context,
        daily_summary_context=daily_context,
    )

    response = await service.start_incident_triage(
        IncidentTriageRequest(violation_event_id=violation.id, require_human_review=False)
    )

    assert response.status == WorkflowStatus.SUCCEEDED
    assert response.interrupted is False
    assert response.output is not None
    assert response.output.workflow == "incident_triage"
    assert any(entry.node == "analyze_incident" for entry in response.trace)


@pytest.mark.asyncio
async def test_violation_review_workflow_interrupts_then_resumes() -> None:
    camera = _camera_record()
    detection = _detection_record()
    violation = _violation_record(severity=ViolationSeverity.HIGH, evidence=True)
    triage_context = IncidentTriageContext(
        source_kind="violation",
        camera=camera,
        detection_event=detection,
        violation_event=violation,
        plate_read=_plate_record(),
        evidence=[
            EvidenceReference(label="violation_image", source="violation", uri="s3://image.jpg", available=True),
            EvidenceReference(label="violation_clip", source="violation", uri="s3://clip.mp4", available=True),
        ],
    )
    review_context = ViolationReviewContext(
        camera=camera,
        violation_event=violation,
        detection_event=detection,
        plate_read=_plate_record(),
        evidence=triage_context.evidence,
    )
    daily_context = DailySummaryContext(
        report_date=date(2026, 4, 4),
        cameras=[CameraDailySummary(camera_id=camera.id, camera_name=camera.name, location_name=camera.location_name, detection_count=8, violation_count=3, open_violation_count=2)],
        total_detections=8,
        total_violations=3,
        total_open_violations=2,
        top_violation_types={"red_light": 3},
    )
    service, repository = _build_service(
        triage_context=triage_context,
        review_context=review_context,
        daily_summary_context=daily_context,
    )

    first = await service.start_violation_review(
        ViolationReviewRequest(violation_event_id=violation.id, requested_by="ops.lead")
    )

    assert first.status == WorkflowStatus.RUNNING
    assert first.interrupted is True
    assert first.interrupt_request is not None
    assert first.output is None

    resumed = await service.resume_workflow(
        first.run_id,
        WorkflowResumeRequest(approved=True, reviewer="analyst.a", note="Evidence looks consistent."),
    )

    assert resumed.status == WorkflowStatus.SUCCEEDED
    assert resumed.interrupted is False
    assert resumed.output is not None
    assert resumed.output.workflow == "violation_review"
    assert resumed.output.disposition.value == "confirm_violation"

    stored = await repository.get_workflow_run(first.run_id)
    assert stored.status == WorkflowStatus.SUCCEEDED

    assert hasattr(repository, "last_disposition")
    assert repository.last_disposition["violation_event_id"] == violation.id
    assert repository.last_disposition["new_status"] == ViolationStatus.CONFIRMED


@pytest.mark.asyncio
async def test_violation_review_skips_interrupt_when_human_approval_not_required() -> None:
    camera = _camera_record()
    violation = _violation_record(severity=ViolationSeverity.HIGH, evidence=True)
    review_context = ViolationReviewContext(
        camera=camera,
        violation_event=violation,
        detection_event=_detection_record(),
        plate_read=_plate_record(),
        evidence=[EvidenceReference(label="violation_image", source="violation", uri="s3://img.jpg", available=True)],
    )
    service, repository = _build_service(
        triage_context=IncidentTriageContext(
            source_kind="violation", camera=camera, violation_event=violation,
            evidence=[EvidenceReference(label="v", source="v", uri="s3://v", available=True)],
        ),
        review_context=review_context,
        daily_summary_context=DailySummaryContext(report_date=date(2026, 4, 4)),
    )

    result = await service.start_violation_review(
        ViolationReviewRequest(
            violation_event_id=violation.id,
            requested_by="auto",
            require_human_approval=False,
        )
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.interrupted is False
    assert result.output is not None
    assert result.output.workflow == "violation_review"
    assert hasattr(repository, "last_disposition")


@pytest.mark.asyncio
async def test_multimodal_review_workflow_returns_grounded_advisory_output() -> None:
    camera = _camera_record()
    detection = _detection_record()
    plate = _plate_record()
    violation = _violation_record(severity=ViolationSeverity.HIGH, evidence=True)
    multimodal_context = _multimodal_review_context(
        camera=camera,
        violation=violation,
        detection=detection,
        plate_read=plate,
        with_media=True,
    )
    service, repository = _build_service(
        triage_context=IncidentTriageContext(
            source_kind="violation",
            camera=camera,
            detection_event=detection,
            violation_event=violation,
            plate_read=plate,
            evidence=[EvidenceReference(label="violation_image", source="violation", uri="s3://img.jpg", available=True)],
        ),
        review_context=ViolationReviewContext(
            camera=camera,
            violation_event=violation,
            detection_event=detection,
            plate_read=plate,
            evidence=[EvidenceReference(label="violation_image", source="violation", uri="s3://img.jpg", available=True)],
        ),
        daily_summary_context=DailySummaryContext(report_date=date(2026, 4, 4)),
        multimodal_review_context=multimodal_context,
    )

    result = await service.start_multimodal_review(
        MultimodalReviewRequest(
            violation_event_id=violation.id,
            requested_by="ops.lead",
            operator_notes="Verify the clip before closing.",
        )
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.interrupted is False
    assert result.output is not None
    assert result.output.workflow == "multimodal_review"
    assert result.output.image_references
    assert result.output.clip_references
    assert result.output.manifest_references
    assert "red" in result.output.likely_cause.lower()
    assert result.output.recommended_operator_action
    assert any("advisory" in note.lower() for note in result.output.audit_notes)
    assert not hasattr(repository, "last_disposition")


@pytest.mark.asyncio
async def test_multimodal_review_workflow_calls_out_metadata_only_cases() -> None:
    camera = _camera_record()
    detection = _detection_record(confidence=0.62)
    violation = _violation_record(severity=ViolationSeverity.HIGH, evidence=False)
    multimodal_context = _multimodal_review_context(
        camera=camera,
        violation=violation,
        detection=detection,
        plate_read=None,
        with_media=False,
    )
    service, _ = _build_service(
        triage_context=IncidentTriageContext(source_kind="violation", camera=camera, violation_event=violation),
        review_context=ViolationReviewContext(camera=camera, violation_event=violation, detection_event=detection),
        daily_summary_context=DailySummaryContext(report_date=date(2026, 4, 4)),
        multimodal_review_context=multimodal_context,
    )

    result = await service.start_multimodal_review(
        MultimodalReviewRequest(violation_event_id=violation.id)
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output is not None
    assert result.output.workflow == "multimodal_review"
    assert result.output.image_references == []
    assert result.output.clip_references == []
    assert any("no attached images or clips" in item.lower() for item in result.output.confidence_caveats)
    assert "request" in result.output.recommended_operator_action.lower()
    assert result.output.escalation_suggestion is not None


@pytest.mark.asyncio
async def test_multimodal_review_workflow_distinguishes_manifest_media_from_direct_attachments() -> None:
    camera = _camera_record()
    detection = _detection_record()
    violation = _violation_record(severity=ViolationSeverity.HIGH, evidence=False)
    multimodal_context = _multimodal_review_context(
        camera=camera,
        violation=violation,
        detection=detection,
        plate_read=None,
        with_media=False,
    ).model_copy(
        update={
            "image_references": [
                MultimodalGroundingReference(
                    kind=MultimodalGroundingReferenceKind.IMAGE,
                    label="key_frame_snapshot",
                    source="evidence_manifest_asset",
                    uri="evidence://planned/frame-101.jpg",
                    available=True,
                )
            ],
            "clip_references": [
                MultimodalGroundingReference(
                    kind=MultimodalGroundingReferenceKind.CLIP,
                    label="clip_window",
                    source="evidence_manifest_asset",
                    uri="evidence://planned/clip-101.mp4",
                    available=True,
                )
            ],
        }
    )
    service, _ = _build_service(
        triage_context=IncidentTriageContext(source_kind="violation", camera=camera, violation_event=violation),
        review_context=ViolationReviewContext(camera=camera, violation_event=violation, detection_event=detection),
        daily_summary_context=DailySummaryContext(report_date=date(2026, 4, 4)),
        multimodal_review_context=multimodal_context,
    )

    result = await service.start_multimodal_review(
        MultimodalReviewRequest(violation_event_id=violation.id)
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output is not None
    assert "manifest-linked media references" in result.output.review_summary.lower()
    assert "attached images and clips" not in result.output.review_summary.lower()
    assert any("direct attached media available: none" in note.lower() for note in result.output.audit_notes)
    assert any("manifest-linked media available: key_frame_snapshot, clip_window" in note.lower() for note in result.output.audit_notes)


@pytest.mark.asyncio
async def test_daily_summary_workflow_can_pause_for_human_approval() -> None:
    camera = _camera_record()
    detection = _detection_record()
    violation = _violation_record(severity=ViolationSeverity.HIGH)
    triage_context = IncidentTriageContext(
        source_kind="violation",
        camera=camera,
        detection_event=detection,
        violation_event=violation,
        plate_read=_plate_record(),
        evidence=[EvidenceReference(label="violation_image", source="violation", uri="s3://img.jpg", available=True)],
    )
    review_context = ViolationReviewContext(
        camera=camera,
        violation_event=violation,
        detection_event=detection,
        plate_read=_plate_record(),
        evidence=triage_context.evidence,
    )
    daily_context = DailySummaryContext(
        report_date=date(2026, 4, 4),
        cameras=[
            CameraDailySummary(
                camera_id=camera.id,
                camera_name=camera.name,
                location_name=camera.location_name,
                detection_count=14,
                violation_count=4,
                open_violation_count=2,
                top_violation_types={"red_light": 3, "stop_line": 1},
                last_incident_at=NOW,
            )
        ],
        total_detections=14,
        total_violations=4,
        total_open_violations=2,
        top_violation_types={"red_light": 3, "stop_line": 1},
        review_backlog=ReviewBacklog(open_violations=2, under_review_violations=1, avg_review_hours=4.5),
        watchlist=WatchlistSection(total_alerts=2, open_alerts=1, top_reasons={"wanted": 1, "bolo": 1}),
        camera_health_concerns=[
            CameraHealthConcern(
                camera_id=camera.id,
                camera_name=camera.name,
                concern="Camera status is maintenance.",
            )
        ],
    )
    service, _ = _build_service(
        triage_context=triage_context,
        review_context=review_context,
        daily_summary_context=daily_context,
    )

    first = await service.start_daily_summary(
        DailySummaryRequest(report_date=date(2026, 4, 4), require_human_approval=True)
    )

    assert first.interrupted is True
    assert first.interrupt_request is not None

    resumed = await service.resume_workflow(
        first.run_id,
        WorkflowResumeRequest(approved=False, reviewer="supervisor.b", note="Revise before circulation."),
    )

    assert resumed.status == WorkflowStatus.SUCCEEDED
    assert resumed.output is not None
    assert resumed.output.workflow == "daily_summary"
    assert "Publication held" in resumed.output.narrative
    assert resumed.output.review_backlog.open_violations == 2
    assert resumed.output.watchlist.open_alerts == 1
    assert len(resumed.output.camera_health_concerns) == 1
    assert resumed.output.generated_at.tzinfo is not None
    assert resumed.output.scope_notes
    assert "# Daily Summary" in resumed.output.markdown
    assert "## Publication Status" in resumed.output.markdown


@pytest.mark.asyncio
async def test_daily_summary_workflow_emits_structured_markdown() -> None:
    camera = _camera_record()
    violation = _violation_record(severity=ViolationSeverity.HIGH)
    service, _ = _build_service(
        triage_context=IncidentTriageContext(source_kind="violation", camera=camera, violation_event=violation),
        review_context=ViolationReviewContext(camera=camera, violation_event=violation),
        daily_summary_context=DailySummaryContext(
            report_date=date(2026, 4, 4),
            cameras=[
                CameraDailySummary(
                    camera_id=camera.id,
                    camera_name=camera.name,
                    location_name=camera.location_name,
                    detection_count=7,
                    violation_count=2,
                    open_violation_count=1,
                    top_violation_types={"red_light": 2},
                )
            ],
            total_detections=7,
            total_violations=2,
            total_open_violations=1,
            top_violation_types={"red_light": 2},
            review_backlog=ReviewBacklog(open_violations=1, under_review_violations=0),
        ),
    )

    response = await service.start_daily_summary(
        DailySummaryRequest(report_date=date(2026, 4, 4), require_human_approval=False)
    )

    assert response.status == WorkflowStatus.SUCCEEDED
    assert response.output is not None
    assert response.output.workflow == "daily_summary"
    assert response.output.generated_at.tzinfo is not None
    assert response.output.scope_notes
    assert "current system state" in response.output.scope_notes[0]
    assert "## Key Totals" in response.output.markdown
    assert "## Scope Notes" in response.output.markdown
    assert "## Review Backlog" in response.output.markdown
    assert response.output.data_gaps == []


@pytest.mark.asyncio
async def test_operator_assist_workflow_returns_grounded_violation_search() -> None:
    camera = _camera_record()
    detection = _detection_record()
    violation = _violation_record(severity=ViolationSeverity.HIGH, evidence=True)
    grounding = _operator_assist_grounding_for_search(
        camera=camera,
        violation=violation,
        detection=detection,
        plate_read=_plate_record(),
    )
    service, _repository = _build_service(
        triage_context=IncidentTriageContext(source_kind="violation", camera=camera, violation_event=violation),
        review_context=ViolationReviewContext(camera=camera, violation_event=violation),
        daily_summary_context=DailySummaryContext(report_date=date(2026, 4, 4)),
        operator_assist_grounding=grounding,
    )

    response = await service.start_operator_assist(
        OperatorAssistRequest(
            query="show all red-light violations from main in the last 2 hours",
            requested_by="ops.lead",
            require_human_review=False,
        )
    )

    assert response.status == WorkflowStatus.SUCCEEDED
    assert response.output is not None
    assert response.output.workflow == "operator_assist"
    assert response.output.intent == OperatorAssistIntent.SEARCH_VIOLATIONS
    assert response.output.grounded is True
    assert response.output.matched_record_count == 1
    assert response.output.interpretation_notes
    assert response.output.filters_applied["resolved_camera_ids"] == [str(camera.id)]
    assert any(ref.reference_id == violation.id for ref in response.output.references)
    assert {entry.node for entry in response.trace} >= {"plan_query", "retrieve_grounding", "compose_answer"}


@pytest.mark.asyncio
async def test_operator_assist_workflow_reports_total_match_count_when_results_are_limited() -> None:
    camera = _camera_record()
    violation = _violation_record(severity=ViolationSeverity.HIGH, evidence=True)
    grounding = _operator_assist_grounding_for_search(camera=camera, violation=violation).model_copy(
        update={"total_matches": 4}
    )
    service, _repository = _build_service(
        triage_context=IncidentTriageContext(source_kind="violation", camera=camera, violation_event=violation),
        review_context=ViolationReviewContext(camera=camera, violation_event=violation),
        daily_summary_context=DailySummaryContext(report_date=date(2026, 4, 4)),
        operator_assist_grounding=grounding,
    )

    response = await service.start_operator_assist(
        OperatorAssistRequest(
            query="show all red-light violations from main in the last 2 hours",
            requested_by="ops.lead",
        )
    )

    assert response.status == WorkflowStatus.SUCCEEDED
    assert response.output is not None
    assert response.output.matched_record_count == 4
    assert "Showing 1 most recent matches" in response.output.answer


@pytest.mark.asyncio
async def test_operator_assist_workflow_returns_grounded_event_search() -> None:
    camera = _camera_record()
    detection = _detection_record()
    grounding = _operator_assist_event_grounding_for_search(camera=camera, detection=detection)
    service, _repository = _build_service(
        triage_context=IncidentTriageContext(source_kind="detection", camera=camera, detection_event=detection),
        review_context=ViolationReviewContext(camera=camera, violation_event=_violation_record()),
        daily_summary_context=DailySummaryContext(report_date=date(2026, 4, 4)),
        operator_assist_grounding=grounding,
    )

    response = await service.start_operator_assist(
        OperatorAssistRequest(
            query="show line crossing events near junction 4 this morning",
            requested_by="ops.lead",
        )
    )

    assert response.status == WorkflowStatus.SUCCEEDED
    assert response.output is not None
    assert response.output.intent == OperatorAssistIntent.SEARCH_EVENTS
    assert response.output.grounded is True
    assert response.output.matched_record_count == 1
    assert response.output.supporting_evidence
    assert any(ref.reference_id == detection.id for ref in response.output.references)


@pytest.mark.asyncio
async def test_operator_assist_workflow_returns_grounded_plate_search() -> None:
    camera = _camera_record()
    detection = _detection_record()
    plate = _plate_record()
    grounding = _operator_assist_plate_grounding_for_search(camera=camera, plate_read=plate, detection=detection)
    service, _repository = _build_service(
        triage_context=IncidentTriageContext(source_kind="detection", camera=camera, detection_event=detection, plate_read=plate),
        review_context=ViolationReviewContext(camera=camera, violation_event=_violation_record(), detection_event=detection, plate_read=plate),
        daily_summary_context=DailySummaryContext(report_date=date(2026, 4, 4)),
        operator_assist_grounding=grounding,
    )

    response = await service.start_operator_assist(
        OperatorAssistRequest(
            query="show plate reads similar to ABC1 in the last 24 hours",
            requested_by="ops.lead",
        )
    )

    assert response.status == WorkflowStatus.SUCCEEDED
    assert response.output is not None
    assert response.output.intent == OperatorAssistIntent.SEARCH_PLATES
    assert response.output.grounded is True
    assert response.output.matched_record_count == 1
    assert response.output.interpretation_notes
    assert any(ref.reference_id == plate.id for ref in response.output.references)


@pytest.mark.asyncio
async def test_operator_assist_workflow_escalates_when_explanation_lacks_anchor() -> None:
    camera = _camera_record()
    violation = _violation_record(severity=ViolationSeverity.HIGH, evidence=True)
    service, _repository = _build_service(
        triage_context=IncidentTriageContext(source_kind="violation", camera=camera, violation_event=violation),
        review_context=ViolationReviewContext(camera=camera, violation_event=violation),
        daily_summary_context=DailySummaryContext(report_date=date(2026, 4, 4)),
    )

    response = await service.start_operator_assist(
        OperatorAssistRequest(query="why was this pedestrian-on-red alert fired", requested_by="ops.lead")
    )

    assert response.status == WorkflowStatus.SUCCEEDED
    assert response.output is not None
    assert response.output.intent == OperatorAssistIntent.EXPLAIN_VIOLATION
    assert response.output.requires_human_review is True
    assert response.output.grounded is False
    assert "violation_event_id" in (response.output.escalation_reason or "")


@pytest.mark.asyncio
async def test_operator_assist_workflow_summarizes_repeated_incidents() -> None:
    camera = _camera_record()
    violation = _violation_record(severity=ViolationSeverity.HIGH, evidence=True)
    grounding = OperatorAssistGrounding(
        plan=OperatorAssistPlan(
            intent=OperatorAssistIntent.SUMMARIZE_REPEATED_INCIDENTS,
            raw_query="summarize repeated incidents at this junction",
            normalized_query="summarize repeated incidents at this junction",
            start_at=NOW - timedelta(days=7),
            end_at=NOW,
            max_results=10,
            rationale=["test summary grounding"],
        ),
        camera_matches=[camera],
        incident_summaries=[
            RepeatedIncidentSummary(
                camera=camera,
                violation_type=ViolationType.RED_LIGHT,
                incident_count=4,
                open_count=2,
                last_occurred_at=NOW,
                sample_violation_event_ids=[violation.id],
            )
        ],
        references=[
            OperatorAssistReference(
                kind=OperatorAssistReferenceKind.CAMERA,
                reference_id=camera.id,
                label=camera.location_name,
                camera_id=camera.id,
            ),
            OperatorAssistReference(
                kind=OperatorAssistReferenceKind.VIOLATION_EVENT,
                reference_id=violation.id,
                label="sample red_light violation",
                occurred_at=violation.occurred_at,
                camera_id=camera.id,
            ),
        ],
    )
    service, _repository = _build_service(
        triage_context=IncidentTriageContext(source_kind="violation", camera=camera, violation_event=violation),
        review_context=ViolationReviewContext(camera=camera, violation_event=violation),
        daily_summary_context=DailySummaryContext(report_date=date(2026, 4, 4)),
        operator_assist_grounding=grounding,
    )

    response = await service.start_operator_assist(
        OperatorAssistRequest(
            query="summarize repeated incidents at this junction",
            camera_id=camera.id,
            requested_by="ops.lead",
        )
    )

    assert response.status == WorkflowStatus.SUCCEEDED
    assert response.output is not None
    assert response.output.intent == OperatorAssistIntent.SUMMARIZE_REPEATED_INCIDENTS
    assert response.output.grounded is True
    assert response.output.matched_record_count == 4
    assert any(ref.reference_id == violation.id for ref in response.output.references)


@pytest.mark.asyncio
async def test_operator_assist_require_human_review_propagates_from_request() -> None:
    camera = _camera_record()
    violation = _violation_record(severity=ViolationSeverity.HIGH, evidence=True)
    grounding = _operator_assist_grounding_for_search(
        camera=camera,
        violation=violation,
    )
    service, _repository = _build_service(
        triage_context=IncidentTriageContext(source_kind="violation", camera=camera, violation_event=violation),
        review_context=ViolationReviewContext(camera=camera, violation_event=violation),
        daily_summary_context=DailySummaryContext(report_date=date(2026, 4, 4)),
        operator_assist_grounding=grounding,
    )

    response = await service.start_operator_assist(
        OperatorAssistRequest(
            query="show all red-light violations from main in the last 2 hours",
            requested_by="ops.lead",
            require_human_review=True,
        )
    )

    assert response.status == WorkflowStatus.SUCCEEDED
    assert response.output is not None
    assert response.output.requires_human_review is True
    assert response.output.escalation_reason is not None


@pytest.mark.asyncio
async def test_operator_assist_grounded_false_when_camera_hint_unresolved() -> None:
    camera = _camera_record()
    violation = _violation_record(severity=ViolationSeverity.HIGH)
    grounding = OperatorAssistGrounding(
        plan=OperatorAssistPlan(
            intent=OperatorAssistIntent.SEARCH_VIOLATIONS,
            raw_query="show red-light violations from nonexistent camera",
            normalized_query="show red-light violations from nonexistent camera",
            camera_hint="nonexistent camera",
            violation_type=ViolationType.RED_LIGHT,
            start_at=NOW - timedelta(hours=2),
            end_at=NOW,
            max_results=10,
            rationale=["test"],
        ),
        camera_matches=[],
        violation_hits=[],
        references=[],
        grounding_notes=["No stored camera matched the hint 'nonexistent camera'."],
    )
    service, _repository = _build_service(
        triage_context=IncidentTriageContext(source_kind="violation", camera=camera, violation_event=violation),
        review_context=ViolationReviewContext(camera=camera, violation_event=violation),
        daily_summary_context=DailySummaryContext(report_date=date(2026, 4, 4)),
        operator_assist_grounding=grounding,
    )

    response = await service.start_operator_assist(
        OperatorAssistRequest(
            query="show red-light violations from nonexistent camera",
            requested_by="ops.lead",
        )
    )

    assert response.status == WorkflowStatus.SUCCEEDED
    assert response.output is not None
    assert response.output.grounded is False
    assert response.output.matched_record_count == 0
    assert response.output.requires_human_review is True


def test_workflow_app_exposes_health_and_execution_routes() -> None:
    camera = _camera_record()
    detection = _detection_record()
    violation = _violation_record(severity=ViolationSeverity.MEDIUM)
    triage_context = IncidentTriageContext(
        source_kind="violation",
        camera=camera,
        detection_event=detection,
        violation_event=violation,
        plate_read=_plate_record(),
        evidence=[EvidenceReference(label="violation_image", source="violation", uri="s3://img.jpg", available=True)],
    )
    review_context = ViolationReviewContext(
        camera=camera,
        violation_event=violation,
        detection_event=detection,
        plate_read=_plate_record(),
        evidence=triage_context.evidence,
    )
    multimodal_context = _multimodal_review_context(
        camera=camera,
        violation=violation,
        detection=detection,
        plate_read=_plate_record(),
        with_media=True,
    )
    daily_context = DailySummaryContext(
        report_date=date(2026, 4, 4),
        cameras=[CameraDailySummary(camera_id=camera.id, camera_name=camera.name, location_name=camera.location_name, detection_count=3, violation_count=1, open_violation_count=1)],
        total_detections=3,
        total_violations=1,
        total_open_violations=1,
        top_violation_types={"red_light": 1},
    )
    service, _ = _build_service(
        triage_context=triage_context,
        review_context=review_context,
        daily_summary_context=daily_context,
        multimodal_review_context=multimodal_context,
        hotspot_report_context=HotspotReportContext(
            report_date=date(2026, 4, 4),
            lookback_days=7,
            top_n=3,
            group_by=HotspotGroupBy.ZONE,
            hotspots=[
                HotspotEntry(
                    camera_id=camera.id,
                    camera_name=camera.name,
                    location_name=f"{camera.location_name} / stop-line-a",
                    zone_id=uuid.uuid4(),
                    zone_name="stop-line-a",
                    zone_type=ZoneType.STOP_LINE.value,
                    violation_count=2,
                    open_count=1,
                    top_violation_types={"red_light": 2},
                )
            ],
            total_violations_in_window=2,
            total_groups_with_violations=1,
            total_cameras_with_violations=1,
        ),
    )
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:", provider_backend="heuristic")
    client = TestClient(create_app(service=service, settings=settings))

    health_response = client.get("/api/v1/health")
    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok"}

    readiness_response = client.get("/api/v1/health/ready")
    assert readiness_response.status_code == 200
    assert readiness_response.json()["service"] == "workflow"
    assert readiness_response.json()["status"] == "ready"

    summary_response = client.post(
        "/api/v1/workflows/daily-summary",
        json={"report_date": "2026-04-04", "require_human_approval": False},
    )
    assert summary_response.status_code == 201
    assert summary_response.json()["workflow_name"] == "daily_summary"
    assert summary_response.json()["status"] == "succeeded"
    assert summary_response.json()["output"]["markdown"].startswith("# Daily Summary")

    hotspot_response = client.post(
        "/api/v1/workflows/hotspot-report",
        json={"report_date": "2026-04-04", "group_by": "zone", "require_human_approval": False},
    )
    assert hotspot_response.status_code == 201
    assert hotspot_response.json()["workflow_name"] == "hotspot_report"
    assert hotspot_response.json()["output"]["group_by"] == "zone"

    assist_response = client.post(
        "/api/v1/workflows/operator-assist",
        json={"query": "show all red-light violations", "requested_by": "ops.lead"},
    )
    assert assist_response.status_code == 201
    assert assist_response.json()["workflow_name"] == "operator_assist"
    assert assist_response.json()["status"] == "succeeded"

    multimodal_response = client.post(
        "/api/v1/workflows/multimodal-review",
        json={"violation_event_id": str(violation.id), "requested_by": "ops.lead"},
    )
    assert multimodal_response.status_code == 201
    assert multimodal_response.json()["workflow_name"] == "multimodal_review"
    assert multimodal_response.json()["status"] == "succeeded"


def test_violation_review_interrupt_and_resume_via_http() -> None:
    """Full HTTP round-trip: start violation review → interrupt → GET run → resume → succeeded."""
    camera = _camera_record()
    detection = _detection_record()
    violation = _violation_record(severity=ViolationSeverity.HIGH, evidence=True)
    triage_context = IncidentTriageContext(
        source_kind="violation",
        camera=camera,
        detection_event=detection,
        violation_event=violation,
        evidence=[EvidenceReference(label="img", source="v", uri="s3://img.jpg", available=True)],
    )
    review_context = ViolationReviewContext(
        camera=camera,
        violation_event=violation,
        detection_event=detection,
        plate_read=_plate_record(),
        evidence=triage_context.evidence,
    )
    daily_context = DailySummaryContext(report_date=date(2026, 4, 4))
    service, _ = _build_service(
        triage_context=triage_context,
        review_context=review_context,
        daily_summary_context=daily_context,
    )
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:", provider_backend="heuristic")
    client = TestClient(create_app(service=service, settings=settings))

    # Step 1: start violation review — should interrupt
    start_resp = client.post(
        "/api/v1/workflows/violation-review",
        json={"violation_event_id": str(violation.id), "requested_by": "ops.lead"},
    )
    assert start_resp.status_code == 201
    body = start_resp.json()
    assert body["status"] == "running"
    assert body["interrupted"] is True
    assert body["interrupt_request"] is not None
    assert body["output"] is None
    run_id = body["run_id"]

    # Step 2: GET the run — still running
    get_resp = client.get(f"/api/v1/workflows/runs/{run_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["status"] == "running"
    assert get_resp.json()["interrupted"] is True

    # Step 3: resume with approval
    resume_resp = client.post(
        f"/api/v1/workflows/runs/{run_id}/resume",
        json={"approved": True, "reviewer": "analyst.a", "note": "Looks good."},
    )
    assert resume_resp.status_code == 200
    resumed = resume_resp.json()
    assert resumed["status"] == "succeeded"
    assert resumed["interrupted"] is False
    assert resumed["output"] is not None
    assert resumed["output"]["workflow"] == "violation_review"
    assert resumed["output"]["disposition"] == "confirm_violation"

    # Step 4: GET the run again — should be succeeded
    final_resp = client.get(f"/api/v1/workflows/runs/{run_id}")
    assert final_resp.status_code == 200
    assert final_resp.json()["status"] == "succeeded"


def test_workflow_strict_startup_checks_fail_for_prod_like_settings() -> None:
    camera = _camera_record()
    violation = _violation_record()
    triage_context = IncidentTriageContext(source_kind="violation", camera=camera, violation_event=violation)
    review_context = ViolationReviewContext(camera=camera, violation_event=violation)
    daily_context = DailySummaryContext(report_date=date(2026, 4, 4))
    service, _ = _build_service(
        triage_context=triage_context,
        review_context=review_context,
        daily_summary_context=daily_context,
    )
    settings = Settings(
        environment="prod",
        strict_startup_checks=True,
        database_url="sqlite+aiosqlite:///:memory:",
        provider_backend="heuristic",
        checkpoint_backend="memory",
    )

    with (
        pytest.raises(RuntimeError, match="Workflow startup readiness checks failed"),
        TestClient(create_app(service=service, settings=settings)),
    ):
        pass


def test_workflow_strict_startup_checks_fail_when_database_probe_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_probe_database_connectivity(_: str) -> tuple[bool, str]:
        return False, "Database connectivity probe failed: unavailable"

    monkeypatch.setattr(
        "apps.workflow.app.main.probe_database_connectivity",
        fake_probe_database_connectivity,
    )
    camera = _camera_record()
    violation = _violation_record()
    triage_context = IncidentTriageContext(
        source_kind="violation",
        camera=camera,
        violation_event=violation,
    )
    review_context = ViolationReviewContext(camera=camera, violation_event=violation)
    daily_context = DailySummaryContext(report_date=date(2026, 4, 4))
    service, _ = _build_service(
        triage_context=triage_context,
        review_context=review_context,
        daily_summary_context=daily_context,
    )
    settings = Settings(
        environment="dev",
        strict_startup_checks=True,
        database_url="postgresql+asyncpg://trafficmind:change-me@db-host:5432/trafficmind",
        provider_backend="heuristic",
        checkpoint_backend="memory",
    )

    with (
        pytest.raises(RuntimeError, match="Workflow startup readiness checks failed"),
        TestClient(create_app(service=service, settings=settings)),
    ):
        pass


async def _seed_repository_data(session_factory: async_sessionmaker) -> tuple[uuid.UUID, date]:
    occurred_at = NOW
    async with session_factory() as session:
        camera = Camera(
            camera_code="CAM-201",
            name="King Fahd Northbound",
            location_name="King Fahd & Olaya",
            approach="northbound",
            timezone="UTC",
            status=CameraStatus.ACTIVE,
            latitude=24.7123,
            longitude=46.6741,
            calibration_config={},
        )
        stream = CameraStream(
            camera=camera,
            name="primary",
            stream_kind=StreamKind.PRIMARY,
            source_type=SourceType.RTSP,
            source_uri="rtsp://trafficmind.local/cam-201",
            source_config={},
            status=StreamStatus.LIVE,
        )
        zone = Zone(
            camera=camera,
            name="stop-line-a",
            zone_type=ZoneType.STOP_LINE,
            status=ZoneStatus.ACTIVE,
            geometry={"start": {"x": 10, "y": 10}, "end": {"x": 100, "y": 10}},
            rules_config={"rules": [{"rule_type": "red_light"}]},
        )
        detection = DetectionEvent(
            camera=camera,
            stream=stream,
            zone=zone,
            event_type=DetectionEventType.LINE_CROSSING,
            occurred_at=occurred_at,
            frame_index=22,
            track_id="T-9",
            object_class="car",
            confidence=0.93,
            bbox={"x1": 100, "y1": 100, "x2": 200, "y2": 220},
            event_payload={"direction": "northbound"},
            image_uri="s3://events/frame.jpg",
            video_uri="s3://events/clip.mp4",
        )
        plate = PlateRead(
            camera=camera,
            stream=stream,
            detection_event=detection,
            status=PlateReadStatus.OBSERVED,
            occurred_at=occurred_at,
            plate_text="XYZ1234",
            normalized_plate_text="XYZ1234",
            confidence=0.89,
            country_code="SA",
            region_code="RUH",
            bbox={"x1": 110, "y1": 140, "x2": 180, "y2": 190},
            crop_image_uri="s3://events/plate.jpg",
            source_frame_uri="s3://events/source.jpg",
            ocr_metadata={"engine": "paddleocr"},
        )
        violation = ViolationEvent(
            camera=camera,
            stream=stream,
            zone=zone,
            detection_event=detection,
            plate_read=plate,
            violation_type=ViolationType.RED_LIGHT,
            severity=ViolationSeverity.HIGH,
            status=ViolationStatus.OPEN,
            occurred_at=occurred_at,
            summary="Vehicle crossed on red.",
            evidence_image_uri="s3://violations/image.jpg",
            evidence_video_uri="s3://violations/clip.mp4",
            rule_metadata={"rule_type": "red_light", "frame_index": 22},
        )
        session.add_all([camera, stream, zone, detection, plate, violation])
        await session.commit()
        await build_violation_evidence_manifest(session, violation.id)
        await session.commit()
        return violation.id, occurred_at.date()


@pytest.mark.asyncio
async def test_sqlalchemy_repository_builds_violation_context_and_run_records() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    violation_id, report_date = await _seed_repository_data(session_factory)
    repository = SqlAlchemyWorkflowRepository(session_factory)

    context = await repository.build_violation_review_context(
        ViolationReviewRequest(violation_event_id=violation_id, requested_by="ops.lead")
    )
    assert context.camera.location_name == "King Fahd & Olaya"
    assert context.violation_event.violation_type == ViolationType.RED_LIGHT
    assert any(item.available for item in context.evidence)
    assert any(item.label == "violation_manifest" for item in context.evidence)

    run = await repository.create_workflow_run(
        workflow_name=WorkflowName.VIOLATION_REVIEW,
        workflow_type=WorkflowType.REVIEW,
        requested_by="ops.lead",
        input_payload={"violation_event_id": str(violation_id)},
        camera_id=context.camera.id,
        violation_event_id=violation_id,
    )
    updated = await repository.update_workflow_run(
        run.id,
        status=WorkflowStatus.SUCCEEDED,
        result_payload={"workflow_name": WorkflowName.VIOLATION_REVIEW.value, "interrupted": False},
        completed_at=NOW,
    )
    stored = await repository.get_workflow_run(run.id)

    assert updated.status == WorkflowStatus.SUCCEEDED
    assert stored.result_payload is not None
    assert stored.result_payload["workflow_name"] == "violation_review"

    daily_context = await repository.build_daily_summary_context(
        DailySummaryRequest(report_date=report_date)
    )
    assert daily_context.total_violations == 1
    assert daily_context.total_detections == 1
    assert daily_context.review_backlog.open_violations == 1
    assert daily_context.watchlist.data_available is True

    async with session_factory() as session:
        reviewed_violation = await session.get(ViolationEvent, violation_id)
        assert reviewed_violation is not None
        reviewed_violation.status = ViolationStatus.CONFIRMED
        reviewed_violation.reviewed_by = "ops.lead"
        reviewed_violation.reviewed_at = NOW + timedelta(hours=2)
        await session.commit()

    weekly_context = await repository.build_weekly_summary_context(
        WeeklySummaryRequest(week_ending=report_date)
    )
    assert weekly_context.review_backlog.avg_review_hours == 2.0

    hotspot_zone_context = await repository.build_hotspot_report_context(
        HotspotReportRequest(report_date=report_date, group_by=HotspotGroupBy.ZONE)
    )
    assert hotspot_zone_context.group_by == HotspotGroupBy.ZONE
    assert hotspot_zone_context.total_violations_in_window == 1
    assert hotspot_zone_context.total_groups_with_violations == 1
    assert hotspot_zone_context.total_cameras_with_violations == 1
    assert hotspot_zone_context.hotspots[0].zone_name == "stop-line-a"
    assert hotspot_zone_context.hotspots[0].zone_type == ZoneType.STOP_LINE.value

    await repository.apply_violation_disposition(
        violation_id,
        new_status=ViolationStatus.CONFIRMED,
        reviewed_by="ops.lead",
        review_note="Confirmed via workflow.",
    )
    async with session_factory() as session:
        updated_violation = await session.get(ViolationEvent, violation_id)
        assert updated_violation is not None
        assert updated_violation.status == ViolationStatus.CONFIRMED
        assert updated_violation.reviewed_by == "ops.lead"
        assert updated_violation.reviewed_at is not None

    await engine.dispose()


@pytest.mark.asyncio
async def test_sqlalchemy_repository_builds_operator_assist_grounding() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    violation_id, report_date = await _seed_repository_data(session_factory)
    repository = SqlAlchemyWorkflowRepository(session_factory)

    search_request = OperatorAssistRequest(
        query="show all red-light violations from king fahd in the last 2 hours",
        max_results=10,
    )
    search_plan = plan_operator_assist_request(search_request, now=NOW + timedelta(minutes=30))
    search_grounding = await repository.build_operator_assist_grounding(search_request, search_plan)

    assert len(search_grounding.violation_hits) == 1
    assert search_grounding.total_matches == 1
    assert search_grounding.violation_hits[0].violation_event.id == violation_id
    assert any(ref.kind == OperatorAssistReferenceKind.VIOLATION_EVENT for ref in search_grounding.references)
    assert search_grounding.supporting_evidence
    assert any(item.metadata.get("subject_id") == str(violation_id) for item in search_grounding.supporting_evidence)

    event_request = OperatorAssistRequest(
        query="show line crossing events at king fahd in the last 2 hours",
        max_results=10,
    )
    event_plan = plan_operator_assist_request(event_request, now=NOW + timedelta(minutes=30))
    event_grounding = await repository.build_operator_assist_grounding(event_request, event_plan)

    assert len(event_grounding.event_hits) == 1
    assert event_grounding.total_matches == 1
    assert any(ref.kind == OperatorAssistReferenceKind.DETECTION_EVENT for ref in event_grounding.references)
    assert event_grounding.supporting_evidence

    plate_request = OperatorAssistRequest(
        query="show plate reads similar to XYZ12 at king fahd in the last 24 hours",
        max_results=10,
    )
    plate_plan = plan_operator_assist_request(plate_request, now=NOW + timedelta(minutes=30))
    plate_grounding = await repository.build_operator_assist_grounding(plate_request, plate_plan)

    assert len(plate_grounding.plate_hits) == 1
    assert plate_grounding.total_matches == 1
    assert any(ref.kind == OperatorAssistReferenceKind.PLATE_READ for ref in plate_grounding.references)
    assert plate_grounding.supporting_evidence

    explain_request = OperatorAssistRequest(
        query="why was this red-light alert fired",
        violation_event_id=violation_id,
    )
    explain_plan = plan_operator_assist_request(explain_request, now=NOW + timedelta(minutes=30))
    explain_grounding = await repository.build_operator_assist_grounding(explain_request, explain_plan)

    assert len(explain_grounding.violation_hits) == 1
    assert explain_grounding.references
    assert any(item.available for item in explain_grounding.supporting_evidence)

    summary_request = OperatorAssistRequest(
        query="summarize repeated incidents at king fahd in the last 7 days",
        max_results=10,
    )
    summary_plan = plan_operator_assist_request(summary_request, now=NOW + timedelta(days=1))
    summary_grounding = await repository.build_operator_assist_grounding(summary_request, summary_plan)

    assert len(summary_grounding.incident_summaries) == 1
    assert summary_grounding.incident_summaries[0].incident_count == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_sqlalchemy_repository_searches_across_multiple_camera_matches_for_junction_hints() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    repository = SqlAlchemyWorkflowRepository(session_factory)
    occurred_at = NOW

    async with session_factory() as session:
        camera_a = Camera(
            camera_code="CAM-J4-001",
            name="Junction 4 Eastbound",
            location_name="Junction 4",
            approach="eastbound",
            timezone="UTC",
            status=CameraStatus.ACTIVE,
            calibration_config={},
        )
        camera_b = Camera(
            camera_code="CAM-J4-002",
            name="Junction 4 Westbound",
            location_name="Junction 4",
            approach="westbound",
            timezone="UTC",
            status=CameraStatus.ACTIVE,
            calibration_config={},
        )
        zone_a = Zone(
            camera=camera_a,
            name="stop-line-a",
            zone_type=ZoneType.STOP_LINE,
            status=ZoneStatus.ACTIVE,
            geometry={"start": {"x": 10, "y": 10}, "end": {"x": 100, "y": 10}},
            rules_config={"rules": [{"rule_type": "red_light"}]},
        )
        zone_b = Zone(
            camera=camera_b,
            name="stop-line-b",
            zone_type=ZoneType.STOP_LINE,
            status=ZoneStatus.ACTIVE,
            geometry={"start": {"x": 20, "y": 20}, "end": {"x": 120, "y": 20}},
            rules_config={"rules": [{"rule_type": "red_light"}]},
        )
        detection_a = DetectionEvent(
            camera=camera_a,
            zone=zone_a,
            event_type=DetectionEventType.LINE_CROSSING,
            occurred_at=occurred_at,
            frame_index=11,
            track_id="T-11",
            object_class="car",
            confidence=0.91,
            bbox={"x1": 100, "y1": 100, "x2": 200, "y2": 220},
            event_payload={},
            image_uri="s3://events/a-frame.jpg",
        )
        detection_b = DetectionEvent(
            camera=camera_b,
            zone=zone_b,
            event_type=DetectionEventType.LINE_CROSSING,
            occurred_at=occurred_at - timedelta(minutes=5),
            frame_index=12,
            track_id="T-12",
            object_class="car",
            confidence=0.92,
            bbox={"x1": 90, "y1": 90, "x2": 210, "y2": 230},
            event_payload={},
            image_uri="s3://events/b-frame.jpg",
        )
        violation_a = ViolationEvent(
            camera=camera_a,
            zone=zone_a,
            detection_event=detection_a,
            violation_type=ViolationType.RED_LIGHT,
            severity=ViolationSeverity.HIGH,
            status=ViolationStatus.OPEN,
            occurred_at=occurred_at,
            summary="Eastbound red-light violation.",
            evidence_image_uri="s3://violations/a.jpg",
            rule_metadata={"rule_type": "red_light"},
        )
        violation_b = ViolationEvent(
            camera=camera_b,
            zone=zone_b,
            detection_event=detection_b,
            violation_type=ViolationType.RED_LIGHT,
            severity=ViolationSeverity.HIGH,
            status=ViolationStatus.OPEN,
            occurred_at=occurred_at - timedelta(minutes=5),
            summary="Westbound red-light violation.",
            evidence_image_uri="s3://violations/b.jpg",
            rule_metadata={"rule_type": "red_light"},
        )
        session.add_all([camera_a, camera_b, zone_a, zone_b, detection_a, detection_b, violation_a, violation_b])
        await session.commit()

    request = OperatorAssistRequest(
        query="find all red-light violations near Junction 4 this morning",
        max_results=10,
    )
    plan = plan_operator_assist_request(request, now=NOW)
    grounding = await repository.build_operator_assist_grounding(request, plan)

    assert grounding.grounding_notes == []
    assert len(grounding.camera_matches) == 2
    assert grounding.total_matches == 2
    assert len(grounding.violation_hits) == 2
    assert {hit.camera.camera_code for hit in grounding.violation_hits} == {"CAM-J4-001", "CAM-J4-002"}
    assert {ref.kind for ref in grounding.references} >= {
        OperatorAssistReferenceKind.CAMERA,
        OperatorAssistReferenceKind.VIOLATION_EVENT,
    }

    await engine.dispose()


@pytest.mark.asyncio
async def test_sqlalchemy_repository_builds_multimodal_review_context_with_history() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    violation_id, _report_date = await _seed_repository_data(session_factory)
    repository = SqlAlchemyWorkflowRepository(session_factory)

    async with session_factory() as session:
        violation = await session.get(ViolationEvent, violation_id)
        assert violation is not None
        violation.reviewed_by = "analyst.a"
        violation.reviewed_at = NOW + timedelta(minutes=20)
        violation.review_note = "Earlier analyst requested a wider clip window."
        session.add(
            WorkflowRun(
                camera_id=violation.camera_id,
                detection_event_id=violation.detection_event_id,
                violation_event_id=violation.id,
                workflow_type=WorkflowType.REVIEW,
                status=WorkflowStatus.SUCCEEDED,
                priority=3,
                requested_by="ops.supervisor",
                started_at=NOW + timedelta(minutes=5),
                completed_at=NOW + timedelta(minutes=8),
                input_payload={"workflow_name": WorkflowName.VIOLATION_REVIEW.value},
                result_payload={
                    "workflow_name": WorkflowName.VIOLATION_REVIEW.value,
                    "output": {
                        "workflow": "violation_review",
                        "summary": "Escalated for manual confirmation.",
                        "disposition": "escalate_supervisor",
                        "confidence": 0.55,
                    },
                },
            )
        )
        await session.commit()

    context = await repository.build_multimodal_review_context(
        MultimodalReviewRequest(violation_event_id=violation_id, requested_by="ops.lead")
    )

    assert context.rule_explanation.reason is not None
    assert context.metadata_references
    assert context.image_references
    assert context.clip_references
    assert context.manifest_references
    assert len(context.prior_review_history) >= 2
    assert any(item.source == "workflow_run" for item in context.prior_review_history)

    await engine.dispose()


@pytest.mark.asyncio
async def test_multimodal_review_preserves_frame_zero_grounding_without_write_back() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    violation_id, _report_date = await _seed_repository_data(session_factory)

    async with session_factory() as session:
        violation = await session.get(ViolationEvent, violation_id)
        assert violation is not None
        violation.status = ViolationStatus.OPEN
        violation.review_note = "Operator has not closed this case yet."
        violation.rule_metadata = {
            "rule_type": "red_light",
            "frame_index": 0,
            "track_id": "T-0",
            "explanation": {
                "reason": "Vehicle entered after the signal was already red.",
                "frame_index": 0,
                "conditions_satisfied": ["signal red", "stop-line crossing"],
                "details": {"signal_state_at_decision": "red", "track_id": "T-0"},
            },
        }
        await session.commit()

    repository = SqlAlchemyWorkflowRepository(session_factory)
    service = WorkflowService(
        repository=repository,
        settings=Settings(database_url="sqlite+aiosqlite:///:memory:", provider_backend="heuristic", checkpoint_backend="memory", debug=False),
    )

    response = await service.start_multimodal_review(
        MultimodalReviewRequest(violation_event_id=violation_id, requested_by="ops.lead")
    )

    assert response.status == WorkflowStatus.SUCCEEDED
    assert response.output is not None
    assert "frame_index=0" in response.output.likely_cause
    assert "track_id=T-0" in response.output.likely_cause

    async with session_factory() as session:
        stored_violation = await session.get(ViolationEvent, violation_id)
        assert stored_violation is not None
        assert stored_violation.status == ViolationStatus.OPEN
        assert stored_violation.review_note == "Operator has not closed this case yet."

    await engine.dispose()


# ── Weekly Summary Workflow ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_weekly_summary_workflow_completes_without_interrupt() -> None:
    camera = _camera_record()
    violation = _violation_record(severity=ViolationSeverity.HIGH)
    weekly_context = WeeklySummaryContext(
        week_ending=date(2026, 4, 4),
        week_start=date(2026, 3, 29),
        daily_breakdowns=[
            CameraDailySummary(
                camera_id=camera.id,
                camera_name=camera.name,
                location_name=camera.location_name,
                detection_count=20,
                violation_count=5,
                open_violation_count=3,
                top_violation_types={"red_light": 4, "stop_line": 1},
            )
        ],
        total_detections=20,
        total_violations=5,
        total_open_violations=3,
        top_violation_types={"red_light": 4, "stop_line": 1},
    )
    service, _ = _build_service(
        triage_context=IncidentTriageContext(source_kind="violation", camera=camera, violation_event=violation),
        review_context=ViolationReviewContext(camera=camera, violation_event=violation),
        daily_summary_context=DailySummaryContext(report_date=date(2026, 4, 4)),
        weekly_summary_context=weekly_context,
    )

    response = await service.start_weekly_summary(
        WeeklySummaryRequest(week_ending=date(2026, 4, 4), require_human_approval=False)
    )

    assert response.status == WorkflowStatus.SUCCEEDED
    assert response.interrupted is False
    assert response.output is not None
    assert response.output.workflow == "weekly_summary"
    assert response.output.total_violations == 5
    assert response.output.total_detections == 20
    assert response.output.week_ending == date(2026, 4, 4)
    assert response.output.generated_at.tzinfo is not None
    assert response.output.scope_notes
    assert "# Weekly Summary" in response.output.markdown
    assert any(entry.node == "generate_summary" for entry in response.trace)


@pytest.mark.asyncio
async def test_weekly_summary_workflow_interrupts_for_approval() -> None:
    camera = _camera_record()
    violation = _violation_record(severity=ViolationSeverity.HIGH)
    weekly_context = WeeklySummaryContext(
        week_ending=date(2026, 4, 4),
        week_start=date(2026, 3, 29),
        total_detections=10,
        total_violations=2,
        total_open_violations=1,
        top_violation_types={"red_light": 2},
    )
    service, _ = _build_service(
        triage_context=IncidentTriageContext(source_kind="violation", camera=camera, violation_event=violation),
        review_context=ViolationReviewContext(camera=camera, violation_event=violation),
        daily_summary_context=DailySummaryContext(report_date=date(2026, 4, 4)),
        weekly_summary_context=weekly_context,
    )

    first = await service.start_weekly_summary(
        WeeklySummaryRequest(week_ending=date(2026, 4, 4), require_human_approval=True)
    )

    assert first.interrupted is True
    assert first.interrupt_request is not None

    resumed = await service.resume_workflow(
        first.run_id,
        WorkflowResumeRequest(approved=True, reviewer="supervisor.c", note="Looks good."),
    )

    assert resumed.status == WorkflowStatus.SUCCEEDED
    assert resumed.output is not None
    assert resumed.output.workflow == "weekly_summary"
    assert resumed.output.scope_notes
    assert "## Reviewer Note" in resumed.output.markdown


@pytest.mark.asyncio
async def test_weekly_summary_workflow_rejected_includes_held_narrative() -> None:
    camera = _camera_record()
    violation = _violation_record(severity=ViolationSeverity.MEDIUM)
    weekly_context = WeeklySummaryContext(
        week_ending=date(2026, 4, 4),
        week_start=date(2026, 3, 29),
        total_detections=6,
        total_violations=1,
        total_open_violations=0,
        top_violation_types={"stop_line": 1},
    )
    service, _ = _build_service(
        triage_context=IncidentTriageContext(source_kind="violation", camera=camera, violation_event=violation),
        review_context=ViolationReviewContext(camera=camera, violation_event=violation),
        daily_summary_context=DailySummaryContext(report_date=date(2026, 4, 4)),
        weekly_summary_context=weekly_context,
    )

    first = await service.start_weekly_summary(
        WeeklySummaryRequest(week_ending=date(2026, 4, 4), require_human_approval=True)
    )
    resumed = await service.resume_workflow(
        first.run_id,
        WorkflowResumeRequest(approved=False, reviewer="supervisor.d", note="Needs revision."),
    )

    assert resumed.status == WorkflowStatus.SUCCEEDED
    assert resumed.output is not None
    assert "Publication held" in resumed.output.narrative
    assert resumed.output.scope_notes
    assert "## Publication Status" in resumed.output.markdown


# ── Hotspot Report Workflow ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_hotspot_report_workflow_completes_without_interrupt() -> None:
    camera = _camera_record()
    violation = _violation_record(severity=ViolationSeverity.HIGH)
    hotspot_context = HotspotReportContext(
        report_date=date(2026, 4, 4),
        lookback_days=7,
        top_n=5,
        group_by=HotspotGroupBy.CAMERA,
        hotspots=[
            HotspotEntry(
                camera_id=camera.id,
                camera_name=camera.name,
                location_name=camera.location_name,
                violation_count=12,
                open_count=4,
                top_violation_types={"red_light": 8, "stop_line": 4},
                last_violation_at=NOW,
            )
        ],
        total_violations_in_window=12,
        total_groups_with_violations=1,
        total_cameras_with_violations=1,
    )
    service, _ = _build_service(
        triage_context=IncidentTriageContext(source_kind="violation", camera=camera, violation_event=violation),
        review_context=ViolationReviewContext(camera=camera, violation_event=violation),
        daily_summary_context=DailySummaryContext(report_date=date(2026, 4, 4)),
        hotspot_report_context=hotspot_context,
    )

    response = await service.start_hotspot_report(
        HotspotReportRequest(report_date=date(2026, 4, 4), lookback_days=7, top_n=5, require_human_approval=False)
    )

    assert response.status == WorkflowStatus.SUCCEEDED
    assert response.interrupted is False
    assert response.output is not None
    assert response.output.workflow == "hotspot_report"
    assert response.output.group_by == HotspotGroupBy.CAMERA
    assert response.output.generated_at.tzinfo is not None
    assert response.output.total_violations_in_window == 12
    assert response.output.total_groups_with_violations == 1
    assert len(response.output.hotspots) == 1
    assert response.output.hotspots[0].violation_count == 12
    assert "# Hotspot Report" in response.output.markdown
    assert any(entry.node == "generate_report" for entry in response.trace)


@pytest.mark.asyncio
async def test_hotspot_report_workflow_supports_zone_grouping() -> None:
    camera = _camera_record()
    violation = _violation_record(severity=ViolationSeverity.HIGH)
    hotspot_context = HotspotReportContext(
        report_date=date(2026, 4, 4),
        lookback_days=7,
        top_n=3,
        group_by=HotspotGroupBy.ZONE,
        hotspots=[
            HotspotEntry(
                camera_id=camera.id,
                camera_name=camera.name,
                location_name=f"{camera.location_name} / stop-line-a",
                zone_id=uuid.uuid4(),
                zone_name="stop-line-a",
                zone_type=ZoneType.STOP_LINE.value,
                violation_count=6,
                open_count=2,
                top_violation_types={"red_light": 4, "stop_line": 2},
                last_violation_at=NOW,
            )
        ],
        total_violations_in_window=8,
        total_groups_with_violations=1,
        total_cameras_with_violations=1,
        unassigned_violations=2,
    )
    service, _ = _build_service(
        triage_context=IncidentTriageContext(source_kind="violation", camera=camera, violation_event=violation),
        review_context=ViolationReviewContext(camera=camera, violation_event=violation),
        daily_summary_context=DailySummaryContext(report_date=date(2026, 4, 4)),
        hotspot_report_context=hotspot_context,
    )

    response = await service.start_hotspot_report(
        HotspotReportRequest(
            report_date=date(2026, 4, 4),
            lookback_days=7,
            top_n=3,
            group_by=HotspotGroupBy.ZONE,
            require_human_approval=False,
        )
    )

    assert response.status == WorkflowStatus.SUCCEEDED
    assert response.output is not None
    assert response.output.group_by == HotspotGroupBy.ZONE
    assert response.output.generated_at.tzinfo is not None
    assert response.output.hotspots[0].zone_name == "stop-line-a"
    assert response.output.unassigned_violations == 2
    assert response.output.data_gaps
    assert "excluded from zone ranking" in response.output.narrative
    assert "stop-line-a" in response.output.markdown


@pytest.mark.asyncio
async def test_hotspot_report_workflow_interrupts_for_approval() -> None:
    camera = _camera_record()
    violation = _violation_record(severity=ViolationSeverity.HIGH)
    hotspot_context = HotspotReportContext(
        report_date=date(2026, 4, 4),
        lookback_days=7,
        top_n=3,
        group_by=HotspotGroupBy.CAMERA,
        hotspots=[
            HotspotEntry(
                camera_id=camera.id,
                camera_name=camera.name,
                location_name=camera.location_name,
                violation_count=8,
                open_count=2,
                top_violation_types={"red_light": 5, "u_turn": 3},
            )
        ],
        total_violations_in_window=8,
        total_groups_with_violations=1,
        total_cameras_with_violations=1,
    )
    service, _ = _build_service(
        triage_context=IncidentTriageContext(source_kind="violation", camera=camera, violation_event=violation),
        review_context=ViolationReviewContext(camera=camera, violation_event=violation),
        daily_summary_context=DailySummaryContext(report_date=date(2026, 4, 4)),
        hotspot_report_context=hotspot_context,
    )

    first = await service.start_hotspot_report(
        HotspotReportRequest(report_date=date(2026, 4, 4), lookback_days=7, top_n=3, require_human_approval=True)
    )

    assert first.interrupted is True
    assert first.interrupt_request is not None

    resumed = await service.resume_workflow(
        first.run_id,
        WorkflowResumeRequest(approved=True, reviewer="analyst.e", note="Hotspots confirmed."),
    )

    assert resumed.status == WorkflowStatus.SUCCEEDED
    assert resumed.output is not None
    assert resumed.output.workflow == "hotspot_report"
    assert resumed.output.generated_at.tzinfo is not None
    assert "## Reviewer Note" in resumed.output.markdown


@pytest.mark.asyncio
async def test_hotspot_report_empty_window_produces_valid_output() -> None:
    camera = _camera_record()
    violation = _violation_record(severity=ViolationSeverity.MEDIUM)
    hotspot_context = HotspotReportContext(
        report_date=date(2026, 4, 4),
        lookback_days=7,
        top_n=5,
        group_by=HotspotGroupBy.CAMERA,
        hotspots=[],
        total_violations_in_window=0,
        total_groups_with_violations=0,
        total_cameras_with_violations=0,
    )
    service, _ = _build_service(
        triage_context=IncidentTriageContext(source_kind="violation", camera=camera, violation_event=violation),
        review_context=ViolationReviewContext(camera=camera, violation_event=violation),
        daily_summary_context=DailySummaryContext(report_date=date(2026, 4, 4)),
        hotspot_report_context=hotspot_context,
    )

    response = await service.start_hotspot_report(
        HotspotReportRequest(report_date=date(2026, 4, 4), require_human_approval=False)
    )

    assert response.status == WorkflowStatus.SUCCEEDED
    assert response.output is not None
    assert response.output.workflow == "hotspot_report"
    assert response.output.generated_at.tzinfo is not None
    assert response.output.total_violations_in_window == 0
    assert len(response.output.hotspots) == 0
    assert response.output.data_gaps == ["No violation records found in the reporting window."]