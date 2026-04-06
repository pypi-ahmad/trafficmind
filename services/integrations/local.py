"""Minimal local/mock adapters for integration-contract validation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from services.integrations.adapters import (
    CASE_SYSTEM_ADAPTERS,
    NOTIFICATION_CHANNEL_ADAPTERS,
    OBJECT_STORAGE_ADAPTERS,
    REPORTING_PIPELINE_ADAPTERS,
    AdapterRegistry,
    CaseSystemAdapter,
    NotificationChannelAdapter,
    ObjectStorageAdapter,
    ReportingPipelineAdapter,
)
from services.integrations.schemas import (
    AdapterDispatchReceipt,
    AdapterDispatchStatus,
    CaseSystemRecord,
    NotificationMessage,
    ObjectStorageWriteRequest,
    ObjectStorageWriteResult,
    ReportingBatch,
)


class JsonlIntegrationSinkAdapter(
    CaseSystemAdapter,
    NotificationChannelAdapter,
    ReportingPipelineAdapter,
):
    """Append normalized integration envelopes to local JSONL files.

    This is intentionally modest and local-only. It is useful for contract
    validation, smoke tests, and demos without claiming any vendor behavior.
    """

    adapter_name = "jsonl_sink"

    def __init__(self, root_dir: str | Path) -> None:
        self._root_dir = Path(root_dir).resolve()
        self._root_dir.mkdir(parents=True, exist_ok=True)

    async def upsert_case(self, record: CaseSystemRecord) -> AdapterDispatchReceipt:
        destination = self._append_jsonl("cases.jsonl", record.model_dump(mode="json"))
        return AdapterDispatchReceipt(
            adapter_name=self.adapter_name,
            operation="upsert_case",
            status=AdapterDispatchStatus.STORED,
            destination=destination,
            external_id=record.external_key,
        )

    async def send_notification(
        self, message: NotificationMessage
    ) -> AdapterDispatchReceipt:
        destination = self._append_jsonl(
            "notifications.jsonl",
            message.model_dump(mode="json"),
        )
        return AdapterDispatchReceipt(
            adapter_name=self.adapter_name,
            operation="send_notification",
            status=AdapterDispatchStatus.STORED,
            destination=destination,
            detail={"recipient_count": len(message.recipients)},
        )

    async def publish_batch(self, batch: ReportingBatch) -> AdapterDispatchReceipt:
        dataset_name = _safe_stem(batch.dataset)
        destination = self._append_jsonl(
            f"reports-{dataset_name}.jsonl",
            batch.model_dump(mode="json"),
        )
        return AdapterDispatchReceipt(
            adapter_name=self.adapter_name,
            operation="publish_batch",
            status=AdapterDispatchStatus.STORED,
            destination=destination,
            detail={"row_count": batch.row_count},
        )

    def _append_jsonl(self, filename: str, payload: dict[str, object]) -> str:
        target = self._root_dir / filename
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True))
            handle.write("\n")
        return str(target)


class LocalFilesystemObjectStorageAdapter(ObjectStorageAdapter):
    """Persist normalized object payloads into a local filesystem root."""

    adapter_name = "local_fs"

    def __init__(self, root_dir: str | Path) -> None:
        self._root_dir = Path(root_dir).resolve()
        self._root_dir.mkdir(parents=True, exist_ok=True)

    async def put_object(
        self, request: ObjectStorageWriteRequest
    ) -> ObjectStorageWriteResult:
        target = self._resolve_target(request.object_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(request.body)
        checksum = hashlib.sha256(request.body).hexdigest()
        return ObjectStorageWriteResult(
            adapter_name=self.adapter_name,
            object_key=request.object_key,
            storage_uri=target.as_uri(),
            content_type=request.content_type,
            size_bytes=len(request.body),
            checksum_sha256=checksum,
        )

    def _resolve_target(self, object_key: str) -> Path:
        normalized_key = object_key.replace("\\", "/").lstrip("/")
        target = (self._root_dir / normalized_key).resolve()
        try:
            target.relative_to(self._root_dir)
        except ValueError as exc:
            msg = "Object keys must stay within the configured local storage root."
            raise ValueError(msg) from exc
        return target


def _safe_stem(value: str) -> str:
    normalized = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value)
    return normalized.strip("-") or "dataset"


def register_local_adapters() -> None:
    _register_if_missing(
        registry=CASE_SYSTEM_ADAPTERS,
        name=JsonlIntegrationSinkAdapter.adapter_name,
        factory=JsonlIntegrationSinkAdapter,
    )
    _register_if_missing(
        registry=NOTIFICATION_CHANNEL_ADAPTERS,
        name=JsonlIntegrationSinkAdapter.adapter_name,
        factory=JsonlIntegrationSinkAdapter,
    )
    _register_if_missing(
        registry=REPORTING_PIPELINE_ADAPTERS,
        name=JsonlIntegrationSinkAdapter.adapter_name,
        factory=JsonlIntegrationSinkAdapter,
    )
    _register_if_missing(
        registry=OBJECT_STORAGE_ADAPTERS,
        name=LocalFilesystemObjectStorageAdapter.adapter_name,
        factory=LocalFilesystemObjectStorageAdapter,
    )


def _register_if_missing(
    *,
    registry: AdapterRegistry[Any],
    name: str,
    factory: Any,
) -> None:
    available = registry.available()
    if name in available:
        return
    registry.register(name, factory)
