# TrafficMind — Current State Audit

**Date:** 2026-04-06

## Repository

| Item | Status |
|---|---|
| Repo root | `E:\Github\trafficmind` |
| VCS | Git repo on `main`, remote `https://github.com/pypi-ahmad/trafficmind.git` |
| Root `.gitignore` | Present and covering the expected local artifacts (`.venv/`, model weights, `node_modules/`, caches, outputs). |

## Environment Snapshot

| Item | Detail |
|---|---|
| Python environment | `.venv/` with Python 3.13.12 |
| Frontend runtime | Next.js 16.2.2, React 19.2.4, TypeScript 5 |
| Core backend stack | FastAPI, Pydantic v2, SQLAlchemy, Alembic |
| Workflow stack | LangGraph workflow service with a deterministic heuristic provider |
| CV runtime | Ultralytics, Torch CUDA build, Supervision, PaddleOCR 3.4 / PaddlePaddle 3.3 (CPU-only on Windows — CUDA wheels not published for any Python version on this platform) |

## What Is Implemented

The following areas contain real code paths and regression coverage today:

- `apps/api/`: versioned FastAPI service, persisted models, Alembic migrations, detection-event search routes, violation search routes, ANPR routes, evidence routes, observability routes, hotspot analytics routes, alert routing/escalation routes, case export routes, and workflow-facing storage.
- `apps/workflow/`: grounded cold-path workflows for incident triage, violation review, advisory multimodal review, daily summary, weekly summary, hotspot reporting, and operator assist, including deterministic natural-language investigation over stored events, violations, and plate reads.
- `services/vision/`: detection-facing schemas and service logic used by deterministic tests.
- `services/tracking/`: multi-object tracking with pluggable backends — two registered backends (ByteTrack via `supervision`, and a pure-Python greedy-IoU tracker with zero external dependencies), shared `StatefulTracker` base for trajectory/lifecycle management, and tested tracking service behavior.
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
- `apps/api/app/services/alerts.py`: operational alert routing foundation with policy-driven signal evaluation, dedup windows, cooldowns, escalation ladders, delivery planning, dispatch orchestration, and audit trails.
- `apps/api/app/services/delivery.py`: real alert delivery adapters — webhook (httpx async POST with configurable auth headers), SMTP email (smtplib with STARTTLS and credentials), log-based fallback for SMS/Slack/Teams — behind a channel-keyed dispatcher with per-attempt failure isolation. Wired into `AlertingService.dispatch_planned_deliveries()` and exposed via `POST /alerts/deliveries/dispatch`.
- `apps/api/app/services/exports.py`: audit-ready case export foundation with structured JSON bundles, markdown report rendering, zip-manifest placeholders, traceable filenames/bundle ids, compact linked-record references, explicit completeness reporting, reconstructed review/workflow audit timelines, and retrieval audit events.
- `apps/api/app/demo/seed.py`: realistic synthetic demo seeding for local development and screenshots, including cameras, test-source streams, zones, detection events, violations, plate reads, review workflows, evidence manifests, and observability-friendly stream heartbeat states.
- `services/streams/`: integrated real-time stream processing pipeline with detection → tracking → OCR → rules composition in a single `process_frame()` path, pluggable backend factories, runtime metrics, heartbeats, and async worker lifecycle.
- `services/reid/`: multi-camera re-identification foundation — embedding-based cross-camera entity association with pluggable interfaces, conservative entity-link planning, representative event anchors, and an auto-confirm / human-review pipeline.
- `services/evaluation/`: new fixture-driven evaluation foundation for detection, tracking, OCR, rule sanity, and workflow report-quality checks.
- `services/integrations/`: vendor-neutral adapter contracts, normalized payload builders, registry helpers, local JSONL and filesystem adapters, and an external signal bridge for future case, notification, reporting, storage, and signal integrations.
- `packages/shared_types/`: canonical shared type contracts (`BBox`, `ObjectCategory`, `Point2D`, `SignalPhase`, `TrafficLightState`, `SceneContext`, etc.) extracted from service schemas into a standalone package; source services re-export for backward compatibility, breaking the rules↔signals circular dependency.
- `tests/smoke/`: golden-path operator smoke test exercising detection → tracking → OCR → rules over a deterministic 5-frame scenario with stub backends (no GPU/models). Runnable via `pytest tests/smoke -m smoke` or `python infra/scripts/run_checks.py --suite smoke`.
- Deployment hardening foundation: commit-safe env profiles, startup/readiness checks for API and workflow services, stream-worker config preflight, cross-service `doctor` / `run_checks` scripts, and a minimal GitHub Actions lint/test/build workflow.

## Advanced Implemented Foundations

