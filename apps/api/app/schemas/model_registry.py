"""API schemas for model/config registry entries."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from apps.api.app.db.enums import ModelRegistryTaskType
from apps.api.app.schemas.domain import ORMSchema


class ModelRegistryEntryCreate(ORMSchema):
    task_type: ModelRegistryTaskType
    model_family: str = Field(min_length=1, max_length=120)
    version_name: str = Field(min_length=1, max_length=160)
    config_bundle: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    notes: str | None = None
    entry_metadata: dict[str, Any] = Field(default_factory=dict)


class ModelRegistryEntryUpdate(ORMSchema):
    is_active: bool | None = None
    notes: str | None = None
    entry_metadata: dict[str, Any] | None = None


class ModelRegistryEntryRead(ORMSchema):
    id: uuid.UUID
    task_type: ModelRegistryTaskType
    model_family: str
    version_name: str
    config_hash: str
    config_bundle: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    notes: str | None = None
    entry_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ModelRegistryListResult(ORMSchema):
    items: list[ModelRegistryEntryRead] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0