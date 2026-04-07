"""Service layer for case export and audit-ready evidence bundle generation."""

from __future__ import annotations

import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.app.db.enums import (
    CaseExportAuditEventType,
    CaseExportFormat,
    CaseExportStatus,
    CaseSubjectKind,
)
from apps.api.app.db.models import (
    Camera,
    CaseExport,
    CaseExportAuditEvent,
    DetectionEvent,
    EvidenceManifest,
    PlateRead,
    ViolationEvent,
    WorkflowRun,
)
from apps.api.app.schemas.exports import (
    CaseExportCreateRequest,
    CaseExportDetailRead,
    CaseExportSummaryRead,
)
from apps.api.app.services.errors import NotFoundError
from services.access_control.policy import (
    AccessContext,
    AccessPermission,
    audit_sensitive_access,
    require_permissions,
    resolve_access_context,
)
from services.evidence.privacy import (
    mask_plate_text,
    resolve_access_resolution,
    sanitize_manifest_for_access,
)
from services.evidence.schemas import (
    EvidenceAccessResolution,
    EvidenceAccessRole,
    EvidenceAssetView,
    EvidenceManifestDocument,
    EvidencePrivacyPolicy,
)

_BUNDLE_FORMAT_VERSION = "1.0"
_DEFAULT_EVIDENCE_PRIVACY_POLICY = EvidencePrivacyPolicy()