These areas are implemented and useful today, but they should still be described as foundations rather than complete enterprise product surfaces:

- Deployment hardening is now real and repeatable for local-first validation: rendered env profiles, startup checks, readiness probes, and cross-service validation scripts are in place.
- `services/integrations/` now centralizes pluggable contracts for case systems, notifications, reporting, object storage, and external signal feeds, plus local adapters for contract validation.
- Signal/controller support remains normalized and state-centric, and the new adapter bridge extends that same pipeline instead of introducing a competing model.

## What Is Partial

These areas exist, but they should not be overstated as production-complete:

- The stream pipeline now chains detection → tracking → OCR → rules in a single `process_frame()` loop, but persistence of emitted violations and plate reads to the database is not yet wired (they are returned in-memory via `FrameResult`).
- The new deployment layer is intentionally single-host and local-first. It improves safety and validation, but it does not yet provide container images, orchestration manifests, or managed secret-store integration.
- Plate OCR is now wired into the stream pipeline (runs on `PLATE`-category detections), but there is still no dedicated plate detector model — the YOLO detector must be trained or configured to emit plate bounding boxes.
- OCR GPU acceleration: the OCR engine and config correctly prefer GPU (`device="gpu:0"`) and auto-detect capability at runtime. However, PaddlePaddle does not publish CUDA-enabled wheels for Windows (any Python version). The runtime therefore falls back to CPU with an informative warning. On Linux with a CUDA-capable Paddle build, GPU inference activates automatically. The `enable_mkldnn` setting is off by default due to a PaddlePaddle 3.x oneDNN bug on Windows; it can be re-enabled on Linux.
- Traffic-light state is handled through deterministic HSV-based post-processing and smoothing, not a separately trained state model.
- The workflow layer is grounded over stored data, but production checkpoint persistence is still local-development oriented.
- The frontend is no longer a blank scaffold. It now includes a map-first operations dashboard with camera and derived-junction markers, hotspot summaries, analytics-backed location rollups, and linked camera/event navigation. The event and violation feeds are now live: the dashboard and events page fetch real paginated data from `GET /events/` and `GET /violations/`, show incident counts per junction, and render recent violations and detection events.
- Some backend surfaces remain intentionally incomplete while storage and review flows mature.
- Historical congestion hotspot analysis is adapter-ready but not yet backed by a persisted lane-snapshot store in the main API.
- Lane hotspot attribution is intentionally conservative: only explicit `lane_id` values or lane-zone assignments are used.
- Signal/controller support is currently state-centric. The repo does not yet persist timing histories or compute cycle length, phase duration, split failure, queue-clearance, delay, or adaptive optimization recommendations.
- Enterprise adapter contracts now exist, but vendor-specific integrations, warehouse connectors, object-storage drivers, and bidirectional sync semantics are intentionally absent.
- Speed estimation is useful for analytics and candidate screening today, but it is not enforcement-grade unless a camera has validated calibration inputs.
- Alert delivery adapters are now real: webhook delivery via httpx, SMTP email via smtplib, and a log-based fallback for SMS/Slack/Teams. Delivery dispatch is orchestrated through `AlertDeliveryDispatcher`, updates attempt states (SENT/FAILED/SKIPPED), and is exposed through a dedicated API endpoint. Vendor-specific SMS and chat-platform adapters (Twilio, native Slack/Teams APIs) are not yet implemented.
- Case export packaging is intentionally JSON-first: it produces reproducible structured bundles plus markdown text and zip-manifest placeholders, but it does not yet claim binary archive generation or polished PDF rendering.
- The model/config registry is intentionally a provenance foundation, not a training platform: it supports deployed runtime bundle tracking and future comparisons, but not experiment scheduling, offline lineage graphs, or benchmark dashboards.
- Privacy and evidence redaction is a policy and schema foundation: it defaults to redacted views, masks plate text, tracks redaction targets per asset, preserves original-to-redacted provenance, and now gates sensitive routes through coarse permissions, but a production pixel-level masking pipeline for face blurring and plate obscuration on actual media files does not yet exist.
- Sensitive authorization is still request-declared rather than identity-backed. The backend now enforces a stable role-to-permission matrix, but callers can still self-assert roles until a real auth/session layer is added.
- Demo mode is now available for local screenshots and walkthroughs. It seeds plausible stored records and health states, but every seeded record is explicitly marked as synthetic demo data and uses `demo://` placeholder asset URIs rather than pretending real media was processed.

## Frontend Reality Check

