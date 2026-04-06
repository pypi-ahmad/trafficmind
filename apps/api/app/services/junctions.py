"""Service layer for junction management."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.app.db.models import Junction
from apps.api.app.schemas.domain import JunctionCreate
from apps.api.app.services.errors import ConflictError, NotFoundError


class JunctionService:
    """Business logic for junction CRUD."""

    async def list_junctions(
        self,
        session: AsyncSession,
        *,
        search: str | None,
        skip: int,
        limit: int,
    ) -> list[Junction]:
        query = select(Junction)
        if search:
            query = query.where(Junction.name.ilike(f"%{search}%"))
        query = query.order_by(Junction.name).offset(skip).limit(limit)
        return list((await session.scalars(query)).all())

    async def get_junction_detail(self, session: AsyncSession, junction_id: uuid.UUID) -> Junction:
        statement = (
            select(Junction)
            .options(selectinload(Junction.cameras))
            .where(Junction.id == junction_id)
        )
        junction = await session.scalar(statement)
        if junction is None:
            raise NotFoundError("Junction not found.")
        return junction

    async def create_junction(self, session: AsyncSession, payload: JunctionCreate) -> Junction:
        junction = Junction(**payload.model_dump())
        session.add(junction)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise ConflictError("A junction with this name already exists.") from exc
        await session.refresh(junction)
        return junction

    async def update_junction(
        self,
        session: AsyncSession,
        junction_id: uuid.UUID,
        payload: JunctionCreate,
    ) -> Junction:
        junction = await self._get_or_raise(session, junction_id)
        for field_name, value in payload.model_dump(exclude_unset=True).items():
            setattr(junction, field_name, value)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise ConflictError("The updated junction conflicts with an existing record.") from exc
        await session.refresh(junction)
        return junction

    async def delete_junction(self, session: AsyncSession, junction_id: uuid.UUID) -> None:
        junction = await self._get_or_raise(session, junction_id)
        await session.delete(junction)
        await session.commit()

    async def _get_or_raise(self, session: AsyncSession, junction_id: uuid.UUID) -> Junction:
        junction = await session.get(Junction, junction_id)
        if junction is None:
            raise NotFoundError("Junction not found.")
        return junction
