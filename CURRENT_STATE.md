# TrafficMind — Current State Audit

**Date:** 2026-04-06

## Repository

| Item | Status |
|---|---|
| Repo root | `E:\Github\trafficmind` |
| VCS | **No root `.git/` present.** The workspace is being treated as a monorepo directory, but version control is not initialized at the root. |
| Root `.gitignore` | Present and covering the expected local artifacts (`.venv/`, model weights, `node_modules/`, caches, outputs). |

## Environment Snapshot

| Item | Detail |
|---|---|
| Python environment | `.venv/` with Python 3.13.12 |
| Frontend runtime | Next.js 16.2.2, React 19.2.4, TypeScript 5 |
| Core backend stack | FastAPI, Pydantic v2, SQLAlchemy, Alembic |
| Workflow stack | LangGraph workflow service with a deterministic heuristic provider |
| CV runtime | Ultralytics, Torch CUDA build, Supervision, PaddleOCR |

## What Is Implemented

The following areas contain real code paths and regression coverage today:

- `apps/api/`: versioned FastAPI service, persisted models, Alembic migrations, detection-event search routes, violation search routes, ANPR routes, evidence routes, observability routes, hotspot analytics routes, alert routing/escalation routes, case export routes, and workflow-facing storage.
- `apps/workflow/`: grounded cold-path workflows for incident triage, violation review, advisory multimodal review, daily summary, weekly summary, hotspot reporting, and operator assist, including deterministic natural-language investigation over stored events, violations, and plate reads.
- `services/vision/`: detection-facing schemas and service logic used by deterministic tests.
- `services/tracking/`: multi-object tracking abstractions and tested tracking service behavior.
- `services/motion/`: calibration-aware speed estimation and motion analytics foundation with explicit rough vs approximate vs calibrated outputs, scene direction labeling, and candidate helpers for wrong-way / overspeed screening.
- `services/flow/`: lane occupancy and queue analytics foundation with rolling-window occupancy, stop-line-relative queue detection, queue persistence duration, congestion indicators, and per-lane utilization metrics.
- `services/hotspot/`: hotspot ranking and spatial trend analytics — persisted detection/violation/watchlist aggregation by source/camera/zone/lane/type/severity, period-vs-period trend deltas, recurring-issue detection, optional congestion-record adapters, explicit ranking metric reporting, and frontend-ready ranking/heatmap/time-series helpers.
- `services/signals/`: traffic-light state classification and temporal smoothing over detected heads.
- `services/rules/`: deterministic rule engine with flagship temporal rules such as red-light and pedestrian-on-red handling.
- `services/ocr/`: OCR service and plate normalization helpers.
- `services/anpr/`: persisted plate search, normalization-aware matching, camera-text filtering, and watchlist-facing plumbing.
- `services/events/`: structured detection-event search helpers shared by the API and workflow layers.
- `services/violations/`: structured violation search helpers shared by the API and workflow layers.
- `services/evidence/`: deterministic evidence manifest packaging for violations and events, with a privacy masking and evidence redaction foundation including role-based access resolution, configurable redaction policy, redacted-vs-original asset provenance, plate text masking, backend permission checks, and honest compliance documentation.
- `services/access_control/`: coarse request-declared permission mapping for sensitive evidence, export, review, watchlist, and alert policy surfaces, including logger-based access audit events and a backend/frontend policy preview contract.
- `services/model_registry/`: lightweight runtime model/config registry with versioned bundles for detector, tracker, OCR, rules, and evidence packaging, plus provenance stamping helpers for persisted outputs.
- `services/health/`: camera and stream health assessment.
- `apps/api/app/services/alerts.py`: operational alert routing foundation with policy-driven signal evaluation, dedup windows, cooldowns, escalation ladders, delivery planning, and audit trails.
- `apps/api/app/services/exports.py`: audit-ready case export foundation with structured JSON bundles, markdown report rendering, zip-manifest placeholders, traceable filenames/bundle ids, compact linked-record references, explicit completeness reporting, reconstructed review/workflow audit timelines, and retrieval audit events.
- `apps/api/app/demo/seed.py`: realistic synthetic demo seeding for local development and screenshots, including cameras, test-source streams, zones, detection events, violations, plate reads, review workflows, evidence manifests, and observability-friendly stream heartbeat states.
- `services/streams/`: ingestion/orchestration foundation with runtime metrics and heartbeats.
- `services/reid/`: multi-camera re-identification foundation — embedding-based cross-camera entity association with pluggable interfaces, conservative entity-link planning, representative event anchors, and an auto-confirm / human-review pipeline.
- `services/evaluation/`: new fixture-driven evaluation foundation for detection, tracking, OCR, rule sanity, and workflow report-quality checks.
- `services/integrations/`: vendor-neutral adapter contracts, normalized payload builders, registry helpers, local JSONL and filesystem adapters, and an external signal bridge for future case, notification, reporting, storage, and signal integrations.
- Deployment hardening foundation: commit-safe env profiles, startup/readiness checks for API and workflow services, stream-worker config preflight, cross-service `doctor` / `run_checks` scripts, and a minimal GitHub Actions lint/test/build workflow.

