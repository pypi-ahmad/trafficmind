"""Repository layer for reading stored workflow context and persisting runs."""

from __future__ import annotations

import abc
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from typing import Any

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from apps.api.app.db.enums import EvidenceSubjectKind, ViolationStatus, WatchlistAlertStatus, WorkflowStatus, WorkflowType
from apps.api.app.db.models import Camera, DetectionEvent, EvidenceManifest, PlateRead, ViolationEvent, WatchlistAlert, WorkflowRun, Zone
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
    OperatorAssistPlateHit,
    OperatorAssistPlan,
    OperatorAssistReference,
    OperatorAssistReferenceKind,
    OperatorAssistRequest,
    OperatorAssistViolationHit,
    PriorReviewRecord,
    RepeatedIncidentSummary,
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
    ReviewBacklog,
    WorkflowName,
)
from services.anpr.search import search_plates
from services.evidence.schemas import EvidenceAssetKind, EvidenceManifestDocument, EvidenceStorageState
from services.events.search import search_detection_events
from services.violations.search import search_violation_events


class WorkflowRepository(abc.ABC):
    """Abstract stored-data access layer for cold-path workflows."""

    @abc.abstractmethod
    async def build_incident_triage_context(self, request: IncidentTriageRequest) -> IncidentTriageContext:
        """Load the stored records required for incident triage."""

    @abc.abstractmethod
    async def build_violation_review_context(self, request: ViolationReviewRequest) -> ViolationReviewContext:
        """Load the stored records required for violation review."""

    @abc.abstractmethod
    async def build_multimodal_review_context(self, request: MultimodalReviewRequest) -> MultimodalReviewContext:
        """Load the stored records required for grounded multimodal review assistance."""

    @abc.abstractmethod
    async def build_daily_summary_context(self, request: DailySummaryRequest) -> DailySummaryContext:
        """Load the stored records required for the daily summary workflow."""

    @abc.abstractmethod
    async def build_operator_assist_grounding(
        self,
        request: OperatorAssistRequest,
        plan: OperatorAssistPlan,
    ) -> OperatorAssistGrounding:
        """Retrieve structured grounding data for an operator-assist plan."""

    @abc.abstractmethod
    async def build_weekly_summary_context(self, request: WeeklySummaryRequest) -> WeeklySummaryContext:
        """Load the stored records required for the weekly summary workflow."""

    @abc.abstractmethod
    async def build_hotspot_report_context(self, request: HotspotReportRequest) -> HotspotReportContext:
        """Load the stored records required for the hotspot report workflow."""

    @abc.abstractmethod
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
        """Create a new workflow run record."""

    @abc.abstractmethod
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
        """Update status, output, or error details for a workflow run."""

    @abc.abstractmethod
    async def get_workflow_run(self, run_id: uuid.UUID) -> StoredWorkflowRun:
        """Return a stored workflow run by id."""

    @abc.abstractmethod
    async def apply_violation_disposition(
        self,
        violation_event_id: uuid.UUID,
        *,
        new_status: ViolationStatus,
        reviewed_by: str | None,
        review_note: str | None,
    ) -> None:
        """Write the review disposition back to the source ViolationEvent."""


class WorkflowRepositoryError(RuntimeError):
    """Base exception for repository failures."""


class RecordNotFoundError(WorkflowRepositoryError):
    """Raised when a stored record cannot be found."""


def _to_camera_record(camera: Camera) -> StoredCameraRecord:
    return StoredCameraRecord(
        id=camera.id,
        camera_code=camera.camera_code,
        name=camera.name,
        location_name=camera.location_name,
        approach=camera.approach,
        status=camera.status,
        latitude=camera.latitude,
        longitude=camera.longitude,
        timezone=camera.timezone,
    )


def _to_detection_record(detection: DetectionEvent) -> StoredDetectionEventRecord:
    return StoredDetectionEventRecord(
        id=detection.id,
        event_type=detection.event_type,
        occurred_at=detection.occurred_at,
        frame_index=detection.frame_index,
        track_id=detection.track_id,
        object_class=detection.object_class,
        confidence=detection.confidence,
        bbox=detection.bbox,
        event_payload=detection.event_payload,
        image_uri=detection.image_uri,
        video_uri=detection.video_uri,
    )


def _to_plate_read_record(plate_read: PlateRead) -> StoredPlateReadRecord:
    return StoredPlateReadRecord(
        id=plate_read.id,
        status=plate_read.status,
        occurred_at=plate_read.occurred_at,
        plate_text=plate_read.plate_text,
        normalized_plate_text=plate_read.normalized_plate_text,
        confidence=plate_read.confidence,
        country_code=plate_read.country_code,
        region_code=plate_read.region_code,
        bbox=plate_read.bbox,
        crop_image_uri=plate_read.crop_image_uri,
        source_frame_uri=plate_read.source_frame_uri,
        ocr_metadata=plate_read.ocr_metadata,
    )


def _to_violation_record(violation: ViolationEvent) -> StoredViolationEventRecord:
    return StoredViolationEventRecord(
        id=violation.id,
        violation_type=violation.violation_type,
        severity=violation.severity,
        status=violation.status,
        occurred_at=violation.occurred_at,
        summary=violation.summary,
        evidence_image_uri=violation.evidence_image_uri,
        evidence_video_uri=violation.evidence_video_uri,
        assigned_to=violation.assigned_to,
        reviewed_by=violation.reviewed_by,
        reviewed_at=violation.reviewed_at,
        review_note=violation.review_note,
        rule_metadata=violation.rule_metadata,
    )


