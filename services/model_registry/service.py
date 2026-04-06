"""Small CRUD and runtime-resolution service for registry entries."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import Select, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.db.models import ModelRegistryEntry
from apps.api.app.services.errors import NotFoundError
from services.model_registry.schemas import ModelRegistrySpec, ModelRegistryTaskType


def _normalize_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalize_json(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_normalize_json(item) for item in value]
    return value


def compute_model_registry_hash(spec: ModelRegistrySpec) -> str:
    payload = {
        "task_type": spec.task_type.value,
        "model_family": spec.model_family,
        "version_name": spec.version_name,
        "config_bundle": _normalize_json(spec.config_bundle),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_model_registry_provenance_snapshot(entry: ModelRegistryEntry | None) -> dict[str, Any] | None:
    if entry is None:
        return None
    return {
        "registry_id": str(entry.id),
        "task_type": entry.task_type.value,
        "model_family": entry.model_family,
        "version_name": entry.version_name,
        "config_hash": entry.config_hash,
        "is_active": entry.is_active,
    }


class ModelRegistryService:
    async def ensure_entry(self, session: AsyncSession, spec: ModelRegistrySpec) -> ModelRegistryEntry:
        config_hash = compute_model_registry_hash(spec)
        stmt = select(ModelRegistryEntry).where(ModelRegistryEntry.config_hash == config_hash)
        entry = await session.scalar(stmt)
        if entry is not None:
            if spec.is_active and not entry.is_active:
                entry.is_active = True
                await self._deactivate_scope(session, entry)
            await session.flush()
            return entry

        entry = ModelRegistryEntry(
            task_type=spec.task_type,
            model_family=spec.model_family,
            version_name=spec.version_name,
            config_hash=config_hash,
            config_bundle=dict(spec.config_bundle),
            is_active=spec.is_active,
            notes=spec.notes,
            entry_metadata=dict(spec.entry_metadata),
        )
        session.add(entry)
        await session.flush()
        if entry.is_active:
            await self._deactivate_scope(session, entry)
        await session.flush()
        return entry

    async def get_entry(self, session: AsyncSession, entry_id: uuid.UUID) -> ModelRegistryEntry:
        entry = await session.get(ModelRegistryEntry, entry_id)
        if entry is None:
            raise NotFoundError("Model registry entry not found.")
        return entry

    async def list_entries(
        self,
        session: AsyncSession,
        *,
        task_type: ModelRegistryTaskType | None,
        model_family: str | None,
        is_active: bool | None,
        limit: int,
        offset: int,
    ) -> tuple[list[ModelRegistryEntry], int]:
        stmt: Select[tuple[ModelRegistryEntry]] = select(ModelRegistryEntry)
        if task_type is not None:
            stmt = stmt.where(ModelRegistryEntry.task_type == task_type)
        if model_family is not None:
            stmt = stmt.where(ModelRegistryEntry.model_family == model_family)
        if is_active is not None:
            stmt = stmt.where(ModelRegistryEntry.is_active == is_active)

        count_stmt = stmt.with_only_columns(ModelRegistryEntry.id)
        rows = list((await session.execute(stmt.order_by(ModelRegistryEntry.created_at.desc()).offset(offset).limit(limit))).scalars().all())
        total = len(list((await session.execute(count_stmt)).scalars().all()))
        return rows, total

    async def update_entry(
        self,
        session: AsyncSession,
        entry_id: uuid.UUID,
        *,
        is_active: bool | None,
        notes: str | None,
        entry_metadata: dict[str, Any] | None,
    ) -> ModelRegistryEntry:
        entry = await self.get_entry(session, entry_id)
        if is_active is not None:
            entry.is_active = is_active
            if is_active:
                await self._deactivate_scope(session, entry)
        if notes is not None:
            entry.notes = notes
        if entry_metadata is not None:
            merged = dict(entry.entry_metadata or {})
            merged.update(entry_metadata)
            entry.entry_metadata = merged
        await session.flush()
        return entry

    async def _deactivate_scope(self, session: AsyncSession, entry: ModelRegistryEntry) -> None:
        await session.execute(
            update(ModelRegistryEntry)
            .where(
                ModelRegistryEntry.task_type == entry.task_type,
                ModelRegistryEntry.model_family == entry.model_family,
                ModelRegistryEntry.id != entry.id,
            )
            .values(is_active=False)
        )


__all__ = [
    "ModelRegistryService",
    "build_model_registry_provenance_snapshot",
    "compute_model_registry_hash",
]