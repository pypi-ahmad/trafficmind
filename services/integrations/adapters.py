"""Adapter interfaces and registries for enterprise integration foundations."""

from __future__ import annotations

import abc
from collections.abc import Callable
from typing import Any

from services.integrations.schemas import (
    AdapterDispatchReceipt,
    CaseSystemRecord,
    NotificationMessage,
    ObjectStorageWriteRequest,
    ObjectStorageWriteResult,
    ReportingBatch,
)
from services.signals.integration import ControllerSignalBatch


class CaseSystemAdapter(abc.ABC):
    adapter_name: str

    @abc.abstractmethod
    async def upsert_case(self, record: CaseSystemRecord) -> AdapterDispatchReceipt:
        """Create or update a case/incident record in an external system."""


class NotificationChannelAdapter(abc.ABC):
    adapter_name: str

    @abc.abstractmethod
    async def send_notification(
        self, message: NotificationMessage
    ) -> AdapterDispatchReceipt:
        """Deliver one normalized notification message."""


class ReportingPipelineAdapter(abc.ABC):
    adapter_name: str

    @abc.abstractmethod
    async def publish_batch(self, batch: ReportingBatch) -> AdapterDispatchReceipt:
        """Publish a normalized reporting batch to an external sink."""


class ObjectStorageAdapter(abc.ABC):
    adapter_name: str

    @abc.abstractmethod
    async def put_object(
        self, request: ObjectStorageWriteRequest
    ) -> ObjectStorageWriteResult:
        """Persist one normalized object payload to an external storage target."""


class ExternalSignalAdapter(abc.ABC):
    adapter_name: str

    @abc.abstractmethod
    async def fetch_controller_events(self) -> ControllerSignalBatch:
        """Fetch one normalized batch of controller-fed signal observations."""

class AdapterRegistry[AdapterT]:
    """Minimal named factory registry for pluggable adapters."""

    def __init__(self, adapter_label: str) -> None:
        self._adapter_label = adapter_label
        self._factories: dict[str, Callable[..., AdapterT]] = {}

    def register(self, name: str, factory: Callable[..., AdapterT]) -> None:
        normalized = name.strip().lower()
        if not normalized:
            msg = f"{self._adapter_label} name cannot be empty."
            raise ValueError(msg)
        if normalized in self._factories:
            msg = f"{self._adapter_label} {normalized!r} is already registered."
            raise ValueError(msg)
        self._factories[normalized] = factory

    def create(self, name: str, **kwargs: Any) -> AdapterT:
        normalized = name.strip().lower()
        try:
            factory = self._factories[normalized]
        except KeyError as exc:
            msg = (
                f"Unknown {self._adapter_label} {name!r}. "
                f"Available: {', '.join(self.available()) or 'none'}"
            )
            raise ValueError(msg) from exc
        return factory(**kwargs)

    def available(self) -> list[str]:
        return sorted(self._factories)


CASE_SYSTEM_ADAPTERS = AdapterRegistry[CaseSystemAdapter]("case system adapter")
NOTIFICATION_CHANNEL_ADAPTERS = AdapterRegistry[NotificationChannelAdapter](
    "notification adapter"
)
REPORTING_PIPELINE_ADAPTERS = AdapterRegistry[ReportingPipelineAdapter](
    "reporting adapter"
)
OBJECT_STORAGE_ADAPTERS = AdapterRegistry[ObjectStorageAdapter](
    "object storage adapter"
)
EXTERNAL_SIGNAL_ADAPTERS = AdapterRegistry[ExternalSignalAdapter](
    "external signal adapter"
)
