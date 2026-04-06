# TrafficMind

Unified traffic computer-vision platform — live video ingestion, vehicle/pedestrian/traffic-light detection, multi-object tracking, plate OCR, deterministic rule evaluation, event storage, audit-friendly model/config provenance, operator review workflows, retrieval-first investigation search, and operational alerting.

---

## What It Does

TrafficMind ingests live or recorded traffic video, runs deterministic computer-vision inference on every frame, evaluates configurable traffic rules against tracked objects, and stores the resulting detections, violations, plate reads, and evidence with versioned runtime provenance for operator review, deterministic investigation search, and case export.

The system is split into two runtime paths:

- **Hot path** — frame-by-frame detection, tracking, OCR, signal-state classification, and rule evaluation. Fully deterministic. No LLM calls, no network I/O, no database writes in the per-frame loop.
- **Cold path** — incident triage, advisory multimodal review, violation review, report generation, and operator assist. Powered by LangGraph workflows over stored records only.

## Problem It Solves

Urban traffic enforcement and monitoring require processing high-volume video feeds, detecting violations with temporal evidence, reading license plates, and routing incidents to human reviewers with structured evidence. TrafficMind provides the perception, rules, and workflow layers needed to do this in a single monorepo with clear boundaries between deterministic inference and cold-path workflow post-processing.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend API | FastAPI, Pydantic v2, SQLAlchemy (async), Alembic |
| Frontend | Next.js 16, React 19, TypeScript 5, Tailwind CSS 4, MapLibre GL |
| CV Inference | Ultralytics YOLO v8, Supervision, PaddleOCR |
| Workflows | LangGraph workflow service with a deterministic heuristic provider |
| Runtime | Python 3.13, PyTorch 2.11 + CUDA |
| Database | PostgreSQL (production), SQLite (local development) |

---

## Repository Structure

```
trafficmind/
├── apps/
│   ├── api/              # FastAPI backend (routes, schemas, services, ORM, migrations)
│   ├── workflow/          # LangGraph cold-path workflow service
│   └── web/              # Future canonical web app location
├── services/
│   ├── vision/           # Object detection (Detector ABC → YOLO backend)
│   ├── tracking/         # Multi-object tracking (Tracker ABC → ByteTrack backend)
│   ├── ocr/              # Plate OCR (OcrEngine ABC → PaddleOCR backend)
│   ├── signals/          # Traffic-light state classification (HSV + temporal smoothing)
│   ├── rules/            # Deterministic rule engine (8 rule types, temporal confirmation)
│   ├── motion/           # Speed estimation, direction labeling, overspeed/wrong-way screening
│   ├── flow/             # Lane occupancy, queue detection, congestion, utilization
│   ├── streams/          # Stream ingestion, worker lifecycle, frame pipeline
│   ├── anpr/             # Plate search, normalization, watchlist helpers
│   ├── events/           # Detection-event search helpers
│   ├── violations/       # Violation search helpers
│   ├── evidence/         # Deterministic evidence manifest packaging
│   ├── integrations/     # Vendor-neutral enterprise adapter contracts + local sinks
│   ├── model_registry/   # Runtime model/config provenance registry helpers
│   ├── health/           # Camera and stream health assessment
│   ├── hotspot/          # Hotspot ranking, spatial trends, recurring-issue detection
│   ├── reid/             # Cross-camera re-identification
│   ├── dwell/            # Vehicle dwell-time analytics
│   └── evaluation/       # Fixture-driven benchmarking and regression checks
├── frontend/             # Next.js operations dashboard (pre-migration to apps/web/)
├── packages/
│   ├── shared-types/     # Cross-app schema contracts (placeholder)
│   └── shared-config/    # Shared configuration conventions (placeholder)
├── infra/
│   ├── docker/           # Docker assets (placeholder)
│   └── scripts/          # Local automation helpers
├── models/               # ML model weights (gitignored)
├── docs/                 # Extended documentation
├── alembic/              # Database migration scripts (10 revisions)
└── tests/                # regression suite (standard backend validation: 697 passed, 2 deselected, plus pre-existing non-blocking warnings)
```

---

## Architecture Overview