def _to_workflow_run_record(run: WorkflowRun) -> StoredWorkflowRun:
    return StoredWorkflowRun(
        id=run.id,
        workflow_type=run.workflow_type,
        status=run.status,
        priority=run.priority,
        requested_by=run.requested_by,
        camera_id=run.camera_id,
        detection_event_id=run.detection_event_id,
        violation_event_id=run.violation_event_id,
        started_at=run.started_at,
        completed_at=run.completed_at,
        input_payload=run.input_payload,
        result_payload=run.result_payload,
        error_message=run.error_message,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _subject_manifest(
    manifests: list[EvidenceManifest],
    *,
    subject_kind: EvidenceSubjectKind,
) -> EvidenceManifest | None:
    for manifest in manifests:
        if manifest.subject_kind == subject_kind:
            return manifest
    return None


def _manifest_reference(
    manifest: EvidenceManifest,
    *,
    label: str,
) -> EvidenceReference:
    return EvidenceReference(
        label=label,
        source="evidence_manifest",
        uri=manifest.manifest_uri or f"evidence-manifest://{manifest.id}",
        available=True,
        metadata={
            "manifest_id": str(manifest.id),
            "manifest_key": manifest.manifest_key,
            "build_revision": manifest.build_revision,
            "subject_kind": manifest.subject_kind.value,
            "subject_id": str(manifest.subject_id),
            "camera_id": str(manifest.camera_id),
            "occurred_at": manifest.occurred_at.isoformat(),
            "storage_namespace": manifest.storage_namespace,
        },
    )


def _record_evidence_metadata(
    *,
    subject_kind: str,
    subject_id: uuid.UUID,
    camera_id: uuid.UUID,
    occurred_at: datetime,
) -> dict[str, Any]:
    return {
        "subject_kind": subject_kind,
        "subject_id": str(subject_id),
        "camera_id": str(camera_id),
        "occurred_at": occurred_at.isoformat(),
    }


def _build_evidence(
    *,
    detection: DetectionEvent | None,
    violation: ViolationEvent | None,
    plate_read: PlateRead | None,
) -> list[EvidenceReference]:
    evidence: list[EvidenceReference] = []
    if detection is not None:
        evidence.extend(
            [
                EvidenceReference(
                    label="detection_image",
                    source="detection_event",
                    uri=detection.image_uri,
                    available=bool(detection.image_uri),
                    metadata=_record_evidence_metadata(
                        subject_kind="detection_event",
                        subject_id=detection.id,
                        camera_id=detection.camera_id,
                        occurred_at=detection.occurred_at,
                    ),
                ),
                EvidenceReference(
                    label="detection_clip",
                    source="detection_event",
                    uri=detection.video_uri,
                    available=bool(detection.video_uri),
                    metadata=_record_evidence_metadata(
                        subject_kind="detection_event",
                        subject_id=detection.id,
                        camera_id=detection.camera_id,
                        occurred_at=detection.occurred_at,
                    ),
                ),
            ]
        )
        manifest = _subject_manifest(
            list(detection.__dict__.get("evidence_manifests", [])),
            subject_kind=EvidenceSubjectKind.DETECTION_EVENT,
        )
        if manifest is not None:
            evidence.append(_manifest_reference(manifest, label="detection_manifest"))
    if violation is not None:
        evidence.extend(
            [
                EvidenceReference(
                    label="violation_image",
                    source="violation_event",
                    uri=violation.evidence_image_uri,
                    available=bool(violation.evidence_image_uri),
                    metadata=_record_evidence_metadata(
                        subject_kind="violation_event",
                        subject_id=violation.id,
                        camera_id=violation.camera_id,
                        occurred_at=violation.occurred_at,
                    ),
                ),
                EvidenceReference(
                    label="violation_clip",
                    source="violation_event",
                    uri=violation.evidence_video_uri,
                    available=bool(violation.evidence_video_uri),
                    metadata=_record_evidence_metadata(
                        subject_kind="violation_event",
                        subject_id=violation.id,
                        camera_id=violation.camera_id,
                        occurred_at=violation.occurred_at,
                    ),
                ),
            ]
        )
        manifest = _subject_manifest(
            list(violation.__dict__.get("evidence_manifests", [])),
            subject_kind=EvidenceSubjectKind.VIOLATION_EVENT,
        )
        if manifest is not None:
            evidence.append(_manifest_reference(manifest, label="violation_manifest"))
    if plate_read is not None:
        evidence.extend(
            [
                EvidenceReference(
                    label="plate_crop",
                    source="plate_read",
                    uri=plate_read.crop_image_uri,
                    available=bool(plate_read.crop_image_uri),
                    metadata=_record_evidence_metadata(
                        subject_kind="plate_read",
                        subject_id=plate_read.id,
                        camera_id=plate_read.camera_id,
                        occurred_at=plate_read.occurred_at,
                    ),
                ),
                EvidenceReference(
                    label="plate_source_frame",
                    source="plate_read",
                    uri=plate_read.source_frame_uri,
                    available=bool(plate_read.source_frame_uri),
                    metadata=_record_evidence_metadata(
                        subject_kind="plate_read",
                        subject_id=plate_read.id,
                        camera_id=plate_read.camera_id,
                        occurred_at=plate_read.occurred_at,
                    ),
                ),
            ]
        )
    return evidence


def _safe_frame_index(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _compact_metadata_value(value: Any) -> Any | None:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list) and len(value) <= 6:
        if all(isinstance(item, (str, int, float, bool)) or item is None for item in value):
            return value
    return None


def _compact_metadata_dict(values: dict[str, Any], *, limit: int = 8) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in values.items():
        if len(compact) >= limit:
            break
        compact_value = _compact_metadata_value(value)
        if compact_value is not None:
            compact[key] = compact_value
    return compact


def _coerce_workflow_name(value: Any) -> WorkflowName | None:
    if not isinstance(value, str):
        return None
    try:
        return WorkflowName(value)
    except ValueError:
        return None


def _first_non_none_int(*values: Any) -> int | None:
    for value in values:
        parsed = _safe_frame_index(value)
        if parsed is not None:
            return parsed
    return None


def _build_multimodal_rule_explanation(
    *,
    violation: ViolationEvent,
    detection: DetectionEvent | None,
) -> MultimodalRuleExplanation:
    metadata = dict(violation.rule_metadata) if violation.rule_metadata else {}
    explanation = metadata.get("explanation") if isinstance(metadata.get("explanation"), dict) else {}
    details = explanation.get("details") if isinstance(explanation.get("details"), dict) else {}
    salient_details = _compact_metadata_dict(details)
    for key in ("light_state", "certainty", "track_id", "signal_state_at_decision"):
        if key in metadata and key not in salient_details:
            compact_value = _compact_metadata_value(metadata.get(key))
            if compact_value is not None:
                salient_details[key] = compact_value
    if detection is not None and "detection_confidence" not in salient_details:
        salient_details["detection_confidence"] = detection.confidence

    conditions = explanation.get("conditions_satisfied") if isinstance(explanation.get("conditions_satisfied"), list) else []
    return MultimodalRuleExplanation(
        rule_type=metadata.get("rule_type") if isinstance(metadata.get("rule_type"), str) else None,
        reason=(explanation.get("reason") if isinstance(explanation.get("reason"), str) else None) or violation.summary,
        frame_index=_first_non_none_int(
            explanation.get("frame_index"),
            metadata.get("frame_index"),
            detection.frame_index if detection is not None else None,
        ),
        conditions_satisfied=[str(item) for item in conditions if isinstance(item, (str, int, float, bool))],
        salient_details=salient_details,
    )


def _append_multimodal_reference(
    references: list[MultimodalGroundingReference],
    reference: MultimodalGroundingReference,
) -> None:
    key = (
        reference.kind,
        reference.label,
        reference.source,
        reference.uri,
        reference.reference_id,
    )
    if any(
        (item.kind, item.label, item.source, item.uri, item.reference_id) == key
        for item in references
    ):
        return
    references.append(reference)


def _workflow_run_history_entry(run: WorkflowRun) -> PriorReviewRecord | None:
    payload = dict(run.result_payload) if isinstance(run.result_payload, dict) else {}
    output = payload.get("output") if isinstance(payload.get("output"), dict) else {}

    summary: str | None = None
    disposition: str | None = None
    confidence: float | None = None
    metadata: dict[str, Any] = {}
    if output:
        review_summary = output.get("review_summary")
        fallback_summary = output.get("summary")
        answer_summary = output.get("answer")
        if isinstance(review_summary, str):
            summary = review_summary
        elif isinstance(fallback_summary, str):
            summary = fallback_summary
        elif isinstance(answer_summary, str):
            summary = answer_summary

        if isinstance(output.get("disposition"), str):
            disposition = output.get("disposition")
        if isinstance(output.get("confidence"), (int, float)):
            confidence = float(output.get("confidence"))
        metadata = _compact_metadata_dict(
            {
                "workflow": output.get("workflow"),
                "recommended_operator_action": output.get("recommended_operator_action"),
                "escalation_suggestion": output.get("escalation_suggestion"),
            },
            limit=3,
        )
    else:
        decision = payload.get("decision")
        if isinstance(decision, str):
            summary = decision
            disposition = decision
        if isinstance(payload.get("confidence"), (int, float)):
            confidence = float(payload.get("confidence"))

    if summary is None:
        return None

    input_payload = dict(run.input_payload) if isinstance(run.input_payload, dict) else {}
    return PriorReviewRecord(
        source="workflow_run",
        recorded_at=run.completed_at or run.updated_at or run.created_at,
        recorded_by=run.requested_by,
        workflow_name=_coerce_workflow_name(input_payload.get("workflow_name") or payload.get("workflow_name")),
        workflow_type=run.workflow_type,
        summary=summary,
        disposition=disposition,
        confidence=confidence,
        metadata=metadata,
    )


def _build_multimodal_references(
    *,
    detection: DetectionEvent | None,
    violation: ViolationEvent,
    plate_read: PlateRead | None,
    operator_notes: str | None,
) -> tuple[
    list[MultimodalGroundingReference],
    list[MultimodalGroundingReference],
    list[MultimodalGroundingReference],
    list[MultimodalGroundingReference],
]:
    metadata_refs: list[MultimodalGroundingReference] = []
    image_refs: list[MultimodalGroundingReference] = []
    clip_refs: list[MultimodalGroundingReference] = []
    manifest_refs: list[MultimodalGroundingReference] = []

    rule_explanation = _build_multimodal_rule_explanation(violation=violation, detection=detection)
    _append_multimodal_reference(
        metadata_refs,
        MultimodalGroundingReference(
            kind=MultimodalGroundingReferenceKind.METADATA,
            label="violation_metadata",
            source="violation_event",
            available=True,
            reference_id=str(violation.id),
            metadata={
                "violation_type": violation.violation_type.value,
                "severity": violation.severity.value,
                "status": violation.status.value,
                "occurred_at": violation.occurred_at.isoformat(),
            },
        ),
    )
    if detection is not None:
        _append_multimodal_reference(
            metadata_refs,
            MultimodalGroundingReference(
                kind=MultimodalGroundingReferenceKind.METADATA,
                label="detection_metadata",
                source="detection_event",
                available=True,
                reference_id=str(detection.id),
                metadata={
                    "event_type": detection.event_type.value,
                    "object_class": detection.object_class,
                    "confidence": detection.confidence,
                    "frame_index": detection.frame_index,
                },
            ),
        )
    if plate_read is not None:
        _append_multimodal_reference(
            metadata_refs,
            MultimodalGroundingReference(
                kind=MultimodalGroundingReferenceKind.METADATA,
                label="plate_metadata",
                source="plate_read",
                available=True,
                reference_id=str(plate_read.id),
                metadata={
                    "normalized_plate_text": plate_read.normalized_plate_text,
                    "confidence": plate_read.confidence,
                },
            ),
        )
    if rule_explanation.reason or rule_explanation.rule_type:
        _append_multimodal_reference(
            metadata_refs,
            MultimodalGroundingReference(
                kind=MultimodalGroundingReferenceKind.METADATA,
                label="rule_explanation",
                source="rule_metadata",
                available=True,
                metadata=rule_explanation.model_dump(mode="json"),
            ),
        )
    if operator_notes:
        _append_multimodal_reference(
            metadata_refs,
            MultimodalGroundingReference(
                kind=MultimodalGroundingReferenceKind.METADATA,
                label="operator_notes",
                source="review_context",
                available=True,
                metadata={"text": operator_notes},
            ),
        )
    if violation.review_note:
        _append_multimodal_reference(
            metadata_refs,
            MultimodalGroundingReference(
                kind=MultimodalGroundingReferenceKind.METADATA,
                label="existing_review_note",
                source="violation_event",
                available=True,
                metadata={"text": violation.review_note},
            ),
        )

    direct_image_candidates = []
    if detection is not None:
        direct_image_candidates.append(("detection_image", "detection_event", detection.image_uri, str(detection.id)))
    direct_image_candidates.extend(
        [
            ("violation_image", "violation_event", violation.evidence_image_uri, str(violation.id)),
            ("plate_crop", "plate_read", plate_read.crop_image_uri if plate_read is not None else None, str(plate_read.id) if plate_read is not None else None),
            ("plate_source_frame", "plate_read", plate_read.source_frame_uri if plate_read is not None else None, str(plate_read.id) if plate_read is not None else None),
        ]
    )
    for label, source, uri, reference_id in direct_image_candidates:
        if uri is None:
            continue
        _append_multimodal_reference(
            image_refs,
            MultimodalGroundingReference(
                kind=MultimodalGroundingReferenceKind.IMAGE,
                label=label,
                source=source,
                uri=uri,
                available=True,
                reference_id=reference_id,
            ),
        )

    direct_clip_candidates = []
    if detection is not None:
        direct_clip_candidates.append(("detection_clip", "detection_event", detection.video_uri, str(detection.id)))
    direct_clip_candidates.append(("violation_clip", "violation_event", violation.evidence_video_uri, str(violation.id)))
    for label, source, uri, reference_id in direct_clip_candidates:
        if uri is None:
            continue
        _append_multimodal_reference(
            clip_refs,
            MultimodalGroundingReference(
                kind=MultimodalGroundingReferenceKind.CLIP,
                label=label,
                source=source,
                uri=uri,
                available=True,
                reference_id=reference_id,
            ),
        )

    manifests: list[EvidenceManifest] = []
    if detection is not None:
        manifests.extend(list(getattr(detection, "evidence_manifests", [])))
    manifests.extend(list(getattr(violation, "evidence_manifests", [])))

    seen_manifest_ids: set[uuid.UUID] = set()
    for manifest in manifests:
        if manifest.id in seen_manifest_ids:
            continue
        seen_manifest_ids.add(manifest.id)
        _append_multimodal_reference(
            manifest_refs,
            MultimodalGroundingReference(
                kind=MultimodalGroundingReferenceKind.MANIFEST,
                label=(
                    "detection_manifest"
                    if manifest.subject_kind == EvidenceSubjectKind.DETECTION_EVENT
                    else "violation_manifest"
                ),
                source="evidence_manifest",
                uri=manifest.manifest_uri or f"evidence-manifest://{manifest.id}",
                available=True,
                reference_id=str(manifest.id),
                metadata={
                    "manifest_key": manifest.manifest_key,
                    "build_revision": manifest.build_revision,
                    "subject_kind": manifest.subject_kind.value,
                },
            ),
        )
        try:
            document = EvidenceManifestDocument.model_validate(manifest.manifest_data)
        except Exception:
            continue
        for asset in document.assets:
            available = asset.available or asset.storage_state == EvidenceStorageState.INLINE
            asset_reference = MultimodalGroundingReference(
                kind=MultimodalGroundingReferenceKind.METADATA,
                label=asset.label,
                source="evidence_manifest_asset",
                uri=asset.uri,
                available=available,
                reference_id=str(manifest.id),
                metadata={
                    "asset_kind": asset.asset_kind.value,
                    "storage_state": asset.storage_state.value,
                    "frame_index": asset.frame_index,
                    "content_type": asset.content_type,
                },
            )
            if asset.asset_kind in {
                EvidenceAssetKind.KEY_FRAME_SNAPSHOT,
                EvidenceAssetKind.OBJECT_CROP,
                EvidenceAssetKind.PLATE_CROP,
            }:
                asset_reference = asset_reference.model_copy(
                    update={"kind": MultimodalGroundingReferenceKind.IMAGE}
                )
                _append_multimodal_reference(image_refs, asset_reference)
            elif asset.asset_kind == EvidenceAssetKind.CLIP_WINDOW:
                asset_reference = asset_reference.model_copy(
                    update={"kind": MultimodalGroundingReferenceKind.CLIP}
                )
                _append_multimodal_reference(clip_refs, asset_reference)
            else:
                _append_multimodal_reference(metadata_refs, asset_reference)

    return metadata_refs, image_refs, clip_refs, manifest_refs


def _camera_reference(camera: StoredCameraRecord) -> OperatorAssistReference:
    return OperatorAssistReference(
        kind=OperatorAssistReferenceKind.CAMERA,
        reference_id=camera.id,
        label=f"{camera.name} ({camera.camera_code})",
        camera_id=camera.id,
        metadata={"location_name": camera.location_name, "status": camera.status.value},
    )


def _append_operator_reference(
    references: list[OperatorAssistReference],
    reference: OperatorAssistReference,
) -> None:
    key = (reference.kind, reference.reference_id)
    if any((item.kind, item.reference_id) == key for item in references):
        return
    references.append(reference)


def _append_evidence_reference(
    evidence: list[EvidenceReference],
    reference: EvidenceReference,
) -> None:
    key = (reference.label, reference.source, reference.uri)
    if any((item.label, item.source, item.uri) == key for item in evidence):
        return
    evidence.append(reference)


def _violation_reference(hit: OperatorAssistViolationHit) -> OperatorAssistReference:
    violation = hit.violation_event
    return OperatorAssistReference(
        kind=OperatorAssistReferenceKind.VIOLATION_EVENT,
        reference_id=violation.id,
        label=f"{violation.violation_type.value} at {hit.camera.location_name}",
        occurred_at=violation.occurred_at,
        camera_id=hit.camera.id,
        metadata={"status": violation.status.value, "severity": violation.severity.value},
    )


def _detection_record_reference(
    camera_id: uuid.UUID,
    detection: StoredDetectionEventRecord,
    *,
    zone_name: str | None = None,
    zone_type: str | None = None,
) -> OperatorAssistReference:
    metadata: dict[str, Any] = {"confidence": detection.confidence, "track_id": detection.track_id}
    if zone_name is not None:
        metadata["zone_name"] = zone_name
    if zone_type is not None:
        metadata["zone_type"] = zone_type
    return OperatorAssistReference(
        kind=OperatorAssistReferenceKind.DETECTION_EVENT,
        reference_id=detection.id,
        label=f"{detection.event_type.value} for {detection.object_class}",
        occurred_at=detection.occurred_at,
        camera_id=camera_id,
        metadata=metadata,
    )


def _plate_record_reference(
    camera_id: uuid.UUID,
    plate: StoredPlateReadRecord,
) -> OperatorAssistReference:
    return OperatorAssistReference(
        kind=OperatorAssistReferenceKind.PLATE_READ,
        reference_id=plate.id,
        label=f"plate {plate.normalized_plate_text}",
        occurred_at=plate.occurred_at,
        camera_id=camera_id,
        metadata={"confidence": plate.confidence},
    )


def _detection_reference(hit: OperatorAssistViolationHit) -> OperatorAssistReference | None:
    detection = hit.detection_event
    if detection is None:
        return None
    return _detection_record_reference(hit.camera.id, detection)


def _plate_reference(hit: OperatorAssistViolationHit) -> OperatorAssistReference | None:
    plate = hit.plate_read
    if plate is None:
        return None
    return _plate_record_reference(hit.camera.id, plate)


def _event_reference(hit: OperatorAssistEventHit) -> OperatorAssistReference:
    return _detection_record_reference(
        hit.camera.id,
        hit.detection_event,
        zone_name=hit.zone_name,
        zone_type=hit.zone_type,
    )


def _plate_hit_reference(hit: OperatorAssistPlateHit) -> OperatorAssistReference:
    return _plate_record_reference(hit.camera.id, hit.plate_read)


async def _build_review_backlog(
    session: AsyncSession,
    *,
    camera_ids: list[uuid.UUID],
    start_at: datetime,
    end_at: datetime,
) -> ReviewBacklog:
    open_violation_count = (
        await session.scalar(
            select(func.count())
            .select_from(ViolationEvent)
            .where(ViolationEvent.camera_id.in_(camera_ids), ViolationEvent.status == ViolationStatus.OPEN)
        )
    ) or 0
    under_review_count = (
        await session.scalar(
            select(func.count())
            .select_from(ViolationEvent)
            .where(ViolationEvent.camera_id.in_(camera_ids), ViolationEvent.status == ViolationStatus.UNDER_REVIEW)
        )
    ) or 0
    oldest_open_at = await session.scalar(
        select(func.min(ViolationEvent.occurred_at))
        .where(ViolationEvent.camera_id.in_(camera_ids), ViolationEvent.status == ViolationStatus.OPEN)
    )
    reviewed_rows = (
        await session.execute(
            select(ViolationEvent.occurred_at, ViolationEvent.reviewed_at)
            .where(
                ViolationEvent.camera_id.in_(camera_ids),
                ViolationEvent.reviewed_at.isnot(None),
                ViolationEvent.reviewed_at >= start_at,
                ViolationEvent.reviewed_at < end_at,
            )
        )
    ).all()
    review_durations_hours = [
        (reviewed_at - occurred_at).total_seconds() / 3600
        for occurred_at, reviewed_at in reviewed_rows
        if reviewed_at is not None and reviewed_at >= occurred_at
    ]
    return ReviewBacklog(
        open_violations=int(open_violation_count),
        under_review_violations=int(under_review_count),
        oldest_open_at=oldest_open_at,
        avg_review_hours=(round(sum(review_durations_hours) / len(review_durations_hours), 1) if review_durations_hours else None),
    )


async def _build_watchlist_section(
    session: AsyncSession,
    *,
    camera_ids: list[uuid.UUID],
    start_at: datetime,
    end_at: datetime,
) -> WatchlistSection:
    try:
        watchlist_total = (
            await session.scalar(
                select(func.count())
                .select_from(WatchlistAlert)
                .where(
                    WatchlistAlert.camera_id.in_(camera_ids),
                    WatchlistAlert.occurred_at >= start_at,
                    WatchlistAlert.occurred_at < end_at,
                )
            )
        ) or 0
        watchlist_open = (
            await session.scalar(
                select(func.count())
                .select_from(WatchlistAlert)
                .where(
                    WatchlistAlert.camera_id.in_(camera_ids),
                    WatchlistAlert.status == WatchlistAlertStatus.OPEN,
                    WatchlistAlert.occurred_at >= start_at,
                    WatchlistAlert.occurred_at < end_at,
                )
            )
        ) or 0
        top_reasons_rows = (
            await session.execute(
                select(WatchlistAlert.reason, func.count())
                .where(
                    WatchlistAlert.camera_id.in_(camera_ids),
                    WatchlistAlert.occurred_at >= start_at,
                    WatchlistAlert.occurred_at < end_at,
                )
                .group_by(WatchlistAlert.reason)
            )
        ).all()
        return WatchlistSection(
            total_alerts=int(watchlist_total),
            open_alerts=int(watchlist_open),
            top_reasons={reason.value: count for reason, count in top_reasons_rows},
            data_available=True,
        )
    except Exception:
        return WatchlistSection(data_available=False)


def _build_camera_health_concerns(cameras: list[Camera]) -> list[CameraHealthConcern]:
    concerns: list[CameraHealthConcern] = []
    for camera in cameras:
        if camera.status.value in {"maintenance", "disabled"}:
            concerns.append(
                CameraHealthConcern(
                    camera_id=camera.id,
                    camera_name=camera.name,
                    concern=f"Camera status is {camera.status.value}.",
                )
            )
    return concerns


class SqlAlchemyWorkflowRepository(WorkflowRepository):
    """SQLAlchemy-backed workflow repository using stored pipeline outputs."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def build_incident_triage_context(self, request: IncidentTriageRequest) -> IncidentTriageContext:
        if request.violation_event_id is not None:
            review_context = await self.build_violation_review_context(
                ViolationReviewRequest(
                    violation_event_id=request.violation_event_id,
                    requested_by=request.requested_by,
                    operator_notes=request.operator_notes,
                    require_human_approval=request.require_human_review,
                )
            )
            return IncidentTriageContext(
                source_kind="violation",
                camera=review_context.camera,
                detection_event=review_context.detection_event,
                violation_event=review_context.violation_event,
                plate_read=review_context.plate_read,
                evidence=review_context.evidence,
                review_context=review_context.review_context,
            )

        assert request.detection_event_id is not None
        async with self._session_factory() as session:
            statement = (
                select(DetectionEvent)
                .options(
                    selectinload(DetectionEvent.camera),
                    selectinload(DetectionEvent.plate_reads),
                    selectinload(DetectionEvent.evidence_manifests),
                    selectinload(DetectionEvent.violation_events),
                    selectinload(DetectionEvent.violation_events).selectinload(ViolationEvent.evidence_manifests),
                )
                .where(DetectionEvent.id == request.detection_event_id)
            )
            detection = await session.scalar(statement)
            if detection is None:
                msg = "Detection event not found."
                raise RecordNotFoundError(msg)

            plate_read = detection.plate_reads[0] if detection.plate_reads else None
            violation = detection.violation_events[0] if detection.violation_events else None
            return IncidentTriageContext(
                source_kind="detection",
                camera=_to_camera_record(detection.camera),
                detection_event=_to_detection_record(detection),
                violation_event=_to_violation_record(violation) if violation is not None else None,
                plate_read=_to_plate_read_record(plate_read) if plate_read is not None else None,
                evidence=_build_evidence(detection=detection, violation=violation, plate_read=plate_read),
                review_context=ReviewContext(
                    requested_by=request.requested_by,
                    operator_notes=request.operator_notes,
                ),
            )

    async def build_violation_review_context(self, request: ViolationReviewRequest) -> ViolationReviewContext:
        async with self._session_factory() as session:
            statement = (
                select(ViolationEvent)
                .options(
                    selectinload(ViolationEvent.camera),
                    selectinload(ViolationEvent.detection_event),
                    selectinload(ViolationEvent.detection_event).selectinload(DetectionEvent.evidence_manifests),
                    selectinload(ViolationEvent.evidence_manifests),
                    selectinload(ViolationEvent.plate_read),
                )
                .where(ViolationEvent.id == request.violation_event_id)
            )
            violation = await session.scalar(statement)
            if violation is None:
                msg = "Violation event not found."
                raise RecordNotFoundError(msg)

            detection = violation.detection_event
            plate_read = violation.plate_read

            return ViolationReviewContext(
                camera=_to_camera_record(violation.camera),
                violation_event=_to_violation_record(violation),
                detection_event=_to_detection_record(detection) if detection is not None else None,
                plate_read=_to_plate_read_record(plate_read) if plate_read is not None else None,
                evidence=_build_evidence(detection=detection, violation=violation, plate_read=plate_read),
                review_context=ReviewContext(
                    requested_by=request.requested_by,
                    operator_notes=request.operator_notes,
                    existing_review_note=violation.review_note,
                    assigned_to=violation.assigned_to,
                    reviewed_by=violation.reviewed_by,
                ),
            )

    async def build_multimodal_review_context(self, request: MultimodalReviewRequest) -> MultimodalReviewContext:
        async with self._session_factory() as session:
            statement = (
                select(ViolationEvent)
                .options(
                    selectinload(ViolationEvent.camera),
                    selectinload(ViolationEvent.detection_event),
                    selectinload(ViolationEvent.detection_event).selectinload(DetectionEvent.evidence_manifests),
                    selectinload(ViolationEvent.evidence_manifests),
                    selectinload(ViolationEvent.plate_read),
                )
                .where(ViolationEvent.id == request.violation_event_id)
            )
            violation = await session.scalar(statement)
            if violation is None:
                msg = "Violation event not found."
                raise RecordNotFoundError(msg)

            detection = violation.detection_event
            plate_read = violation.plate_read
            rule_explanation = _build_multimodal_rule_explanation(
                violation=violation,
                detection=detection,
            )
            metadata_refs, image_refs, clip_refs, manifest_refs = _build_multimodal_references(
                detection=detection,
                violation=violation,
                plate_read=plate_read,
                operator_notes=request.operator_notes,
            )
            prior_review_history = await self._load_prior_review_history(
                session,
                violation=violation,
                detection=detection,
                include_prior_review_history=request.include_prior_review_history,
                limit=request.prior_review_limit,
            )

            return MultimodalReviewContext(
                camera=_to_camera_record(violation.camera),
                violation_event=_to_violation_record(violation),
                detection_event=_to_detection_record(detection) if detection is not None else None,
                plate_read=_to_plate_read_record(plate_read) if plate_read is not None else None,
                review_context=ReviewContext(
                    requested_by=request.requested_by,
                    operator_notes=request.operator_notes,
                    existing_review_note=violation.review_note,
                    assigned_to=violation.assigned_to,
                    reviewed_by=violation.reviewed_by,
                ),
                rule_explanation=rule_explanation,
                metadata_references=metadata_refs,
                image_references=image_refs,
                clip_references=clip_refs,
                manifest_references=manifest_refs,
                prior_review_history=prior_review_history,
            )

    async def build_daily_summary_context(self, request: DailySummaryRequest) -> DailySummaryContext:
        start_at = datetime.combine(request.report_date, time.min, tzinfo=timezone.utc)
        end_at = start_at + timedelta(days=1)

        async with self._session_factory() as session:
            camera_statement = select(Camera)
            if request.camera_id is not None:
                camera_statement = camera_statement.where(Camera.id == request.camera_id)
            cameras = list((await session.scalars(camera_statement.order_by(Camera.created_at.asc()))).all())
            if request.camera_id is not None and not cameras:
                msg = "Camera not found for daily summary."
                raise RecordNotFoundError(msg)

            if not cameras:
                return DailySummaryContext(report_date=request.report_date, camera_scope=request.camera_id, requested_by=request.requested_by)

            camera_ids = [camera.id for camera in cameras]

            detection_counts_stmt = (
                select(DetectionEvent.camera_id, func.count())
                .where(
                    DetectionEvent.camera_id.in_(camera_ids),
                    DetectionEvent.occurred_at >= start_at,
                    DetectionEvent.occurred_at < end_at,
                )
                .group_by(DetectionEvent.camera_id)
            )
            violation_counts_stmt = (
                select(ViolationEvent.camera_id, func.count())
                .where(
                    ViolationEvent.camera_id.in_(camera_ids),
                    ViolationEvent.occurred_at >= start_at,
                    ViolationEvent.occurred_at < end_at,
                )
                .group_by(ViolationEvent.camera_id)
            )
            open_counts_stmt = (
                select(ViolationEvent.camera_id, func.count())
                .where(
                    ViolationEvent.camera_id.in_(camera_ids),
                    ViolationEvent.status == ViolationStatus.OPEN,
                )
                .group_by(ViolationEvent.camera_id)
            )
            last_incident_stmt = (
                select(ViolationEvent.camera_id, func.max(ViolationEvent.occurred_at))
                .where(ViolationEvent.camera_id.in_(camera_ids))
                .group_by(ViolationEvent.camera_id)
            )
            top_types_stmt = (
                select(ViolationEvent.camera_id, ViolationEvent.violation_type, func.count())
                .where(
                    ViolationEvent.camera_id.in_(camera_ids),
                    ViolationEvent.occurred_at >= start_at,
                    ViolationEvent.occurred_at < end_at,
                )
                .group_by(ViolationEvent.camera_id, ViolationEvent.violation_type)
            )
            open_examples_stmt = (
                select(ViolationEvent)
                .options(selectinload(ViolationEvent.camera))
                .where(
                    ViolationEvent.camera_id.in_(camera_ids),
                    ViolationEvent.status == ViolationStatus.OPEN,
                )
                .order_by(ViolationEvent.occurred_at.desc())
                .limit(request.include_open_violation_examples)
            )

            detection_counts = dict((await session.execute(detection_counts_stmt)).all())
            violation_counts = dict((await session.execute(violation_counts_stmt)).all())
            open_counts = dict((await session.execute(open_counts_stmt)).all())
            last_incident_map = dict((await session.execute(last_incident_stmt)).all())

            top_types_by_camera: dict[uuid.UUID, dict[str, int]] = defaultdict(dict)
            top_types_totals: dict[str, int] = defaultdict(int)
            for camera_id, violation_type, count in (await session.execute(top_types_stmt)).all():
                top_types_by_camera[camera_id][violation_type.value] = count
                top_types_totals[violation_type.value] += count

            open_examples = [
                _to_violation_record(item)
                for item in (await session.scalars(open_examples_stmt)).all()
            ]

            summaries = [
                CameraDailySummary(
                    camera_id=camera.id,
                    camera_name=camera.name,
                    location_name=camera.location_name,
                    detection_count=int(detection_counts.get(camera.id, 0)),
                    violation_count=int(violation_counts.get(camera.id, 0)),
                    open_violation_count=int(open_counts.get(camera.id, 0)),
                    top_violation_types=top_types_by_camera.get(camera.id, {}),
                    last_incident_at=last_incident_map.get(camera.id),
                )
                for camera in cameras
            ]
            review_backlog = await _build_review_backlog(
                session,
                camera_ids=camera_ids,
                start_at=start_at,
                end_at=end_at,
            )
            watchlist = await _build_watchlist_section(
                session,
                camera_ids=camera_ids,
                start_at=start_at,
                end_at=end_at,
            )
            health_concerns = _build_camera_health_concerns(cameras)

            return DailySummaryContext(
                report_date=request.report_date,
                camera_scope=request.camera_id,
                cameras=summaries,
                total_detections=sum(item.detection_count for item in summaries),
                total_violations=sum(item.violation_count for item in summaries),
                total_open_violations=sum(item.open_violation_count for item in summaries),
                top_violation_types=dict(top_types_totals),
                open_violation_examples=open_examples,
                review_backlog=review_backlog,
                watchlist=watchlist,
                camera_health_concerns=health_concerns,
                requested_by=request.requested_by,
            )

    async def build_weekly_summary_context(self, request: WeeklySummaryRequest) -> WeeklySummaryContext:
        week_end_date = request.week_ending
        week_start_date = week_end_date - timedelta(days=6)
        start_at = datetime.combine(week_start_date, time.min, tzinfo=timezone.utc)
        end_at = datetime.combine(week_end_date, time.min, tzinfo=timezone.utc) + timedelta(days=1)

        async with self._session_factory() as session:
            camera_statement = select(Camera)
            if request.camera_id is not None:
                camera_statement = camera_statement.where(Camera.id == request.camera_id)
            cameras = list((await session.scalars(camera_statement.order_by(Camera.created_at.asc()))).all())
            if request.camera_id is not None and not cameras:
                msg = "Camera not found for weekly summary."
                raise RecordNotFoundError(msg)

            if not cameras:
                return WeeklySummaryContext(
                    week_ending=week_end_date,
                    week_start=week_start_date,
                    camera_scope=request.camera_id,
                    requested_by=request.requested_by,
                )

            camera_ids = [camera.id for camera in cameras]

            detection_counts_stmt = (
                select(DetectionEvent.camera_id, func.count())
                .where(
                    DetectionEvent.camera_id.in_(camera_ids),
                    DetectionEvent.occurred_at >= start_at,
                    DetectionEvent.occurred_at < end_at,
                )
                .group_by(DetectionEvent.camera_id)
            )
            violation_counts_stmt = (
                select(ViolationEvent.camera_id, func.count())
                .where(
                    ViolationEvent.camera_id.in_(camera_ids),
                    ViolationEvent.occurred_at >= start_at,
                    ViolationEvent.occurred_at < end_at,
                )
                .group_by(ViolationEvent.camera_id)
            )
            open_counts_stmt = (
                select(ViolationEvent.camera_id, func.count())
                .where(
                    ViolationEvent.camera_id.in_(camera_ids),
                    ViolationEvent.status == ViolationStatus.OPEN,
                )
                .group_by(ViolationEvent.camera_id)
            )
            top_types_stmt = (
                select(ViolationEvent.camera_id, ViolationEvent.violation_type, func.count())
                .where(
                    ViolationEvent.camera_id.in_(camera_ids),
                    ViolationEvent.occurred_at >= start_at,
                    ViolationEvent.occurred_at < end_at,
                )
                .group_by(ViolationEvent.camera_id, ViolationEvent.violation_type)
            )
            last_incident_stmt = (
                select(ViolationEvent.camera_id, func.max(ViolationEvent.occurred_at))
                .where(
                    ViolationEvent.camera_id.in_(camera_ids),
                    ViolationEvent.occurred_at >= start_at,
                    ViolationEvent.occurred_at < end_at,
                )
                .group_by(ViolationEvent.camera_id)
            )

            detection_counts = dict((await session.execute(detection_counts_stmt)).all())
            violation_counts = dict((await session.execute(violation_counts_stmt)).all())
            open_counts = dict((await session.execute(open_counts_stmt)).all())
            last_incident_map = dict((await session.execute(last_incident_stmt)).all())
            top_types_by_camera: dict[uuid.UUID, dict[str, int]] = defaultdict(dict)
            top_types_totals: dict[str, int] = defaultdict(int)
            for camera_id, violation_type, count in (await session.execute(top_types_stmt)).all():
                top_types_by_camera[camera_id][violation_type.value] = count
                top_types_totals[violation_type.value] += count

            summaries = [
                CameraDailySummary(
                    camera_id=camera.id,
                    camera_name=camera.name,
                    location_name=camera.location_name,
                    detection_count=int(detection_counts.get(camera.id, 0)),
                    violation_count=int(violation_counts.get(camera.id, 0)),
                    open_violation_count=int(open_counts.get(camera.id, 0)),
                    top_violation_types=top_types_by_camera.get(camera.id, {}),
                    last_incident_at=last_incident_map.get(camera.id),
                )
                for camera in cameras
            ]
            review_backlog = await _build_review_backlog(
                session,
                camera_ids=camera_ids,
                start_at=start_at,
                end_at=end_at,
            )
            watchlist = await _build_watchlist_section(
                session,
                camera_ids=camera_ids,
                start_at=start_at,
                end_at=end_at,
            )
            health_concerns = _build_camera_health_concerns(cameras)

            return WeeklySummaryContext(
                week_ending=week_end_date,
                week_start=week_start_date,
                camera_scope=request.camera_id,
                daily_breakdowns=summaries,
                total_detections=sum(item.detection_count for item in summaries),
                total_violations=sum(item.violation_count for item in summaries),
                total_open_violations=sum(item.open_violation_count for item in summaries),
                top_violation_types=dict(top_types_totals),
                review_backlog=review_backlog,
                watchlist=watchlist,
                camera_health_concerns=health_concerns,
                requested_by=request.requested_by,
            )

    async def build_hotspot_report_context(self, request: HotspotReportRequest) -> HotspotReportContext:
        start_at = datetime.combine(request.report_date - timedelta(days=request.lookback_days - 1), time.min, tzinfo=timezone.utc)
        end_at = datetime.combine(request.report_date, time.min, tzinfo=timezone.utc) + timedelta(days=1)

        async with self._session_factory() as session:
            total_violations = (
                await session.scalar(
                    select(func.count())
                    .select_from(ViolationEvent)
                    .where(ViolationEvent.occurred_at >= start_at, ViolationEvent.occurred_at < end_at)
                )
            ) or 0
            total_cameras_with_violations = (
                await session.scalar(
                    select(func.count(func.distinct(ViolationEvent.camera_id)))
                    .where(ViolationEvent.occurred_at >= start_at, ViolationEvent.occurred_at < end_at)
                )
            ) or 0

            if request.group_by == HotspotGroupBy.CAMERA:
                violation_by_camera = (
                    await session.execute(
                        select(ViolationEvent.camera_id, func.count())
                        .where(ViolationEvent.occurred_at >= start_at, ViolationEvent.occurred_at < end_at)
                        .group_by(ViolationEvent.camera_id)
                        .order_by(func.count().desc())
                        .limit(request.top_n)
                    )
                ).all()

                if not violation_by_camera:
                    return HotspotReportContext(
                        report_date=request.report_date,
                        lookback_days=request.lookback_days,
                        top_n=request.top_n,
                        group_by=request.group_by,
                        total_violations_in_window=int(total_violations),
                        total_groups_with_violations=0,
                        total_cameras_with_violations=int(total_cameras_with_violations),
                        requested_by=request.requested_by,
                    )

                camera_ids = [camera_id for camera_id, _ in violation_by_camera]
                camera_map = {
                    camera.id: camera
                    for camera in (await session.scalars(select(Camera).where(Camera.id.in_(camera_ids)))).all()
                }
                open_counts = dict(
                    (
                        await session.execute(
                            select(ViolationEvent.camera_id, func.count())
                            .where(
                                ViolationEvent.camera_id.in_(camera_ids),
                                ViolationEvent.status == ViolationStatus.OPEN,
                                ViolationEvent.occurred_at >= start_at,
                                ViolationEvent.occurred_at < end_at,
                            )
                            .group_by(ViolationEvent.camera_id)
                        )
                    ).all()
                )
                top_types_rows = (
                    await session.execute(
                        select(ViolationEvent.camera_id, ViolationEvent.violation_type, func.count())
                        .where(
                            ViolationEvent.camera_id.in_(camera_ids),
                            ViolationEvent.occurred_at >= start_at,
                            ViolationEvent.occurred_at < end_at,
                        )
                        .group_by(ViolationEvent.camera_id, ViolationEvent.violation_type)
                    )
                ).all()
                top_types_by_camera: dict[uuid.UUID, dict[str, int]] = defaultdict(dict)
                for camera_id, violation_type, count in top_types_rows:
                    top_types_by_camera[camera_id][violation_type.value] = count
                last_violation_map = dict(
                    (
                        await session.execute(
                            select(ViolationEvent.camera_id, func.max(ViolationEvent.occurred_at))
                            .where(
                                ViolationEvent.camera_id.in_(camera_ids),
                                ViolationEvent.occurred_at >= start_at,
                                ViolationEvent.occurred_at < end_at,
                            )
                            .group_by(ViolationEvent.camera_id)
                        )
                    ).all()
                )

                hotspots: list[HotspotEntry] = []
                for camera_id, v_count in violation_by_camera:
                    camera = camera_map.get(camera_id)
                    if camera is None:
                        continue
                    hotspots.append(
                        HotspotEntry(
                            camera_id=camera.id,
                            camera_name=camera.name,
                            location_name=camera.location_name,
                            violation_count=int(v_count),
                            open_count=int(open_counts.get(camera_id, 0)),
                            top_violation_types=top_types_by_camera.get(camera_id, {}),
                            last_violation_at=last_violation_map.get(camera_id),
                        )
                    )

                return HotspotReportContext(
                    report_date=request.report_date,
                    lookback_days=request.lookback_days,
                    top_n=request.top_n,
                    group_by=request.group_by,
                    hotspots=hotspots,
                    total_violations_in_window=int(total_violations),
                    total_groups_with_violations=int(total_cameras_with_violations),
                    total_cameras_with_violations=int(total_cameras_with_violations),
                    requested_by=request.requested_by,
                )

            violation_by_zone = (
                await session.execute(
                    select(ViolationEvent.zone_id, func.count())
                    .where(
                        ViolationEvent.occurred_at >= start_at,
                        ViolationEvent.occurred_at < end_at,
                        ViolationEvent.zone_id.is_not(None),
                    )
                    .group_by(ViolationEvent.zone_id)
                    .order_by(func.count().desc())
                    .limit(request.top_n)
                )
            ).all()
            total_groups_with_violations = (
                await session.scalar(
                    select(func.count(func.distinct(ViolationEvent.zone_id)))
                    .where(
                        ViolationEvent.occurred_at >= start_at,
                        ViolationEvent.occurred_at < end_at,
                        ViolationEvent.zone_id.is_not(None),
                    )
                )
            ) or 0
            unassigned_violations = (
                await session.scalar(
                    select(func.count())
                    .select_from(ViolationEvent)
                    .where(
                        ViolationEvent.occurred_at >= start_at,
                        ViolationEvent.occurred_at < end_at,
                        ViolationEvent.zone_id.is_(None),
                    )
                )
            ) or 0

            if not violation_by_zone:
                return HotspotReportContext(
                    report_date=request.report_date,
                    lookback_days=request.lookback_days,
                    top_n=request.top_n,
                    group_by=request.group_by,
                    total_violations_in_window=int(total_violations),
                    total_groups_with_violations=int(total_groups_with_violations),
                    total_cameras_with_violations=int(total_cameras_with_violations),
                    unassigned_violations=int(unassigned_violations),
                    requested_by=request.requested_by,
                )

            zone_ids = [zone_id for zone_id, _ in violation_by_zone if zone_id is not None]
            zone_map = {
                zone.id: zone
                for zone in (
                    await session.scalars(
                        select(Zone)
                        .options(selectinload(Zone.camera))
                        .where(Zone.id.in_(zone_ids))
                    )
                ).all()
            }
            open_counts = dict(
                (
                    await session.execute(
                        select(ViolationEvent.zone_id, func.count())
                        .where(
                            ViolationEvent.zone_id.in_(zone_ids),
                            ViolationEvent.status == ViolationStatus.OPEN,
                            ViolationEvent.occurred_at >= start_at,
                            ViolationEvent.occurred_at < end_at,
                        )
                        .group_by(ViolationEvent.zone_id)
                    )
                ).all()
            )
            top_types_rows = (
                await session.execute(
                    select(ViolationEvent.zone_id, ViolationEvent.violation_type, func.count())
                    .where(
                        ViolationEvent.zone_id.in_(zone_ids),
                        ViolationEvent.occurred_at >= start_at,
                        ViolationEvent.occurred_at < end_at,
                    )
                    .group_by(ViolationEvent.zone_id, ViolationEvent.violation_type)
                )
            ).all()
            top_types_by_zone: dict[uuid.UUID, dict[str, int]] = defaultdict(dict)
            for zone_id, violation_type, count in top_types_rows:
                assert zone_id is not None
                top_types_by_zone[zone_id][violation_type.value] = count
            last_violation_map = dict(
                (
                    await session.execute(
                        select(ViolationEvent.zone_id, func.max(ViolationEvent.occurred_at))
                        .where(
                            ViolationEvent.zone_id.in_(zone_ids),
                            ViolationEvent.occurred_at >= start_at,
                            ViolationEvent.occurred_at < end_at,
                        )
                        .group_by(ViolationEvent.zone_id)
                    )
                ).all()
            )

            hotspots: list[HotspotEntry] = []
            for zone_id, v_count in violation_by_zone:
                if zone_id is None:
                    continue
                zone = zone_map.get(zone_id)
                if zone is None:
                    continue
                hotspots.append(
                    HotspotEntry(
                        camera_id=zone.camera_id,
                        camera_name=zone.camera.name,
                        location_name=f"{zone.camera.location_name} / {zone.name}",
                        zone_id=zone.id,
                        zone_name=zone.name,
                        zone_type=zone.zone_type.value,
                        violation_count=int(v_count),
                        open_count=int(open_counts.get(zone_id, 0)),
                        top_violation_types=top_types_by_zone.get(zone_id, {}),
                        last_violation_at=last_violation_map.get(zone_id),
                    )
                )

            return HotspotReportContext(
                report_date=request.report_date,
                lookback_days=request.lookback_days,
                top_n=request.top_n,
                group_by=request.group_by,
                hotspots=hotspots,
                total_violations_in_window=int(total_violations),
                total_groups_with_violations=int(total_groups_with_violations),
                total_cameras_with_violations=int(total_cameras_with_violations),
                unassigned_violations=int(unassigned_violations),
                requested_by=request.requested_by,
            )

    async def _load_prior_review_history(
        self,
        session: AsyncSession,
        *,
        violation: ViolationEvent,
        detection: DetectionEvent | None,
        include_prior_review_history: bool,
        limit: int,
    ) -> list[PriorReviewRecord]:
        history: list[PriorReviewRecord] = []
        if violation.review_note or violation.reviewed_by or violation.reviewed_at is not None:
            history.append(
                PriorReviewRecord(
                    source="violation_event",
                    recorded_at=violation.reviewed_at or violation.updated_at or violation.occurred_at,
                    recorded_by=violation.reviewed_by,
                    summary=violation.review_note
                    or f"Violation status was set to {violation.status.value}.",
                    disposition=violation.status.value,
                    metadata={"status": violation.status.value},
                )
            )

        if not include_prior_review_history or limit == 0:
            history.sort(key=lambda item: item.recorded_at, reverse=True)
            return history

        conditions = [WorkflowRun.violation_event_id == violation.id]
        if detection is not None:
            conditions.append(WorkflowRun.detection_event_id == detection.id)
        statement = (
            select(WorkflowRun)
            .where(or_(*conditions), WorkflowRun.status == WorkflowStatus.SUCCEEDED)
            .order_by(WorkflowRun.completed_at.desc(), WorkflowRun.created_at.desc())
            .limit(limit)
        )
        runs = (await session.scalars(statement)).all()
        for run in runs:
            entry = _workflow_run_history_entry(run)
            if entry is not None:
                history.append(entry)

        history.sort(key=lambda item: item.recorded_at, reverse=True)
        return history

    async def build_operator_assist_grounding(
        self,
        request: OperatorAssistRequest,
        plan: OperatorAssistPlan,
    ) -> OperatorAssistGrounding:
        async with self._session_factory() as session:
            camera_matches = await self._resolve_camera_matches(
                session,
                explicit_camera_id=request.camera_id,
                camera_hint=plan.camera_hint,
            )

            if request.camera_id is not None and not camera_matches:
                msg = "Camera not found for operator assist."
                raise RecordNotFoundError(msg)

            grounding_notes: list[str] = []
            references = [_camera_reference(camera) for camera in camera_matches]

            if plan.intent == OperatorAssistIntent.UNKNOWN:
                return OperatorAssistGrounding(
                    plan=plan,
                    camera_matches=camera_matches,
                    references=references,
                    grounding_notes=["The query did not map to a supported operator-assist retrieval plan."],
                )

            if plan.intent == OperatorAssistIntent.EXPLAIN_VIOLATION:
                if plan.explicit_violation_event_id is None:
                    return OperatorAssistGrounding(
                        plan=plan,
                        camera_matches=camera_matches,
                        references=references,
                        grounding_notes=[
                            "A specific stored violation_event_id is required to explain why an alert fired."
                        ],
                    )

                violation = await self._load_violation_with_context(session, plan.explicit_violation_event_id)
                if violation is None:
                    msg = "Violation event not found for operator assist."
                    raise RecordNotFoundError(msg)

                hit = self._to_operator_violation_hit(violation)
                references = [
                    _camera_reference(hit.camera),
                    _violation_reference(hit),
                ]
                detection_ref = _detection_reference(hit)
                plate_ref = _plate_reference(hit)
                if detection_ref is not None:
                    references.append(detection_ref)
                if plate_ref is not None:
                    references.append(plate_ref)

                return OperatorAssistGrounding(
                    plan=plan,
                    camera_matches=[hit.camera],
                    violation_hits=[hit],
                    supporting_evidence=_build_evidence(
                        detection=violation.detection_event,
                        violation=violation,
                        plate_read=violation.plate_read,
                    ),
                    references=references,
                )

            if plan.intent in {
                OperatorAssistIntent.SEARCH_EVENTS,
                OperatorAssistIntent.SEARCH_PLATES,
                OperatorAssistIntent.SEARCH_VIOLATIONS,
            } and request.camera_id is None and plan.camera_hint is not None:
                if not camera_matches:
                    grounding_notes.append(f"No stored camera matched the hint {plan.camera_hint!r}.")
                    return OperatorAssistGrounding(
                        plan=plan,
                        camera_matches=[],
                        references=[],
                        grounding_notes=grounding_notes,
                    )
            scoped_camera_id = camera_matches[0].id if len(camera_matches) == 1 else None
            scoped_camera_query = (
                plan.camera_hint
                if request.camera_id is None and plan.camera_hint is not None and len(camera_matches) > 1
                else None
            )

            if plan.intent == OperatorAssistIntent.SEARCH_EVENTS:
                items, total = await search_detection_events(
                    session,
                    camera_id=scoped_camera_id,
                    camera_query=scoped_camera_query,
                    event_type=plan.event_type,
                    status=plan.event_status,
                    occurred_after=plan.start_at,
                    occurred_before=plan.end_at,
                    object_class=plan.object_class,
                    zone_type=plan.zone_type,
                    limit=plan.max_results,
                )
                hits = [self._to_operator_event_hit(item) for item in items]
                references = [_camera_reference(camera) for camera in camera_matches]
                for hit in hits:
                    for reference in self._references_for_event_hit(hit):
                        _append_operator_reference(references, reference)
                evidence: list[EvidenceReference] = []
                for item in items[:3]:
                    for reference in _build_evidence(detection=item, violation=None, plate_read=None):
                        _append_evidence_reference(evidence, reference)
                return OperatorAssistGrounding(
                    plan=plan,
                    camera_matches=camera_matches,
                    event_hits=hits,
                    total_matches=int(total),
                    supporting_evidence=evidence,
                    references=references,
                )

            if plan.intent == OperatorAssistIntent.SEARCH_PLATES:
                items, total = await search_plates(
                    session,
                    plate_text=plan.plate_text,
                    partial=plan.partial_plate,
                    normalized=True,
                    camera_id=scoped_camera_id,
                    camera_query=scoped_camera_query,
                    occurred_after=plan.start_at,
                    occurred_before=plan.end_at,
                    status=plan.plate_status,
                    limit=plan.max_results,
                )
                hits = [self._to_operator_plate_hit(item) for item in items]
                references = [_camera_reference(camera) for camera in camera_matches]
                for hit in hits:
                    for reference in self._references_for_plate_hit(hit):
                        _append_operator_reference(references, reference)
                evidence = []
                for item in items[:3]:
                    for reference in _build_evidence(
                        detection=item.detection_event,
                        violation=None,
                        plate_read=item,
                    ):
                        _append_evidence_reference(evidence, reference)
                return OperatorAssistGrounding(
                    plan=plan,
                    camera_matches=camera_matches,
                    plate_hits=hits,
                    total_matches=int(total),
                    supporting_evidence=evidence,
                    references=references,
                )

            if plan.intent == OperatorAssistIntent.SEARCH_VIOLATIONS:
                multi_violation_types = plan.violation_types if len(plan.violation_types) > 1 else None
                items, total = await search_violation_events(
                    session,
                    camera_id=scoped_camera_id,
                    camera_query=scoped_camera_query,
                    violation_type=plan.violation_type if multi_violation_types is None else None,
                    violation_types=multi_violation_types,
                    status=plan.violation_status,
                    occurred_after=plan.start_at,
                    occurred_before=plan.end_at,
                    object_class=plan.object_class,
                    plate_text=plan.plate_text,
                    partial_plate=plan.partial_plate,
                    zone_type=plan.zone_type,
                    limit=plan.max_results,
                )
                hits = [self._to_operator_violation_hit(item) for item in items]
                references = [_camera_reference(camera) for camera in camera_matches]
                for hit in hits:
                    for reference in self._references_for_hit(hit):
                        _append_operator_reference(references, reference)
                evidence = []
                for item in items[:3]:
                    for reference in _build_evidence(
                        detection=item.detection_event,
                        violation=item,
                        plate_read=item.plate_read,
                    ):
                        _append_evidence_reference(evidence, reference)
                return OperatorAssistGrounding(
                    plan=plan,
                    camera_matches=camera_matches,
                    violation_hits=hits,
                    total_matches=int(total),
                    supporting_evidence=evidence,
                    references=references,
                )

            if plan.intent == OperatorAssistIntent.SUMMARIZE_REPEATED_INCIDENTS:
                if request.camera_id is None and plan.camera_hint is None:
                    return OperatorAssistGrounding(
                        plan=plan,
                        camera_matches=[],
                        references=[],
                        grounding_notes=[
                            "Repeated-incident summaries require a specific camera or junction scope."
                        ],
                    )
                if request.camera_id is None and plan.camera_hint is not None:
                    if not camera_matches:
                        return OperatorAssistGrounding(
                            plan=plan,
                            camera_matches=[],
                            references=[],
                            grounding_notes=[f"No stored camera matched the hint {plan.camera_hint!r}."],
                        )
                    if len(camera_matches) > 1:
                        return OperatorAssistGrounding(
                            plan=plan,
                            camera_matches=camera_matches,
                            references=references,
                            grounding_notes=[
                                f"Camera hint {plan.camera_hint!r} matched multiple stored cameras."
                            ],
                        )

                statement = (
                    select(ViolationEvent)
                    .options(selectinload(ViolationEvent.camera))
                    .where(ViolationEvent.camera_id.in_([camera.id for camera in camera_matches]))
                    .order_by(ViolationEvent.occurred_at.desc())
                )
                if plan.start_at is not None:
                    statement = statement.where(ViolationEvent.occurred_at >= plan.start_at)
                if plan.end_at is not None:
                    statement = statement.where(ViolationEvent.occurred_at < plan.end_at)

                grouped: dict[tuple[uuid.UUID, str], list[ViolationEvent]] = {}
                for violation in (await session.scalars(statement)).all():
                    grouped.setdefault((violation.camera_id, violation.violation_type.value), []).append(violation)

                summaries: list[RepeatedIncidentSummary] = []
                references = [_camera_reference(camera) for camera in camera_matches]
                for group in grouped.values():
                    first = group[0]
                    camera_record = _to_camera_record(first.camera)
                    summaries.append(
                        RepeatedIncidentSummary(
                            camera=camera_record,
                            violation_type=first.violation_type,
                            incident_count=len(group),
                            open_count=sum(1 for item in group if item.status == ViolationStatus.OPEN),
                            last_occurred_at=max(item.occurred_at for item in group),
                            sample_violation_event_ids=[item.id for item in group[:3]],
                        )
                    )
                summaries.sort(key=lambda item: (item.incident_count, item.open_count), reverse=True)

                for summary in summaries[:3]:
                    for violation_id in summary.sample_violation_event_ids:
                        references.append(
                            OperatorAssistReference(
                                kind=OperatorAssistReferenceKind.VIOLATION_EVENT,
                                reference_id=violation_id,
                                label=f"sample {summary.violation_type.value} violation",
                                camera_id=summary.camera.id,
                            )
                        )

                return OperatorAssistGrounding(
                    plan=plan,
                    camera_matches=camera_matches,
                    incident_summaries=summaries,
                    references=references,
                )

            return OperatorAssistGrounding(plan=plan, camera_matches=camera_matches, references=references)

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
        async with self._session_factory() as session:
            run = WorkflowRun(
                workflow_type=workflow_type,
                status=WorkflowStatus.QUEUED,
                priority=priority,
                requested_by=requested_by,
                camera_id=camera_id,
                detection_event_id=detection_event_id,
                violation_event_id=violation_event_id,
                input_payload={**input_payload, "workflow_name": workflow_name.value},
            )
            session.add(run)
            await session.commit()
            await session.refresh(run)
            return _to_workflow_run_record(run)

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
        async with self._session_factory() as session:
            run = await session.get(WorkflowRun, run_id)
            if run is None:
                msg = "Workflow run not found."
                raise RecordNotFoundError(msg)

            run.status = status
            if result_payload is not None:
                run.result_payload = result_payload
            if error_message is not None:
                run.error_message = error_message
            if started_at is not None:
                run.started_at = started_at
            if completed_at is not None:
                run.completed_at = completed_at

            await session.commit()
            await session.refresh(run)
            return _to_workflow_run_record(run)

    async def get_workflow_run(self, run_id: uuid.UUID) -> StoredWorkflowRun:
        async with self._session_factory() as session:
            run = await session.get(WorkflowRun, run_id)
            if run is None:
                msg = "Workflow run not found."
                raise RecordNotFoundError(msg)
            return _to_workflow_run_record(run)

    async def apply_violation_disposition(
        self,
        violation_event_id: uuid.UUID,
        *,
        new_status: ViolationStatus,
        reviewed_by: str | None,
        review_note: str | None,
    ) -> None:
        async with self._session_factory() as session:
            violation = await session.get(ViolationEvent, violation_event_id)
            if violation is None:
                msg = "Violation event not found for disposition write-back."
                raise RecordNotFoundError(msg)
            violation.status = new_status
            if reviewed_by is not None:
                violation.reviewed_by = reviewed_by
            if review_note is not None:
                violation.review_note = review_note
            violation.reviewed_at = datetime.now(timezone.utc)
            await session.commit()

    async def _resolve_camera_matches(
        self,
        session: AsyncSession,
        *,
        explicit_camera_id: uuid.UUID | None,
        camera_hint: str | None,
    ) -> list[StoredCameraRecord]:
        if explicit_camera_id is not None:
            camera = await session.get(Camera, explicit_camera_id)
            return [_to_camera_record(camera)] if camera is not None else []
        if camera_hint is None:
            return []

        search_term = f"%{camera_hint.lower()}%"
        statement = (
            select(Camera)
            .where(
                or_(
                    func.lower(Camera.camera_code).like(search_term),
                    func.lower(Camera.name).like(search_term),
                    func.lower(Camera.location_name).like(search_term),
                )
            )
            .order_by(Camera.name.asc())
        )
        return [_to_camera_record(camera) for camera in (await session.scalars(statement)).all()]

    async def _load_violation_with_context(
        self,
        session: AsyncSession,
        violation_event_id: uuid.UUID,
    ) -> ViolationEvent | None:
        statement = (
            select(ViolationEvent)
            .options(
                selectinload(ViolationEvent.camera),
                selectinload(ViolationEvent.detection_event),
                selectinload(ViolationEvent.detection_event).selectinload(DetectionEvent.evidence_manifests),
                selectinload(ViolationEvent.evidence_manifests),
                selectinload(ViolationEvent.plate_read),
            )
            .where(ViolationEvent.id == violation_event_id)
        )
        return await session.scalar(statement)

    @staticmethod
    def _to_operator_violation_hit(violation: ViolationEvent) -> OperatorAssistViolationHit:
        detection = violation.detection_event
        plate_read = violation.plate_read
        return OperatorAssistViolationHit(
            camera=_to_camera_record(violation.camera),
            violation_event=_to_violation_record(violation),
            detection_event=_to_detection_record(detection) if detection is not None else None,
            plate_read=_to_plate_read_record(plate_read) if plate_read is not None else None,
        )

    @staticmethod
    def _to_operator_event_hit(detection: DetectionEvent) -> OperatorAssistEventHit:
        zone = detection.zone
        return OperatorAssistEventHit(
            camera=_to_camera_record(detection.camera),
            detection_event=_to_detection_record(detection),
            zone_name=zone.name if zone is not None else None,
            zone_type=zone.zone_type.value if zone is not None else None,
        )

    @staticmethod
    def _to_operator_plate_hit(plate_read: PlateRead) -> OperatorAssistPlateHit:
        detection = plate_read.detection_event
        return OperatorAssistPlateHit(
            camera=_to_camera_record(plate_read.camera),
            plate_read=_to_plate_read_record(plate_read),
            detection_event=_to_detection_record(detection) if detection is not None else None,
        )

    @staticmethod
    def _references_for_hit(hit: OperatorAssistViolationHit) -> list[OperatorAssistReference]:
        refs: list[OperatorAssistReference] = []
        _append_operator_reference(refs, _camera_reference(hit.camera))
        _append_operator_reference(refs, _violation_reference(hit))
        detection_ref = _detection_reference(hit)
        plate_ref = _plate_reference(hit)
        if detection_ref is not None:
            _append_operator_reference(refs, detection_ref)
        if plate_ref is not None:
            _append_operator_reference(refs, plate_ref)
        return refs

    @staticmethod
    def _references_for_event_hit(hit: OperatorAssistEventHit) -> list[OperatorAssistReference]:
        refs: list[OperatorAssistReference] = []
        _append_operator_reference(refs, _camera_reference(hit.camera))
        _append_operator_reference(refs, _event_reference(hit))
        return refs

    @staticmethod
    def _references_for_plate_hit(hit: OperatorAssistPlateHit) -> list[OperatorAssistReference]:
        refs: list[OperatorAssistReference] = []
        _append_operator_reference(refs, _camera_reference(hit.camera))
        _append_operator_reference(refs, _plate_hit_reference(hit))
        if hit.detection_event is not None:
            _append_operator_reference(refs, _detection_record_reference(hit.camera.id, hit.detection_event))
        return refs