## Advanced Implemented Foundations

These areas are implemented and useful today, but they should still be described as foundations rather than complete enterprise product surfaces:

- Deployment hardening is now real and repeatable for local-first validation: rendered env profiles, startup checks, readiness probes, and cross-service validation scripts are in place.
- `services/integrations/` now centralizes pluggable contracts for case systems, notifications, reporting, object storage, and external signal feeds, plus local adapters for contract validation.
- Signal/controller support remains normalized and state-centric, and the new adapter bridge extends that same pipeline instead of introducing a competing model.

## What Is Partial

These areas exist, but they should not be overstated as production-complete:

- End-to-end live perception is still a foundation, not a fully hardened deployment pipeline.
- The new deployment layer is intentionally single-host and local-first. It improves safety and validation, but it does not yet provide container images, orchestration manifests, or managed secret-store integration.
- Plate OCR exists, but there is still no dedicated plate detector wired into the hot path to provide reliable crops automatically.
- Traffic-light state is handled through deterministic HSV-based post-processing and smoothing, not a separately trained state model.
- The workflow layer is grounded over stored data, but production checkpoint persistence is still local-development oriented.
- The frontend is no longer a blank scaffold. It now includes a map-first operations dashboard with camera and derived-junction markers, hotspot summaries, analytics-backed location rollups, and linked camera/event navigation, but it still does not cover the full operator product surface.
- Some backend surfaces remain intentionally incomplete while storage and review flows mature.
- Historical congestion hotspot analysis is adapter-ready but not yet backed by a persisted lane-snapshot store in the main API.
- Lane hotspot attribution is intentionally conservative: only explicit `lane_id` values or lane-zone assignments are used.
- Signal/controller support is currently state-centric. The repo does not yet persist timing histories or compute cycle length, phase duration, split failure, queue-clearance, delay, or adaptive optimization recommendations.
- Enterprise adapter contracts now exist, but vendor-specific integrations, outbound delivery senders, warehouse connectors, object-storage drivers, and bidirectional sync semantics are intentionally absent.
- Speed estimation is useful for analytics and candidate screening today, but it is not enforcement-grade unless a camera has validated calibration inputs.
- Alert delivery integrations remain intentionally honest placeholders: the foundation persists planned deliveries and audit events, but no email/webhook/SMS sender is wired yet.
- Case export packaging is intentionally JSON-first: it produces reproducible structured bundles plus markdown text and zip-manifest placeholders, but it does not yet claim binary archive generation or polished PDF rendering.
- The model/config registry is intentionally a provenance foundation, not a training platform: it supports deployed runtime bundle tracking and future comparisons, but not experiment scheduling, offline lineage graphs, or benchmark dashboards.
- Privacy and evidence redaction is a policy and schema foundation: it defaults to redacted views, masks plate text, tracks redaction targets per asset, preserves original-to-redacted provenance, and now gates sensitive routes through coarse permissions, but a production pixel-level masking pipeline for face blurring and plate obscuration on actual media files does not yet exist.
- Sensitive authorization is still request-declared rather than identity-backed. The backend now enforces a stable role-to-permission matrix, but callers can still self-assert roles until a real auth/session layer is added.
- Demo mode is now available for local screenshots and walkthroughs. It seeds plausible stored records and health states, but every seeded record is explicitly marked as synthetic demo data and uses `demo://` placeholder asset URIs rather than pretending real media was processed.