```
                    ┌──────────────────────────────────────────┐
                    │              TrafficMind                  │
                    │                                          │
  ┌──────────┐     │  ┌──────────┐   ┌────────────────────┐  │
  │ Frontend │─────│──│ API      │   │ Stream Workers     │  │
  │ Next.js  │     │  │ FastAPI  │   │ (GPU hot path)     │  │
  └──────────┘     │  └────┬─────┘   │ Detection          │  │
                    │       │         │ Tracking            │  │
                    │       │         │ OCR · Signals       │  │
                    │  ┌────┴─────┐   │ Rules · Evidence    │  │
                    │  │ Workflow │   └────────────────────┘  │
                    │  │ LangGraph│                           │
                    │  └────┬─────┘   ┌────────────────────┐  │
                    │       │         │ Integration        │  │
                    │       │         │ Adapters + Local   │  │
                    │       │         │ Validation Sinks   │  │
                    │  ┌────┴──────┐                           │
                    │  │ Database  │                           │
                    │  │ PG/SQLite │                           │
                    │  └───────────┘                           │
                    └──────────────────────────────────────────┘
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for layer separation, design decisions, and the deterministic/workflow boundary.

---

## Core Implemented Product

### Perception (Hot Path)

| Capability | Module | Status |
|---|---|---|
| Object detection (vehicles, pedestrians, traffic lights) | `services/vision/` | Implemented — YOLO v8 backend |
| Multi-object tracking | `services/tracking/` | Implemented — ByteTrack backend |
| Plate OCR | `services/ocr/` | Implemented — PaddleOCR backend + normalization |
| Traffic-light state understanding | `services/signals/` | Implemented — HSV pixel voting, temporal smoothing, and controller-feed integration foundation |
| Rule evaluation (8 rule types) | `services/rules/` | Implemented — temporal confirmation for flagship rules |
| Dwell and stationary-object analysis | `services/dwell/` | Implemented — scenario thresholds for illegal parking, no-stopping, bus-stop occupation, stalled vehicles |
| Speed estimation and direction labeling | `services/motion/` | Implemented — calibration-aware, three accuracy tiers |
| Lane occupancy, queue, congestion | `services/flow/` | Implemented — rolling-window analytics |
| Hotspot and spatial trend analytics | `services/hotspot/` | Implemented — ranking, heatmap buckets, recurring-issue summaries |
| Cross-camera re-identification foundation | `services/reid/` | Implemented — entity association, candidate matching, review pipeline |
| Stream ingestion and orchestration | `services/streams/` | Implemented — worker lifecycle, metrics, heartbeats |
| Evidence manifest packaging | `services/evidence/` | Implemented — deterministic frame selection, asset keys |
| Model/config provenance registry | `services/model_registry/` | Implemented — versioned runtime bundles for detector, tracker, OCR, rules, and evidence |
| Privacy masking & redaction foundation | `services/evidence/privacy.py` | Implemented — role-based access, plate masking, redacted asset provenance |
| Sensitive access-control policy foundation | `services/access_control/` | Implemented — coarse permissions, route enforcement, audit logging |

### Backend API

| Capability | Endpoint Group | Status |
|---|---|---|
| Camera and stream CRUD | `/api/v1/cameras`, `/api/v1/streams` | Implemented |
| Detection event search | `/api/v1/events` | Implemented |
| Violation search | `/api/v1/violations` | Implemented |
| Plate search and lookup | `/api/v1/plates` | Implemented |
| Watchlist CRUD and plate matching | `/api/v1/watchlist` | Implemented |
| Evidence manifests (build + fetch) | `/api/v1/violations/{id}/evidence`, `/api/v1/events/{id}/evidence` | Implemented |
| Evaluation summaries | `GET /api/v1/analytics/evaluation` | Implemented — fixture-backed and local-artifact-backed benchmark summaries |
| Hotspot analytics | `POST /api/v1/analytics/hotspots` | Implemented |
| Camera/stream health dashboard | `/api/v1/observability/dashboard` | Implemented |
| Service readiness probes | `/api/v1/health/ready`, workflow `/api/v1/health/ready` | Implemented — startup/readiness checks for local-first deployment validation |
| Alert routing and escalation | `/api/v1/alerts` (15+ endpoints) | Implemented |
| Case export bundles | `/api/v1/exports` | Implemented — JSON, markdown, zip-manifest |
| Model/config registry | `/api/v1/model-registry` | Implemented — admin writes, audit-oriented reads, active/inactive bundle tracking |
| Access policy preview | `GET /api/v1/access/policy` | Implemented — role-to-permission matrix and action requirements |
| Stream job management | `/api/v1/jobs` | Implemented |

### Cold-Path Workflows

| Workflow | Status |
|---|---|
| Incident triage | Implemented |
| Violation review (human-in-the-loop) | Implemented |
| Multimodal review copilot (grounded, advisory) | Implemented |
| Daily summary report | Implemented |
| Weekly summary report | Implemented |
| Hotspot report | Implemented |
| Operator assist (retrieval-first investigation search) | Implemented |

The workflow service runs with a deterministic heuristic provider today. The provider boundary is explicit, but no model-backed workflow provider is wired yet.

### Frontend

| Feature | Status |
|---|---|
| Map-first operations dashboard | Implemented |
| Camera detail route | Implemented |
| Event filtering and navigation | Implemented |
| Evaluation and benchmark summary foundation | Implemented |
| Violation review UI | Not started |
| Analytics charts | In progress |

### Data

| Item | Status |
|---|---|
| ORM models | 22 SQLAlchemy models |
| Database migrations | 10 Alembic revisions |
| Enum types | 30+ StrEnum types |
| Regression suite | Standard backend validation: 697 passed, 2 deselected, plus pre-existing non-blocking warnings; 1 known demo-seed observability failure remains excluded by default |

---

## Advanced Implemented Foundations

These foundations exist in working code today, but they are intentionally narrower than full enterprise product claims:

- **Enterprise integration adapters** — `services/integrations/` defines pluggable contracts for external case systems, notification channels, reporting pipelines, object storage providers, and external signal sources. Built-in adapters are limited to local JSONL sinks and local filesystem object storage so the contracts can be exercised honestly without pretending vendor support exists.
- **Signal/controller bridge** — normalized controller-state ingestion already exists in `services/signals/`; the adapter bridge extends that foundation without replacing the current normalization and arbitration path.
- **Deployment validation layer** — env profile rendering, readiness checks, `doctor`, `run_checks`, and minimal GitHub Actions CI now provide a local-first validation baseline.

See [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) for the explicit boundary between implemented adapter foundations and future vendor integrations.

---

## Future Integration Points

These areas either remain intentionally partial or are explicit next-step extensions:

- **Semantic/vector retrieval** — not implemented; investigation search remains deterministic and filter-backed over stored records.
- **Alert delivery** — policies, routing, escalation, and audit are implemented; outbound email/webhook/SMS senders are not wired.
- **Case export rendering** — JSON bundles are complete; markdown is embedded; zip archive generation is a manifest placeholder.
- **Enterprise vendor adapters** — ServiceNow, Maximo, Jira Service Management, Slack, Teams, S3-compatible storage, and warehouse/reporting targets are not implemented. The repo now provides adapter contracts and local sinks only.
- **Model/config registry** — runtime provenance is implemented for stored outputs, but the repo still does not claim training orchestration or experiment scheduling. The evaluation dashboard is limited to fixture-backed and local-artifact-backed summaries.
- **Dedicated plate detection** — OCR relies on generic vehicle detection crops. No dedicated plate-localization model is integrated.
- **Traffic-light state model** — classification uses HSV pixel analysis, not a trained state model.
- **Live perception deployment** — the pipeline foundation is stable; production hardening and deployment packaging are incomplete.
- **CI/CD and deployment** — a local-first foundation now exists: env profiles, readiness checks, validation scripts, and GitHub Actions lint/test/build jobs. Dockerfiles, orchestrator manifests, and cloud deployment assets are still intentionally absent.
- **Workflow checkpointing** — in-memory; no durable backend for production resumption.

---

## Local Development

### Prerequisites

- Python 3.12+ (3.13 recommended)
- Node.js 18+ (for frontend)
- GPU with CUDA support (optional, for CV inference)

### Quick Start

```bash
# render the default local env profile
python infra/scripts/render_env.py --profile local --output .env

