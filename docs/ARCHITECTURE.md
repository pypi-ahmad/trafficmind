# Architecture

## Overview

TrafficMind is a local-first monorepo with a strict boundary between deterministic real-time computer vision and higher-level cold-path workflows. Every design decision stems from one principle: **the per-frame inference path must never depend on network calls, LLMs, or database writes.**

## System Layers

### Hot Path — Deterministic Perception (GPU)

The real-time path runs entirely on the local GPU and CPU. No LangGraph, no LLM calls, no external API requests:

```
Video source → Frame acquisition → Object detection → Multi-object tracking
    → Plate OCR → Signal-state classification → Rule evaluation
    → Evidence manifest packaging → Structured event emission
```

| Step | Module | Output |
|---|---|---|
| Frame acquisition | `services/streams/` | Decoded frames with metadata |
| Object detection | `services/vision/` | Bounding boxes, classes, confidences |
| Tracking | `services/tracking/` | Track IDs, trajectories |
| Plate OCR | `services/ocr/` | Raw and normalized plate text |
| Signal classification | `services/signals/` | Per-head traffic-light state |
| Speed/direction | `services/motion/` | Speed estimates, heading, wrong-way/overspeed flags |
| Rule evaluation | `services/rules/` | Pre-violations and confirmed violations |
| Evidence packaging | `services/evidence/` | Structured manifest with frame selection and asset keys |

The hot path emits structured events for downstream consumers. Persistence decisions live outside the per-frame loop so the database is not flooded with per-frame data.

### Cold Path — Workflow Orchestration (LangGraph)

The workflow layer operates exclusively on **stored records**. It never touches raw frames or inference outputs directly:

| Workflow | Purpose |
|---|---|
| Incident triage | Classify severity, recommend actions, optional human gate |
| Violation review | Recommend disposition, human-in-the-loop approval |
| Daily summary | Aggregate recent activity into a narrative report |
| Weekly summary | Weekly trend analysis and statistical summary |
| Hotspot report | Spatial analysis of recurring incident clusters |
| Operator assist | Retrieval-first Q&A grounded in stored data |

Workflows use `interrupt()` for human-in-the-loop gates. The workflow service manages execution, resumption, and trace collection. Checkpoint persistence is currently in-memory.

### API Layer

`apps/api/` is a standard FastAPI application with:

- Pydantic v2 request/response schemas
- SQLAlchemy async ORM with 22 models
- Alembic migrations (10 revisions)
- Versioned routes under `/api/v1/`
- Dependency injection for database sessions

### Frontend

`frontend/` is a Next.js 16 application with:

- App Router, React 19, TypeScript 5
- Tailwind CSS 4 for styling
- MapLibre GL for interactive maps
- Operations dashboard with camera markers, hotspot overlays, and linked detail views

## Design Decisions

### Hot path stays pure

No network model calls, no LLM invocations, no database writes inside per-frame inference. Stream workers own the frame loop and call the `FramePipeline` per frame. The pipeline composes detection → tracking → signal state → rules → evidence → event emission.

### Cold path is grounded

Workflow outputs are backed by stored records and typed contexts. The reasoning provider receives structured context objects built from persisted data, not raw inference state. This prevents hallucination and ensures auditability.

### Temporal rule confirmation

Flagship rules (red-light, pedestrian-on-red, stop-line) do not fire on a single frame. The rules engine records pre-violation candidates and only confirms them after enough post-event evidence exists — additional frames, elapsed time, or distance beyond the stop line. This prevents single-frame noise from generating violations.

### Traffic-flow analytics are explicit

Lane occupancy and queue detection use configured rolling windows, zone polygons, and stop-line-relative queue anchors. Queue length is the count of near-stationary objects in a contiguous chain from the anchor point. No opaque heuristics.

### Hotspot scoring is transparent

Hotspot rank equals raw event count. When severity weights are supplied, the weighted score is the sum of operator-provided weights per event. The API exposes `ranking_metric` so consumers know whether rank is count-based or weighted. No hidden "AI score."

### Alerting is policy-driven

Source systems emit normalized signals. The alerting layer applies severity thresholds, dedup windows, cooldowns, and escalation ladders via configured policies. Delivery channels (email, webhook, SMS, Slack, Teams) are defined as reusable targets. Outbound sender integrations are not yet wired — the system persists planned deliveries and audit events honestly.

### Case exports are structured

Bundles are JSON-first and reproducible. Markdown text and zip-manifest views are layered on top of the canonical JSON payload. Every bundle carries traceable metadata, a compact source-reference map, and an explicit completeness block that calls out missing assets.

