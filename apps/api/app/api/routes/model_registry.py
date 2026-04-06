"""Routes for listing and administering model/config registry entries."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status

from apps.api.app.api.access import enforce_route_permissions
from apps.api.app.api.dependencies import DbSession
from apps.api.app.db.enums import ModelRegistryTaskType
from apps.api.app.schemas.model_registry import (
    ModelRegistryEntryCreate,
    ModelRegistryEntryRead,
    ModelRegistryEntryUpdate,
    ModelRegistryListResult,
)
from apps.api.app.services.errors import NotFoundError
from services.access_control.policy import AccessPermission
from services.evidence.schemas import EvidenceAccessRole
from services.model_registry import ModelRegistryService, ModelRegistrySpec

router = APIRouter(prefix="/model-registry", tags=["model-registry"])

_service = ModelRegistryService()


@router.get("", response_model=ModelRegistryListResult)
async def list_model_registry_entries(
    db: DbSession,
    task_type: ModelRegistryTaskType | None = Query(default=None),
    model_family: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    access_role: EvidenceAccessRole = Query(
        EvidenceAccessRole.OPERATOR,
        description="Caller role for provenance and registry inspection authorization",
    ),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> ModelRegistryListResult:
    enforce_route_permissions(
        role=access_role,
        required_permissions=[AccessPermission.VIEW_SENSITIVE_AUDIT_TRAIL],
        resource="model_registry",
        action="list model registry entries",
    )
    items, total = await _service.list_entries(
        db,
        task_type=task_type,
        model_family=model_family,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )
    return ModelRegistryListResult(
        items=[ModelRegistryEntryRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=ModelRegistryEntryRead, status_code=status.HTTP_201_CREATED)
async def create_model_registry_entry(
    db: DbSession,
    body: ModelRegistryEntryCreate,
    access_role: EvidenceAccessRole = Query(
        EvidenceAccessRole.OPERATOR,
        description="Caller role for model/config registry administration",
    ),
) -> ModelRegistryEntryRead:
    enforce_route_permissions(
        role=access_role,
        required_permissions=[AccessPermission.MANAGE_MODEL_REGISTRY],
        resource="model_registry",
        action="create model registry entry",
        audit_details={"task_type": body.task_type.value, "model_family": body.model_family},
    )
    entry = await _service.ensure_entry(
        db,
        ModelRegistrySpec(
            task_type=body.task_type,
            model_family=body.model_family,
            version_name=body.version_name,
            config_bundle=body.config_bundle,
            is_active=body.is_active,
            notes=body.notes,
            entry_metadata=body.entry_metadata,
        ),
    )
    await db.commit()
    await db.refresh(entry)
    return ModelRegistryEntryRead.model_validate(entry)


@router.get("/{entry_id}", response_model=ModelRegistryEntryRead)
async def get_model_registry_entry(
    db: DbSession,
    entry_id: uuid.UUID,
    access_role: EvidenceAccessRole = Query(
        EvidenceAccessRole.OPERATOR,
        description="Caller role for provenance and registry inspection authorization",
    ),
) -> ModelRegistryEntryRead:
    enforce_route_permissions(
        role=access_role,
        required_permissions=[AccessPermission.VIEW_SENSITIVE_AUDIT_TRAIL],
        resource="model_registry",
        action="get model registry entry",
        entity_id=str(entry_id),
    )
    try:
        entry = await _service.get_entry(db, entry_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ModelRegistryEntryRead.model_validate(entry)


@router.patch("/{entry_id}", response_model=ModelRegistryEntryRead)
async def update_model_registry_entry(
    db: DbSession,
    entry_id: uuid.UUID,
    body: ModelRegistryEntryUpdate,
    access_role: EvidenceAccessRole = Query(
        EvidenceAccessRole.OPERATOR,
        description="Caller role for model/config registry administration",
    ),
) -> ModelRegistryEntryRead:
    enforce_route_permissions(
        role=access_role,
        required_permissions=[AccessPermission.MANAGE_MODEL_REGISTRY],
        resource="model_registry",
        action="update model registry entry",
        entity_id=str(entry_id),
    )
    try:
        entry = await _service.update_entry(
            db,
            entry_id,
            is_active=body.is_active,
            notes=body.notes,
            entry_metadata=body.entry_metadata,
        )
        await db.commit()
        await db.refresh(entry)
    except NotFoundError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ModelRegistryEntryRead.model_validate(entry)