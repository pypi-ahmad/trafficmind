<div align="center">

<!-- Hero Banner -->
<br/>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://img.shields.io/badge/%F0%9F%9A%A6-TrafficMind-ffffff?style=for-the-badge&labelColor=0d1117&color=16213e" height="65">
  <img src="https://img.shields.io/badge/%F0%9F%9A%A6-TrafficMind-1a1a2e?style=for-the-badge&labelColor=0d1117&color=16213e" height="65"/>
</picture>

<br/><br/>

**Unified Traffic Intelligence Platform**

<p>
<em>From raw video frames to operator-ready violation evidence — detection, tracking, OCR, rule evaluation, workflow triage, and spatial analytics in one monorepo.</em>
</p>

<br/>

<!-- Primary Tech Stack Badges -->
[![Python 3.13](https://img.shields.io/badge/Python-3.13-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Next.js 16](https://img.shields.io/badge/Next.js_16-000000?style=for-the-badge&logo=next.js&logoColor=white)](https://nextjs.org)
[![React 19](https://img.shields.io/badge/React_19-61DAFB?style=for-the-badge&logo=react&logoColor=black)](https://react.dev)
[![TypeScript 5](https://img.shields.io/badge/TypeScript_5-3178C6?style=for-the-badge&logo=typescript&logoColor=white)](https://typescriptlang.org)
[![PyTorch](https://img.shields.io/badge/PyTorch-EE4C2C?style=for-the-badge&logo=pytorch&logoColor=white)](https://pytorch.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)](https://postgresql.org)
[![SQLAlchemy 2](https://img.shields.io/badge/SQLAlchemy_2-D71F00?style=for-the-badge&logo=sqlalchemy&logoColor=white)](https://sqlalchemy.org)
[![Tailwind CSS 4](https://img.shields.io/badge/Tailwind_4-06B6D4?style=for-the-badge&logo=tailwindcss&logoColor=white)](https://tailwindcss.com)
[![LangGraph](https://img.shields.io/badge/%F0%9F%A6%9C_LangGraph-1C3C3C?style=for-the-badge)](https://langchain-ai.github.io/langgraph/)

<br/>

<!-- Navigation -->
<a href="#-quick-start"><img src="https://img.shields.io/badge/%F0%9F%9A%80_Quick_Start-Guide-2ea44f?style=flat-square" alt="Quick Start"/></a>&nbsp;
<a href="#-architecture"><img src="https://img.shields.io/badge/%F0%9F%8F%97_Architecture-Overview-blue?style=flat-square" alt="Architecture"/></a>&nbsp;
<a href="#-testing"><img src="https://img.shields.io/badge/%F0%9F%A7%AA_Testing-Suite-brightgreen?style=flat-square&logo=pytest&logoColor=white" alt="Tests"/></a>&nbsp;
<a href="#-documentation"><img src="https://img.shields.io/badge/%F0%9F%93%9A_Docs-17_guides-mediumpurple?style=flat-square" alt="Docs"/></a>

<!-- Metric Badges -->
<br/><br/>
<img src="https://img.shields.io/badge/ORM_Models-23-0969da?style=flat-square" alt="Models"/>
<img src="https://img.shields.io/badge/Migrations-13-0969da?style=flat-square" alt="Migrations"/>
<img src="https://img.shields.io/badge/Test_Files-50-brightgreen?style=flat-square" alt="Test Files"/>
<img src="https://img.shields.io/badge/Rule_Types-11-orange?style=flat-square" alt="Rules"/>
<img src="https://img.shields.io/badge/Workflows-7-8957e5?style=flat-square" alt="Workflows"/>
<img src="https://img.shields.io/badge/API_Routes-16-0969da?style=flat-square" alt="Routes"/>
<img src="https://img.shields.io/badge/Services-21-e8590c?style=flat-square" alt="Services"/>
<img src="https://img.shields.io/badge/Shared_Types-31-9333ea?style=flat-square" alt="Shared Types"/>

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
- [Perception Pipeline](#-perception-pipeline-hot-path)
- [Backend API](#-backend-api)
- [Cold-Path Workflows](#-cold-path-workflows)
- [Frontend](#-frontend)
- [Rules Engine](#-rules-engine)
- [Shared Types](#-shared-types)
- [Data Layer](#-data-layer)
- [Quick Start](#-quick-start)
- [Testing](#-testing)
- [Demo Mode](#-demo-mode)
- [Documentation](#-documentation)
- [Usage Guide](#-usage-guide)
- [Limitations](#-limitations)
- [License](#-license)

</details>

---

## 💡 Why TrafficMind

<table>
<tr>
<td width="58%">

Urban traffic enforcement requires processing high-volume video feeds, detecting violations with temporal evidence, reading license plates, and routing incidents to human reviewers with structured evidence.

**TrafficMind provides all of this in a single monorepo with clear boundaries between deterministic inference and cold-path post-processing.**

The system is split into two clearly separated runtime paths:

| | 🔥 **Hot Path** | 🧊 **Cold Path** |
|:---:|---|---|
| **Purpose** | Frame-by-frame perception & rule evaluation | Post-hoc triage, review & reporting |
| **Runtime** | Detect → Track → OCR → Signals → Rules | LangGraph workflows over stored records |
| **Guarantees** | Deterministic · No network I/O · No DB writes per-frame | Grounded exclusively over persisted data |
| **Latency** | Real-time (per-frame) | Async / operator-triggered |

</td>
<td width="42%">

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

---

## 🛠 Tech Stack

<table>
<tr>
<td width="50%">

### 🔧 Backend & Infrastructure

| | Technology | Details |
|:---:|---|---|
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/fastapi/fastapi-original.svg" width="18"/> | **FastAPI** | Async API · Pydantic v2 validation |
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/sqlalchemy/sqlalchemy-original.svg" width="18"/> | **SQLAlchemy 2** | Async ORM · 23 models |
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/postgresql/postgresql-original.svg" width="18"/> | **PostgreSQL** | Production data store |
| <img src="https://img.shields.io/badge/-SQLite-003B57?style=flat&logo=sqlite&logoColor=white" height="14"/> | **SQLite** | Local dev / CI |
| 🔄 | **Alembic** | 13 migration revisions |
| 🦜 | **LangGraph** | 7 cold-path workflow graphs |
| 📦 | **Pydantic v2** | 31 shared type contracts |

</td>
<td width="50%">

### 🖥 Frontend & UI

| | Technology | Details |
|:---:|---|---|
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/nextjs/nextjs-original.svg" width="18"/> | **Next.js 16** | App Router · SSR · RSC |
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/react/react-original.svg" width="18"/> | **React 19** | Server Components |
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/typescript/typescript-original.svg" width="18"/> | **TypeScript 5** | Strict types end-to-end |
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/tailwindcss/tailwindcss-original.svg" width="18"/> | **Tailwind CSS 4** | Utility-first styling |
| 🗺️ | **MapLibre GL** | Spatial operations map |

</td>
</tr>
<tr>
<td width="50%">

### 🧠 Computer Vision & ML

| | Technology | Details |
|:---:|---|---|
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/pytorch/pytorch-original.svg" width="18"/> | **PyTorch 2.11** | CUDA-accelerated inference |
| 🎯 | **Ultralytics YOLO** | Object detection backends |
| 👁️ | **Supervision** | ByteTrack multi-object tracking |
| 🔤 | **PaddleOCR 3.4** | License plate recognition |
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/opencv/opencv-original.svg" width="18"/> | **OpenCV 4.13** | Image processing |
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/numpy/numpy-original.svg" width="18"/> | **NumPy** | Array operations |

</td>
<td width="50%">

### ⚙️ DevOps & Quality

| | Technology | Details |
|:---:|---|---|
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/python/python-original.svg" width="18"/> | **Python 3.13** | Modern runtime |
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/pytest/pytest-original.svg" width="18"/> | **pytest** | 50 test files · 80% coverage floor |
| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/github/github-original.svg" width="18"/> | **GitHub Actions** | Lint · test · build CI |
| 🐳 | **Docker** | Containerization (reserved, not yet shipped) |
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
├── 🔧 apps/
│   ├── api/                  FastAPI backend — routes, schemas, services, ORM, migrations
│   ├── workflow/             LangGraph cold-path workflow service
│   └── web/                  Future canonical web app location
│
├── 🧠 services/
│   ├── vision/               Detection (Detector ABC → YOLO, Plate backends)
│   ├── tracking/             Tracking (Tracker ABC → ByteTrack, IoU, Centroid)
│   ├── ocr/                  Plate OCR (OcrEngine ABC → PaddleOCR)
│   ├── signals/              Traffic-light classification (HSV + smoothing)
│   ├── rules/                Deterministic rule engine — 11 rule types
│   ├── motion/               Speed estimation, direction labeling
│   ├── flow/                 Lane occupancy, queue detection, congestion
│   ├── dwell/                Vehicle dwell-time analytics
│   ├── streams/              Stream ingestion, worker lifecycle, frame pipeline
│   ├── anpr/                 Plate search, normalization, watchlist helpers
│   ├── events/               Detection-event search
│   ├── violations/           Violation search
│   ├── evidence/             Evidence packaging + privacy/redaction
│   ├── integrations/         Enterprise adapters + local sinks
│   ├── model_registry/       Runtime model/config provenance
│   ├── health/               Camera/stream health assessment
│   ├── hotspot/              Spatial trend analytics and ranking
│   ├── reid/                 Cross-camera re-identification
│   └── evaluation/           Fixture-driven benchmarking
│
├── 🖥  frontend/              Next.js 16 operations dashboard
│
├── 📦 packages/
│   └── shared_types/         Cross-boundary contracts — geometry, enums, events, scene
│
├── 🏗  infra/
│   ├── docker/               Container assets
│   └── scripts/              Automation — run_checks, render_env, doctor, local_smoke
│
├── 🗃  alembic/               13 database migration revisions
├── 📚 docs/                  17 documentation guides
├── 🧪 tests/                 50 test files · 15+ modules
└── 🤖 models/                ML model weights (gitignored)
```

---

## 🎯 Perception Pipeline (Hot Path)

The hot-path perception pipeline composes pluggable backends into a single deterministic `process_frame()` loop:

```
  📹 Frame In  →  🎯 Detect  →  📍 Track  →  🔤 OCR  →  🚦 Classify  →  📏 Evaluate Rules  →  📸 Evidence
```

<table>
<tr><th>Capability</th><th>Module</th><th>Backends</th><th>Status</th></tr>
<tr><td>🎯 Object Detection</td><td><code>services/vision/</code></td><td>YOLO · Plate Heuristic</td><td><img src="https://img.shields.io/badge/-2_backends-brightgreen?style=flat-square"/></td></tr>
<tr><td>📍 Multi-Object Tracking</td><td><code>services/tracking/</code></td><td>ByteTrack · IoU · Centroid</td><td><img src="https://img.shields.io/badge/-3_backends-brightgreen?style=flat-square"/></td></tr>
<tr><td>🔤 License Plate OCR</td><td><code>services/ocr/</code></td><td>PaddleOCR + normalization</td><td><img src="https://img.shields.io/badge/-Implemented-brightgreen?style=flat-square"/></td></tr>
<tr><td>🚦 Traffic-Light State</td><td><code>services/signals/</code></td><td>HSV voting + temporal smoothing</td><td><img src="https://img.shields.io/badge/-Implemented-brightgreen?style=flat-square"/></td></tr>
<tr><td>📏 Rule Evaluation</td><td><code>services/rules/</code></td><td>11 deterministic rule types</td><td><img src="https://img.shields.io/badge/-11_rules-brightgreen?style=flat-square"/></td></tr>
<tr><td>🏎 Speed Estimation</td><td><code>services/motion/</code></td><td>Calibration-aware · 3 quality tiers</td><td><img src="https://img.shields.io/badge/-Implemented-brightgreen?style=flat-square"/></td></tr>
<tr><td>🚗 Dwell Analysis</td><td><code>services/dwell/</code></td><td>Parking · bus-stop · stalled</td><td><img src="https://img.shields.io/badge/-Implemented-brightgreen?style=flat-square"/></td></tr>
<tr><td>📊 Lane Analytics</td><td><code>services/flow/</code></td><td>Occupancy · queues · congestion</td><td><img src="https://img.shields.io/badge/-Implemented-brightgreen?style=flat-square"/></td></tr>
<tr><td>🔥 Hotspot Analytics</td><td><code>services/hotspot/</code></td><td>Ranking · heatmap · trends</td><td><img src="https://img.shields.io/badge/-Implemented-brightgreen?style=flat-square"/></td></tr>
<tr><td>🔄 Cross-Camera Re-ID</td><td><code>services/reid/</code></td><td>Entity association + review</td><td><img src="https://img.shields.io/badge/-Foundation-blue?style=flat-square"/></td></tr>
<tr><td>📹 Stream Orchestration</td><td><code>services/streams/</code></td><td>Worker lifecycle · metrics</td><td><img src="https://img.shields.io/badge/-Implemented-brightgreen?style=flat-square"/></td></tr>
<tr><td>📸 Evidence Packaging</td><td><code>services/evidence/</code></td><td>Deterministic frame selection</td><td><img src="https://img.shields.io/badge/-Implemented-brightgreen?style=flat-square"/></td></tr>
<tr><td>🔒 Privacy & Redaction</td><td><code>services/evidence/</code></td><td>Role-based · plate masking</td><td><img src="https://img.shields.io/badge/-Implemented-brightgreen?style=flat-square"/></td></tr>
<tr><td>📋 Model Provenance</td><td><code>services/model_registry/</code></td><td>Versioned runtime bundles</td><td><img src="https://img.shields.io/badge/-Implemented-brightgreen?style=flat-square"/></td></tr>
</table>

> **🔌 Pluggable Backends** — Both detector and tracker use an ABC + registry pattern. New backends (e.g. RT-DETR, custom ANPR model) can be registered without modifying existing code.

---

## ⚡ Backend API

**16 endpoint groups** powering the full traffic operations lifecycle:

| | Endpoint Group | Routes | Description |
|:---:|---|---|---|
| 📷 | **Cameras & Streams** | `/cameras` `/streams` | CRUD · health · video source registration |
| 🔗 | **Junctions** | `/junctions` | Junction entity CRUD · camera grouping |
| 🎯 | **Detection Events** | `/events` | Paginated search · 14+ filters |
| ⚠️ | **Violations** | `/violations` | Search by type/severity/status · review |
| 📈 | **Summary Totals** | `/events/summary` `/violations/summary` | Dashboard stat aggregations |
| 🔤 | **Plate Search** | `/plates` | ANPR lookup · normalization-aware matching |
| 📋 | **Watchlists** | `/watchlist` | Entry CRUD · plate matching alerts |
| 📸 | **Evidence** | `/{type}/{id}/evidence` | Manifest build and retrieval |
| 📊 | **Analytics** | `/analytics/hotspots` | Spatial ranking · trends · heatmaps |
| 🩺 | **Observability** | `/observability/dashboard` | Camera/stream health dashboard |
| 🔔 | **Alerts** | `/alerts` | Routing · escalation · delivery dispatch |
| 📦 | **Case Export** | `/exports` | JSON bundles · markdown · zip-manifest |
| 🤖 | **Model Registry** | `/model-registry` | Runtime bundle tracking · provenance |
| � | **Signals** | `/signals` | Traffic signal integration · controller events |
| �🔐 | **Access Policy** | `/access/policy` | Role-to-permission matrix |
| 💚 | **Health** | `/health/ready` | Startup & readiness probes |
| 🏭 | **Jobs** | `/jobs` | Stream job management |

---

## 🦜 Cold-Path Workflows

Seven LangGraph-powered workflow graphs operating exclusively over stored records:

| # | Workflow | Description | Status |
|:---:|---|---|:---:|
| 1 | 🔍 **Incident Triage** | Automated incident classification and routing | ✅ |
| 2 | ✅ **Violation Review** | Human-in-the-loop violation confirmation | ✅ |
| 3 | 🤖 **Multimodal Review** | Grounded advisory analysis of evidence | ✅ |
| 4 | 📅 **Daily Summary** | Automated daily operations report | ✅ |
| 5 | 📆 **Weekly Summary** | Automated weekly trend report | ✅ |
| 6 | 🔥 **Hotspot Report** | Spatial concentration analysis | ✅ |
| 7 | 💬 **Operator Assist** | Retrieval-first natural language investigation | ✅ |

Additionally, `POST /runs/{run_id}/resume` resumes a paused workflow run (used for human-in-the-loop gates).

> 🧠 The workflow service uses a deterministic heuristic provider. The provider boundary is explicit — model-backed providers can be swapped in without modifying graph definitions.

---

## 🖥 Frontend

The **Next.js 16** operations dashboard provides a map-first view of the camera network:

| Feature | Status | Details |
|---|:---:|---|
| 🗺️ Map-first operations dashboard | ✅ | Camera markers · junction grouping · hotspot overlays |
| 📷 Camera detail and stream view | ✅ | Status · metadata · linked events |
| 🎯 Event and violation feeds | ✅ | Real paginated data from `GET /events` and `GET /violations` |
| 🔍 Feed filters and pagination | ✅ | Type · status · time presets · camera scope |
| 📊 Summary totals and breakdowns | ✅ | By-status · by-severity · by-type aggregations |
| 🔗 Junction-level camera grouping | ✅ | Derived from location names · multi-camera intersections |
| 📊 Hotspot and spatial analytics | ✅ | Backed by persisted hotspot analytics when available |
| 📈 Evaluation benchmark summaries | ✅ | Detection · tracking · OCR · rule · signal metrics |
| ⚠️ Violation review UI | ✅ | Confirm / dismiss with operator name and review note |
| 🔔 Operational alerts | ✅ | Filter by status · severity · source · Acknowledge and Resolve actions |
| 📦 Case export listing | ✅ | Filter by status · subject type (read-only) |
| ⚙️ Settings and access policy | ✅ | Active policy and role display |
| ❓ Operator help & glossary | ✅ | Navigation guide · glossary · severity levels · common tasks |

---

## 📏 Rules Engine

**11 deterministic rule types** evaluated against tracked objects and zone geometry:

| Rule Type | Confirmation | Evidence Strategy |
|---|:---:|---|
| 🔴 Red-light crossing | Multi-frame ✅ | Pre + post violation frames |
| 🚶 Pedestrian on red | Multi-frame ✅ | Trajectory evidence |
| 🛑 Stop-line crossing | Multi-frame ✅ | Approach + violation frames |
| ↩️ Wrong-way travel | Instant | Direction vector evidence |
| ➖ Line crossing | Instant | Crossing geometry |
| 🚧 Zone entry | Instant | Zone boundary breach |
| ⏱ Zone dwell time | Duration-based | Timestamped occupancy |
| 🅿️ Illegal parking | Duration-based | Timestamped occupancy |
| 🚫 No stopping | Duration-based | Timestamped occupancy |
| 🚌 Bus stop occupation | Duration-based | Timestamped occupancy |
| 🚗 Stalled vehicle | Duration-based | Timestamped occupancy |

> 🔬 **Flagship rules** (red-light, pedestrian-on-red, stop-line) hold pre-violation candidates until sufficient post-event evidence accumulates. Unknown or stale signal state does not generate candidates.

---

## 📦 Shared Types

Cross-boundary type contracts live in `packages/shared_types/` — the single source of truth for types that cross service boundaries:

| Module | Contents | Consumers |
|---|---|---|
| `enums.py` | 13 StrEnum types — zone · event · violation · rule · re-id · source · workflow | API ORM · rules · tracking · streams · workflow · reid |
| `geometry.py` | `BBox` · `Point2D` · `ObjectCategory` · `LineSegment` · `PolygonZone` | Vision · tracking · OCR · rules · signals · flow · motion · dwell |
| `scene.py` | `SceneContext` · `TrafficLightState` · `SignalPhase` · signal state types | Signals · rules · streams |
| `events.py` | `ViolationRecord` · `PreViolationRecord` · `Explanation` · `RuleEvaluationResult` | Rules · streams · API persistence |

> 📖 See [packages/shared_types/README.md](packages/shared_types/README.md) for governance rules on what belongs here vs. what stays in service-local schemas.

---

## 🗄 Data Layer

<div align="center">

| 📊 ORM Models | 🔄 Migrations | 📦 Shared Enums | 🏠 Local Enums | 🔗 Type Contracts |
|:---:|:---:|:---:|:---:|:---:|
| **23** models | **13** revisions | **13** cross-cutting | **20** domain-scoped | **31** in `shared_types` |

</div>

---

## 🚀 Quick Start

### Golden Path (Local)

| Requirement | Version | Notes |
|:---:|:---:|---|
| 🐍 Python | 3.12+ (3.13 recommended) | Core runtime |
| 📦 Node.js | 22+ | Frontend build |
| 🎮 CUDA GPU | Optional | Not required for the documented smoke path |

Run these commands in order from the repo root:

```bash
# 1️⃣  Clone and enter the repository
git clone https://github.com/pypi-ahmad/trafficmind.git
cd trafficmind

# 2️⃣  Create and activate a Python virtual environment
python -m venv .venv
.venv\Scripts\activate           # Windows
source .venv/bin/activate         # Linux / macOS

# 3️⃣  Install Python dependencies
pip install -r requirements-dev.lock
pip install --no-deps -e .

# 4️⃣  (Optional) Add CV extras for stream inference or local model work
pip install -e ".[cv]"

# 5️⃣  Install frontend dependencies
cd frontend
npm ci
cd ..

# 6️⃣  Render local env files for Python services and Next.js
python infra/scripts/render_env.py --profile local --output .env --frontend-output frontend/.env.local --force

# 7️⃣  Run database migrations
alembic upgrade head

# 8️⃣  Seed the demo dataset used by the live smoke path
python -m apps.api.app.demo.seed --create-schema
```

Start the services in three terminals:

```bash
# Terminal A — API
uvicorn apps.api.app.main:app --reload --port 8000

# Terminal B — Workflow
uvicorn apps.workflow.app.main:app --reload --port 8010

# Terminal C — Frontend
cd frontend && npm run dev
```

Run the live local smoke check from a fourth terminal:

```bash
python infra/scripts/local_smoke.py --env-file .env --expect-demo-data
```

Expected result:

- `api readiness` and `workflow readiness` pass
- `/cameras`, `/events`, `/violations`, and `/events/summary/totals` return live JSON
- `operator-assist` succeeds through the workflow service
- The frontend home page renders live camera content and the events page renders camera-scoped context

> 📖 See [LOCAL_DEVELOPMENT.md](docs/LOCAL_DEVELOPMENT.md) for the explicit golden path, port fallback instructions, expected outputs, and troubleshooting.

### 🎬 Additional Commands

```bash
# Heavier non-live foundation regression
python infra/scripts/run_checks.py --suite golden-path

# Demo seeding with walkthrough report
python -m apps.api.app.demo.seed --scenario city_center_baseline --report-path report.json

# Test the worker pipeline (no GPU required)
python -m services.streams --source-kind test --max-frames 60

# Evaluation suite
python -m services.evaluation tests/fixtures/evaluation/benchmark_suite.json
```

> **📦 Dependency source of truth:** `pyproject.toml` — lock files generated by `uv pip compile` and committed.

---

## 🧪 Testing

<div align="center">

[![Tests](https://img.shields.io/badge/Test_Files-50-brightgreen?style=for-the-badge&logo=pytest&logoColor=white)](#)
[![Coverage](https://img.shields.io/badge/Coverage_Floor-80%25-blue?style=for-the-badge)](#)
[![Modules](https://img.shields.io/badge/Module_Coverage-15+-orange?style=for-the-badge)](#)

</div>

```bash
# 🧪 Full suite
python -m pytest tests/ -q

# 🎯 Specific module
python -m pytest tests/rules/ -v

# 📊 With coverage
python -m pytest tests/ --cov=apps --cov=services --cov-report=term-missing

# 🏁 Golden-path regression
python infra/scripts/run_checks.py --suite golden-path

# 🌐 Live local smoke
python infra/scripts/local_smoke.py --env-file .env --expect-demo-data
```

<details>
<summary><strong>📊 Test Coverage by Module</strong></summary>

| Module | Coverage Area |
|---|---|
| 📏 `tests/rules/` | Rule evaluation · flagship temporal rules · fixture-driven progression |
| 📍 `tests/tracking/` | IoU · centroid · ByteTrack · lifecycle · multi-object · direction |
| 🎯 `tests/vision/` | Detection schemas · registry · plate detector · YOLO integration |
| 📊 `tests/flow/` | Lane occupancy · queue · congestion · utilization analytics |
| 🔥 `tests/hotspot/` | Aggregation · trends · severity weighting · recurring issues |
| 🚦 `tests/signals/` | Signal classifier · state tracker · HSV pipeline |
| 📹 `tests/streams/` | Integrated pipeline · worker lifecycle · backpressure |
| 🏎 `tests/motion/` | Speed estimation · direction labeling · calibration tiers |
| 🔤 `tests/ocr/` | OCR service · normalization |
| 🩺 `tests/health/` | Camera health assessor · alert thresholds |
| ⚡ `tests/api/` | Camera · junction · event · violation · alert · export · summary endpoints |
| 🦜 `tests/workflow/` | All 7 LangGraph workflows · interrupt/resume · NL planner |
| 🔌 `tests/integrations/` | Adapter builders · local sinks · object storage · signal bridge |
| 📈 `tests/evaluation/` | Benchmark foundation · metrics edge cases |
| 💨 `tests/smoke/` | Golden-path operator flow · E2E persistence |

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

> 🔁 Demo data is clearly distinguishable from real processed data at every layer. The seeder is **idempotent** — rerunning replaces existing demo records.

---

## 📚 Documentation

| | Document | Description |
|:---:|:---:|---|
| 📐 | [ARCHITECTURE.md](docs/ARCHITECTURE.md) | System layers · design decisions · deterministic boundary |
| 🛠 | [LOCAL_DEVELOPMENT.md](docs/LOCAL_DEVELOPMENT.md) | Full setup guide · env vars · database · golden path |
| 🚀 | [DEPLOYMENT.md](docs/DEPLOYMENT.md) | Env profiles · readiness checks · CI scope · secrets |
| 🗄 | [DATA_MODEL.md](docs/DATA_MODEL.md) | ORM models · relationships · enums · migration history |
| 🔌 | [INTEGRATIONS.md](docs/INTEGRATIONS.md) | Core product vs adapter foundations vs enterprise extensions |
| 📋 | [PROVENANCE.md](docs/PROVENANCE.md) | Model/config registry · runtime provenance · reproducibility |
| 🦜 | [WORKFLOWS.md](docs/WORKFLOWS.md) | Cold-path workflow definitions and lifecycle |
| ⚠️ | [LIMITATIONS.md](docs/LIMITATIONS.md) | Known gaps · honest constraints · extension points |
| 🩺 | [camera-health.md](docs/camera-health.md) | Health signals · alert severities · thresholds |
| 📸 | [evidence.md](docs/evidence.md) | Evidence manifest structure · asset-key conventions |
| 🔒 | [PRIVACY.md](docs/PRIVACY.md) | Privacy masking · redaction · access control |
| 🔤 | [anpr.md](docs/anpr.md) | Plate search · normalization · watchlist matching |
| 📊 | [evaluation.md](docs/evaluation.md) | Evaluation artifacts · benchmark interpretation |
| 🚦 | [SIGNAL_INTEGRATION.md](docs/SIGNAL_INTEGRATION.md) | Traffic signal state integration |
| 📹 | [WORKER_PIPELINE.md](docs/WORKER_PIPELINE.md) | Stream worker pipeline architecture |
| 📓 | [notebooks.md](docs/notebooks.md) | Colab MCP setup and local fallback |

---

## 📖 Usage Guide

For complete operational documentation — setup, configuration, page-by-page feature coverage, API reference, and troubleshooting — see **[USAGE.md](USAGE.md)**.

<details>
<summary><strong>Sections in USAGE.md</strong></summary>

| Section | Description |
|---|---|
| [Who This Is For](USAGE.md#who-this-is-for) | Intended audiences |
| [Before You Start](USAGE.md#before-you-start) | Service overview and port map |
| [Prerequisites](USAGE.md#prerequisites) | Python, Node.js, and optional GPU requirements |
| [Environment Configuration](USAGE.md#environment-configuration) | `.env` generation, frontend env, database setup |
| [Starting the Application](USAGE.md#starting-the-application) | Install, migrate, start all three services |
| [System Architecture at a Glance](USAGE.md#system-architecture-at-a-glance) | Hot path / cold path separation |
| [Frontend — Operator Interface](USAGE.md#frontend--operator-interface) | Dashboard, Cases, Alerts, Camera Detail, Evaluation, Reports, Settings, Help |
| [Backend — API Reference](USAGE.md#backend--api-reference) | Core resources, infrastructure endpoints, violation review |
| [Workflow Service](USAGE.md#workflow-service) | 8 workflow endpoints, provider and checkpoint backends |
| [Database Migrations](USAGE.md#database-migrations) | Alembic commands and migration inventory |
| [Utility Scripts](USAGE.md#utility-scripts) | `render_env`, `doctor`, `run_checks`, `local_smoke` |
| [Running Tests](USAGE.md#running-tests) | pytest commands and coverage |
| [Environment Variables Reference](USAGE.md#environment-variables-reference) | Full env-var table by category |
| [Map Providers](USAGE.md#map-providers) | `coordinate-grid` and `maplibre` configuration |
| [Error States and Troubleshooting](USAGE.md#error-states-and-troubleshooting) | Common issues and resolution steps |
| [Limitations](USAGE.md#limitations) | Known constraints and caveats |

</details>

---

## ⚠️ Limitations

| Area | Constraint |
|---|---|
| **Authentication** | No login or session management in the frontend. Access control is enforced at the API layer via `access_role` parameters. |
| **Alert actions** | Acknowledge and Resolve actions are available in the frontend. Suppress and escalate are backend-only; no UI for those operations currently. |
| **Export creation** | The backend supports creating case export bundles. The frontend reports page lists existing exports only. |
| **Bulk operations** | Violation review is per-item only. No batch confirm/dismiss interface. |
| **Workflow checkpointing** | In-memory only. Workflow state is lost on service restart. |
| **Containerization** | No Dockerfiles shipped. `infra/docker/` is reserved for future use. |
| **Redis** | `REDIS_URL` is defined in environment templates but Redis integration is not active. |
| **Database** | SQLite for local development/CI only. Production deployments require PostgreSQL. |

> 📖 See [LIMITATIONS.md](docs/LIMITATIONS.md) for a more detailed discussion of known constraints and extension points.

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
