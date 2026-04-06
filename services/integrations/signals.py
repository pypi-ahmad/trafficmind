"""Bridge adapter-fetched controller events into the existing signal service."""

from __future__ import annotations

from services.integrations.adapters import ExternalSignalAdapter
from services.integrations.schemas import SignalSyncReceipt
from services.signals.integration import SignalIntegrationService


class ExternalSignalSyncBridge:
    """Apply pluggable external signal adapters to the current signal service."""

    def __init__(self, integration_service: SignalIntegrationService) -> None:
        self._integration_service = integration_service

    async def sync_once(self, adapter: ExternalSignalAdapter) -> SignalSyncReceipt:
        batch = await adapter.fetch_controller_events()
        result = self._integration_service.ingest_events(batch)
        return SignalSyncReceipt(
            adapter_name=adapter.adapter_name,
            fetched_event_count=len(batch.events),
            accepted_count=result.accepted_count,
            ignored_older_count=result.ignored_older_count,
            tracked_signal_count=result.tracked_signal_count,
        )
