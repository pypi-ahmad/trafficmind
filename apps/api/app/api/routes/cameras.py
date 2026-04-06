"""Camera and ingestion source management endpoints."""

from __future__ import annotations

import uuid
from typing import NoReturn

from fastapi import APIRouter, HTTPException, Query, Response, status

from apps.api.app.api.dependencies import DbSession
from apps.api.app.db.enums import CameraStatus, SourceType, StreamStatus
from apps.api.app.schemas.cameras import (
    CameraCreateRequest,
    CameraListResponse,
    CameraStreamCreateRequest,
    CameraStreamListResponse,
    CameraStreamUpdateRequest,
    CameraUpdateRequest,
    VideoSourceRegistrationRequest,
)
from apps.api.app.schemas.domain import CameraDetail, CameraStreamRead
from apps.api.app.services import CameraService
from apps.api.app.services.errors import ConflictError, NotFoundError, ServiceValidationError

router = APIRouter(prefix="/cameras", tags=["cameras"])
stream_router = APIRouter(prefix="/streams", tags=["streams"])
camera_service = CameraService()


def _raise_http_error(error: Exception) -> NoReturn:
    if isinstance(error, NotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    if isinstance(error, ConflictError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    if isinstance(error, ServiceValidationError):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    raise error


@router.get("", response_model=CameraListResponse)
async def list_cameras(
    db_session: DbSession,
    status_filter: CameraStatus | None = Query(default=None, alias="status"),
    source_type: SourceType | None = None,
    search: str | None = Query(default=None, min_length=1),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> CameraListResponse:
    items, total = await camera_service.list_cameras(
        db_session,
        status=status_filter,
        source_type=source_type,
        search=search,
        skip=skip,
        limit=limit,
    )
    return CameraListResponse(items=items, total=total)


@router.post("", response_model=CameraDetail, status_code=status.HTTP_201_CREATED)
async def create_camera(
    payload: CameraCreateRequest,
    db_session: DbSession,
) -> CameraDetail:
    try:
        return await camera_service.create_camera(db_session, payload)
    except (NotFoundError, ConflictError, ServiceValidationError) as error:
        _raise_http_error(error)


@router.get("/{camera_id}", response_model=CameraDetail)
async def get_camera(camera_id: uuid.UUID, db_session: DbSession) -> CameraDetail:
    try:
        return await camera_service.get_camera_detail(db_session, camera_id)
    except (NotFoundError, ConflictError, ServiceValidationError) as error:
        _raise_http_error(error)


@router.patch("/{camera_id}", response_model=CameraDetail)
async def update_camera(
    camera_id: uuid.UUID,
    payload: CameraUpdateRequest,
    db_session: DbSession,
) -> CameraDetail:
    try:
        return await camera_service.update_camera(db_session, camera_id, payload)
    except (NotFoundError, ConflictError, ServiceValidationError) as error:
        _raise_http_error(error)


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_camera(camera_id: uuid.UUID, db_session: DbSession) -> Response:
    try:
        await camera_service.delete_camera(db_session, camera_id)
    except (NotFoundError, ConflictError, ServiceValidationError) as error:
        _raise_http_error(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{camera_id}/streams", response_model=CameraStreamListResponse)
async def list_camera_streams(
    camera_id: uuid.UUID,
    db_session: DbSession,
    source_type: SourceType | None = None,
    status_filter: StreamStatus | None = Query(default=None, alias="status"),
    is_enabled: bool | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> CameraStreamListResponse:
    try:
        items, total = await camera_service.list_streams(
            db_session,
            camera_id=camera_id,
            source_type=source_type,
            status=status_filter,
            is_enabled=is_enabled,
            skip=skip,
            limit=limit,
        )
    except (NotFoundError, ConflictError, ServiceValidationError) as error:
        _raise_http_error(error)
    return CameraStreamListResponse(items=items, total=total)


@router.post("/{camera_id}/streams", response_model=CameraStreamRead, status_code=status.HTTP_201_CREATED)
async def create_camera_stream(
    camera_id: uuid.UUID,
    payload: CameraStreamCreateRequest,
    db_session: DbSession,
) -> CameraStreamRead:
    try:
        return await camera_service.create_stream(db_session, camera_id=camera_id, payload=payload)
    except (NotFoundError, ConflictError, ServiceValidationError) as error:
        _raise_http_error(error)


@stream_router.get("", response_model=CameraStreamListResponse)
async def list_streams(
    db_session: DbSession,
    camera_id: uuid.UUID | None = None,
    source_type: SourceType | None = None,
    status_filter: StreamStatus | None = Query(default=None, alias="status"),
    is_enabled: bool | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> CameraStreamListResponse:
    try:
        items, total = await camera_service.list_streams(
            db_session,
            camera_id=camera_id,
            source_type=source_type,
            status=status_filter,
            is_enabled=is_enabled,
            skip=skip,
            limit=limit,
        )
    except (NotFoundError, ConflictError, ServiceValidationError) as error:
        _raise_http_error(error)
    return CameraStreamListResponse(items=items, total=total)


@stream_router.get("/{stream_id}", response_model=CameraStreamRead)
async def get_stream(stream_id: uuid.UUID, db_session: DbSession) -> CameraStreamRead:
    try:
        return await camera_service.get_stream(db_session, stream_id)
    except (NotFoundError, ConflictError, ServiceValidationError) as error:
        _raise_http_error(error)


@stream_router.patch("/{stream_id}", response_model=CameraStreamRead)
async def update_stream(
    stream_id: uuid.UUID,
    payload: CameraStreamUpdateRequest,
    db_session: DbSession,
) -> CameraStreamRead:
    try:
        return await camera_service.update_stream(db_session, stream_id=stream_id, payload=payload)
    except (NotFoundError, ConflictError, ServiceValidationError) as error:
        _raise_http_error(error)


@stream_router.delete("/{stream_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_stream(stream_id: uuid.UUID, db_session: DbSession) -> Response:
    try:
        await camera_service.delete_stream(db_session, stream_id)
    except (NotFoundError, ConflictError, ServiceValidationError) as error:
        _raise_http_error(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@stream_router.post("/register-video-source", response_model=CameraDetail, status_code=status.HTTP_201_CREATED)
async def register_video_source(
    payload: VideoSourceRegistrationRequest,
    db_session: DbSession,
) -> CameraDetail:
    try:
        return await camera_service.register_video_source(db_session, payload)
    except (NotFoundError, ConflictError, ServiceValidationError) as error:
        _raise_http_error(error)