class CaseExportService:
    """Generate and persist audit-ready case export bundles."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_export(
        self,
        session: AsyncSession,
        body: CaseExportCreateRequest,
    ) -> CaseExport:
        access_context = resolve_access_context(body.access_role)
        require_permissions(
            context=access_context,
            required_permissions=[AccessPermission.EXPORT_EVIDENCE],
            resource="case_export",
            action="create export",
            entity_id=str(body.subject_id),
        )
        audit_sensitive_access(
            context=access_context,
            action="create export",
            resource="case_export",
            entity_id=str(body.subject_id),
            outcome="allowed",
            details={"requested_view": body.requested_view.value if body.requested_view else None},
        )
        now = datetime.now(timezone.utc)
        export_id = uuid.uuid4()
        access = self._resolve_export_access(body.access_role, body.requested_view)
        filename = self._build_filename(
            body.subject_kind,
            body.subject_id,
            export_id,
            body.export_format,
            now,
        )

        export = CaseExport(
            id=export_id,
            subject_kind=body.subject_kind,
            subject_id=body.subject_id,
            export_format=body.export_format,
            status=CaseExportStatus.PENDING,
            requested_by=body.requested_by,
            bundle_version=_BUNDLE_FORMAT_VERSION,
            filename=filename,
        )
        session.add(export)
        await session.flush()

        try:
            bundle_data, completeness = await self._generate_bundle(
                session,
                body.subject_kind,
                body.subject_id,
                body.export_format,
                access=access,
                access_context=access_context,
            )
            export.bundle_data = self._attach_bundle_metadata(
                bundle_data,
                export_id=export.id,
                filename=export.filename,
                generated_at=now,
                subject_kind=body.subject_kind,
                subject_id=body.subject_id,
                requested_by=body.requested_by,
                access=access,
            )
            export.completeness = completeness
            export.status = CaseExportStatus.COMPLETED
            export.completed_at = now

            self._record_audit(
                session,
                export,
                CaseExportAuditEventType.CREATED,
                actor=body.requested_by,
                note="Export bundle generated successfully.",
                event_payload={
                    "filename": export.filename,
                    "subject_kind": body.subject_kind.value,
                    "subject_id": str(body.subject_id),
                    "export_format": body.export_format.value,
                    "access_role": access.requested_role.value,
                    "resolved_view": access.resolved_view.value,
                },
            )
            self._record_audit(
                session,
                export,
                CaseExportAuditEventType.COMPLETED,
                actor=body.requested_by,
                event_payload={
                    "filename": export.filename,
                    "missing_or_incomplete_count": len(completeness.get("missing_or_incomplete", [])),
                    "resolved_view": access.resolved_view.value,
                },
            )
        except NotFoundError:
            raise
        except Exception as exc:
            export.status = CaseExportStatus.FAILED
            export.error_message = str(exc)
            self._record_audit(
                session,
                export,
                CaseExportAuditEventType.FAILED,
                actor=body.requested_by,
                note=str(exc),
                event_payload={
                    "filename": export.filename,
                    "access_role": access.requested_role.value,
                    "requested_view": access.requested_view.value if access.requested_view else None,
                },
            )

        await session.flush()
        return await self.get_export(session, export.id)

    async def get_export(self, session: AsyncSession, export_id: uuid.UUID) -> CaseExport:
        stmt = (
            select(CaseExport)
            .execution_options(populate_existing=True)
            .options(selectinload(CaseExport.audit_events))
            .where(CaseExport.id == export_id)
        )
        result = await session.scalar(stmt)
        if result is None:
            raise NotFoundError("Case export not found.")
        result.audit_events.sort(
            key=lambda event: (event.created_at, self._audit_event_rank(event.event_type), event.id)
        )
        return result

    async def record_download(
        self,
        session: AsyncSession,
        export_id: uuid.UUID,
        *,
        actor: str,
        note: str | None,
    ) -> CaseExport:
        export = await self.get_export(session, export_id)
        self._record_audit(
            session,
            export,
            CaseExportAuditEventType.DOWNLOADED,
            actor=actor,
            note=note or "Export bundle retrieval recorded.",
            event_payload={
                "filename": export.filename,
                "export_format": export.export_format.value,
                "bundle_version": export.bundle_version,
            },
        )
        await session.flush()
        return await self.get_export(session, export.id)

    async def list_exports(
        self,
        session: AsyncSession,
        *,
        subject_kind: CaseSubjectKind | None,
        subject_id: uuid.UUID | None,
        status: CaseExportStatus | None,
        limit: int,
        offset: int,
    ) -> tuple[list[CaseExport], int]:
        stmt = select(CaseExport)
        if subject_kind is not None:
            stmt = stmt.where(CaseExport.subject_kind == subject_kind)
        if subject_id is not None:
            stmt = stmt.where(CaseExport.subject_id == subject_id)
        if status is not None:
            stmt = stmt.where(CaseExport.status == status)

        total = await self._count(session, stmt)
        items = list(
            (await session.execute(
                stmt.order_by(CaseExport.created_at.desc()).offset(offset).limit(limit)
            )).scalars().all()
        )
        return items, total

    # ------------------------------------------------------------------
    # Bundle generation
    # ------------------------------------------------------------------

    def _resolve_export_access(
        self,
        access_role: EvidenceAccessRole | None = None,
        requested_view: EvidenceAssetView | None = None,
    ) -> EvidenceAccessResolution:
        role = access_role or EvidenceAccessRole.EXPORT_SERVICE
        return resolve_access_resolution(
            policy=_DEFAULT_EVIDENCE_PRIVACY_POLICY,
            role=role,
            requested_view=requested_view,
            default_view=_DEFAULT_EVIDENCE_PRIVACY_POLICY.default_export_view,
        )

    @staticmethod
    def _build_privacy_section(
        access: EvidenceAccessResolution,
        serialized_evidence_manifests: list[dict[str, Any]],
        *,
        access_context: AccessContext,
    ) -> dict[str, Any]:
        policy = _DEFAULT_EVIDENCE_PRIVACY_POLICY
        return {
            "requested_view": access.requested_view.value if access.requested_view else None,
            "asset_view": access.resolved_view.value,
            "original_access_authorized": access.original_access_authorized,
            "resolution_notes": access.resolution_notes,
            "permissions": [permission.value for permission in access_context.permissions],
            "audit_trail_visible": access_context.has_permission(
                AccessPermission.VIEW_SENSITIVE_AUDIT_TRAIL
            ),
            "policy": {
                "default_asset_view": policy.default_asset_view.value,
                "default_export_view": policy.default_export_view.value,
                "preserve_original_assets": policy.preserve_original_assets,
                "redaction_targets": [t.value for t in policy.redaction_targets],
                "authorized_original_roles": [r.value for r in policy.authorized_original_roles],
                "enforcement_notes": policy.enforcement_notes,
                "compliance_notes": policy.compliance_notes,
            },
            "evidence_manifest_count": len(serialized_evidence_manifests),
        }

    @staticmethod
    def _build_incident_media_refs(
        violation: ViolationEvent,
        serialized_evidence_manifests: list[dict[str, Any]],
        *,
        access: EvidenceAccessResolution | None = None,
    ) -> dict[str, Any]:
        redacted = access is not None and access.resolved_view == EvidenceAssetView.REDACTED
        return {
            "evidence_image_uri": None if redacted else violation.evidence_image_uri,
            "evidence_video_uri": None if redacted else violation.evidence_video_uri,
            "asset_view": access.resolved_view.value if access else EvidenceAssetView.ORIGINAL.value,
            "redacted": redacted,
            "source_media_restricted": redacted
            and any([violation.evidence_image_uri, violation.evidence_video_uri]),
            "note": (
                "Original incident media URIs are hidden in redacted exports. Redacted asset references, when available, are declared inside evidence manifests."
                if redacted
                else None
            ),
        }

    @staticmethod
    def _sanitize_detection_payload(
        event_payload: dict[str, Any],
        *,
        redacted: bool,
    ) -> dict[str, Any]:
        if not event_payload:
            return {}
        if not redacted:
            return dict(event_payload)

        sanitized: dict[str, Any] = {}
        for key, value in event_payload.items():
            lowered = key.lower()
            if lowered.endswith("_uri") or lowered in {"image_uri", "video_uri"}:
                sanitized[key] = None
            elif "plate" in lowered and "text" in lowered and isinstance(value, str):
                sanitized[key] = mask_plate_text(value)
            else:
                sanitized[key] = value
        return sanitized

    @staticmethod
    def _is_structured_manifest_data(manifest_data: dict[str, Any]) -> bool:
        return all(key in manifest_data for key in ("subject", "selection_policy", "timeline"))

    @staticmethod
    def _redact_legacy_manifest_data(manifest_data: dict[str, Any]) -> dict[str, Any]:
        redacted_manifest = dict(manifest_data)
        hidden_original_refs = any(redacted_manifest.get(key) for key in ("frames", "clips", "plates"))
        redacted_manifest["frames"] = []
        redacted_manifest["clips"] = []
        redacted_manifest["plates"] = []
        redacted_manifest["privacy_redaction_notice"] = (
            "Legacy manifest asset references are hidden in redacted exports because this manifest does not persist dedicated redacted asset variants."
        )
        redacted_manifest["original_asset_refs_hidden"] = hidden_original_refs
        return redacted_manifest

    @classmethod
    def _serialize_manifest_data_for_access(
        cls,
        manifest_data: dict[str, Any],
        access: EvidenceAccessResolution | None,
    ) -> tuple[dict[str, Any], EvidenceAccessResolution | None]:
        if access is None:
            return manifest_data, access

        if cls._is_structured_manifest_data(manifest_data):
            document = EvidenceManifestDocument.model_validate(manifest_data)
            manifest_access = resolve_access_resolution(
                policy=document.privacy_policy,
                role=access.requested_role,
                requested_view=access.requested_view,
                default_view=document.privacy_policy.default_export_view,
            )
            if manifest_access.resolved_view == EvidenceAssetView.REDACTED:
                sanitized = sanitize_manifest_for_access(document=document, access=manifest_access)
                sanitized = sanitized.model_copy(
                    update={
                        "subject": sanitized.subject.model_copy(
                            update={"plate_text": mask_plate_text(sanitized.subject.plate_text)}
                        )
                    }
                )
                return sanitized.model_dump(mode="json"), manifest_access
            return manifest_data, manifest_access

        if access.resolved_view == EvidenceAssetView.REDACTED:
            return cls._redact_legacy_manifest_data(manifest_data), access
        return manifest_data, access

    async def _generate_bundle(
        self,
        session: AsyncSession,
        subject_kind: CaseSubjectKind,
        subject_id: uuid.UUID,
        export_format: CaseExportFormat,
        *,
        access: EvidenceAccessResolution,
        access_context: AccessContext,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if subject_kind == CaseSubjectKind.VIOLATION_EVENT:
            return await self._bundle_violation(
                session,
                subject_id,
                export_format,
                access=access,
                access_context=access_context,
            )
        raise NotFoundError(f"Export for subject kind '{subject_kind}' is not yet supported.")

    async def _bundle_violation(
        self,
        session: AsyncSession,
        violation_id: uuid.UUID,
        export_format: CaseExportFormat,
        *,
        access: EvidenceAccessResolution,
        access_context: AccessContext,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        violation = await self._load_violation(session, violation_id)
        can_view_sensitive_audit = access_context.has_permission(
            AccessPermission.VIEW_SENSITIVE_AUDIT_TRAIL
        )

        camera_data = self._serialize_camera(violation.camera) if violation.camera else None
        detection_data = self._serialize_detection(violation.detection_event, access=access)
        plate_rows = await self._load_plate_reads(session, violation)
        evidence_manifests = await self._load_evidence_manifests(session, violation_id)
        workflows = await self._load_workflows(session, violation_id)
        serialized_evidence_manifests = [
            self._serialize_evidence(manifest, access=access) for manifest in evidence_manifests
        ]
        incident_media_refs = self._build_incident_media_refs(
            violation,
            serialized_evidence_manifests,
            access=access,
        )
        plate_reads = [self._serialize_plate_read(plate_read, access=access) for plate_read in plate_rows]

        review_data = (
            self._build_review_section(violation)
            if can_view_sensitive_audit
            else self._build_restricted_review_section(violation)
        )
        rule_explanation = self._build_rule_explanation(violation)
        track_metadata = self._build_track_metadata(violation.detection_event)
        audit_trail = (
            self._build_audit_trail(violation, workflows)
            if can_view_sensitive_audit
            else self._build_restricted_audit_trail(violation)
        )
        workflow_decisions = (
            [self._serialize_workflow(wf) for wf in workflows] if can_view_sensitive_audit else []
        )

        completeness = self._assess_completeness(
            violation=violation,
            plate_reads=plate_rows,
            evidence_manifests=evidence_manifests,
            workflows=workflows,
            track_metadata=track_metadata,
            rule_explanation=rule_explanation,
        )

        structured: dict[str, Any] = {
            "format_version": _BUNDLE_FORMAT_VERSION,
            "incident": {
                "id": str(violation.id),
                "violation_type": violation.violation_type.value,
                "severity": violation.severity.value,
                "status": violation.status.value,
                "occurred_at": violation.occurred_at.isoformat(),
                "summary": violation.summary,
                "evidence_image_uri": incident_media_refs["evidence_image_uri"],
                "evidence_video_uri": incident_media_refs["evidence_video_uri"],
                "asset_view": access.resolved_view.value,
                "redaction_applied": access.resolved_view == EvidenceAssetView.REDACTED,
            },
            "privacy": self._build_privacy_section(
                access,
                serialized_evidence_manifests,
                access_context=access_context,
            ),
            "incident_summary": self._build_incident_summary(violation),
            "source_references": self._build_source_references(
                violation,
                plate_rows,
                evidence_manifests,
                workflows,
                access=access,
                include_sensitive_audit=can_view_sensitive_audit,
            ),
            "camera": camera_data,
            "detection_context": detection_data,
            "track_metadata": track_metadata,
            "plate_reads": plate_reads,
            "evidence_manifests": serialized_evidence_manifests,
            "review": review_data,
            "rule_explanation": rule_explanation,
            "workflow_decisions": workflow_decisions,
            "audit_trail": audit_trail,
            "completeness": completeness,
        }

        if export_format == CaseExportFormat.MARKDOWN:
            structured["report_text"] = self._render_markdown(structured, violation)
        elif export_format == CaseExportFormat.ZIP_MANIFEST:
            structured["asset_manifest"] = self._build_asset_manifest(
                violation,
                plate_rows,
                evidence_manifests,
                access=access,
            )

        return structured, completeness

    # ------------------------------------------------------------------
    # Data loaders
    # ------------------------------------------------------------------

    async def _load_violation(self, session: AsyncSession, violation_id: uuid.UUID) -> ViolationEvent:
        stmt = (
            select(ViolationEvent)
            .options(
                selectinload(ViolationEvent.camera),
                selectinload(ViolationEvent.stream),
                selectinload(ViolationEvent.zone),
                selectinload(ViolationEvent.detection_event),
                selectinload(ViolationEvent.plate_read),
            )
            .where(ViolationEvent.id == violation_id)
        )
        violation = await session.scalar(stmt)
        if violation is None:
            raise NotFoundError("Violation event not found.")
        return violation

    async def _load_plate_reads(self, session: AsyncSession, violation: ViolationEvent) -> list[PlateRead]:
        if violation.plate_read_id is None and violation.detection_event_id is None:
            return []
        conditions = []
        if violation.plate_read_id is not None:
            conditions.append(PlateRead.id == violation.plate_read_id)
        if violation.detection_event_id is not None:
            conditions.append(PlateRead.detection_event_id == violation.detection_event_id)
        stmt = select(PlateRead).where(or_(*conditions)).order_by(PlateRead.occurred_at)
        return list((await session.execute(stmt)).scalars().all())

    async def _load_evidence_manifests(self, session: AsyncSession, violation_id: uuid.UUID) -> list[EvidenceManifest]:
        stmt = (
            select(EvidenceManifest)
            .where(EvidenceManifest.violation_event_id == violation_id)
            .order_by(EvidenceManifest.occurred_at)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def _load_workflows(self, session: AsyncSession, violation_id: uuid.UUID) -> list[WorkflowRun]:
        stmt = (
            select(WorkflowRun)
            .where(WorkflowRun.violation_event_id == violation_id)
            .order_by(WorkflowRun.created_at)
        )
        return list((await session.execute(stmt)).scalars().all())

    # ------------------------------------------------------------------
    # Serializers
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize_camera(camera: Camera) -> dict[str, Any]:
        return {
            "id": str(camera.id),
            "camera_code": camera.camera_code,
            "name": camera.name,
            "location_name": camera.location_name,
            "latitude": camera.latitude,
            "longitude": camera.longitude,
        }

    @staticmethod
    def _serialize_detection(
        detection: DetectionEvent | None,
        *,
        access: EvidenceAccessResolution | None = None,
    ) -> dict[str, Any] | None:
        if detection is None:
            return None
        redacted = access is not None and access.resolved_view == EvidenceAssetView.REDACTED
        return {
            "id": str(detection.id),
            "camera_id": str(detection.camera_id),
            "stream_id": str(detection.stream_id) if detection.stream_id else None,
            "zone_id": str(detection.zone_id) if detection.zone_id else None,
            "event_type": detection.event_type.value,
            "occurred_at": detection.occurred_at.isoformat(),
            "track_id": detection.track_id,
            "object_class": detection.object_class,
            "confidence": detection.confidence,
            "bbox": detection.bbox,
            "frame_index": detection.frame_index,
            "image_uri": None if redacted else detection.image_uri,
            "video_uri": None if redacted else detection.video_uri,
            "event_payload": CaseExportService._sanitize_detection_payload(
                dict(detection.event_payload) if detection.event_payload else {},
                redacted=redacted,
            ),
            "asset_view": access.resolved_view.value if access else EvidenceAssetView.ORIGINAL.value,
            "redacted": redacted,
            "source_media_restricted": redacted and any([detection.image_uri, detection.video_uri]),
        }

    @staticmethod
    def _serialize_plate_read(
        pr: PlateRead,
        *,
        access: EvidenceAccessResolution | None = None,
    ) -> dict[str, Any]:
        redacted = access is not None and access.resolved_view == EvidenceAssetView.REDACTED
        plate_text = mask_plate_text(pr.plate_text) if redacted else pr.plate_text
        normalized = (
            mask_plate_text(pr.normalized_plate_text)
            if redacted and pr.normalized_plate_text
            else pr.normalized_plate_text
        )
        return {
            "id": str(pr.id),
            "camera_id": str(pr.camera_id),
            "stream_id": str(pr.stream_id) if pr.stream_id else None,
            "detection_event_id": str(pr.detection_event_id) if pr.detection_event_id else None,
            "status": pr.status.value,
            "plate_text": plate_text,
            "normalized_plate_text": normalized,
            "confidence": pr.confidence,
            "occurred_at": pr.occurred_at.isoformat(),
            "country_code": pr.country_code,
            "region_code": pr.region_code,
            "bbox": pr.bbox,
            "crop_image_uri": None if redacted else pr.crop_image_uri,
            "source_frame_uri": None if redacted else pr.source_frame_uri,
            "ocr_metadata": ({"redacted": True} if redacted and pr.ocr_metadata else dict(pr.ocr_metadata) if pr.ocr_metadata else {}),
            "redacted": redacted,
            "source_media_restricted": redacted and any([pr.crop_image_uri, pr.source_frame_uri]),
        }

    @classmethod
    def _serialize_evidence(
        cls,
        em: EvidenceManifest,
        *,
        access: EvidenceAccessResolution | None = None,
    ) -> dict[str, Any]:
        manifest_data = dict(em.manifest_data) if em.manifest_data else {}
        manifest_data, effective_access = cls._serialize_manifest_data_for_access(manifest_data, access)
        redacted = effective_access is not None and effective_access.resolved_view == EvidenceAssetView.REDACTED
        assets = manifest_data.get("assets", [])
        return {
            "id": str(em.id),
            "subject_kind": em.subject_kind.value,
            "subject_id": str(em.subject_id),
            "manifest_key": em.manifest_key,
            "build_revision": em.build_revision,
            "camera_id": str(em.camera_id),
            "stream_id": str(em.stream_id) if em.stream_id else None,
            "zone_id": str(em.zone_id) if em.zone_id else None,
            "detection_event_id": str(em.detection_event_id) if em.detection_event_id else None,
            "violation_event_id": str(em.violation_event_id) if em.violation_event_id else None,
            "plate_read_id": str(em.plate_read_id) if em.plate_read_id else None,
            "event_frame_index": em.event_frame_index,
            "storage_namespace": em.storage_namespace,
            "manifest_uri": None if redacted else em.manifest_uri,
            "manifest_data": manifest_data,
            "asset_counts": {
                "total": len(assets),
                "frames": len(manifest_data.get("frames", [])),
                "clips": len(manifest_data.get("clips", [])),
                "plates": len(manifest_data.get("plates", [])),
            },
            "occurred_at": em.occurred_at.isoformat(),
            "asset_view": (
                effective_access.resolved_view.value if effective_access else EvidenceAssetView.ORIGINAL.value
            ),
            "redacted": redacted,
            "manifest_uri_restricted": redacted and em.manifest_uri is not None,
        }

    @staticmethod
    def _serialize_workflow(wf: WorkflowRun) -> dict[str, Any]:
        result_payload = dict(wf.result_payload) if wf.result_payload else None
        return {
            "id": str(wf.id),
            "camera_id": str(wf.camera_id) if wf.camera_id else None,
            "detection_event_id": str(wf.detection_event_id) if wf.detection_event_id else None,
            "violation_event_id": str(wf.violation_event_id) if wf.violation_event_id else None,
            "workflow_type": wf.workflow_type.value,
            "status": wf.status.value,
            "priority": wf.priority,
            "requested_by": wf.requested_by,
            "created_at": wf.created_at.isoformat(),
            "started_at": wf.started_at.isoformat() if wf.started_at else None,
            "completed_at": wf.completed_at.isoformat() if wf.completed_at else None,
            "input_payload": dict(wf.input_payload) if wf.input_payload else {},
            "result_payload": result_payload,
            "decision": result_payload.get("decision") if result_payload else None,
            "error_message": wf.error_message,
        }

    @staticmethod
    def _build_review_section(violation: ViolationEvent) -> dict[str, Any]:
        actions_taken: list[dict[str, Any]] = []
        if violation.assigned_to:
            actions_taken.append(
                {
                    "action": "assigned",
                    "actor": violation.assigned_to,
                    "timestamp": None,
                    "note": "Assignment timestamp is not persisted on violation rows.",
                }
            )
        if violation.reviewed_by or violation.reviewed_at:
            actions_taken.append(
                {
                    "action": "reviewed",
                    "actor": violation.reviewed_by,
                    "timestamp": violation.reviewed_at.isoformat() if violation.reviewed_at else None,
                    "note": violation.review_note,
                    "status_after": violation.status.value,
                }
            )

        review_signals = {
            "has_assignment": violation.assigned_to is not None,
            "has_reviewer_identity": violation.reviewed_by is not None,
            "has_review_timestamp": violation.reviewed_at is not None,
            "has_review_note": bool(violation.review_note),
        }

        return {
            "assigned_to": violation.assigned_to,
            "reviewed_by": violation.reviewed_by,
            "reviewed_at": violation.reviewed_at.isoformat() if violation.reviewed_at else None,
            "review_note": violation.review_note,
            "status": violation.status.value,
            "is_reviewed": any(review_signals.values()),
            "review_signals": review_signals,
            "actions_taken": actions_taken,
        }

    @staticmethod
    def _build_incident_summary(violation: ViolationEvent) -> dict[str, Any]:
        return {
            "title": f"{violation.violation_type.value} incident",
            "summary": violation.summary,
            "severity": violation.severity.value,
            "status": violation.status.value,
            "occurred_at": violation.occurred_at.isoformat(),
        }

    @staticmethod
    def _build_restricted_review_section(violation: ViolationEvent) -> dict[str, Any]:
        return {
            "available": False,
            "restricted": True,
            "status": violation.status.value,
            "is_reviewed": any([violation.reviewed_by, violation.reviewed_at, violation.review_note]),
            "note": "Review identities and notes are hidden for roles without sensitive audit visibility.",
        }

    @staticmethod
    def _build_restricted_audit_trail(violation: ViolationEvent) -> dict[str, Any]:
        return {
            "current_status": violation.status.value,
            "reviewers": [],
            "timeline": [],
            "restricted": True,
            "note": "Audit timeline visibility requires the view_sensitive_audit_trail permission.",
        }

    @staticmethod
    def _build_rule_explanation(violation: ViolationEvent) -> dict[str, Any]:
        details = dict(violation.rule_metadata) if violation.rule_metadata else {}
        return {
            "available": bool(details),
            "rule_id": details.get("rule_id"),
            "details": details,
            "note": None if details else "No persisted rule explanation is available for this violation.",
        }

    @staticmethod
    def _build_track_metadata(detection: DetectionEvent | None) -> dict[str, Any]:
        if detection is None:
            return {
                "available": False,
                "track_id": None,
                "object_class": None,
                "frame_index": None,
                "bbox": None,
                "note": "No persisted detection context is linked to this violation.",
            }

        return {
            "available": True,
            "track_id": detection.track_id,
            "object_class": detection.object_class,
            "frame_index": detection.frame_index,
            "bbox": detection.bbox,
            "confidence": detection.confidence,
            "occurred_at": detection.occurred_at.isoformat(),
            "note": None if detection.track_id else "Detection is linked but no track_id was persisted.",
        }

    @staticmethod
    def _build_source_references(
        violation: ViolationEvent,
        plate_reads: list[PlateRead],
        evidence_manifests: list[EvidenceManifest],
        workflows: list[WorkflowRun],
        *,
        access: EvidenceAccessResolution | None = None,
        include_sensitive_audit: bool = True,
    ) -> dict[str, Any]:
        return {
            "subject": {
                "kind": CaseSubjectKind.VIOLATION_EVENT.value,
                "id": str(violation.id),
            },
            "camera_id": str(violation.camera_id),
            "stream_id": str(violation.stream_id) if violation.stream_id else None,
            "zone_id": str(violation.zone_id) if violation.zone_id else None,
            "detection_event_id": str(violation.detection_event_id) if violation.detection_event_id else None,
            "primary_plate_read_id": str(violation.plate_read_id) if violation.plate_read_id else None,
            "plate_read_ids": [str(plate_read.id) for plate_read in plate_reads],
            "evidence_manifest_ids": [str(manifest.id) for manifest in evidence_manifests],
            "workflow_run_ids": [str(workflow.id) for workflow in workflows] if include_sensitive_audit else [],
            "asset_view": access.resolved_view.value if access else EvidenceAssetView.ORIGINAL.value,
        }

    @staticmethod
    def _sanitize_bundle_for_access(
        bundle_data: dict[str, Any],
        *,
        access_context: AccessContext,
    ) -> dict[str, Any]:
        if access_context.has_permission(AccessPermission.VIEW_SENSITIVE_AUDIT_TRAIL):
            return bundle_data

        bundle = deepcopy(bundle_data)
        bundle["review"] = {
            "available": False,
            "restricted": True,
            "note": "Review identities and notes are hidden for this role.",
        }
        bundle["workflow_decisions"] = []
        bundle["audit_trail"] = {
            "restricted": True,
            "timeline": [],
            "note": "Audit trail visibility requires the view_sensitive_audit_trail permission.",
        }
        source_references = dict(bundle.get("source_references") or {})
        source_references["workflow_run_ids"] = []
        bundle["source_references"] = source_references
        if "report_text" in bundle:
            bundle["report_text"] = (
                "Report text is hidden for this role because it may include restricted review or audit details."
            )
        privacy = dict(bundle.get("privacy") or {})
        privacy["audit_trail_visible"] = False
        privacy["audit_visibility_note"] = (
            "Sensitive review and audit details are hidden for this role."
        )
        bundle["privacy"] = privacy
        return bundle

    def serialize_export_summary(
        self,
        export: CaseExport,
        *,
        access_context: AccessContext,
    ) -> dict[str, Any]:
        require_permissions(
            context=access_context,
            required_permissions=[AccessPermission.EXPORT_EVIDENCE],
            resource="case_export",
            action="list export summary",
            entity_id=str(export.id),
        )
        audit_sensitive_access(
            context=access_context,
            action="list export summary",
            resource="case_export",
            entity_id=str(export.id),
            outcome="allowed",
        )
        return CaseExportSummaryRead.model_validate(export).model_dump(mode="json")

    def serialize_export_detail(
        self,
        export: CaseExport,
        *,
        access_context: AccessContext,
    ) -> dict[str, Any]:
        require_permissions(
            context=access_context,
            required_permissions=[AccessPermission.EXPORT_EVIDENCE],
            resource="case_export",
            action="view export detail",
            entity_id=str(export.id),
        )
        audit_sensitive_access(
            context=access_context,
            action="view export detail",
            resource="case_export",
            entity_id=str(export.id),
            outcome="allowed",
        )
        detail = CaseExportDetailRead.model_validate(export).model_dump(mode="json")
        detail["bundle_data"] = self._sanitize_bundle_for_access(
            detail.get("bundle_data") or {},
            access_context=access_context,
        )
        if not access_context.has_permission(AccessPermission.VIEW_SENSITIVE_AUDIT_TRAIL):
            detail["audit_events"] = []
        return detail

    @classmethod
    def _build_audit_trail(
        cls,
        violation: ViolationEvent,
        workflows: list[WorkflowRun],
    ) -> dict[str, Any]:
        timeline: list[dict[str, Any]] = [
            {
                "event_type": "violation_recorded",
                "actor": None,
                "timestamp": cls._isoformat(violation.created_at),
                "status_after": None,
                "note": "Violation record persisted.",
                "inferred": False,
            }
        ]

        if violation.assigned_to:
            timeline.append(
                {
                    "event_type": "review_assigned",
                    "actor": violation.assigned_to,
                    "timestamp": None,
                    "status_after": None,
                    "note": "Reviewer assignment exists, but its timestamp is not persisted separately.",
                    "inferred": True,
                }
            )

        if violation.reviewed_by or violation.reviewed_at:
            timeline.append(
                {
                    "event_type": "review_completed",
                    "actor": violation.reviewed_by,
                    "timestamp": cls._isoformat(violation.reviewed_at),
                    "status_after": violation.status.value,
                    "note": violation.review_note,
                    "inferred": False,
                }
            )

        for workflow in workflows:
            timeline.append(
                {
                    "event_type": "workflow_requested",
                    "actor": workflow.requested_by,
                    "timestamp": cls._isoformat(workflow.created_at),
                        "status_after": None,
                        "workflow_status": workflow.status.value,
                        "workflow_type": workflow.workflow_type.value,
                        "workflow_run_id": str(workflow.id),
                        "note": workflow.workflow_type.value,
                    "inferred": False,
                }
            )
            if workflow.started_at is not None:
                timeline.append(
                    {
                        "event_type": "workflow_started",
                        "actor": workflow.requested_by,
                        "timestamp": cls._isoformat(workflow.started_at),
                        "status_after": None,
                        "workflow_status": workflow.status.value,
                        "workflow_type": workflow.workflow_type.value,
                        "workflow_run_id": str(workflow.id),
                        "note": workflow.workflow_type.value,
                        "inferred": False,
                    }
                )
            if workflow.completed_at is not None:
                decision = None
                if workflow.result_payload:
                    decision = workflow.result_payload.get("decision")
                timeline.append(
                    {
                        "event_type": "workflow_completed",
                        "actor": workflow.requested_by,
                        "timestamp": cls._isoformat(workflow.completed_at),
                        "status_after": None,
                        "workflow_status": workflow.status.value,
                        "workflow_type": workflow.workflow_type.value,
                        "workflow_run_id": str(workflow.id),
                        "action_taken": decision,
                        "note": workflow.error_message or decision or workflow.workflow_type.value,
                        "inferred": False,
                    }
                )

        timeline.sort(key=lambda item: (item["timestamp"] is None, item["timestamp"] or "", item["event_type"]))
        reviewers = sorted({actor for actor in [violation.assigned_to, violation.reviewed_by] if actor})

        return {
            "current_status": violation.status.value,
            "reviewers": reviewers,
            "timeline": timeline,
            "status_history_complete": False,
            "limitations": [
                "Violation rows store current review fields, but they do not persist every intermediate status transition as a first-class audit log.",
                "Reviewer assignment timestamps are unavailable unless another workflow or note captured them.",
            ],
        }

    # ------------------------------------------------------------------
    # Completeness assessment
    # ------------------------------------------------------------------

    @staticmethod
    def _assess_completeness(
        *,
        violation: ViolationEvent,
        plate_reads: list[PlateRead],
        evidence_manifests: list[EvidenceManifest],
        workflows: list[WorkflowRun],
        track_metadata: dict[str, Any],
        rule_explanation: dict[str, Any],
    ) -> dict[str, Any]:
        missing: list[str] = []

        has_evidence = len(evidence_manifests) > 0
        has_plate = len(plate_reads) > 0
        has_review = any([violation.reviewed_by, violation.reviewed_at, violation.review_note])
        has_workflow = len(workflows) > 0
        has_track_metadata = bool(track_metadata.get("available"))
        has_rule_explanation = bool(rule_explanation.get("available"))

        if not has_evidence:
            missing.append("No evidence manifests linked to this violation.")
        if not has_plate:
            missing.append("No plate reads found for this violation.")
        if not has_review:
            missing.append("Violation has not been reviewed yet.")
        if not has_workflow:
            missing.append("No workflow runs found for this violation.")
        if not violation.evidence_image_uri:
            missing.append("Evidence image URI is not available.")
        if not violation.evidence_video_uri:
            missing.append("Evidence video URI is not available.")
        if not has_track_metadata:
            missing.append("No linked track metadata is available for this violation.")
        if not has_rule_explanation:
            missing.append("No persisted rule explanation is available for this violation.")

        return {
            "is_complete": len(missing) == 0,
            "has_evidence": has_evidence,
            "has_plate_read": has_plate,
            "has_review": has_review,
            "has_workflow": has_workflow,
            "has_track_metadata": has_track_metadata,
            "has_rule_explanation": has_rule_explanation,
            "missing_assets": missing,
            "missing_or_incomplete": missing,
            "audit_limitations": [
                "Intermediate violation status transitions are reconstructed from persisted review/workflow fields; a dedicated status-history model does not exist yet.",
            ],
        }

    # ------------------------------------------------------------------
    # Markdown renderer
    # ------------------------------------------------------------------

    @staticmethod
    def _render_markdown(structured: dict[str, Any], violation: ViolationEvent) -> str:
        lines: list[str] = []
        lines.append("# Case Export Report")
        lines.append("")
        lines.append(f"**Violation ID:** {violation.id}")
        lines.append(f"**Type:** {violation.violation_type.value}")
        lines.append(f"**Severity:** {violation.severity.value}")
        lines.append(f"**Status:** {violation.status.value}")
        lines.append(f"**Occurred:** {violation.occurred_at.isoformat()}")
        lines.append("")

        if violation.summary:
            lines.append("## Incident Summary")
            lines.append("")
            lines.append(violation.summary)
            lines.append("")

        camera = structured.get("camera")
        if camera:
            lines.append("## Camera")
            lines.append("")
            lines.append(f"- **Code:** {camera['camera_code']}")
            lines.append(f"- **Name:** {camera['name']}")
            lines.append(f"- **Location:** {camera['location_name']}")
            lines.append("")

        det = structured.get("detection_context")
        if det:
            lines.append("## Detection Context")
            lines.append("")
            lines.append(f"- **Track ID:** {det.get('track_id', 'N/A')}")
            lines.append(f"- **Object Class:** {det.get('object_class', 'N/A')}")
            lines.append(f"- **Confidence:** {det.get('confidence', 'N/A')}")
            lines.append("")

        plates = structured.get("plate_reads", [])
        if plates:
            lines.append("## Plate Reads")
            lines.append("")
            for pr in plates:
                lines.append(f"- **{pr['plate_text']}** (normalized: {pr['normalized_plate_text']}, confidence: {pr['confidence']})")
            lines.append("")

        review = structured.get("review", {})
        if review.get("reviewed_by"):
            lines.append("## Review")
            lines.append("")
            lines.append(f"- **Reviewed by:** {review['reviewed_by']}")
            lines.append(f"- **Reviewed at:** {review.get('reviewed_at', 'N/A')}")
            if review.get("review_note"):
                lines.append(f"- **Note:** {review['review_note']}")
            lines.append("")

        rule = structured.get("rule_explanation", {})
        if rule:
            lines.append("## Rule Explanation")
            lines.append("")
            if rule.get("available"):
                lines.append(f"- **Rule ID:** {rule.get('rule_id', 'N/A')}")
                for key, value in rule.get("details", {}).items():
                    lines.append(f"- **{key}:** {value}")
            else:
                lines.append(f"- {rule.get('note', 'No persisted rule explanation is available.')}")
            lines.append("")

        wfs = structured.get("workflow_decisions", [])
        if wfs:
            lines.append("## Workflow Decisions")
            lines.append("")
            for wf in wfs:
                lines.append(f"- **{wf['workflow_type']}** — status: {wf['status']}, requested by: {wf.get('requested_by', 'N/A')}")
                if wf.get("result_payload"):
                    lines.append(f"  - Result: {wf['result_payload']}")
            lines.append("")

        audit_trail = structured.get("audit_trail", {})
        timeline = audit_trail.get("timeline", [])
        if timeline:
            lines.append("## Audit Trail")
            lines.append("")
            for event in timeline:
                when = event.get("timestamp") or "timestamp unavailable"
                actor = event.get("actor") or "system"
                lines.append(f"- **{event['event_type']}** — {when} by {actor}")
            lines.append("")

        completeness = structured.get("completeness", {})
        missing = completeness.get("missing_or_incomplete", [])
        if missing:
            lines.append("## Completeness Notes")
            lines.append("")
            for item in missing:
                lines.append(f"- {item}")
            lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Asset manifest builder (zip_manifest format)
    # ------------------------------------------------------------------

    @classmethod
    def _build_asset_manifest(
        cls,
        violation: ViolationEvent,
        plate_reads: list[PlateRead],
        evidence_manifests: list[EvidenceManifest],
        *,
        access: EvidenceAccessResolution | None = None,
    ) -> dict[str, Any]:
        assets: list[dict[str, Any]] = []
        missing_assets: list[str] = []
        redacted = access is not None and access.resolved_view == EvidenceAssetView.REDACTED

        if violation.evidence_image_uri:
            if redacted:
                missing_assets.append("evidence_image_restricted_by_privacy_policy")
            else:
                assets.append({"uri": violation.evidence_image_uri, "kind": "evidence_image", "source": "violation_event"})
        else:
            missing_assets.append("evidence_image")
        if violation.evidence_video_uri:
            if redacted:
                missing_assets.append("evidence_video_restricted_by_privacy_policy")
            else:
                assets.append({"uri": violation.evidence_video_uri, "kind": "evidence_video", "source": "violation_event"})
        else:
            missing_assets.append("evidence_video")

        for pr in plate_reads:
            if pr.crop_image_uri:
                if redacted:
                    missing_assets.append(f"plate_crop_restricted_by_privacy_policy:{pr.id}")
                else:
                    assets.append({"uri": pr.crop_image_uri, "kind": "plate_crop", "plate_read_id": str(pr.id)})
            if pr.source_frame_uri:
                if redacted:
                    missing_assets.append(f"plate_source_frame_restricted_by_privacy_policy:{pr.id}")
                else:
                    assets.append({"uri": pr.source_frame_uri, "kind": "plate_source_frame", "plate_read_id": str(pr.id)})

        for em in evidence_manifests:
            serialized_manifest = cls._serialize_evidence(em, access=access)
            if serialized_manifest.get("manifest_uri"):
                assets.append({
                    "uri": serialized_manifest["manifest_uri"],
                    "kind": "evidence_manifest",
                    "evidence_manifest_id": str(em.id),
                })
            elif redacted and em.manifest_uri:
                missing_assets.append(f"evidence_manifest_restricted_by_privacy_policy:{em.id}")

            data = serialized_manifest.get("manifest_data") or {}
            if cls._is_structured_manifest_data(data):
                for asset in data.get("assets", []):
                    if asset.get("uri"):
                        assets.append(
                            {
                                "uri": asset["uri"],
                                "kind": asset.get("asset_kind", "evidence_asset"),
                                "label": asset.get("label"),
                                "asset_view": asset.get("asset_view"),
                                "evidence_manifest_id": str(em.id),
                            }
                        )
                continue

            for frame in data.get("frames", []):
                assets.append({"uri": frame, "kind": "evidence_frame", "evidence_manifest_id": str(em.id)})
            for clip in data.get("clips", []):
                assets.append({"uri": clip, "kind": "evidence_clip", "evidence_manifest_id": str(em.id)})

        return {
            "archive_filename": f"case_assets_{str(violation.id)[:8]}.zip",
            "archive_generated": False,
            "note": "Placeholder manifest only. The service does not generate a binary zip archive yet.",
            "asset_count": len(assets),
            "assets": assets,
            "missing_assets": missing_assets,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_filename(
        subject_kind: CaseSubjectKind,
        subject_id: uuid.UUID,
        export_id: uuid.UUID,
        export_format: CaseExportFormat,
        ts: datetime,
    ) -> str:
        date_str = ts.strftime("%Y%m%d_%H%M%S")
        subject_short_id = str(subject_id)[:8]
        export_short_id = str(export_id)[:8]
        ext = {
            CaseExportFormat.JSON: ".json",
            CaseExportFormat.MARKDOWN: ".md",
            CaseExportFormat.ZIP_MANIFEST: ".zip-manifest.json",
        }[export_format]
        return f"case_{subject_kind.value}_{subject_short_id}_{export_short_id}_{date_str}{ext}"

    @staticmethod
    def _attach_bundle_metadata(
        bundle_data: dict[str, Any],
        *,
        export_id: uuid.UUID,
        filename: str,
        generated_at: datetime,
        subject_kind: CaseSubjectKind,
        subject_id: uuid.UUID,
        requested_by: str | None,
        access: EvidenceAccessResolution | None = None,
    ) -> dict[str, Any]:
        enriched = dict(bundle_data)
        enriched["bundle_metadata"] = {
            "bundle_id": str(export_id),
            "filename": filename,
            "generated_at": generated_at.isoformat(),
            "requested_by": requested_by,
            "subject_kind": subject_kind.value,
            "subject_id": str(subject_id),
            "asset_view": access.resolved_view.value if access else EvidenceAssetView.ORIGINAL.value,
            "redacted": access is not None and access.resolved_view == EvidenceAssetView.REDACTED,
        }
        return enriched

    @staticmethod
    def _isoformat(value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.isoformat()

    @staticmethod
    def _record_audit(
        session: AsyncSession,
        export: CaseExport,
        event_type: CaseExportAuditEventType,
        *,
        actor: str | None = None,
        note: str | None = None,
        event_payload: dict[str, Any] | None = None,
    ) -> None:
        session.add(
            CaseExportAuditEvent(
                case_export_id=export.id,
                event_type=event_type,
                actor=actor,
                note=note,
                event_payload=event_payload or {},
            )
        )

    @staticmethod
    def _audit_event_rank(event_type: CaseExportAuditEventType) -> int:
        ranks = {
            CaseExportAuditEventType.CREATED: 0,
            CaseExportAuditEventType.COMPLETED: 1,
            CaseExportAuditEventType.FAILED: 2,
            CaseExportAuditEventType.DOWNLOADED: 3,
        }
        return ranks[event_type]

    @staticmethod
    async def _count(session: AsyncSession, statement) -> int:
        count_stmt = select(func.count()).select_from(statement.order_by(None).subquery())
        total = await session.scalar(count_stmt)
        return int(total or 0)
