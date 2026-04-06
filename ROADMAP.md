# TrafficMind Roadmap

## Phase 0 — Repository Structure ✅

- Established `apps/`, `services/`, `packages/`, `infra/`, `docs/`, and `tests/`
- Preserved the `frontend/` startup path during migration
- Added shared env templates and architecture documentation

## Phase 1 — API and Workflow App Foundations ✅

- Functional FastAPI app in `apps/api/` with versioned routing, settings, logging
- LangGraph workflow service in `apps/workflow/` with typed state machines
- Shared schemas and config conventions established

## Phase 2 — Deterministic Vision Services ✅

- Detection service in `services/vision/` with YOLO26 backend
- Multi-object tracking in `services/tracking/` with ByteTrack backend
- OCR pipeline in `services/ocr/` with PaddleOCR backend and plate normalization
- Deterministic rule engine in `services/rules/` with 8 rule types and temporal confirmation
- Traffic-light signal perception in `services/signals/` with HSV classification and state tracking

## Phase 3 — Event and Review Platform ✅

- Persisted cameras, zones, streams, events, violations, and evidence manifests
- Versioned API endpoints for cameras, events, violations, ANPR, evidence, and observability
- Workflow service connected to stored events with human approval paths
- Incident triage, violation review, daily/weekly/hotspot reporting, and operator-assist workflows
- ANPR plate search, watchlist matching, and alert generation

## Phase 4 — Web Product (In Progress)

- `frontend/` contains an operations dashboard, camera detail, and events routes
- Full migration to `apps/web/` is deferred until the API surface matures further
- Remaining: review/investigation flows, reporting surfaces, real-time monitoring views

## Phase 5 — Production Hardening (In Progress)

- Stream orchestration with worker lifecycle, metrics, heartbeats, and health assessment
- Camera/stream health assessment with configurable thresholds and alert severities
- Deterministic evaluation foundation for regression and benchmark hygiene
- Remaining: Docker assets, CI/CD pipeline, deployment automation, persistent workflow checkpointing

## Phase 6 — Model and Pipeline Maturity (Not Started)

- Dedicated plate-detection model integration for reliable ANPR crops
- Traffic-light state model evaluation vs current HSV-based approach
- End-to-end perception pipeline hardening under real traffic conditions
- Dataset collection, annotation, and model fine-tuning infrastructure