# activate Python environment
.venv\Scripts\activate           # Windows
source .venv/bin/activate        # Linux/macOS

# install API + workflow dependencies
pip install -e ".[dev,workflow]"

# add CV extras when you want to run detection, OCR, or stream inference locally
pip install -e ".[cv]"

# start backend API
uvicorn apps.api.app.main:app --reload

# start workflow service
uvicorn apps.workflow.app.main:app --reload --port 8010

# start frontend
cd frontend && npm install && npm run dev

# run tests
python -m pytest tests/ -q

# run the repeatable validation surface
python infra/scripts/run_checks.py --suite all
```

### Seed Demo Data

```bash
# create tables and seed synthetic demo data
python -m apps.api.app.demo.seed --create-schema

# write a walkthrough report
python -m apps.api.app.demo.seed --report-path demo-seed-report.json

# list available scenarios
python -m apps.api.app.demo.seed --list-scenarios
```

### Run Perception Pipeline

```bash
# test stream (no GPU required)
python -m services.streams --source-kind test --max-frames 60 --disable-detection --disable-tracking

# local video file
python -m services.streams --source-kind file --source-uri path/to/video.mp4 --max-processing-fps 10

# evaluation suite
python -m services.evaluation tests/fixtures/evaluation/benchmark_suite.json

