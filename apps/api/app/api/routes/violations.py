"""Violation search and evidence endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Response, status

from apps.api.app.api.access import enforce_route_permissions
from apps.api.app.api.dependencies import DbSession
from apps.api.app.db.enums import ViolationStatus, ViolationType, ZoneType
from apps.api.app.schemas.domain import (
    ViolationEventRead,
    ViolationReviewActionRequest,
    ViolationSearchResult,
)
from apps.api.app.services.errors import NotFoundError
from services.access_control.policy import AccessPermission
from services.evidence.schemas import EvidenceAccessRole, EvidenceAssetView, EvidenceManifestRead
from services.evidence.service import (
    EvidenceSubjectNotFoundError,
    build_violation_evidence_manifest,
    get_violation_evidence_manifest,
)
from services.violations.review import apply_violation_review_action
from services.violations.search import search_violation_events

router = APIRouter(prefix="/violations", tags=["violations"])


@router.get("/", response_model=ViolationSearchResult)
async def list_violations(
    db: DbSession,
    camera_id: uuid.UUID | None = Query(None),
    camera_query: str | None = Query(None, description="Camera code, name, or location filter"),
    stream_id: uuid.UUID | None = Query(None),
    zone_id: uuid.UUID | None = Query(None),
    detection_event_id: uuid.UUID | None = Query(None),
    plate_read_id: uuid.UUID | None = Query(None),
    violation_type: ViolationType | None = Query(None),
    status_filter: ViolationStatus | None = Query(None, alias="status"),
    occurred_after: datetime | None = Query(None),
    occurred_before: datetime | None = Query(None),
    object_class: str | None = Query(None, max_length=64),
    plate_text: str | None = Query(None, description="Exact or partial related plate text"),
    partial_plate: bool = Query(False),
    normalization_country_code: str | None = Query(None, max_length=8),
    assigned_to: str | None = Query(None, max_length=120),
    reviewed_by: str | None = Query(None, max_length=120),
    zone_type: ZoneType | None = Query(None),
    has_evidence: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> ViolationSearchResult:
    items, total = await search_violation_events(
        db,
        camera_id=camera_id,
        camera_query=camera_query,
        stream_id=stream_id,
        zone_id=zone_id,
        detection_event_id=detection_event_id,
        plate_read_id=plate_read_id,
        violation_type=violation_type,
        status=status_filter,
        occurred_after=occurred_after,
        occurred_before=occurred_before,
        object_class=object_class,
        plate_text=plate_text,
        partial_plate=partial_plate,
        normalization_country_code=normalization_country_code,
        assigned_to=assigned_to,
        reviewed_by=reviewed_by,
        zone_type=zone_type,
        has_evidence=has_evidence,
        limit=limit,
        offset=offset,
    )
    return ViolationSearchResult(
        items=[ViolationEventRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{violation_id}/evidence", response_model=EvidenceManifestRead)
async def get_violation_evidence(
    db: DbSession,
    violation_id: uuid.UUID,
    access_role: EvidenceAccessRole = Query(
        EvidenceAccessRole.OPERATOR,
        description="Caller role for privacy-aware access resolution",
    ),
    requested_view: EvidenceAssetView | None = Query(
        None,
        description="Preferred asset view (original or redacted); policy may downgrade",
    ),
) -> EvidenceManifestRead:
    """Fetch the stored evidence manifest for one violation event."""
    required_permissions = [AccessPermission.VIEW_REDACTED_EVIDENCE]
    if requested_view == EvidenceAssetView.ORIGINAL:
        required_permissions.append(AccessPermission.VIEW_UNREDACTED_EVIDENCE)
    enforce_route_permissions(
        role=access_role,
        required_permissions=required_permissions,
        resource="violation_evidence",
        action="retrieve evidence manifest",
        entity_id=str(violation_id),
        audit_details={"requested_view": requested_view.value if requested_view else None},
    )
    manifest = await get_violation_evidence_manifest(
        db, violation_id, access_role=access_role, requested_view=requested_view,
    )
    if manifest is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence manifest not found for violation")
    return manifest


@router.post("/{violation_id}/evidence", response_model=EvidenceManifestRead)
async def build_violation_evidence(
    response: Response,
    db: DbSession,
    violation_id: uuid.UUID,
    rebuild: bool = Query(False, description="Rebuild the manifest even if one already exists"),
    storage_namespace: str = Query("evidence", max_length=64),
    access_role: EvidenceAccessRole = Query(
        EvidenceAccessRole.OPERATOR,
        description="Caller role for privacy-aware access resolution",
    ),
    requested_view: EvidenceAssetView | None = Query(
        None,
        description="Preferred asset view (original or redacted); policy may downgrade",
    ),
) -> EvidenceManifestRead:
    """Build or refresh the evidence manifest for one violation event."""
    required_permissions = [AccessPermission.VIEW_REDACTED_EVIDENCE]
    if requested_view == EvidenceAssetView.ORIGINAL:
        required_permissions.append(AccessPermission.VIEW_UNREDACTED_EVIDENCE)
    enforce_route_permissions(
        role=access_role,
        required_permissions=required_permissions,
        resource="violation_evidence",
        action="build evidence manifest",
        entity_id=str(violation_id),
        audit_details={"requested_view": requested_view.value if requested_view else None},
    )
    existing = await get_violation_evidence_manifest(
        db, violation_id, access_role=access_role, requested_view=requested_view,
    )
    if existing is not None and not rebuild:
        response.status_code = status.HTTP_200_OK
        return existing

    try:
        manifest = await build_violation_evidence_manifest(
            db,
            violation_id,
            storage_namespace=storage_namespace,
            rebuild=rebuild,
            access_role=access_role,
            requested_view=requested_view,
        )
        await db.commit()
    except EvidenceSubjectNotFoundError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    response.status_code = status.HTTP_201_CREATED if existing is None else status.HTTP_200_OK
    return manifest


@router.post("/{violation_id}/review", response_model=ViolationEventRead)
async def review_violation(
    db: DbSession,
    violation_id: uuid.UUID,
    body: ViolationReviewActionRequest,
    access_role: EvidenceAccessRole = Query(
        EvidenceAccessRole.OPERATOR,
        description="Caller role for incident review authorization",
    ),
) -> ViolationEventRead:
    """Approve or reject a violation through an explicit review action."""
    enforce_route_permissions(
        role=access_role,
        required_permissions=[AccessPermission.APPROVE_REJECT_INCIDENTS],
        resource="violation_review",
        action=f"{body.action} violation",
        entity_id=str(violation_id),
        audit_details={"actor": body.actor},
    )
    try:
        violation = await apply_violation_review_action(
            db,
            violation_id,
            actor=body.actor,
            action=body.action,
            note=body.note,
        )
        await db.commit()
    except NotFoundError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ViolationEventRead.model_validate(violation)
