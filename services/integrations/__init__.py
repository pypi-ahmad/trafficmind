"""Enterprise integration adapter foundations for TrafficMind.

Importing the package root registers the local built-ins, but app-aware builder
helpers are imported lazily so the generic adapter surface stays lightweight.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from services.integrations.local import register_local_adapters

_EXPORTS: dict[str, tuple[str, str]] = {
    "AdapterDispatchReceipt": (
        "services.integrations.schemas",
        "AdapterDispatchReceipt",
    ),
    "AdapterDispatchStatus": (
        "services.integrations.schemas",
        "AdapterDispatchStatus",
    ),
    "AdapterRegistry": ("services.integrations.adapters", "AdapterRegistry"),
    "CASE_SYSTEM_ADAPTERS": (
        "services.integrations.adapters",
        "CASE_SYSTEM_ADAPTERS",
    ),
    "CaseSystemAdapter": ("services.integrations.adapters", "CaseSystemAdapter"),
    "CaseSystemRecord": ("services.integrations.schemas", "CaseSystemRecord"),
    "EXTERNAL_SIGNAL_ADAPTERS": (
        "services.integrations.adapters",
        "EXTERNAL_SIGNAL_ADAPTERS",
    ),
    "ExternalSignalAdapter": (
        "services.integrations.adapters",
        "ExternalSignalAdapter",
    ),
    "ExternalSignalSyncBridge": (
        "services.integrations.signals",
        "ExternalSignalSyncBridge",
    ),
    "IntegrationMetadata": ("services.integrations.schemas", "IntegrationMetadata"),
    "IntegrationReference": (
        "services.integrations.schemas",
        "IntegrationReference",
    ),
    "JsonlIntegrationSinkAdapter": (
        "services.integrations.local",
        "JsonlIntegrationSinkAdapter",
    ),
    "LocalFilesystemObjectStorageAdapter": (
        "services.integrations.local",
        "LocalFilesystemObjectStorageAdapter",
    ),
    "NOTIFICATION_CHANNEL_ADAPTERS": (
        "services.integrations.adapters",
        "NOTIFICATION_CHANNEL_ADAPTERS",
    ),
    "NotificationChannelAdapter": (
        "services.integrations.adapters",
        "NotificationChannelAdapter",
    ),
    "NotificationMessage": (
        "services.integrations.schemas",
        "NotificationMessage",
    ),
    "OBJECT_STORAGE_ADAPTERS": (
        "services.integrations.adapters",
        "OBJECT_STORAGE_ADAPTERS",
    ),
    "ObjectStorageAdapter": (
        "services.integrations.adapters",
        "ObjectStorageAdapter",
    ),
    "ObjectStorageWriteRequest": (
        "services.integrations.schemas",
        "ObjectStorageWriteRequest",
    ),
    "ObjectStorageWriteResult": (
        "services.integrations.schemas",
        "ObjectStorageWriteResult",
    ),
    "REPORTING_PIPELINE_ADAPTERS": (
        "services.integrations.adapters",
        "REPORTING_PIPELINE_ADAPTERS",
    ),
    "ReportingBatch": ("services.integrations.schemas", "ReportingBatch"),
    "ReportingPipelineAdapter": (
        "services.integrations.adapters",
        "ReportingPipelineAdapter",
    ),
    "SignalSyncReceipt": ("services.integrations.schemas", "SignalSyncReceipt"),
    "build_case_record_from_export": (
        "services.integrations.builders",
        "build_case_record_from_export",
    ),
    "build_case_record_from_workflow_run": (
        "services.integrations.builders",
        "build_case_record_from_workflow_run",
    ),
    "build_notification_message_from_alert": (
        "services.integrations.builders",
        "build_notification_message_from_alert",
    ),
    "build_object_storage_write_request_from_export": (
        "services.integrations.builders",
        "build_object_storage_write_request_from_export",
    ),
    "build_reporting_batch_from_workflow_run": (
        "services.integrations.builders",
        "build_reporting_batch_from_workflow_run",
    ),
    "register_local_adapters": (
        "services.integrations.local",
        "register_local_adapters",
    ),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg) from exc

    module = import_module(module_name)
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted([*globals(), *_EXPORTS])

register_local_adapters()
