"""Junction management endpoints."""

from __future__ import annotations

import uuid
from typing import NoReturn

from fastapi import APIRouter, HTTPException, Query, Response, status

from apps.api.app.api.dependencies import DbSession
from apps.api.app.schemas.domain import JunctionCreate, JunctionDetail, JunctionRead
from apps.api.app.services.errors import ConflictError, NotFoundError
from apps.api.app.services.junctions import JunctionService

router = APIRouter(prefix="/junctions", tags=["junctions"])
junction_service = JunctionService()


def _raise_http_error(error: Exception) -> NoReturn:
    if isinstance(error, NotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    if isinstance(error, ConflictError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    raise error


@router.get("", response_model=list[JunctionRead])
async def list_junctions(
    db_session: DbSession,
    search: str | None = Query(default=None, min_length=1),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[JunctionRead]:
    return await junction_service.list_junctions(db_session, search=search, skip=skip, limit=limit)


@router.post("", response_model=JunctionRead, status_code=status.HTTP_201_CREATED)
async def create_junction(
    payload: JunctionCreate,
    db_session: DbSession,
) -> JunctionRead:
    try:
        return await junction_service.create_junction(db_session, payload)
    except (NotFoundError, ConflictError) as error:
        _raise_http_error(error)


@router.get("/{junction_id}", response_model=JunctionDetail)
async def get_junction(junction_id: uuid.UUID, db_session: DbSession) -> JunctionDetail:
    try:
        return await junction_service.get_junction_detail(db_session, junction_id)
    except NotFoundError as error:
        _raise_http_error(error)


@router.patch("/{junction_id}", response_model=JunctionRead)
async def update_junction(
    junction_id: uuid.UUID,
    payload: JunctionCreate,
    db_session: DbSession,
) -> JunctionRead:
    try:
        return await junction_service.update_junction(db_session, junction_id, payload)
    except (NotFoundError, ConflictError) as error:
        _raise_http_error(error)


@router.delete("/{junction_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_junction(junction_id: uuid.UUID, db_session: DbSession) -> Response:
    try:
        await junction_service.delete_junction(db_session, junction_id)
    except NotFoundError as error:
        _raise_http_error(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
