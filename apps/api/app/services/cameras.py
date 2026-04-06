"""Service layer for camera and ingestion source management."""

from __future__ import annotations

from datetime import datetime, timezone

import uuid

from sqlalchemy import distinct, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.app.db.enums import CameraStatus, SourceType, StreamStatus
from apps.api.app.db.models import Camera, CameraStream
from apps.api.app.schemas.cameras import (
    CameraCreateRequest,
    CameraStreamCreateRequest,
    CameraStreamUpdateRequest,
    CameraUpdateRequest,
    VideoSourceRegistrationRequest,
)
from apps.api.app.services.errors import ConflictError, NotFoundError, ServiceValidationError


class CameraService:
    """Business logic for camera and stream registration APIs."""

    async def list_cameras(
        self,
        session: AsyncSession,
        *,
        status: CameraStatus | None,
        source_type: SourceType | None,
        search: str | None,
        skip: int,
        limit: int | None,
    ) -> tuple[list[Camera], int]:
        query = select(Camera).options(selectinload(Camera.streams))
        count_query = select(func.count(distinct(Camera.id))).select_from(Camera)

        if source_type is not None:
            query = query.join(Camera.streams)
            count_query = count_query.join(Camera.streams)

        filters = self._camera_filters(status=status, source_type=source_type, search=search)
        if filters:
            query = query.where(*filters)
            count_query = count_query.where(*filters)

        query = query.order_by(Camera.created_at.desc()).offset(skip)
        if limit is not None:
            query = query.limit(limit)
        items = (await session.scalars(query)).unique().all()
        total = await session.scalar(count_query) or 0
        return list(items), total

    async def get_camera_detail(self, session: AsyncSession, camera_id: uuid.UUID) -> Camera:
        statement = (
            select(Camera)
            .options(selectinload(Camera.streams), selectinload(Camera.zones))
            .where(Camera.id == camera_id)
        )
        camera = await session.scalar(statement)
        if camera is None:
            msg = "Camera not found."
            raise NotFoundError(msg)
        return camera

    async def create_camera(self, session: AsyncSession, payload: CameraCreateRequest) -> Camera:
        camera = Camera(**payload.model_dump())
        session.add(camera)

        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise ConflictError("A camera with this camera_code already exists.") from exc

        return await self.get_camera_detail(session, camera.id)

    async def update_camera(
        self,
        session: AsyncSession,
        camera_id: uuid.UUID,
        payload: CameraUpdateRequest,
    ) -> Camera:
        camera = await self._get_camera_or_raise(session, camera_id)
        updates = payload.model_dump(exclude_unset=True)

        if "calibration_config" in updates and "calibration_updated_at" not in updates:
            updates["calibration_updated_at"] = datetime.now(timezone.utc)

        for field_name, value in updates.items():
            setattr(camera, field_name, value)

        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise ConflictError("The updated camera conflicts with an existing record.") from exc

        return await self.get_camera_detail(session, camera.id)

    async def delete_camera(self, session: AsyncSession, camera_id: uuid.UUID) -> None:
        camera = await self._get_camera_or_raise(session, camera_id)
        await session.delete(camera)

        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise ConflictError(
                "Camera cannot be deleted while dependent events or workflow history still reference it."
            ) from exc

    async def list_streams(
        self,
        session: AsyncSession,
        *,
        camera_id: uuid.UUID | None,
        source_type: SourceType | None,
        status: StreamStatus | None,
        is_enabled: bool | None,
        skip: int,
        limit: int,
    ) -> tuple[list[CameraStream], int]:
        query = select(CameraStream)
        count_query = select(func.count()).select_from(CameraStream)
        filters = []

        if camera_id is not None:
            await self._get_camera_or_raise(session, camera_id)
            filters.append(CameraStream.camera_id == camera_id)
        if source_type is not None:
            filters.append(CameraStream.source_type == source_type)
        if status is not None:
            filters.append(CameraStream.status == status)
        if is_enabled is not None:
            filters.append(CameraStream.is_enabled == is_enabled)

        if filters:
            query = query.where(*filters)
            count_query = count_query.where(*filters)

        query = query.order_by(CameraStream.created_at.desc()).offset(skip).limit(limit)
        items = (await session.scalars(query)).all()
        total = await session.scalar(count_query) or 0
        return list(items), total

    async def get_stream(self, session: AsyncSession, stream_id: uuid.UUID) -> CameraStream:
        stream = await session.scalar(select(CameraStream).where(CameraStream.id == stream_id))
        if stream is None:
            msg = "Camera stream not found."
            raise NotFoundError(msg)
        return stream

    async def create_stream(
        self,
        session: AsyncSession,
        *,
        camera_id: uuid.UUID,
        payload: CameraStreamCreateRequest,
    ) -> CameraStream:
        await self._get_camera_or_raise(session, camera_id)
        stream = CameraStream(camera_id=camera_id, **payload.model_dump())
        session.add(stream)

        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise ConflictError("A stream with this name already exists for the camera.") from exc

        await session.refresh(stream)
        return stream

    async def update_stream(
        self,
        session: AsyncSession,
        *,
        stream_id: uuid.UUID,
        payload: CameraStreamUpdateRequest,
    ) -> CameraStream:
        stream = await self.get_stream(session, stream_id)
        updates = payload.model_dump(exclude_unset=True)
        merged_payload = self._build_stream_validation_payload(stream)
        merged_payload.update(updates)
        validated = CameraStreamCreateRequest.model_validate(merged_payload)

        for field_name, value in validated.model_dump().items():
            setattr(stream, field_name, value)

        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise ConflictError("The updated stream conflicts with an existing record.") from exc

        await session.refresh(stream)
        return stream

    async def delete_stream(self, session: AsyncSession, stream_id: uuid.UUID) -> None:
        stream = await self.get_stream(session, stream_id)
        await session.delete(stream)

        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise ConflictError(
                "Camera stream cannot be deleted while dependent events still reference it."
            ) from exc

    async def register_video_source(
        self,
        session: AsyncSession,
        payload: VideoSourceRegistrationRequest,
    ) -> Camera:
        if payload.camera_id is not None:
            camera = await self._get_camera_or_raise(session, payload.camera_id)
        else:
            if payload.camera is None:
                msg = "Video source registration requires camera metadata for new cameras."
                raise ServiceValidationError(msg)
            camera = Camera(**payload.camera.model_dump())
            session.add(camera)
            await session.flush()

        stream = CameraStream(camera_id=camera.id, **payload.stream.model_dump())
        session.add(stream)

        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise ConflictError("Video source registration conflicts with an existing camera or stream.") from exc

        return await self.get_camera_detail(session, camera.id)

    async def _get_camera_or_raise(self, session: AsyncSession, camera_id: uuid.UUID) -> Camera:
        camera = await session.get(Camera, camera_id)
        if camera is None:
            msg = "Camera not found."
            raise NotFoundError(msg)
        return camera

    def _camera_filters(
        self,
        *,
        status: CameraStatus | None,
        source_type: SourceType | None,
        search: str | None,
    ) -> list[object]:
        filters: list[object] = []
        if status is not None:
            filters.append(Camera.status == status)
        if source_type is not None:
            filters.append(CameraStream.source_type == source_type)
        if search:
            escaped = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            filters.append(
                or_(
                    Camera.camera_code.ilike(pattern, escape="\\"),
                    Camera.name.ilike(pattern, escape="\\"),
                    Camera.location_name.ilike(pattern, escape="\\"),
                )
            )
        return filters

    def _build_stream_validation_payload(self, stream: CameraStream) -> dict[str, object]:
        return {
            "name": stream.name,
            "stream_kind": stream.stream_kind,
            "source_type": stream.source_type,
            "source_uri": stream.source_uri,
            "source_config": stream.source_config,
            "status": stream.status,
            "is_enabled": stream.is_enabled,
            "resolution_width": stream.resolution_width,
            "resolution_height": stream.resolution_height,
            "fps_hint": stream.fps_hint,
        }