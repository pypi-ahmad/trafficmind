# Integration Adapter Foundations

`services/integrations/` provides vendor-neutral adapter contracts for the
enterprise-facing edges of TrafficMind.

Current categories:

- external incident/case systems
- notification channels
- BI/reporting pipelines
- object storage providers
- external signal adapters that feed the existing controller-state service

The package is intentionally abstract. It does not ship fake SaaS bindings.

Boundary note:

- core adapter contracts and registries live in `adapters.py`
- vendor-neutral payload types live in `schemas.py`
- local/mock implementations live in `local.py`
- app-aware payload builders live in `builders.py`

That split keeps the generic adapter surface reusable without forcing API and
workflow schema imports unless a caller actually needs builder helpers.

Implemented local/mock adapters:

- `JsonlIntegrationSinkAdapter` — appends normalized case, notification, and
  reporting envelopes to local JSONL files for contract validation and demos.
- `LocalFilesystemObjectStorageAdapter` — writes normalized object payloads to
  a local filesystem root.

The adapter payload builders consume public TrafficMind schemas instead of ORM
internals where possible. That keeps future integrations aligned with the
product contract rather than the storage implementation.

Current builder coverage:

- operational alerts → normalized notification envelopes
- case exports → normalized external case records and object-storage writes
- workflow runs → normalized external case records and reporting batches

