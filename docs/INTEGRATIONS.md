# Integration Foundations

This document separates three things that are easy to blur together:

- core TrafficMind product surfaces that are implemented today
- advanced integration foundations that are implemented but intentionally modest
- future integration points that are explicitly not claimed as complete yet

## Core Implemented Product

These are product capabilities with working application code today:

- operational alert routing policies, planned deliveries, and alert audit trails
- case export bundle generation and export audit trails
- workflow execution, interruption, resumption, and stored run records
- normalized external signal ingestion and conservative arbitration into rules-facing scene state

## Advanced Implemented Foundations

These are real foundations, but they are not the same thing as full enterprise integrations.

### Vendor-neutral adapter contracts

`services/integrations/` now defines pluggable adapter interfaces for:

- external incident and case systems
- notification channels
- BI and reporting pipelines
- object storage providers
- external signal adapters that feed the existing controller-state service

The package also exposes payload builders that map current TrafficMind public schemas into normalized envelopes instead of requiring future integrations to read ORM internals directly.

The boundary inside the package matters:

- `adapters.py`, `schemas.py`, and `local.py` stay generic and reusable
- `builders.py` is the app-aware translation layer from current product contracts into adapter payloads

That separation keeps the adapter foundation extensible without making every consumer depend on API and workflow schema imports by default.

Current builder coverage:

- operational alerts → normalized notification envelopes
- case exports → normalized external case records and object-storage write requests
- workflow runs → normalized external case records and reporting batches

### Minimal local/mock adapters

Two intentionally small built-ins exist today:

- `JsonlIntegrationSinkAdapter` appends case, notification, and reporting envelopes to local JSONL files
- `LocalFilesystemObjectStorageAdapter` writes normalized payloads to a local filesystem root

These adapters are useful for contract validation, demos, and local smoke tests. They are not vendor simulations.

### External signal adapter bridge

TrafficMind already had normalized controller-state ingestion in `services/signals/integration.py`.
The new `ExternalSignalSyncBridge` lets future adapter implementations fetch controller events from arbitrary sources and hand them into the existing normalization and arbitration service without rewriting that logic.

## Future Integration Points

These are deliberate extension points, not completed integrations:

- ServiceNow, Maximo, Jira Service Management, or other case-management adapters
- email, SMS, Slack, Teams, webhook, or incident-paging delivery senders
- warehouse, lakehouse, or BI streaming/reporting sinks
- S3, Azure Blob, GCS, or on-prem object-storage drivers
- vendor-specific signal-controller protocols, authentication flows, and durable controller-state persistence

## Honesty Boundary

TrafficMind does not currently claim:

- any working vendor SaaS integration
- durable outbound delivery execution
- managed object storage uploads in production
- enterprise incident synchronization semantics such as conflict resolution or bidirectional reconciliation
- signal-vendor protocol support beyond the normalized controller-state foundation

That boundary is intentional. The adapter layer exists to reduce future rewrite pain, not to overstate current enterprise readiness.