# write a stored evaluation artifact for the UI
python -m services.evaluation tests/fixtures/evaluation/benchmark_suite.json --output outputs/evaluation/fixture-baseline.json --artifact-label fixture-baseline
```

See [docs/LOCAL_DEVELOPMENT.md](docs/LOCAL_DEVELOPMENT.md) for full setup, environment variables, and troubleshooting.
See [docs/evaluation.md](docs/evaluation.md) for how evaluation artifacts are generated and how to interpret the resulting UI.

---

## Demo Mode

Demo mode seeds the local database with realistic synthetic data for development, screenshots, and walkthroughs. It does not replay production data or fabricate benchmark results.

**What gets seeded:** 3 cameras (online, degraded, offline health states), 4 streams, 5 zones, 4 detection events, 3 plate reads, 3 violations (confirmed, under review, dismissed), 3 evidence manifests, 3 workflows.

**How demo data is labeled:**

| Marker | Where |
|---|---|
| `DEMO-` prefix | Camera codes |
| `source_type=test` | All demo streams |
| `demo://` scheme | All asset URIs |
| `trafficmind_record_origin.mode=demo_seed` | All metadata payloads |

Demo data is clearly distinguishable from real processed data at every layer. The seeder is idempotent — rerunning it replaces existing demo records without duplicating.

---

## Rules Engine

The rules engine evaluates 8 deterministic rule types against tracked objects and zone geometry:

| Rule Type | Temporal Confirmation |
|---|---|
| Red-light crossing | Yes — multi-frame evidence required |
| Pedestrian on red | Yes |
| Stop-line crossing | Yes |
| Wrong-way travel | No |
| Speeding | No |
| Illegal turn | No |
| Dwell time | No — duration-based |
| Line crossing | No |

Flagship rules (red-light, pedestrian-on-red, stop-line) hold pre-violation candidates until sufficient post-event evidence exists. Unknown or stale signal state does not generate candidates.

---

## Testing

```bash
# full suite
python -m pytest tests/ -q

# specific module
python -m pytest tests/rules/ -v

# with coverage
python -m pytest tests/ --cov=apps --cov=services --cov-report=term-missing
```

The test suite covers: rule evaluation, tracking, flow analytics, hotspot analytics, health assessment, signal classification, stream orchestration, OCR, vision, motion, API endpoints, alert routing, case export, integration adapter foundations, demo seeding, evidence manifests, workflow execution, and evaluation metrics.

---

## Documentation

| Document | Description |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System layers, design decisions, deterministic boundary |
| [docs/LOCAL_DEVELOPMENT.md](docs/LOCAL_DEVELOPMENT.md) | Full setup guide, environment variables, database, frontend |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Environment profiles, readiness checks, CI scope, secrets guidance, supported run modes |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | ORM models, relationships, enums, migration history |
| [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) | Core product vs adapter foundations vs future enterprise integration points |
| [docs/PROVENANCE.md](docs/PROVENANCE.md) | Model/config registry scope, runtime provenance links, and reproducibility goals |
| [docs/WORKFLOWS.md](docs/WORKFLOWS.md) | Cold-path workflow definitions and lifecycle |
| [docs/LIMITATIONS.md](docs/LIMITATIONS.md) | Known gaps, honest constraints, and extension points |
| [docs/camera-health.md](docs/camera-health.md) | Health signal definitions, alert severities, thresholds |
| [docs/evidence.md](docs/evidence.md) | Evidence manifest structure and asset-key conventions |
| [docs/PRIVACY.md](docs/PRIVACY.md) | Privacy masking, evidence redaction, and request-declared access control |
| [docs/anpr.md](docs/anpr.md) | Plate search behavior, normalization, watchlist matching |

---

## Roadmap

| Phase | Status |
|---|---|
| Repository structure and architecture | Complete |
| API and workflow foundations | Complete |
| Deterministic vision services | Complete |
| Event and review platform | Complete |
| Web product (operations dashboard, review UI) | In progress |
| Production hardening (env profiles, CI/CD, readiness checks, deployment docs) | In progress |
| Model and pipeline maturity (plate detector, signal model) | Not started |

---

## License

Private repository. All rights reserved.
