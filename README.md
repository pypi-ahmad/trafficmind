<div align="center">

# 🚦 TrafficMind

### Unified Traffic Intelligence Platform

[![Python 3.13](https://img.shields.io/badge/Python-3.13-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Next.js 16](https://img.shields.io/badge/Next.js_16-000000?style=for-the-badge&logo=next.js&logoColor=white)](https://nextjs.org)
[![React 19](https://img.shields.io/badge/React_19-61DAFB?style=for-the-badge&logo=react&logoColor=black)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white)](https://typescriptlang.org)
[![PyTorch](https://img.shields.io/badge/PyTorch-EE4C2C?style=for-the-badge&logo=pytorch&logoColor=white)](https://pytorch.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)](https://postgresql.org)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-D71F00?style=for-the-badge&logo=sqlalchemy&logoColor=white)](https://sqlalchemy.org)

**Live video ingestion · Real-time detection & tracking · Plate OCR · Deterministic rule evaluation · Operator workflows · Spatial analytics · Operational alerting**

[![Tests](https://img.shields.io/badge/Tests-794_passed-brightgreen?style=flat-square&logo=pytest&logoColor=white)](#-testing)
[![Models](https://img.shields.io/badge/ORM_Models-23-blue?style=flat-square)](#-data-layer)
[![Migrations](https://img.shields.io/badge/Migrations-13-blue?style=flat-square)](#-data-layer)
[![Rules](https://img.shields.io/badge/Rule_Types-8-orange?style=flat-square)](#-rules-engine)
[![Workflows](https://img.shields.io/badge/Workflows-7-purple?style=flat-square)](#-cold-path-workflows)

---

*End-to-end traffic monitoring — from raw video frames to operator-ready violation evidence — in a single, well-tested monorepo.*

</div>

---

## 📋 Table of Contents

- [Overview](#-overview)
- [Tech Stack](#-tech-stack)
- [Architecture](#-architecture)
- [Repository Structure](#-repository-structure)
- [Perception Pipeline (Hot Path)](#-perception-pipeline-hot-path)
- [Backend API](#-backend-api)
- [Cold-Path Workflows](#-cold-path-workflows)
- [Frontend](#-frontend)
- [Rules Engine](#-rules-engine)
- [Data Layer](#-data-layer)
- [Quick Start](#-quick-start)
- [Testing](#-testing)
- [Demo Mode](#-demo-mode)
- [Documentation](#-documentation)
- [Roadmap](#-roadmap)
- [License](#-license)

---

## 🔍 Overview

TrafficMind ingests live or recorded traffic video, runs deterministic computer-vision inference on every frame, evaluates configurable traffic rules against tracked objects, and stores the resulting detections, violations, plate reads, and evidence with versioned runtime provenance for operator review, investigation search, and case export.

The system is split into two clearly separated runtime paths:

| | 🔥 **Hot Path** | 🧊 **Cold Path** |
|---|---|---|
| **Purpose** | Frame-by-frame perception & rule evaluation | Post-hoc triage, review & reporting |
| **Runtime** | Detection → Tracking → OCR → Signals → Rules | LangGraph workflows over stored records |
| **Guarantees** | Fully deterministic · No network I/O · No DB writes in the per-frame loop | Grounded over persisted data only |
| **Latency** | Real-time (per-frame) | Async / operator-triggered |

### Problem It Solves

Urban traffic enforcement and monitoring require processing high-volume video feeds, detecting violations with temporal evidence, reading license plates, and routing incidents to human reviewers with structured evidence. TrafficMind provides the perception, rules, and workflow layers needed to do this in a single monorepo with clear boundaries between deterministic inference and cold-path post-processing.

---

## 🛠 Tech Stack

<table>
<tr>
<td width="50%">

### Backend & Infrastructure

| | Technology |
|---|---|
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/fastapi/fastapi-original.svg" width="16"/> | **FastAPI** · async API with Pydantic v2 validation |
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/sqlalchemy/sqlalchemy-original.svg" width="16"/> | **SQLAlchemy** · async ORM with 23 models |
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/postgresql/postgresql-original.svg" width="16"/> | **PostgreSQL** / SQLite · production / local dev |
| 🔄 | **Alembic** · 13 migration revisions |
| 🦜 | **LangGraph** · 7 cold-path workflow graphs |
| 📦 | **Pydantic v2** · 30+ shared StrEnum types |

</td>
<td width="50%">

### Frontend & UI

| | Technology |
|---|---|
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/nextjs/nextjs-original.svg" width="16"/> | **Next.js 16** · React 19 app router |
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/typescript/typescript-original.svg" width="16"/> | **TypeScript 5** · strict types end-to-end |
| 🎨 | **Tailwind CSS 4** · utility-first styling |
| 🗺️ | **MapLibre GL** · spatial operations map |

</td>
</tr>
<tr>
<td width="50%">

### Computer Vision & ML

| | Technology |
|---|---|
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/pytorch/pytorch-original.svg" width="16"/> | **PyTorch 2.11** · CUDA-accelerated inference |
| 🎯 | **Ultralytics YOLO** · object detection backend |
| 👁️ | **Supervision** · ByteTrack multi-object tracking |
| 🔤 | **PaddleOCR** · license plate recognition |
| 📐 | **OpenCV** · image processing & plate heuristics |
| 🔢 | **NumPy** · array operations |

</td>
<td width="50%">

### DevOps & Quality

| | Technology |
|---|---|
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/python/python-original.svg" width="16"/> | **Python 3.13** · modern runtime |
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/pytest/pytest-original.svg" width="16"/> | **pytest** · 794 tests passing |
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/github/github-original.svg" width="16"/> | **GitHub Actions** · lint / test / build CI |
| 🐳 | **Docker** · containerization (planned) |
| 📋 | **uv** · dependency resolution & lock files |

</td>
</tr>
</table>

---

## 🏗 Architecture

```
                          ┌─────────────────────────────────────────────┐
                          │              🚦  TrafficMind                │
                          │                                             │
    ┌──────────────┐      │  ┌────────────┐    ┌──────────────────────┐│
    │  🖥  Frontend │──────│──│ ⚡ API     │    │  🎥 Stream Workers   ││
    │   Next.js 16 │      │  │  FastAPI   │    │   (GPU Hot Path)     ││
    │   React 19   │      │  └─────┬──────┘    │                      ││
    │   MapLibre   │      │        │           │  🎯 Detection        ││
    └──────────────┘      │        │           │  📍 Tracking          ││
                          │        │           │  🔤 OCR · 🚦 Signals  ││
                          │  ┌─────┴──────┐    │  📏 Rules · 📸 Evid.  ││
                          │  │ 🦜 Workflow │    └──────────────────────┘│
                          │  │  LangGraph  │                            │
                          │  └─────┬──────┘    ┌──────────────────────┐│
                          │        │           │  🔌 Integration       ││
                          │        │           │  Adapters + Local     ││
                          │        │           │  Validation Sinks     ││
                          │  ┌─────┴──────┐    └──────────────────────┘│
                          │  │ 🗄  Database │                           │
                          │  │  PG / SQLite│                           │
                          │  └────────────┘                            │
                          └─────────────────────────────────────────────┘
```

> 📖 See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for layer separation, design decisions, and the deterministic/workflow boundary.

---

## 📁 Repository Structure

```
trafficmind/
├── 🔧 apps/
│   ├── api/                 # FastAPI backend (routes, schemas, services, ORM, migrations)
│   ├── workflow/            # LangGraph cold-path workflow service
│   └── web/                 # Future canonical web app location
│
├── 🧠 services/
│   ├── vision/              # Detection (Detector ABC → YOLO, Plate backends)
│   ├── tracking/            # Tracking (Tracker ABC → ByteTrack, IoU, Centroid backends)
│   ├── ocr/                 # Plate OCR (OcrEngine ABC → PaddleOCR backend)
│   ├── signals/             # Traffic-light classification (HSV + temporal smoothing)
│   ├── rules/               # Deterministic rule engine (8 rule types)
│   ├── motion/              # Speed estimation, direction labeling
│   ├── flow/                # Lane occupancy, queue detection, congestion
│   ├── streams/             # Stream ingestion, worker lifecycle, frame pipeline
│   ├── anpr/                # Plate search, normalization, watchlist helpers
│   ├── events/              # Detection-event search helpers
│   ├── violations/          # Violation search helpers
│   ├── evidence/            # Evidence manifest packaging + privacy/redaction
│   ├── integrations/        # Enterprise adapter contracts + local sinks
│   ├── model_registry/      # Runtime model/config provenance registry
│   ├── health/              # Camera and stream health assessment
│   ├── hotspot/             # Spatial trend analytics and ranking
│   ├── reid/                # Cross-camera re-identification
│   ├── dwell/               # Vehicle dwell-time analytics
│   └── evaluation/          # Fixture-driven benchmarking
│
├── 🖥  frontend/            # Next.js operations dashboard
├── 📦 packages/
│   └── shared_types/        # Cross-boundary type contracts (BBox, ObjectCategory, enums, events)
│
├── 🏗  infra/
│   ├── docker/              # Docker assets
│   └── scripts/             # Automation (run_checks, render_env, doctor)
│
├── 🗃  alembic/             # 13 database migration revisions
├── 📚 docs/                 # Extended documentation
├── 🧪 tests/               # 794 tests across 15+ test modules
└── 🤖 models/              # ML model weights (gitignored)
```

---

## 🎯 Perception Pipeline (Hot Path)

The hot-path perception pipeline composes pluggable backends into a single deterministic `process_frame()` loop:

```
  📹 Frame In  →  🎯 Detect  →  📍 Track  →  🔤 OCR  →  🚦 Classify  →  📏 Evaluate Rules  →  📸 Package Evidence
```

| Capability | Module | Backends | Status |
|---|---|---|---|
| 🎯 Object Detection | `services/vision/` | YOLO v8 · Plate Heuristic | ✅ 2 backends |
| 📍 Multi-Object Tracking | `services/tracking/` | ByteTrack · IoU · Centroid | ✅ 3 backends |
| 🔤 License Plate OCR | `services/ocr/` | PaddleOCR + normalization | ✅ Implemented |
| 🚦 Traffic-Light State | `services/signals/` | HSV voting + temporal smoothing | ✅ Implemented |
| 📏 Rule Evaluation | `services/rules/` | 8 deterministic rule types | ✅ Implemented |
| 🏎 Speed Estimation | `services/motion/` | Calibration-aware, 3 accuracy tiers | ✅ Implemented |
| 🚗 Dwell Analysis | `services/dwell/` | Illegal parking, bus-stop, stalled | ✅ Implemented |
| 📊 Lane Analytics | `services/flow/` | Occupancy, queues, congestion | ✅ Implemented |
| 🔥 Hotspot Analytics | `services/hotspot/` | Ranking, heatmap, trends | ✅ Implemented |
| 🔄 Cross-Camera Re-ID | `services/reid/` | Entity association + review pipeline | ✅ Foundation |
| 📹 Stream Orchestration | `services/streams/` | Worker lifecycle, metrics, heartbeats | ✅ Implemented |
| 📸 Evidence Packaging | `services/evidence/` | Deterministic frame selection | ✅ Implemented |
| 🔒 Privacy & Redaction | `services/evidence/privacy.py` | Role-based access, plate masking | ✅ Implemented |
| 📋 Model Provenance | `services/model_registry/` | Versioned runtime bundles | ✅ Implemented |

> **Pluggable Backends:** Both detector and tracker abstractions use an ABC + registry pattern. New backends (e.g. RT-DETR, custom ANPR model) can be registered without modifying existing code.

---

## ⚡ Backend API

**15+ endpoint groups** powering the full traffic operations lifecycle:

| Endpoint Group | Routes | Description |
|---|---|---|
| 📷 Cameras & Streams | `/api/v1/cameras`, `/api/v1/streams` | CRUD, health, video source registration |
| 🔗 Junctions | `/api/v1/junctions` | Junction entity CRUD, camera grouping |
| 🎯 Detection Events | `/api/v1/events` | Paginated search, temporal filtering |
| ⚠️ Violations | `/api/v1/violations` | Search, severity, review status |
| 🔤 Plate Search | `/api/v1/plates` | ANPR lookup, normalization-aware matching |
| 📋 Watchlists | `/api/v1/watchlist` | Entry CRUD, plate matching |
| 📸 Evidence | `/api/v1/{type}/{id}/evidence` | Manifest build and retrieval |
| 📊 Analytics | `/api/v1/analytics/hotspots` | Spatial ranking, trends, heatmaps |
| 🩺 Observability | `/api/v1/observability/dashboard` | Camera/stream health dashboard |
| 🔔 Alerts | `/api/v1/alerts` | Routing, escalation, delivery dispatch |
| 📦 Case Export | `/api/v1/exports` | JSON bundles, markdown, zip-manifest |
| 🤖 Model Registry | `/api/v1/model-registry` | Runtime bundle tracking, provenance |
| 🔐 Access Policy | `/api/v1/access/policy` | Role-to-permission matrix |
| 💚 Health | `/api/v1/health/ready` | Startup & readiness probes |
| 🏭 Jobs | `/api/v1/jobs` | Stream job management |

---

## 🦜 Cold-Path Workflows

Seven LangGraph-powered workflow graphs operating exclusively over stored records:

| Workflow | Description | Status |
|---|---|---|
| 🔍 Incident Triage | Automated incident classification and routing | ✅ |
| ✅ Violation Review | Human-in-the-loop violation confirmation | ✅ |
| 🤖 Multimodal Review Copilot | Grounded advisory analysis of evidence | ✅ |
| 📅 Daily Summary | Automated daily operations report | ✅ |
| 📆 Weekly Summary | Automated weekly trend report | ✅ |
| 🔥 Hotspot Report | Spatial concentration analysis | ✅ |
| 💬 Operator Assist | Retrieval-first natural language investigation | ✅ |

> The workflow service uses a deterministic heuristic provider. The provider boundary is explicit — model-backed providers can be swapped in without modifying graph definitions.

---

## 🖥 Frontend

The Next.js 16 operations dashboard provides a map-first view of the camera network:

| Feature | Status |
|---|---|
| 🗺️ Map-first operations dashboard | ✅ Implemented |
| 📷 Camera detail and stream view | ✅ Implemented |
| 🎯 Live event and violation feeds | ✅ Implemented |
| 🔗 Junction-level camera grouping | ✅ Implemented |
| 📊 Hotspot and spatial analytics | ✅ Implemented |
| 📈 Evaluation benchmark summaries | ✅ Implemented |
| ⚠️ Violation review UI | 🔜 Planned |
| 📊 Analytics charts | 🚧 In progress |

---

## 📏 Rules Engine

8 deterministic rule types evaluated against tracked objects and zone geometry:

| Rule Type | Temporal Confirmation | Evidence |
|---|---|---|
| 🔴 Red-light crossing | ✅ Multi-frame required | Pre + post violation frames |
| 🚶 Pedestrian on red | ✅ Multi-frame required | Trajectory evidence |
| 🛑 Stop-line crossing | ✅ Multi-frame required | Approach + violation frames |
| ↩️ Wrong-way travel | — | Direction vector evidence |
| 🏎 Speeding | — | Speed estimation evidence |
| 🚫 Illegal turn | — | Trajectory evidence |
| ⏱ Dwell time | Duration-based | Timestamped occupancy |
| ➖ Line crossing | — | Crossing geometry |

> **Flagship rules** (red-light, pedestrian-on-red, stop-line) hold pre-violation candidates until sufficient post-event evidence accumulates. Unknown or stale signal state does not generate candidates.

---

## 🗄 Data Layer

| Metric | Value |
|---|---|
| 📊 ORM Models | 23 SQLAlchemy models |
| 🔄 Migrations | 13 Alembic revisions |
| 📦 Enum Types | 30+ StrEnum types |
| 🔗 Shared Contracts | `packages/shared_types/` — BBox, ObjectCategory, enums, events |

---

## 🚀 Quick Start

### Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| 🐍 Python | 3.12+ (3.13 recommended) | Core runtime |
| 📦 Node.js | 18+ | Frontend build |
| 🎮 CUDA GPU | Optional | Auto-detected via PyTorch; OCR falls back to CPU on Windows |

### Installation

```bash
# 1️⃣  Clone and enter the repository
git clone https://github.com/pypi-ahmad/trafficmind.git
cd trafficmind

# 2️⃣  Create and activate a Python virtual environment
python -m venv .venv
.venv\Scripts\activate           # Windows
source .venv/bin/activate        # Linux / macOS

# 3️⃣  Install dependencies
pip install -r requirements-dev.lock
pip install --no-deps -e .

# 4️⃣  (Optional) Add CV extras for detection, OCR, or stream inference
pip install -e ".[cv]"

# 5️⃣  Configure environment
cp .env.example .env
# or: python infra/scripts/render_env.py --profile local --output .env

# 6️⃣  Initialize the database
alembic upgrade head

# 7️⃣  Start all services
uvicorn apps.api.app.main:app --reload --port 8000      # ⚡ API       → localhost:8000
uvicorn apps.workflow.app.main:app --reload --port 8010  # 🦜 Workflow  → localhost:8010
cd frontend && npm install && npm run dev                # 🖥  Frontend → localhost:3000
```

> **📦 Dependency source of truth:** `pyproject.toml`
> Lock files generated by `uv pip compile` and committed. `requirements.txt` is a thin shim pointing to `requirements.lock`.

### 🎭 Seed Demo Data

```bash
python -m apps.api.app.demo.seed --create-schema         # Create tables + seed demo data
python -m apps.api.app.demo.seed --report-path report.json  # Write walkthrough report
python -m apps.api.app.demo.seed --list-scenarios           # List available scenarios
```

### 🎬 Run Perception Pipeline

```bash
# Test stream (no GPU required)
python -m services.streams --source-kind test --max-frames 60

# Local video file
python -m services.streams --source-kind file --source-uri path/to/video.mp4

# Evaluation suite
python -m services.evaluation tests/fixtures/evaluation/benchmark_suite.json
```

> 📖 See [docs/LOCAL_DEVELOPMENT.md](docs/LOCAL_DEVELOPMENT.md) for the full setup guide, environment variables, and troubleshooting.

---

## 🧪 Testing

```bash
# Full suite (794 tests)
python -m pytest tests/ -q

# Specific module
python -m pytest tests/rules/ -v

# With coverage report
python -m pytest tests/ --cov=apps --cov=services --cov-report=term-missing

# Golden-path regression (DB → pipeline → API → workflow → frontend build)
python infra/scripts/run_checks.py --suite golden-path
```

<details>
<summary><strong>📊 Test Coverage by Module</strong></summary>

| Module | Coverage Area |
|---|---|
| `tests/rules/` | Rule evaluation, flagship temporal rules, fixture-driven progression |
| `tests/tracking/` | IoU, centroid, ByteTrack backends, lifecycle, multi-object, direction |
| `tests/vision/` | Detection schemas, registry, plate detector, YOLO integration |
| `tests/flow/` | Lane occupancy, queue, congestion, utilization analytics |
| `tests/hotspot/` | Aggregation, trends, severity weighting, recurring issues |
| `tests/signals/` | Signal classifier, state tracker, HSV pipeline |
| `tests/streams/` | Integrated pipeline, worker lifecycle, backpressure |
| `tests/motion/` | Speed estimation, direction labeling, calibration tiers |
| `tests/ocr/` | OCR service, normalization |
| `tests/health/` | Camera health assessor, alert thresholds |
| `tests/api/` | Camera, junction, event, violation, alert, export, delivery endpoints |
| `tests/workflow/` | All 7 LangGraph workflows, interrupt/resume, NL planner |
| `tests/integrations/` | Adapter builders, local sinks, object storage, signal bridge |
| `tests/evaluation/` | Benchmark foundation, metrics edge cases |
| `tests/smoke/` | Golden-path operator flow, E2E persistence |

</details>

---

## 🎭 Demo Mode

Demo mode seeds the local database with realistic synthetic data for development, screenshots, and walkthroughs. **It does not replay production data or fabricate benchmark results.**

**Seeded data:** 3 cameras · 4 streams · 5 zones · 4 detection events · 3 plate reads · 3 violations · 3 evidence manifests · 3 workflows

| Marker | Where | Purpose |
|---|---|---|
| `DEMO-` prefix | Camera codes | Identify synthetic cameras |
| `source_type=test` | All demo streams | Distinguish from real sources |
| `demo://` scheme | All asset URIs | Prevent accidental storage lookups |
| `trafficmind_record_origin.mode=demo_seed` | All metadata | Full audit traceability |

> Demo data is clearly distinguishable from real processed data at every layer. The seeder is **idempotent** — rerunning replaces existing demo records without duplicating.

---

## 📚 Documentation

| Document | Description |
|---|---|
| 📐 [ARCHITECTURE.md](docs/ARCHITECTURE.md) | System layers, design decisions, deterministic boundary |
| 🛠 [LOCAL_DEVELOPMENT.md](docs/LOCAL_DEVELOPMENT.md) | Full setup guide, environment variables, database, frontend |
| 🚀 [DEPLOYMENT.md](docs/DEPLOYMENT.md) | Environment profiles, readiness checks, CI scope, secrets |
| 🗄 [DATA_MODEL.md](docs/DATA_MODEL.md) | ORM models, relationships, enums, migration history |
| 🔌 [INTEGRATIONS.md](docs/INTEGRATIONS.md) | Core product vs adapter foundations vs enterprise extensions |
| 📋 [PROVENANCE.md](docs/PROVENANCE.md) | Model/config registry, runtime provenance, reproducibility |
| 🦜 [WORKFLOWS.md](docs/WORKFLOWS.md) | Cold-path workflow definitions and lifecycle |
| ⚠️ [LIMITATIONS.md](docs/LIMITATIONS.md) | Known gaps, honest constraints, extension points |
| 🩺 [camera-health.md](docs/camera-health.md) | Health signals, alert severities, thresholds |
| 📸 [evidence.md](docs/evidence.md) | Evidence manifest structure and asset-key conventions |
| 🔒 [PRIVACY.md](docs/PRIVACY.md) | Privacy masking, redaction, request-declared access control |
| 🔤 [anpr.md](docs/anpr.md) | Plate search behavior, normalization, watchlist matching |
| 📊 [evaluation.md](docs/evaluation.md) | Evaluation artifacts, benchmark interpretation |

---

## 🗺 Roadmap

| Phase | Status | Progress |
|---|---|---|
| 🏗 Repository structure & architecture | Complete | ████████████ 100% |
| ⚡ API & workflow foundations | Complete | ████████████ 100% |
| 🧠 Deterministic vision services | Complete | ████████████ 100% |
| 📋 Event & review platform | Complete | ████████████ 100% |
| 🔌 Enterprise integration adapters | Complete | ████████████ 100% |
| 🔗 Explicit junction entity | Complete | ████████████ 100% |
| 🎯 Pluggable backend validation | Complete | ████████████ 100% |
| 🖥 Web product (dashboard, review UI) | In progress | ████████░░░░ 70% |
| 🚀 Production hardening (CI/CD, containers) | In progress | ██████░░░░░░ 50% |
| 🤖 Model maturity (plate detector, signal model) | Planned | ██░░░░░░░░░░ 15% |

---

## 📄 License

Private repository. All rights reserved.
