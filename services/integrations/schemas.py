"""Vendor-neutral schemas for outbound and inbound enterprise integrations."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AdapterDispatchStatus(StrEnum):
    ACCEPTED = "accepted"
    STORED = "stored"
    FAILED = "failed"


class IntegrationMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_system: str = "trafficmind"
    environment: str = "local"
    schema_version: str = "1.0"
    record_type: str
    emitted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tags: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)


class IntegrationReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: str
    identifier: str
    label: str | None = None
    uri: str | None = None


class CaseSystemRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    metadata: IntegrationMetadata
    external_key: str
    title: str
    summary: str | None = None
    status: str
    severity: str | None = None
    assignee: str | None = None
    opened_at: datetime | None = None
    updated_at: datetime | None = None
    references: list[IntegrationReference] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)


class NotificationMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    metadata: IntegrationMetadata
    title: str
    body: str
    severity: str | None = None
    dedup_key: str | None = None
    channel_hint: str | None = None
    recipients: list[str] = Field(default_factory=list)
    references: list[IntegrationReference] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)


class ReportingBatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    metadata: IntegrationMetadata
    dataset: str
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0


class ObjectStorageWriteRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    metadata: IntegrationMetadata
    object_key: str
    content_type: str
    body: bytes
    object_metadata: dict[str, str] = Field(default_factory=dict)


class ObjectStorageWriteResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    adapter_name: str
    object_key: str
    storage_uri: str
    content_type: str
    size_bytes: int
    checksum_sha256: str
    stored_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AdapterDispatchReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    adapter_name: str
    operation: str
    status: AdapterDispatchStatus
    accepted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    destination: str | None = None
    external_id: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class SignalSyncReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    adapter_name: str
    fetched_event_count: int
    accepted_count: int
    ignored_older_count: int
    tracked_signal_count: int
    synced_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
