"""Detection event search, summary, and evidence endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Response, status

from apps.api.app.api.access import enforce_route_permissions
from apps.api.app.api.dependencies import DbSession
from apps.api.app.db.enums import DetectionEventStatus, DetectionEventType, ZoneType
from apps.api.app.schemas.domain import (
    CameraEventCountRow,
    DetectionEventRead,
    DetectionEventSearchResult,
    EventSummaryTotals,
)
from services.access_control.policy import AccessPermission
from services.evidence.schemas import EvidenceAccessRole, EvidenceAssetView, EvidenceManifestRead
from services.evidence.service import (
    EvidenceSubjectNotFoundError,
    build_detection_evidence_manifest,
    get_detection_evidence_manifest,
)
from services.events.search import search_detection_events

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/", response_model=DetectionEventSearchResult)
async def list_events(
    db: DbSession,
    camera_id: uuid.UUID | None = Query(None),
    camera_query: str | None = Query(None, description="Camera code, name, or location filter"),
    stream_id: uuid.UUID | None = Query(None),
    zone_id: uuid.UUID | None = Query(None),
    event_type: DetectionEventType | None = Query(None),
    status_filter: DetectionEventStatus | None = Query(None, alias="status"),
    occurred_after: datetime | None = Query(None),
    occurred_before: datetime | None = Query(None),
    object_class: str | None = Query(None, max_length=64),
    track_id: str | None = Query(None, max_length=64),
    zone_type: ZoneType | None = Query(None),
    has_evidence: bool | None = Query(None),
    min_confidence: float | None = Query(None, ge=0.0, le=1.0),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> DetectionEventSearchResult:
    items, total = await search_detection_events(
        db,
        camera_id=camera_id,
        camera_query=camera_query,
        stream_id=stream_id,
        zone_id=zone_id,
        event_type=event_type,
        status=status_filter,
        occurred_after=occurred_after,
        occurred_before=occurred_before,
        object_class=object_class,
        track_id=track_id,
        zone_type=zone_type,
        has_evidence=has_evidence,
        min_confidence=min_confidence,
        limit=limit,
        offset=offset,
    )
    return DetectionEventSearchResult(
        items=[DetectionEventRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/summary/by-camera", response_model=list[CameraEventCountRow])
async def event_counts_by_camera_endpoint(
    db: DbSession,
    occurred_after: datetime | None = Query(None),
    occurred_before: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> list[CameraEventCountRow]:
    """Lightweight event counts grouped by camera for dashboard cards."""
    from apps.api.app.services.feed_summary import event_counts_by_camera

    rows = await event_counts_by_camera(
        db,
        occurred_after=occurred_after,
        occurred_before=occurred_before,
        limit=limit,
    )
    return [CameraEventCountRow.model_validate(row) for row in rows]


@router.get("/summary/totals", response_model=EventSummaryTotals)
async def event_summary_totals_endpoint(
    db: DbSession,
    camera_id: uuid.UUID | None = Query(None),
    occurred_after: datetime | None = Query(None),
    occurred_before: datetime | None = Query(None),
) -> EventSummaryTotals:
    """Flat aggregate counts of detection events by status and type."""
    from apps.api.app.services.feed_summary import event_summary_totals

    result = await event_summary_totals(
        db,
        camera_id=camera_id,
        occurred_after=occurred_after,
        occurred_before=occurred_before,
    )
    return EventSummaryTotals.model_validate(result)


@router.get("/{event_id}/evidence", response_model=EvidenceManifestRead)
async def get_event_evidence_manifest(
    db: DbSession,
    event_id: uuid.UUID,
    access_role: EvidenceAccessRole = Query(
        EvidenceAccessRole.OPERATOR,
        description="Caller role for privacy-aware access resolution",
    ),
    requested_view: EvidenceAssetView | None = Query(
        None,
        description="Preferred asset view (original or redacted); policy may downgrade",
    ),
) -> EvidenceManifestRead:
    """Fetch the stored evidence manifest for one detection event."""
    required_permissions = [AccessPermission.VIEW_REDACTED_EVIDENCE]
    if requested_view == EvidenceAssetView.ORIGINAL:
        required_permissions.append(AccessPermission.VIEW_UNREDACTED_EVIDENCE)
    enforce_route_permissions(
        role=access_role,
        required_permissions=required_permissions,
        resource="detection_evidence",
        action="retrieve evidence manifest",
        entity_id=str(event_id),
        audit_details={"requested_view": requested_view.value if requested_view else None},
    )
    manifest = await get_detection_evidence_manifest(
        db, event_id, access_role=access_role, requested_view=requested_view,
    )
    if manifest is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence manifest not found for event")
    return manifest


@router.post("/{event_id}/evidence", response_model=EvidenceManifestRead)
async def build_event_evidence_manifest(
    response: Response,
    db: DbSession,
    event_id: uuid.UUID,
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
    """Build or refresh the evidence manifest for one detection event."""
    required_permissions = [AccessPermission.VIEW_REDACTED_EVIDENCE]
    if requested_view == EvidenceAssetView.ORIGINAL:
        required_permissions.append(AccessPermission.VIEW_UNREDACTED_EVIDENCE)
    enforce_route_permissions(
        role=access_role,
        required_permissions=required_permissions,
        resource="detection_evidence",
        action="build evidence manifest",
        entity_id=str(event_id),
        audit_details={"requested_view": requested_view.value if requested_view else None},
    )
    existing = await get_detection_evidence_manifest(
        db, event_id, access_role=access_role, requested_view=requested_view,
    )
    if existing is not None and not rebuild:
        response.status_code = status.HTTP_200_OK
        return existing

    try:
        manifest = await build_detection_evidence_manifest(
            db,
            event_id,
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
