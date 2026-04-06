"""Case export and audit-ready evidence bundle endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status

from apps.api.app.api.access import enforce_route_permissions
from apps.api.app.api.dependencies import DbSession
from apps.api.app.db.enums import CaseExportStatus, CaseSubjectKind
from apps.api.app.schemas.exports import (
    CaseExportAuditActionRequest,
    CaseExportCreateRequest,
    CaseExportDetailRead,
    CaseExportListResult,
    CaseExportSummaryRead,
)
from services.access_control.policy import AccessDeniedError, AccessPermission, resolve_access_context
from apps.api.app.services.errors import NotFoundError
from apps.api.app.services.exports import CaseExportService
from services.evidence.schemas import EvidenceAccessRole

router = APIRouter(prefix="/exports", tags=["exports"])

_service = CaseExportService()


@router.post("", response_model=CaseExportDetailRead, status_code=status.HTTP_201_CREATED)
async def create_export(db: DbSession, body: CaseExportCreateRequest) -> CaseExportDetailRead:
    try:
        export = await _service.create_export(db, body)
        await db.commit()
        access_context = resolve_access_context(body.access_role)
    except NotFoundError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AccessDeniedError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return CaseExportDetailRead.model_validate(
        _service.serialize_export_detail(export, access_context=access_context)
    )


@router.get("", response_model=CaseExportListResult)
async def list_exports(
    db: DbSession,
    subject_kind: CaseSubjectKind | None = Query(default=None),
    subject_id: uuid.UUID | None = Query(default=None),
    export_status: CaseExportStatus | None = Query(default=None, alias="status"),
    access_role: EvidenceAccessRole = Query(
        EvidenceAccessRole.OPERATOR,
        description="Caller role for export listing authorization",
    ),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> CaseExportListResult:
    access_context = resolve_access_context(access_role)
    items, total = await _service.list_exports(
        db,
        subject_kind=subject_kind,
        subject_id=subject_id,
        status=export_status,
        limit=limit,
        offset=offset,
    )
    try:
        serialized_items = [
            CaseExportSummaryRead.model_validate(
                _service.serialize_export_summary(item, access_context=access_context)
            )
            for item in items
        ]
    except AccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return CaseExportListResult(items=serialized_items, total=total, limit=limit, offset=offset)


@router.get("/{export_id}", response_model=CaseExportDetailRead)
async def get_export(
    db: DbSession,
    export_id: uuid.UUID,
    access_role: EvidenceAccessRole = Query(
        EvidenceAccessRole.OPERATOR,
        description="Caller role for export detail authorization",
    ),
) -> CaseExportDetailRead:
    access_context = resolve_access_context(access_role)
    try:
        export = await _service.get_export(db, export_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    try:
        payload = _service.serialize_export_detail(export, access_context=access_context)
    except AccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return CaseExportDetailRead.model_validate(payload)


@router.post("/{export_id}/downloads", response_model=CaseExportDetailRead)
async def record_export_download(
    db: DbSession,
    export_id: uuid.UUID,
    body: CaseExportAuditActionRequest,
    access_role: EvidenceAccessRole = Query(
        EvidenceAccessRole.OPERATOR,
        description="Caller role for export download authorization",
    ),
) -> CaseExportDetailRead:
    enforce_route_permissions(
        role=access_role,
        required_permissions=[AccessPermission.EXPORT_EVIDENCE],
        resource="case_export",
        action="record export download",
        entity_id=str(export_id),
        audit_details={"actor": body.actor},
    )
    access_context = resolve_access_context(access_role)
    try:
        export = await _service.record_download(db, export_id, actor=body.actor, note=body.note)
        await db.commit()
    except NotFoundError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    try:
        payload = _service.serialize_export_detail(export, access_context=access_context)
    except AccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return CaseExportDetailRead.model_validate(payload)
