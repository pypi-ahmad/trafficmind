"""Shared schemas for model/config registry entries and runtime provenance specs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from apps.api.app.db.enums import ModelRegistryTaskType


class ModelRegistrySpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_type: ModelRegistryTaskType
    model_family: str = Field(min_length=1, max_length=120)
    version_name: str = Field(min_length=1, max_length=160)
    config_bundle: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    notes: str | None = None
    entry_metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = ["ModelRegistrySpec", "ModelRegistryTaskType"]