### Enterprise integrations stay off the core path

`services/integrations/` defines vendor-neutral adapter contracts for external case systems, notification channels, reporting pipelines, object storage providers, and external signal sources. The adapters are driven by normalized payload builders that consume public TrafficMind schemas such as alert detail, case export detail, and workflow run records rather than reaching into ORM internals.

This keeps enterprise integrations outside the deterministic hot path and outside the core storage model. The current built-ins are intentionally modest: local JSONL sinks and local filesystem object storage. They validate the contracts without pretending any SaaS or vendor driver is already implemented.

External signal support follows the same rule. The adapter layer does not replace `services/signals/integration.py`; it bridges new signal sources into the existing controller-state normalization and arbitration flow.

### Evidence is deterministic

Violation manifests carry frame-selection rules, asset keys derived from camera/date/subject/revision, and render hints (bounding boxes, zone geometry, signal-state annotations). Frame selection follows deterministic rules — no random sampling.

### Evaluation is fixture-driven

Benchmark metrics are repeatable and tied to committed fixture files. The evaluation module makes no external quality claims. It exists for internal regression, sanity checking, and local comparison.

## Data Flow

```
┌─────────────┐     ┌───────────────┐     ┌──────────────┐
│ Video Source │────▶│ Stream Worker │────▶│ Frame        │
│ RTSP / File  │     │ (hot path)    │     │ Pipeline     │
└─────────────┘     └───────┬───────┘     └──────┬───────┘
                            │                     │
                            ▼                     ▼
                    ┌───────────────┐     ┌──────────────┐
                    │ Metrics &     │     │ Structured   │
                    │ Heartbeats    │     │ Events       │
                    └───────────────┘     └──────┬───────┘
                                                  │
                                                  ▼
                                          ┌──────────────┐
                                          │ Database     │
                                          │ (PG/SQLite)  │
                                          └──────┬───────┘
                                                  │
                       ┌──────────────────────────┼──────────────┐
                       │                          │              │
                       ▼                          ▼              ▼
               ┌──────────────┐          ┌──────────┐   ┌───────────┐
               │ API (FastAPI)│          │ Workflow │   │ Alerting  │
               │ REST + Query │          │ LangGraph│   │ Engine    │
               └──────┬───────┘          └─────┬────┘   └─────┬─────┘
                      │                        │              │
                      └──────────┬─────────────┴───────┬──────┘
                                 ▼                     ▼
                         ┌──────────────┐     ┌──────────────┐
                         │ Integration  │     │ Frontend     │
                         │ Adapters     │     │ Next.js      │
                         └──────┬───────┘     └──────────────┘
                                │
                                ▼
                         ┌──────────────┐
                         │ Local sinks /│
                         │ future vendors│
                         └──────────────┘
```

## Module Boundaries

Each `services/` module follows a consistent pattern:

- **Interface** (`interface.py`) — abstract base class defining the contract
- **Backend** (`backends/`) — concrete implementations (YOLO, ByteTrack, PaddleOCR)
- **Schemas** (`schemas.py`) — Pydantic models for inputs and outputs
- **Config** (`config.py`) — environment-driven configuration
- **README** — module-specific documentation

Services communicate through typed schemas. No service directly imports another service's internal state.

## Database

- **Engine:** SQLAlchemy async with Alembic migrations
- **Development:** SQLite via `aiosqlite`
- **Production target:** PostgreSQL via `asyncpg`
- **Models:** 22 ORM classes covering cameras, streams, zones, detections, violations, plates, evidence, workflows, alerts, watchlist, re-identification, and case exports
- **Conventions:** UUID primary keys, timestamp mixins, strategic indices on `camera_id`, `status`, `created_at`, `occurred_at`

See [DATA_MODEL.md](DATA_MODEL.md) for the full entity reference.

## Frontend Architecture

The operations dashboard uses a map-first layout:

- Camera markers plotted by lat/lng coordinates
- Junction grouping derived from `location_name` proximity
- Hotspot overlays driven by `POST /api/v1/analytics/hotspots`
- Linked camera detail and event filter routes sharing selection context

The frontend consumes the FastAPI backend exclusively through REST endpoints. No WebSocket connections are used yet.

## Transitional Notes

- The current Next.js app lives in `frontend/`. It will migrate to `apps/web/` once the API surface is more complete.
- `packages/shared-types/` and `packages/shared-config/` are reserved for future cross-app schema consolidation. Most shared types currently live in service-specific schema modules.