## Frontend Reality Check

`frontend/` contains real application code under `src/app/` and `src/features/operations/`, including an operations dashboard, camera detail route, and events route. The dashboard now consumes live camera metadata plus hotspot analytics for recent location summaries, renders explicit camera/junction map markers, and preserves selection context across map, detail, and event-filter views. It should still be described as an early operations UI, not as a finished product and not as an untouched scaffold.

## Validation Snapshot

The standard backend validation surface was executed during the latest audit pass:

- `tests/workflow` — workflow service, multimodal review, quality checks, operator-assist planner
- `tests/rules` — rule engine, flagship temporal rules, fixture-driven rule progression
- `tests/api` — ANPR, record search, evidence, camera API, camera health, hotspot API, foundation, sample-data tests
- `tests/ocr` — OCR service and normalization
- `tests/tracking` — tracking service behavior
- `tests/motion` — calibration-aware speed estimation and motion analytics
- `tests/flow` — lane occupancy, queue, congestion, and utilization analytics
- `tests/hotspot` — hotspot aggregation, trend deltas, recurring issues, severity weighting, output helpers
- `tests/vision` — detection-facing schemas and service behavior
- `tests/signals` — signal classifier, state tracker, HSV pipeline
- `tests/streams` — stream orchestration, perception pipeline
- `tests/health` — health assessor, alert thresholds, dashboard aggregation
- `tests/evaluation` — benchmark foundation, metrics edge cases
- `tests/integrations` — adapter builders, local sinks, object storage foundation, external signal bridge

Result: **697 passed, 2 deselected, plus pre-existing non-blocking warnings**.

The warnings remain non-blocking. They include the pre-existing `aiosqlite` worker-thread cleanup warnings observed around API tests plus OCR import-time `setuptools` and Paddle warnings during registry provenance coverage. The default backend check still deselects the pre-existing known failure `tests/api/test_demo_seed.py::test_demo_seed_surfaces_in_camera_and_observability_apis`, which expects one online camera in the seeded observability dashboard while the current payload reports zero.

This covers the deterministic evaluation layer, fixture-based sample-data checks for flagship rule logic, ANPR search/normalization, evidence manifests, workflow report quality, signal classification, stream orchestration, camera/stream health assessment, lane-flow analytics, hotspot trend analytics, the reviewed storage-backed hotspot API, and the new integration adapter foundation.

Targeted follow-up after this audit: `tests/api/test_alert_routing.py` passed with **4 tests**, covering policy/target creation, signal deduplication, escalation processing, alert state transitions, and acknowledged-alert reroute suppression.

Case export validation: `tests/api/test_case_export.py` covers structured JSON, markdown report text, honest missing-evidence reporting, list/retrieval behavior, not-found handling, and zip-manifest placeholder packaging.

Demo seed validation: `tests/api/test_demo_seed.py` covers dataset consistency, idempotent reseeding, and camera/observability API visibility for the seeded demo scenario.

## Benchmarking / Evaluation Reality Check

The repository now has a deterministic evaluation foundation, but it is important to describe it correctly:

- It is fixture-driven and intended for regression, sanity checking, and repeatable local comparison.
- It does **not** claim real-world benchmark leadership or model quality beyond the supplied fixtures.
- It is useful for catching structural regressions in detection outputs, tracking continuity, OCR quality, rule firing behavior, signal classification accuracy, and report rendering.

## Known Gaps and Risks

1. `requirements.txt` is still a frozen dependency dump rather than a curated application dependency declaration.
2. The current model inventory does not include a dedicated plate detector or a dedicated traffic-light state model.
3. CI/CD and deployment validation now have a minimal honest foundation, but container builds, orchestration, and persistent workflow checkpoints are still incomplete.
4. There is still no root git repository initialized for the monorepo.
