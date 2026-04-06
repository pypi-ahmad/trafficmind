<div align="center">

<img src="https://img.shields.io/badge/🚦-TrafficMind-1a1a2e?style=for-the-badge&labelColor=0d1117&color=16213e" height="60"/>

<br/>

### **Unified Traffic Intelligence Platform**

<p align="center">
<em>End-to-end traffic monitoring — from raw video frames to operator-ready violation evidence — in a single, well-tested monorepo.</em>
</p>

<br/>

[![Python 3.13](https://img.shields.io/badge/Python-3.13-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Next.js 16](https://img.shields.io/badge/Next.js_16-000000?style=for-the-badge&logo=next.js&logoColor=white)](https://nextjs.org)
[![React 19](https://img.shields.io/badge/React_19-61DAFB?style=for-the-badge&logo=react&logoColor=black)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white)](https://typescriptlang.org)
[![PyTorch](https://img.shields.io/badge/PyTorch-EE4C2C?style=for-the-badge&logo=pytorch&logoColor=white)](https://pytorch.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)](https://postgresql.org)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-D71F00?style=for-the-badge&logo=sqlalchemy&logoColor=white)](https://sqlalchemy.org)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS_4-06B6D4?style=for-the-badge&logo=tailwindcss&logoColor=white)](https://tailwindcss.com)
[![LangGraph](https://img.shields.io/badge/🦜_LangGraph-1C3C3C?style=for-the-badge)](https://langchain-ai.github.io/langgraph/)

<br/>

<p align="center">
<a href="#-quick-start"><img src="https://img.shields.io/badge/🚀_Quick_Start-Guide-2ea44f?style=flat-square" alt="Quick Start"/></a>
<a href="#-architecture"><img src="https://img.shields.io/badge/🏗_Architecture-Overview-blue?style=flat-square" alt="Architecture"/></a>
<a href="#-testing"><img src="https://img.shields.io/badge/🧪_Tests-813_passed-brightgreen?style=flat-square&logo=pytest&logoColor=white" alt="Tests"/></a>
<a href="#-documentation"><img src="https://img.shields.io/badge/📚_Docs-17_pages-mediumpurple?style=flat-square" alt="Docs"/></a>
</p>

<p align="center">
<img src="https://img.shields.io/badge/ORM_Models-23-0969da?style=flat-square&logo=database&logoColor=white" alt="Models"/>
<img src="https://img.shields.io/badge/Migrations-13-0969da?style=flat-square" alt="Migrations"/>
<img src="https://img.shields.io/badge/Test_Files-50-brightgreen?style=flat-square" alt="Test Files"/>
<img src="https://img.shields.io/badge/Rule_Types-11-orange?style=flat-square" alt="Rules"/>
<img src="https://img.shields.io/badge/Workflows-7-8957e5?style=flat-square" alt="Workflows"/>
<img src="https://img.shields.io/badge/API_Route_Groups-15+-0969da?style=flat-square" alt="Routes"/>
<img src="https://img.shields.io/badge/Shared_Enums-33-e8590c?style=flat-square" alt="Enums"/>
</p>

---

**Live video ingestion** · **Real-time detection & tracking** · **Plate OCR** · **Deterministic rule evaluation** · **Operator workflows** · **Spatial analytics** · **Operational alerting**

</div>

<br/>

## 📋 Table of Contents

<details>
<summary><strong>Click to expand</strong></summary>

- [Why TrafficMind](#-why-trafficmind)
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

</details>

---

## 💡 Why TrafficMind

<table>
<tr>
<td width="60%">

Urban traffic enforcement and monitoring require processing high-volume video feeds, detecting violations with temporal evidence, reading license plates, and routing incidents to human reviewers with structured evidence.

**TrafficMind provides all of this in a single monorepo with clear boundaries between deterministic inference and cold-path post-processing.**

The system is split into two clearly separated runtime paths:

</td>
<td width="40%">

```
    ┌─────────────────────┐
    │   📹 Video Feeds    │
    └─────────┬───────────┘
              ▼
    ┌─────────────────────┐
    │  🧠 Perception      │
    │  Detect → Track →   │
    │  OCR → Rules        │
    └─────────┬───────────┘
              ▼
    ┌─────────────────────┐
    │  ⚡ API + Workflows  │
    │  Store → Triage →   │
    │  Review → Export    │
    └─────────┬───────────┘
              ▼
    ┌─────────────────────┐
    │  🖥️ Operator UI      │
    │  Map → Events →     │
    │  Evidence → Reports │
    └─────────────────────┘
```

</td>
</tr>
</table>

| | 🔥 **Hot Path** | 🧊 **Cold Path** |
|:---:|---|---|
| **Purpose** | Frame-by-frame perception & rule evaluation | Post-hoc triage, review & reporting |
| **Runtime** | Detection → Tracking → OCR → Signals → Rules | LangGraph workflows over stored records |
| **Guarantees** | Fully deterministic · No network I/O · No DB writes in the per-frame loop | Grounded exclusively over persisted data |
| **Latency** | Real-time (per-frame) | Async / operator-triggered |

---

## 🛠 Tech Stack

<table>
<tr>
<td width="50%">

### 🔧 Backend & Infrastructure

| | Technology | Details |
|:---:|---|---|
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/fastapi/fastapi-original.svg" width="20"/> | **FastAPI** | Async API, Pydantic v2 validation |
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/sqlalchemy/sqlalchemy-original.svg" width="20"/> | **SQLAlchemy 2** | Async ORM, 23 models |
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/postgresql/postgresql-original.svg" width="20"/> | **PostgreSQL** | Production data store |
| <img src="https://img.shields.io/badge/-SQLite-003B57?style=flat&logo=sqlite&logoColor=white" height="16"/> | **SQLite** | Local development |
| 🔄 | **Alembic** | 13 migration revisions |
| 🦜 | **LangGraph** | 7 cold-path workflow graphs |
| 📦 | **Pydantic v2** | 33 shared StrEnum types |

</td>
<td width="50%">

### 🖥 Frontend & UI

| | Technology | Details |
|:---:|---|---|
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/nextjs/nextjs-original.svg" width="20"/> | **Next.js 16** | React 19, App Router, SSR |
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/typescript/typescript-original.svg" width="20"/> | **TypeScript 5** | Strict types end-to-end |
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/tailwindcss/tailwindcss-original.svg" width="20"/> | **Tailwind CSS 4** | Utility-first styling |
| 🗺️ | **MapLibre GL** | Spatial operations map |
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/react/react-original.svg" width="20"/> | **React 19** | Server components |

</td>
</tr>
<tr>
<td width="50%">

### 🧠 Computer Vision & ML

| | Technology | Details |
|:---:|---|---|
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/pytorch/pytorch-original.svg" width="20"/> | **PyTorch 2.11** | CUDA-accelerated inference |
| 🎯 | **Ultralytics YOLO** | Object detection backends |
| 👁️ | **Supervision** | ByteTrack multi-object tracking |
| 🔤 | **PaddleOCR** | License plate recognition |
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/opencv/opencv-original.svg" width="20"/> | **OpenCV** | Image processing & heuristics |
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/numpy/numpy-original.svg" width="20"/> | **NumPy** | Array operations |

</td>
<td width="50%">

### ⚙️ DevOps & Quality

| | Technology | Details |
|:---:|---|---|
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/python/python-original.svg" width="20"/> | **Python 3.13** | Modern runtime |
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/pytest/pytest-original.svg" width="20"/> | **pytest** | 813 tests, 50 test files |
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/github/github-original.svg" width="20"/> | **GitHub Actions** | Lint / test / build CI |
| 🐳 | **Docker** | Containerization (planned) |
| 📋 | **uv** | Dependency resolution & locks |
| 🔍 | **Ruff** | Linting & formatting |

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

> 📖 See [ARCHITECTURE.md](docs/ARCHITECTURE.md) for layer separation, design decisions, and the deterministic/workflow boundary.

---

## 📁 Repository Structure

```
trafficmind/
│
├── 🔧  apps/
│   ├── api/                 # FastAPI backend (routes, schemas, services, ORM, migrations)
│   ├── workflow/            # LangGraph cold-path workflow service
│   └── web/                 # Future canonical web app location
│
├── 🧠  services/
│   ├── vision/              # Detection (Detector ABC → YOLO, Plate backends)
│   ├── tracking/            # Tracking (Tracker ABC → ByteTrack, IoU, Centroid backends)
│   ├── ocr/                 # Plate OCR (OcrEngine ABC → PaddleOCR backend)
│   ├── signals/             # Traffic-light classification (HSV + temporal smoothing)
│   ├── rules/               # Deterministic rule engine (11 rule types)
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
├── 🖥   frontend/            # Next.js 16 operations dashboard
├── 📦  packages/
│   └── shared_types/        # Cross-boundary type contracts (BBox, ObjectCategory, enums, events)
│
├── 🏗   infra/
│   ├── docker/              # Docker assets
│   └── scripts/             # Automation (run_checks, render_env, doctor)
│
├── 🗃   alembic/             # 13 database migration revisions
├── 📚  docs/                 # 17 documentation pages
├── 🧪  tests/               # 813 tests · 50 test files · 15+ modules
└── 🤖  models/              # ML model weights (gitignored)
```

---

## 🎯 Perception Pipeline (Hot Path)

The hot-path perception pipeline composes pluggable backends into a single deterministic `process_frame()` loop:

```
  📹 Frame In  →  🎯 Detect  →  📍 Track  →  🔤 OCR  →  🚦 Classify  →  📏 Evaluate Rules  →  📸 Package Evidence
```

<table>
<tr><th>Capability</th><th>Module</th><th>Backends</th><th>Status</th></tr>
<tr><td>🎯 Object Detection</td><td><code>services/vision/</code></td><td>YOLO v8 · Plate Heuristic</td><td><img src="https://img.shields.io/badge/-2_backends-brightgreen?style=flat-square"/></td></tr>
<tr><td>📍 Multi-Object Tracking</td><td><code>services/tracking/</code></td><td>ByteTrack · IoU · Centroid</td><td><img src="https://img.shields.io/badge/-3_backends-brightgreen?style=flat-square"/></td></tr>
<tr><td>🔤 License Plate OCR</td><td><code>services/ocr/</code></td><td>PaddleOCR + normalization</td><td><img src="https://img.shields.io/badge/-Implemented-brightgreen?style=flat-square"/></td></tr>
<tr><td>🚦 Traffic-Light State</td><td><code>services/signals/</code></td><td>HSV voting + temporal smoothing</td><td><img src="https://img.shields.io/badge/-Implemented-brightgreen?style=flat-square"/></td></tr>
<tr><td>📏 Rule Evaluation</td><td><code>services/rules/</code></td><td>11 deterministic rule types</td><td><img src="https://img.shields.io/badge/-Implemented-brightgreen?style=flat-square"/></td></tr>
<tr><td>🏎 Speed Estimation</td><td><code>services/motion/</code></td><td>Calibration-aware, 3 tiers</td><td><img src="https://img.shields.io/badge/-Implemented-brightgreen?style=flat-square"/></td></tr>
<tr><td>🚗 Dwell Analysis</td><td><code>services/dwell/</code></td><td>Parking, bus-stop, stalled</td><td><img src="https://img.shields.io/badge/-Implemented-brightgreen?style=flat-square"/></td></tr>
<tr><td>📊 Lane Analytics</td><td><code>services/flow/</code></td><td>Occupancy, queues, congestion</td><td><img src="https://img.shields.io/badge/-Implemented-brightgreen?style=flat-square"/></td></tr>
<tr><td>🔥 Hotspot Analytics</td><td><code>services/hotspot/</code></td><td>Ranking, heatmap, trends</td><td><img src="https://img.shields.io/badge/-Implemented-brightgreen?style=flat-square"/></td></tr>
<tr><td>🔄 Cross-Camera Re-ID</td><td><code>services/reid/</code></td><td>Entity association + review</td><td><img src="https://img.shields.io/badge/-Foundation-blue?style=flat-square"/></td></tr>
<tr><td>📹 Stream Orchestration</td><td><code>services/streams/</code></td><td>Worker lifecycle, metrics</td><td><img src="https://img.shields.io/badge/-Implemented-brightgreen?style=flat-square"/></td></tr>
<tr><td>📸 Evidence Packaging</td><td><code>services/evidence/</code></td><td>Deterministic frame selection</td><td><img src="https://img.shields.io/badge/-Implemented-brightgreen?style=flat-square"/></td></tr>
<tr><td>🔒 Privacy & Redaction</td><td><code>services/evidence/</code></td><td>Role-based, plate masking</td><td><img src="https://img.shields.io/badge/-Implemented-brightgreen?style=flat-square"/></td></tr>
<tr><td>📋 Model Provenance</td><td><code>services/model_registry/</code></td><td>Versioned runtime bundles</td><td><img src="https://img.shields.io/badge/-Implemented-brightgreen?style=flat-square"/></td></tr>
</table>

> **🔌 Pluggable Backends** — Both detector and tracker abstractions use an ABC + registry pattern. New backends (e.g. RT-DETR, custom ANPR model) can be registered without modifying existing code.

---

## ⚡ Backend API

**15+ endpoint groups** powering the full traffic operations lifecycle:

| Endpoint Group | Routes | Description |
|:---:|---|---|
| 📷 | **Cameras & Streams** `/cameras`, `/streams` | CRUD, health, video source registration |
| 🔗 | **Junctions** `/junctions` | Junction entity CRUD, camera grouping |
| 🎯 | **Detection Events** `/events` | Paginated search with 14+ filters |
| ⚠️ | **Violations** `/violations` | Search by type/severity/status, review workflow |
| 🔤 | **Plate Search** `/plates` | ANPR lookup, normalization-aware matching |
| 📋 | **Watchlists** `/watchlist` | Entry CRUD, plate matching alerts |
| 📸 | **Evidence** `/{type}/{id}/evidence` | Manifest build and retrieval |
| 📊 | **Analytics** `/analytics/hotspots` | Spatial ranking, trends, heatmaps |
| 📈 | **Summary Totals** `/events/summary`, `/violations/summary` | Dashboard stat aggregations |
| 🩺 | **Observability** `/observability/dashboard` | Camera/stream health dashboard |
| 🔔 | **Alerts** `/alerts` | Routing, escalation, delivery dispatch |
| 📦 | **Case Export** `/exports` | JSON bundles, markdown, zip-manifest |
| 🤖 | **Model Registry** `/model-registry` | Runtime bundle tracking, provenance |
| 🔐 | **Access Policy** `/access/policy` | Role-to-permission matrix |
| 💚 | **Health** `/health/ready` | Startup & readiness probes |
| 🏭 | **Jobs** `/jobs` | Stream job management |

---

## 🦜 Cold-Path Workflows

Seven LangGraph-powered workflow graphs operating exclusively over stored records:

| # | Workflow | Description | Status |
|:---:|---|---|:---:|
| 1 | 🔍 **Incident Triage** | Automated incident classification and routing | ✅ |
| 2 | ✅ **Violation Review** | Human-in-the-loop violation confirmation | ✅ |
| 3 | 🤖 **Multimodal Review Copilot** | Grounded advisory analysis of evidence | ✅ |
| 4 | 📅 **Daily Summary** | Automated daily operations report | ✅ |
| 5 | 📆 **Weekly Summary** | Automated weekly trend report | ✅ |
| 6 | 🔥 **Hotspot Report** | Spatial concentration analysis | ✅ |
| 7 | 💬 **Operator Assist** | Retrieval-first natural language investigation | ✅ |

> 🧠 The workflow service uses a deterministic heuristic provider. The provider boundary is explicit — model-backed providers can be swapped in without modifying graph definitions.

---

## 🖥 Frontend

The **Next.js 16** operations dashboard provides a map-first view of the camera network with real-time data:

| Feature | Status | Details |
|---|:---:|---|
| 🗺️ Map-first operations dashboard | ✅ | Camera markers, junction grouping, hotspot overlays |
| 📷 Camera detail and stream view | ✅ | Status, metadata, linked events |
| 🎯 Live event and violation feeds | ✅ | Real paginated data from `GET /events/` and `GET /violations/` |
| 🔍 Feed filters and pagination | ✅ | Type, status, time presets, camera scope, offset pagination |
| 📊 Summary totals and breakdowns | ✅ | By-status, by-severity, by-type aggregations |
| 🔗 Junction-level camera grouping | ✅ | Derived from location names, multi-camera intersections |
| 📊 Hotspot and spatial analytics | ✅ | Backed by persisted hotspot analytics when available |
| 📈 Evaluation benchmark summaries | ✅ | Detection, tracking, OCR, rule, workflow metrics |
| ⚠️ Violation review UI | 🔜 | Planned |
| 📊 Analytics charts | 🚧 | In progress |

---

## 📏 Rules Engine

**11 deterministic rule types** evaluated against tracked objects and zone geometry:

| Rule Type | Confirmation | Evidence Strategy |
|---|:---:|---|
| 🔴 Red-light crossing | Multi-frame ✅ | Pre + post violation frames |
| 🚶 Pedestrian on red | Multi-frame ✅ | Trajectory evidence |
| 🛑 Stop-line crossing | Multi-frame ✅ | Approach + violation frames |
| ↩️ Wrong-way travel | — | Direction vector evidence |
| ➖ Line crossing | — | Crossing geometry |
| 🚧 Zone entry | — | Zone boundary breach |
| ⏱ Zone dwell time | Duration-based | Timestamped occupancy |
| 🅿️ Illegal parking | Duration-based | Timestamped occupancy |
| 🚫 No stopping | Duration-based | Timestamped occupancy |
| 🚌 Bus stop occupation | Duration-based | Timestamped occupancy |
| 🚗 Stalled vehicle | Duration-based | Timestamped occupancy |

> 🔬 **Flagship rules** (red-light, pedestrian-on-red, stop-line) hold pre-violation candidates until sufficient post-event evidence accumulates. Unknown or stale signal state does not generate candidates.

---

## 🗄 Data Layer

<div align="center">

| 📊 ORM Models | 🔄 Migrations | 📦 Enum Types | 🔗 Shared Contracts |
|:---:|:---:|:---:|:---:|
| **23** SQLAlchemy models | **13** Alembic revisions | **33** StrEnum types | `packages/shared_types/` |

</div>

---

## 🚀 Quick Start

### Prerequisites

| Requirement | Version | Notes |
|:---:|:---:|---|
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

> 📖 See [LOCAL_DEVELOPMENT.md](docs/LOCAL_DEVELOPMENT.md) for the full setup guide, environment variables, and troubleshooting.

---

## 🧪 Testing

<div align="center">

[![Tests](https://img.shields.io/badge/Tests-813_passed-brightgreen?style=for-the-badge&logo=pytest&logoColor=white)](#)
[![Test Files](https://img.shields.io/badge/Test_Files-50-blue?style=for-the-badge)](#)
[![Modules](https://img.shields.io/badge/Modules-15+-orange?style=for-the-badge)](#)

</div>

```bash
# 🧪 Full suite
python -m pytest tests/ -q

# 🎯 Specific module
python -m pytest tests/rules/ -v

# 📊 With coverage report
python -m pytest tests/ --cov=apps --cov=services --cov-report=term-missing

# 🏁 Golden-path regression (DB → pipeline → API → workflow → frontend build)
python infra/scripts/run_checks.py --suite golden-path
```

<details>
<summary><strong>📊 Test Coverage by Module (click to expand)</strong></summary>

<br/>

| Module | Coverage Area |
|---|---|
| 📏 `tests/rules/` | Rule evaluation, flagship temporal rules, fixture-driven progression |
| 📍 `tests/tracking/` | IoU, centroid, ByteTrack backends, lifecycle, multi-object, direction |
| 🎯 `tests/vision/` | Detection schemas, registry, plate detector, YOLO integration |
| 📊 `tests/flow/` | Lane occupancy, queue, congestion, utilization analytics |
| 🔥 `tests/hotspot/` | Aggregation, trends, severity weighting, recurring issues |
| 🚦 `tests/signals/` | Signal classifier, state tracker, HSV pipeline |
| 📹 `tests/streams/` | Integrated pipeline, worker lifecycle, backpressure |
| 🏎 `tests/motion/` | Speed estimation, direction labeling, calibration tiers |
| 🔤 `tests/ocr/` | OCR service, normalization |
| 🩺 `tests/health/` | Camera health assessor, alert thresholds |
| ⚡ `tests/api/` | Camera, junction, event, violation, alert, export, delivery, summary endpoints |
| 🦜 `tests/workflow/` | All 7 LangGraph workflows, interrupt/resume, NL planner |
| 🔌 `tests/integrations/` | Adapter builders, local sinks, object storage, signal bridge |
| 📈 `tests/evaluation/` | Benchmark foundation, metrics edge cases |
| 💨 `tests/smoke/` | Golden-path operator flow, E2E persistence |

</details>

---

## 🎭 Demo Mode

Demo mode seeds the local database with realistic synthetic data for development, screenshots, and walkthroughs. **It does not replay production data or fabricate benchmark results.**

<div align="center">

`3 cameras` · `4 streams` · `5 zones` · `4 detection events` · `3 plate reads` · `3 violations` · `3 evidence manifests` · `3 workflows`

</div>

| Marker | Where | Purpose |
|:---:|---|---|
| `DEMO-` prefix | Camera codes | Identify synthetic cameras |
| `source_type=test` | All demo streams | Distinguish from real sources |
| `demo://` scheme | All asset URIs | Prevent accidental storage lookups |
| `mode=demo_seed` | All metadata | Full audit traceability |

> 🔁 Demo data is clearly distinguishable from real processed data at every layer. The seeder is **idempotent** — rerunning replaces existing demo records without duplicating.

---

## 📚 Documentation

| Document | Description |
|:---:|---|
| 📐 [ARCHITECTURE.md](docs/ARCHITECTURE.md) | System layers, design decisions, deterministic boundary |
| 🛠 [LOCAL_DEVELOPMENT.md](docs/LOCAL_DEVELOPMENT.md) | Full setup guide, env vars, database, frontend |
| 🚀 [DEPLOYMENT.md](docs/DEPLOYMENT.md) | Env profiles, readiness checks, CI scope, secrets |
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
|---|:---:|:---:|
| 🏗  Repository structure & architecture | ✅ Complete | ![100%](https://img.shields.io/badge/-100%25-brightgreen?style=flat-square) |
| ⚡  API & workflow foundations | ✅ Complete | ![100%](https://img.shields.io/badge/-100%25-brightgreen?style=flat-square) |
| 🧠  Deterministic vision services | ✅ Complete | ![100%](https://img.shields.io/badge/-100%25-brightgreen?style=flat-square) |
| 📋  Event & review platform | ✅ Complete | ![100%](https://img.shields.io/badge/-100%25-brightgreen?style=flat-square) |
| 🔌  Enterprise integration adapters | ✅ Complete | ![100%](https://img.shields.io/badge/-100%25-brightgreen?style=flat-square) |
| 🔗  Explicit junction entity | ✅ Complete | ![100%](https://img.shields.io/badge/-100%25-brightgreen?style=flat-square) |
| 🎯  Pluggable backend validation | ✅ Complete | ![100%](https://img.shields.io/badge/-100%25-brightgreen?style=flat-square) |
| 🖥  Web product (dashboard, review UI) | 🚧 In progress | ![70%](https://img.shields.io/badge/-70%25-yellow?style=flat-square) |
| 🚀  Production hardening (CI/CD, containers) | 🚧 In progress | ![50%](https://img.shields.io/badge/-50%25-yellow?style=flat-square) |
| 🤖  Model maturity (plate detector, signal model) | 📝 Planned | ![15%](https://img.shields.io/badge/-15%25-lightgrey?style=flat-square) |

---

<div align="center">

## 📄 License

**Private repository. All rights reserved.**

---

<sub>Built with ❤️ using Python, FastAPI, Next.js, PyTorch, and LangGraph</sub>

<br/>

[![Python](https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white)](#)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](#)
[![Next.js](https://img.shields.io/badge/Next.js-000?style=flat-square&logo=next.js&logoColor=white)](#)
[![React](https://img.shields.io/badge/React-61DAFB?style=flat-square&logo=react&logoColor=black)](#)
[![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=flat-square&logo=typescript&logoColor=white)](#)
[![PyTorch](https://img.shields.io/badge/PyTorch-EE4C2C?style=flat-square&logo=pytorch&logoColor=white)](#)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=flat-square&logo=postgresql&logoColor=white)](#)
[![Tailwind](https://img.shields.io/badge/Tailwind-06B6D4?style=flat-square&logo=tailwindcss&logoColor=white)](#)

</div>