`frontend/` contains real application code under `src/app/` and `src/features/operations/`, including an operations dashboard, camera detail route, and events route. The dashboard now consumes live camera metadata, hotspot analytics for recent location summaries, and real event/violation feeds from the backend (`GET /events/`, `GET /violations/`). Feed availability is reported as "live" when the backend returns paginated results, and incident counts per junction are derived from real data rather than placeholders. The events page renders recent violations (with severity badges, type, status, and assignment) and detection events (with confidence, object class, and track ID). It should still be described as an early operations UI, not as a finished product and not as an untouched scaffold.

## Validation Snapshot

The standard backend validation surface was executed during the latest audit pass:

- `tests/workflow` — **82 tests, verified 2026-04-06**: full LangGraph graph execution for all 7 workflows, interrupt/resume cycles, violation write-back, SQLAlchemy integration, HTTP route smoke tests, operator-assist NL planner (intent detection, filter extraction, time parsing), and report quality gates
- `tests/rules` — rule engine, flagship temporal rules, fixture-driven rule progression
- `tests/api` — ANPR, record search, evidence, camera API, camera health, hotspot API, foundation, sample-data tests
- `tests/ocr` — OCR service and normalization
- `tests/tracking` — tracking service behavior including IoU tracker backend, lifecycle, multi-object association, direction estimation
- `tests/motion` — calibration-aware speed estimation and motion analytics
- `tests/flow` — lane occupancy, queue, congestion, and utilization analytics
- `tests/hotspot` — hotspot aggregation, trend deltas, recurring issues, severity weighting, output helpers
- `tests/vision` — detection-facing schemas and service behavior
- `tests/signals` — signal classifier, state tracker, HSV pipeline
- `tests/streams` — **28 tests**: integrated detection→tracking→OCR→rules pipeline, event batch construction, worker lifecycle, orchestrator concurrency, backpressure
- `tests/health` — health assessor, alert thresholds, dashboard aggregation
- `tests/evaluation` — benchmark foundation, metrics edge cases
- `tests/integrations` — adapter builders, local sinks, object storage foundation, external signal bridge

Result: **744 passed, 5 pre-existing failures (supervision/ultralytics not installed, demo seed camera count), plus non-blocking warnings**.

The warnings remain non-blocking. They include the pre-existing `aiosqlite` worker-thread cleanup warnings observed around API tests plus OCR import-time `setuptools` and Paddle warnings during registry provenance coverage. The default backend check still deselects the pre-existing known failure `tests/api/test_demo_seed.py::test_demo_seed_surfaces_in_camera_and_observability_apis`, which expects one online camera in the seeded observability dashboard while the current payload reports zero.

This covers the deterministic evaluation layer, fixture-based sample-data checks for flagship rule logic, ANPR search/normalization, evidence manifests, workflow report quality, signal classification, stream orchestration, camera/stream health assessment, lane-flow analytics, hotspot trend analytics, the reviewed storage-backed hotspot API, and the new integration adapter foundation.

Targeted follow-up after this audit: `tests/api/test_alert_routing.py` passed with **4 tests**, covering policy/target creation, signal deduplication, escalation processing, alert state transitions, and acknowledged-alert reroute suppression.

Alert delivery validation: `tests/api/test_alert_delivery.py` passed with **14 tests**, covering webhook success/HTTP error/connection error, SMTP success/missing host/connection failure, log adapter behaviour, dispatcher routing/failure marking/skip-on-missing/isolated-failures, default dispatcher channel coverage, and a full integration flow (seed → policy → signal → PLANNED → dispatch → SENT).

Case export validation: `tests/api/test_case_export.py` covers structured JSON, markdown report text, honest missing-evidence reporting, list/retrieval behavior, not-found handling, and zip-manifest placeholder packaging.

Demo seed validation: `tests/api/test_demo_seed.py` covers dataset consistency, idempotent reseeding, and camera/observability API visibility for the seeded demo scenario.

## Benchmarking / Evaluation Reality Check

The repository now has a deterministic evaluation foundation, but it is important to describe it correctly:

- It is fixture-driven and intended for regression, sanity checking, and repeatable local comparison.
- It does **not** claim real-world benchmark leadership or model quality beyond the supplied fixtures.
- It is useful for catching structural regressions in detection outputs, tracking continuity, OCR quality, rule firing behavior, signal classification accuracy, and report rendering.

## Known Gaps and Risks

1. The current model inventory does not include a dedicated plate detector or a dedicated traffic-light state model.
2. CI/CD and deployment validation now have a minimal honest foundation, but container builds, orchestration, and persistent workflow checkpoints are still incomplete.
3. PaddlePaddle CUDA wheels are not available for Windows. OCR GPU acceleration requires a Linux deployment with `paddlepaddle` built with CUDA, or a future Paddle release with Windows CUDA support.
