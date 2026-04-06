# TrafficMind — Implementation Plan

**Date:** 2026-04-04
**Status:** Greenfield (env + model ready, no application code yet)

---

## 1  Target Architecture

### 1.1  High-level split

```
┌─────────────────────────────────────────────────────────────────┐
│                         TrafficMind                             │
│                                                                 │
│  ┌──────────┐  ┌─────────────────────────┐  ┌───────────────┐  │
│  │ frontend │  │        backend          │  │   workers      │  │
│  │ Next.js  │──│  FastAPI (REST + WS)    │──│ (CV pipeline)  │  │
│  │ TS + TW  │  │  Auth, CRUD, Streaming  │  │ Detection      │  │
│  └──────────┘  │  Event storage          │  │ Tracking       │  │
│                │  LangGraph orchestration │  │ OCR            │  │
│                └─────────────────────────┘  │ Rule engine    │  │
│                          │                  └───────────────┘  │
│                    ┌─────┴──────┐                              │
│                    │ PostgreSQL │                              │
│                    │ + Redis    │                              │
│                    └────────────┘                              │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2  Principles

1. **Hot path is deterministic.** Frame ingestion → detection → tracking → OCR → rule evaluation → event emit. No LLM in this loop.
2. **LangGraph is for cold-path workflows only.** Incident triage, operator-assist, report generation, review flows, human-in-the-loop approval.
3. **Monorepo.** One Git root with `apps/`, `services/`, `packages/`, and `infra/` as the standard layout.
4. **Separation of concerns.** Deterministic CV and rule-processing live under `services/`; app entrypoints live under `apps/`.
5. **Config via environment.** 12-factor. No hardcoded secrets.
6. **Database from day one.** SQLAlchemy + Alembic on PostgreSQL. SQLite for local dev.
7. **Testable.** Every module has a corresponding test. Mocked I/O for unit tests.

### 1.2.1  Deterministic vs Agentic Boundary

| Layer | Responsibilities | Must stay deterministic? | LangGraph allowed? |
|---|---|---|---|
| Ingestion | RTSP/file/video upload decode, frame sampling, buffering | Yes | No |
| CV inference | Detection, tracking, OCR, traffic-light state classification | Yes | No |
| Rule engine | Zone checks, line crossing, stop-line logic, red-light logic, violation scoring | Yes | No |
| Event persistence | Store detections, tracks, violations, evidence references | Yes | No |
| Review workflows | Queue routing, operator review state, approval steps | No | Yes |
| Incident triage | Severity classification, summarisation, suggested next steps | No | Yes |
| Reporting | Narrative summaries, daily/weekly reports, operator assist | No | Yes |

This boundary is strict: **no per-frame LLM calls, no agent inside worker inference loops, and no agent dependency for violation detection correctness.**

### 1.3  Target folder structure

```
trafficmind/
├── apps/
│   ├── web/                         # Canonical web app location
│   ├── api/
│   │   └── app/                     # FastAPI application package
│   └── workflow/
│       └── app/                     # LangGraph workflow service package
│
├── services/
│   ├── vision/                      # Deterministic detection and scene understanding
│   ├── tracking/                    # Deterministic multi-object tracking
│   ├── ocr/                         # OCR and ANPR processing
│   └── rules/                       # Deterministic rule engine
│
├── packages/
│   ├── shared-types/                # Shared schemas and contracts
│   └── shared-config/               # Shared environment and config contracts
│
├── infra/
│   ├── docker/                      # Docker and compose assets
│   └── scripts/                     # Local automation scripts
│
├── docs/                            # Supporting documentation
├── tests/                           # Repository-level tests
├── frontend/                        # Current runnable Next.js app, preserved during migration
├── models/                          # Model weights (gitignored)
│   └── yolo26x.pt
│
├── .env.example                     # Required env vars documented
├── .gitignore
├── README.md
├── ARCHITECTURE.md
├── ROADMAP.md
├── CURRENT_STATE.md
└── IMPLEMENTATION_PLAN.md
```

---

## 2  Phased Roadmap

### Phase 0 — Repo Hygiene  *(~1 session)*

**Goal:** Clean starting point, proper config, project builds.

| # | Task | Detail |
|---|---|---|
| 0.1 | Remove `.venv-1/` | Stale orphan venv |
| 0.2 | Remove `frontend/.git/` | Conflicts with root monorepo |
| 0.3 | Create `pyproject.toml` | Replace flat `requirements.txt` with grouped deps (`[project]`, `[project.optional-dependencies]` for dev/test) |
| 0.4 | Standardize env templates | Root and app-level `.env.example` files |
| 0.5 | Create root docs | `README.md`, `ARCHITECTURE.md`, `ROADMAP.md` |
| 0.6 | Python linting config | `ruff` in `pyproject.toml` |
| 0.7 | Init root git repo | Single `.git` at root |
| 0.8 | Stub directory structure | Create `apps/`, `services/`, `packages/`, `infra/`, `docs/`, and `tests/` |

**Exit criteria:** `ruff check .` passes on empty stubs. Frontend builds. Git tracks everything.

---

### Phase 1 — CV Pipeline Core  *(~2-3 sessions)*

**Goal:** Deterministic detection + tracking works on a test video, end-to-end.

| # | Task | Detail |
|---|---|---|
| 1.1 | `services/vision/` | Wrap `ultralytics.YOLO` for detection. Initial support should be limited to what the checkpoint actually covers well: vehicles, pedestrians, and traffic-light object detection. |
| 1.2 | `packages/shared-types/` | Define shared detection, track, plate-read, frame-result, and violation contracts. |
| 1.3 | `services/tracking/` | Wrap `supervision.ByteTrack`. Accept detections, return tracked objects with IDs. |
| 1.4 | `services/ocr/` | Wrap PaddleOCR. Consume pre-cropped plate regions and return OCR results. Do not assume plate localisation already exists. |
| 1.5 | `services/vision/` | Add deterministic traffic-light state classification using either robust color analysis or a dedicated classifier. |
| 1.6 | Service composition | Compose detect → track → classify lights. Plate OCR path should remain feature-flagged until a reliable plate detector exists. |
| 1.7 | Decide plate-detection strategy | Either fine-tune YOLO26 for plates or introduce a dedicated ANPR/plate detector. This is a required design choice before claiming end-to-end ANPR. |
| 1.8 | Tests | Unit tests for each module with fixture images. Mock YOLO model for fast tests; one integration test with real model. |

**Exit criteria:** `python -m pytest cv/tests/` green. Pipeline processes `sample.mp4` and prints detections + tracks per frame.

---

### Phase 2 — Rule Engine + Zones  *(~1-2 sessions)*

**Goal:** Given tracked objects and zone definitions, detect violations deterministically.

| # | Task | Detail |
|---|---|---|
| 2.1 | `packages/shared-types/` | Define `Zone`, `Line`, `StopLine`, `Crosswalk`, and direction constraint contracts |
| 2.2 | `services/rules/` | Build the per-frame rule evaluator that consumes tracked scene state and emits violations |
| 2.3 | `services/rules/` | Implement red-light, stop-line, wrong-way, pedestrian safety, illegal-turn, and speed rules |
| 2.4 | Tests | Synthetic track sequences → assert expected violations |

**Exit criteria:** `python -m pytest rules/tests/` green. Can demo red-light violation detection on scripted data.

---

### Phase 3 — Backend API + Database  *(~2-3 sessions)*

**Goal:** REST API up, database stores cameras / events / violations, WebSocket streams live status.

| # | Task | Detail |
|---|---|---|
| 3.1 | `apps/api/app/core/` | pydantic-settings config, logging, and dependency wiring |
| 3.2 | `apps/api/app/db/` | SQLAlchemy async engine + session factory |
| 3.3 | `apps/api/app/db/` | ORM models: `Camera`, `Event`, `Violation`, `Zone`, `ZoneLine` |
| 3.4 | Alembic setup | `alembic init`, initial migration |
| 3.5 | `packages/shared-types/` + `apps/api/app/` | Request/response contracts and API-facing schema bindings |
| 3.6 | `apps/api/app/services/` | CRUD + business logic services |
| 3.7 | `apps/api/app/api/` | REST routes: cameras CRUD, events list/filter, violations list/review, zones CRUD, health check |
| 3.8 | `apps/api/app/api/streams.py` | WebSocket endpoint for live detection feed |
| 3.9 | `apps/api/app/main.py` | FastAPI app factory, CORS, router includes, lifespan |
| 3.10 | Tests | Pytest + httpx `AsyncClient` against test DB |

**Exit criteria:** `uvicorn backend.app.main:app` starts. SwaggerUI shows all endpoints. CRUD works against SQLite.

---

### Phase 4 — Stream Workers  *(~1-2 sessions)*

**Goal:** Worker process reads video source, runs CV pipeline + rules, writes events to DB, pushes frames over WS.

| # | Task | Detail |
|---|---|---|
| 4.1 | Worker package under `apps/api/` or `services/` | Async loop: OpenCV VideoCapture → vision/tracking/ocr/rules → store event → push WS |
| 4.2 | Upload processor | Process uploaded video file in background, store results |
| 4.3 | Worker ↔ API integration | Worker uses the same DB session factory and shared types |
| 4.4 | RTSP + file support | VideoCapture for both RTSP URLs and local file paths |
| 4.5 | Tests | Mock VideoCapture, verify event emission |

**Exit criteria:** Start worker pointing at a test video → events appear in DB → live frames available over WS.

---

### Phase 5 — Frontend Dashboard  *(~3-4 sessions)*

**Goal:** Functional operator dashboard.

| # | Task | Detail |
|---|---|---|
| 5.1 | Layout + navigation | Sidebar: Dashboard, Cameras, Events, Violations, Zones, Reports |
| 5.2 | Dashboard page | Overview stats: active cameras, total events today, recent violations |
| 5.3 | Cameras page | List cameras, add/edit RTSP config, status indicator |
| 5.4 | Live view | WebSocket video stream with bounding-box overlay (canvas or SVG) |
| 5.5 | Events page | Filterable table of events with thumbnails |
| 5.6 | Violations page | Violation cards with evidence frames + review/approve/reject |
| 5.7 | Zones page | Visual zone editor (draw polygons/lines on camera still) |
| 5.8 | API client layer | Typed fetch wrappers or React Query setup |

**Exit criteria:** All pages render with real API data. Live view shows detection boxes.

---

### Phase 6 — LangGraph Agentic Workflows  *(~2-3 sessions)*

**Goal:** Cold-path AI workflows integrated.

| # | Task | Detail |
|---|---|---|
| 6.1 | `apps/workflow/app/tools/` | LangChain tools wrapping event and violation queries |
| 6.2 | `apps/workflow/app/graphs/triage.py` | LangGraph triage graph routing incidents to auto-approve or human review |
| 6.3 | `apps/workflow/app/graphs/review.py` | Human-in-the-loop review graph |
| 6.4 | `apps/workflow/app/graphs/report.py` | Report generation graph |
| 6.5 | `apps/workflow/app/graphs/assist.py` | Operator-assist query graph |
| 6.6 | API integration | Endpoints to trigger workflows, poll status, submit human decisions |
| 6.7 | Frontend integration | Review workflow UI, report viewer, assistant chat panel |
| 6.8 | Tests | Test graphs with mocked LLM responses |

**Exit criteria:** Triage auto-classifies test violations. Review flow pauses for human input. Report generates coherent text.

---

### Phase 7 — Productionisation  *(~2 sessions)*

| # | Task | Detail |
|---|---|---|
| 7.1 | Docker | `Dockerfile.backend`, `Dockerfile.worker`, `Dockerfile.frontend`, `docker-compose.yml` with Postgres + Redis |
| 7.2 | Redis | Cache + pub/sub for worker → API → WS fan-out |
| 7.3 | Auth | JWT-based API auth (or API key for v1) |
| 7.4 | Logging | Structured JSON logs (structlog or stdlib) |
| 7.5 | CI | GitHub Actions: lint, test, build |
| 7.6 | Model management | Script to download / verify model weights |
| 7.7 | Performance | Profile CV pipeline; batch inference; GPU support flag |

---

### Phase 8 — Extended Capabilities  *(future)*

| # | Task | Detail |
|---|---|---|
| 8.1 | DeepStream integration | NVIDIA DeepStream pipeline for GPU-accelerated multi-stream |
| 8.2 | YOLO26-seg / pose models | Segmentation for lane boundaries; pose for pedestrian intent |
| 8.3 | Speed estimation | Homography calibration + tracker displacement |
| 8.4 | Multi-camera tracking | Re-ID across camera views |
| 8.5 | Alert system | Email / SMS / webhook on critical violations |
| 8.6 | Analytics | Time-series traffic flow, heatmaps, congestion scoring |

---

## 3  Dependency Strategy

Replace the flat `requirements.txt` with `pyproject.toml`:

```toml
[project]
name = "trafficmind"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.135",
    "uvicorn[standard]>=0.43",
    "pydantic>=2.12",
    "pydantic-settings>=2.13",
    "sqlalchemy>=2.0",
    "alembic>=1.15",
    "python-dotenv>=1.2",
    "python-multipart>=0.0.20",
    "websockets>=16.0",
    "httpx>=0.28",
    "ultralytics>=8.4",
    "supervision>=0.27",
    "paddleocr>=3.4",
    "paddlepaddle>=3.3",
    "opencv-python-headless>=4.13",
    "numpy>=2.4",
    "langgraph>=1.1",
    "langchain>=1.2",
    "langchain-openai>=1.1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.25",
    "pytest-cov>=6.0",
    "httpx",          # for TestClient
    "ruff>=0.11",
]
```

**Note:** Only `opencv-python-headless` — drop the redundant `opencv-python` and `opencv-contrib-python` that were pulled in transitively.

---

## 4  Key Design Decisions

| Decision | Rationale |
|---|---|
| **CV pipeline is a library, not a service** | Imported by workers. No HTTP overhead per frame. Easy to test. Can later be wrapped in a gRPC service or DeepStream plugin if needed. |
| **Workers are separate processes** | Don't block the API server. Can be scaled independently. Use DB + Redis for communication. |
| **SQLite for local dev, Postgres for prod** | SQLAlchemy makes this transparent. No Docker dependency for first run. |
| **LangGraph graphs are stateless by default** | Use LangGraph checkpointer only for human-in-the-loop review flows where durable state is needed. |
| **Supervision for tracking** | Already installed; provides ByteTrack, BoTSORT, zone polygon logic, line counting — avoids reimplementing. |
| **Single `pyproject.toml`** | Standard Python packaging. One install command. Works with pip, uv, or poetry. |

---

## 5  Open Questions (to resolve as we build)

1. **GPU availability** — Current torch is CPU-only. If CUDA is available, swap to `torch+cu124`. YOLO26x benefits hugely from GPU.
2. **Multi-stream concurrency** — Single worker per camera vs thread pool vs async. Decide in Phase 4 based on load profile.
3. **Auth model** — Simple API keys vs JWT vs OAuth. Decide in Phase 7 based on deployment target.
4. **LLM provider** — Currently have `langchain-openai`. May need local models or Azure OpenAI for prod.
5. **Video storage** — Store violation clips on disk vs object storage (S3/MinIO). Defer to Phase 7.
6. **Plate region detection** — Use YOLO26 with a fine-tuned plate class, or a separate ANPR model? Evaluate in Phase 1.
7. **Traffic-light state approach** — Classical color-state classifier first vs dedicated fine-tuned model. Decide based on camera distance, night scenes, and occlusion quality.

---

## 6  Immediate Next Steps

Start with **Phase 0** (repo hygiene) and **Phase 1** (CV pipeline core) — these are independent of the frontend and unblock everything downstream.
