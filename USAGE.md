# TrafficMind — Usage Guide

Unified traffic intelligence platform. From raw video frames to operator-ready violation evidence — detection, tracking, OCR, rule evaluation, workflow triage, and spatial analytics in one monorepo.

---

## Table of Contents

- [Who This Is For](#who-this-is-for)
- [Before You Start](#before-you-start)
- [Prerequisites](#prerequisites)
- [Environment Configuration](#environment-configuration)
- [Starting the Application](#starting-the-application)
- [System Architecture at a Glance](#system-architecture-at-a-glance)
- [Frontend — Operator Interface](#frontend--operator-interface)
  - [Dashboard](#dashboard)
  - [Cases](#cases)
  - [Alerts](#alerts)
  - [Camera Detail](#camera-detail)
  - [Evaluation](#evaluation)
  - [Reports](#reports)
  - [Settings](#settings)
  - [Help](#help)
- [Backend — API Reference](#backend--api-reference)
- [Workflow Service](#workflow-service)
- [Database Migrations](#database-migrations)
- [Utility Scripts](#utility-scripts)
- [Running Tests](#running-tests)
- [Environment Variables Reference](#environment-variables-reference)
- [Map Providers](#map-providers)
- [Error States and Troubleshooting](#error-states-and-troubleshooting)
- [Limitations](#limitations)

---

## Who This Is For

- **Traffic operators** reviewing violations, managing cases, and monitoring camera health through the web interface.
- **System administrators** configuring access control policies, managing camera streams, and maintaining the platform.
- **ML engineers** evaluating detection/tracking/OCR model performance through the evaluation dashboard.
- **Developers** extending the backend services, API routes, or frontend pages.

---

## Before You Start

TrafficMind is a monorepo with three runtime services:

| Service | Port | Technology | Entry Point |
|---------|------|------------|-------------|
| **API** | `8000` | FastAPI (Python 3.13) | `apps/api/app/main.py` |
| **Workflow** | `8010` | FastAPI + LangGraph | `apps/workflow/app/main.py` |
| **Frontend** | `3000` | Next.js 16 + React 19 | `frontend/` |

The API and Frontend are required for the operator interface. The Workflow service is optional and provides cold-path LangGraph workflows (incident triage, violation review, reporting).

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.13 | Required for API and Workflow services |
| Node.js | 22+ | Required for the frontend |
| npm | Bundled with Node.js | Package management for frontend |
| Git | Any recent | Repository access |

**Optional (for ML inference):**

| Requirement | Notes |
|-------------|-------|
| CUDA-capable GPU | For accelerated YOLO detection and PaddleOCR |
| YOLO model weights | Place at `./models/yolo26x.pt` (path configurable via `YOLO_MODEL_PATH`) |

---

## Environment Configuration

### 1. Generate your local `.env`

Use the render script to generate environment files from a profile:

```bash
python infra/scripts/render_env.py --profile local --output .env --force
```

Available profiles: `local`, `dev`, `staging`, `prod`. Profile templates live in `infra/env/`.

### 2. Generate the frontend `.env.local`

The render script can also generate frontend environment variables:

```bash
python infra/scripts/render_env.py --profile local --output .env --force
```

Or manually create `frontend/.env.local`:

```env
TRAFFICMIND_API_BASE_URL=http://127.0.0.1:8000/api/v1
NEXT_PUBLIC_TRAFFICMIND_API_BASE_URL=http://127.0.0.1:8000/api/v1
NEXT_PUBLIC_MAP_PROVIDER=coordinate-grid
```

### 3. Database

By default, local development uses SQLite:

```env
DATABASE_URL=sqlite+aiosqlite:///./trafficmind.db
```

Production deployments use PostgreSQL:

```env
DATABASE_URL=postgresql+asyncpg://trafficmind:<password>@<host>:5432/trafficmind
```

---

## Starting the Application

### Install dependencies

```bash
# Backend (from repo root)
pip install -r requirements-dev.lock
pip install --no-deps -e .

# Frontend
cd frontend
npm ci
```

### Run database migrations

```bash
alembic upgrade head
```

### Start the API server

```bash
uvicorn apps.api.app.main:app --host 0.0.0.0 --port 8000
```

On startup, the API server:
1. Probes database connectivity.
2. Builds a readiness report (detection, tracking, OCR, signal classification availability).
3. Starts the stream orchestrator for video ingestion jobs.

### Start the Workflow service (optional)

```bash
uvicorn apps.workflow.app.main:app --host 0.0.0.0 --port 8010
```

### Start the Frontend

```bash
cd frontend
npm run dev
```

The operator interface is available at **http://localhost:3000**.

### Verify the setup

```bash
# Health check
curl http://localhost:8000/api/v1/health

# Readiness probe
curl http://localhost:8000/api/v1/health/ready

# System doctor
python infra/scripts/doctor.py --service api

# Full smoke test (requires all three services running)
python infra/scripts/local_smoke.py
```

---

## System Architecture at a Glance

TrafficMind separates work into two processing paths:

**Hot Path (deterministic perception)** — Frame-by-frame inference with no network I/O, no LLM calls, and no database writes per-frame:

> Video → Frames → Detection (YOLO) → Tracking (ByteTrack) → OCR (PaddleOCR) → Signal Classification → Rule Evaluation → Evidence Packaging → Event Persistence

**Cold Path (workflow orchestration)** — LangGraph workflows that operate over persisted records:

> Incident triage · Violation review · Daily/weekly summary · Hotspot reporting · Operator assist

The cold path uses `interrupt()` for human-in-the-loop gates. The workflow provider backend is configurable: `heuristic` (default, no LLM required) or `openai` (requires `OPENAI_API_KEY`).

---

## Frontend — Operator Interface

The frontend provides 8 pages plus one dynamic route, accessible via the persistent navigation bar.

**Primary navigation:** Dashboard, Cases, Alerts, Cameras  
**Secondary navigation:** Evaluation, Reports, Settings, Help

### Dashboard

**Route:** `/`

The operations dashboard displays:

- **Camera network map** — Camera markers positioned by coordinates. Supports two views: interactive map (when a MapLibre-compatible provider is configured) and a coordinate grid fallback.
- **Operational statistics** — Mapped cameras, active cameras, intersection count, detection and violation counts.
- **Sidebar** — Clicking a camera or intersection on the map shows its details: status, location, recent activity, configured streams and zones, related hotspot summaries with severity badges.
- **Activity feeds** — Recent violations and detection events.

**Stat cards:** Map Status, Analytics Status, Incident Feeds, Mapped Cameras, Active Cameras, Intersections, Camera Detections, Violations.

### Cases

**Route:** `/cases`

The case review page is the primary operator workflow surface.

**Data feeds:** Violations (reviewable cases) and detection events (supporting evidence) are loaded in parallel from the API.

**Filters** (all URL-parameter based):
- **Time window** — Presets: Last hour, Last 24h, Last 7 days, Last 30 days. Custom date ranges via `occurredAfter` / `occurredBefore` URL parameters.
- **Case type** — Red light, speeding, illegal turn, stop line, wrong way, illegal parking, no stopping, pedestrian conflict, bus stop violation, stalled vehicle.
- **Case status** — Open, Under Review, Confirmed, Dismissed.
- **Detection status** — New, Enriched, Suppressed.
- **Camera** — Single camera filter (set via dashboard map or URL parameter `cameraId`).
- **Intersection** — Filter by intersection ID (set via dashboard or URL parameter `junctionId`).

**Actions:**
- **Confirm** a violation — Marks the violation as confirmed. Requires the operator's name. Optional review note.
- **Dismiss** a violation — Marks the violation as dismissed. Requires the operator's name. Optional review note.

Both actions call `POST /api/v1/violations/{id}/review` and revalidate the page. Violations already in a terminal state (confirmed or dismissed) do not show action buttons.

**Pagination:** 20 items per page. Violations and detections paginate independently.

### Alerts

**Route:** `/alerts`

Lists operational alerts generated by policy rules.

**Filters:**
- **Status** — New, Acknowledged, Escalated, Resolved, Suppressed.
- **Severity** — Critical, High, Medium, Low, Info.
- **Source** — Violation event, Watchlist alert, Camera health, Stream health, Workflow backlog, Manual.

The alerts page is currently **read-only**. The backend supports acknowledge, resolve, suppress, and escalate actions (`POST /api/v1/alerts/{id}/<action>`), but these are not yet wired in the frontend.

### Camera Detail

**Route:** `/cameras/[cameraId]`

Shows detailed information for a single camera:

- **Header** — Camera name, location, status badge (Active, Setting Up, Maintenance, Disabled).
- **Statistics** — Status, coordinates (or "Not mapped"), stream count, zone count.
- **Camera Information** — Camera code, approach, timezone, last updated timestamp, notes.
- **Streams** — Attached video feed connections with status badges. Empty state explains that streams are configured by an administrator.
- **Detection Zones** — Configured monitoring areas within the camera frame. Empty state explains that zones define where events are monitored.

**Navigation links:** View incidents (→ Cases filtered by camera), View intersection (→ Dashboard with intersection selected).

### Evaluation

**Route:** `/evaluation`

The model evaluation dashboard displays benchmark results from controlled test sets.

- **Summary cards** — Measured rows, stored artifacts, tagged model versions.
- **Filters** — Task type, scenario, model/config version, camera tag, date range.
- **Benchmark results** — Detection accuracy (precision, recall), tracking continuity, OCR accuracy, rule validation, signal classification.
- **Review notes** — Manual annotations when artifacts include reviewer notes.
- **Evaluation sources** — Lists the benchmark tests and stored report files that feed the dashboard.

Results are sourced from the path configured in `TRAFFICMIND_EVALUATION_FIXTURE_SUITE_PATH` and `TRAFFICMIND_EVALUATION_ARTIFACT_DIR`.

### Reports

**Route:** `/reports`

Lists exported evidence bundles. Filters by export status (pending, completed, failed) and subject type (violation event, detection event, watchlist alert, operational alert).

The reports page is currently **read-only**. The backend supports export creation (`POST /api/v1/exports`) but the creation UI is not yet exposed in the frontend.

### Settings

**Route:** `/settings`

Displays the active access control policy, including role/permission assignments. Read-only for operators; configuration is managed by administrators.

### Help

**Route:** `/help`

Operator reference guide containing:

- **Getting Around** — Navigation descriptions with direct links to each page.
- **Glossary** — Definitions for: Violation, Detection, Case, Alert, Zone, Stream, Junction, Escalation, Export, Severity.
- **Severity Levels** — Explanation of Critical, High, Medium, Low with usage context.
- **Common Tasks** — Step-by-step guides for: reviewing a violation case, filtering cases by camera, checking camera health, understanding an alert.

---

## Backend — API Reference

All endpoints are versioned under `/api/v1`. The API uses JSON request/response bodies with Pydantic validation.

### Core Resources

| Prefix | Resource | Key Operations |
|--------|----------|----------------|
| `/cameras` | Cameras and streams | List, get detail, list streams |
| `/junctions` | Intersections | List, get detail |
| `/events` | Detection events | Search with filters, summary by camera |
| `/violations` | Violation events | Search with filters, summary by camera, review (approve/reject) |
| `/alerts` | Operational alerts | Search with filters, acknowledge, resolve, suppress, escalate |
| `/exports` | Case export bundles | List, create, get detail, download, audit |
| `/plates` | Plate reads (ANPR) | List, get detail |
| `/watchlist` | Watchlist entries | List, create, update, check |

### Infrastructure

| Prefix | Resource | Key Operations |
|--------|----------|----------------|
| `/health` | Health probes | Liveness (`/health`), readiness (`/health/ready`) |
| `/info` | Service metadata | Version, environment |
| `/config/public` | Public configuration | Non-secret config values |
| `/jobs` | Stream ingestion jobs | List, get, stop, pause, resume |
| `/access` | Access control | Get active policy |
| `/analytics` | Spatial analytics | Hotspot data, evaluation metrics |
| `/signals` | Traffic signal integration | Controller events, file feed, polling |
| `/model-registry` | Model versioning | List, get registered models |

### Violation Review Endpoint

```
POST /api/v1/violations/{id}/review?access_role=reviewer

{
  "actor": "Jane Doe",
  "action": "approve" | "reject",
  "note": "Optional review note"
}
```

Returns the updated violation record. Requires the `APPROVE_REJECT_INCIDENTS` permission.

---

## Workflow Service

The workflow service runs at port `8010` and exposes eight workflow endpoints:

| Endpoint | Workflow |
|----------|----------|
| `POST /api/v1/workflows/incident-triage` | Classify and route new incidents |
| `POST /api/v1/workflows/violation-review` | Structured violation review |
| `POST /api/v1/workflows/multimodal-review` | Review with image/video evidence |
| `POST /api/v1/workflows/daily-summary` | Generate daily operational summary |
| `POST /api/v1/workflows/weekly-summary` | Generate weekly operational summary |
| `POST /api/v1/workflows/hotspot-report` | Spatial hotspot analysis report |
| `POST /api/v1/workflows/operator-assist` | Interactive operator assistance |
| `POST /api/v1/workflows/runs/{run_id}/resume` | Resume a paused workflow run |

**Provider backends:**
- `heuristic` (default) — Deterministic rule-based logic, no LLM required.
- `openai` — LLM-powered workflows via LangChain OpenAI. Requires `OPENAI_API_KEY`.

**Checkpoint backends:**
- `memory` (default) — In-memory state, lost on restart.

---

## Database Migrations

TrafficMind uses Alembic for schema migrations. The database has 23 ORM models across 13 migration revisions.

```bash
# Apply all migrations
alembic upgrade head

# Check current revision
alembic current

# Generate a new migration
alembic revision --autogenerate -m "description"
```

Migration files are in `alembic/versions/`, covering: database foundation, plate read OCR metadata, violation rule metadata, watchlist entries, evidence manifests, re-identification tables, alert routing, case exports, model registry, junction entities, and more.

---

## Utility Scripts

All utility scripts are in `infra/scripts/` and run with Python from the repo root.

| Script | Purpose | Usage |
|--------|---------|-------|
| `render_env.py` | Generate `.env` from an environment profile | `python infra/scripts/render_env.py --profile local --output .env --force` |
| `doctor.py` | System health checks (DB, settings, features) | `python infra/scripts/doctor.py --service api` |
| `run_checks.py` | CI orchestrator for lint, format, and tests | `python infra/scripts/run_checks.py --suite backend` |
| `local_smoke.py` | Golden-path smoke test (all services must be running) | `python infra/scripts/local_smoke.py` |

### run_checks.py suites

| Suite | What It Runs |
|-------|-------------|
| `backend` | doctor → ruff check → pytest (excludes integration tests) |
| `frontend` | doctor (frontend) → eslint → next build |
| `smoke` | pytest with `-m smoke` marker |
| `golden-path` | alembic upgrade → smoke → API + workflow routes → frontend build |
| `all` | All of the above |

---

## Running Tests

```bash
# All backend tests (excludes integration tests by default)
pytest

# Include integration tests (requires model files / GPU)
pytest -m integration

# Smoke tests only (golden-path: detection → tracking → OCR → rules)
pytest -m smoke

# With coverage
pytest --cov

# Frontend lint
cd frontend && npm run lint

# Frontend build check
cd frontend && npm run build
```

Coverage threshold: 80% on `apps/` and `services/`.

---

## Environment Variables Reference

### Core

| Variable | Default | Description |
|----------|---------|-------------|
| `TRAFFICMIND_ENV` | `local` | Environment name: `local`, `dev`, `staging`, `prod` |
| `TRAFFICMIND_STRICT_STARTUP_CHECKS` | `false` | If `true`, API fails to start when modules are not ready |
| `LOG_LEVEL` | `INFO` | Logging level |
| `DATABASE_URL` | `sqlite+aiosqlite:///./trafficmind.db` | Database connection string |
| `TRAFFICMIND_ALLOWED_ORIGINS` | `http://localhost:3000,...` | CORS allowed origins (comma-separated) |

### Service Ports

| Variable | Default | Description |
|----------|---------|-------------|
| `API_PORT` | `8000` | API server port |
| `WORKFLOW_PORT` | `8010` | Workflow server port |
| `WEB_PORT` | `3000` | Frontend dev server port |

### Service URLs

| Variable | Default | Description |
|----------|---------|-------------|
| `TRAFFICMIND_API_BASE_URL` | `http://127.0.0.1:8000/api/v1` | API base URL (server-side) |
| `NEXT_PUBLIC_TRAFFICMIND_API_BASE_URL` | `http://127.0.0.1:8000/api/v1` | API base URL (browser-side) |
| `TRAFFICMIND_WORKFLOW_BASE_URL` | `http://127.0.0.1:8010/api/v1` | Workflow service URL |

### Vision and ML

| Variable | Default | Description |
|----------|---------|-------------|
| `MODEL_DIR` | `./models` | Directory containing model weight files |
| `YOLO_MODEL_PATH` | `./models/yolo26x.pt` | Path to YOLO detection model |
| `VISION_DEVICE` | `auto` | Inference device: `auto`, `cuda`, `cpu` |
| `VISION_HALF_PRECISION` | `true` | Enable FP16 inference |
| `OCR_USE_GPU` | `true` | Enable GPU for PaddleOCR |

### Map Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `NEXT_PUBLIC_MAP_PROVIDER` | `coordinate-grid` | Map backend: `coordinate-grid` or `maplibre` |
| `NEXT_PUBLIC_MAP_STYLE_URL` | *(empty)* | MapLibre style URL (required when provider is `maplibre`) |
| `NEXT_PUBLIC_MAP_ACCESS_TOKEN` | *(empty)* | Map tile provider access token |

### Workflow

| Variable | Default | Description |
|----------|---------|-------------|
| `WORKFLOW_PROVIDER_BACKEND` | `heuristic` | Workflow engine: `heuristic` or `openai` |
| `WORKFLOW_CHECKPOINT_BACKEND` | `memory` | State persistence: `memory` |
| `OPENAI_API_KEY` | *(empty)* | Required when `WORKFLOW_PROVIDER_BACKEND=openai` |

### Evaluation

| Variable | Default | Description |
|----------|---------|-------------|
| `TRAFFICMIND_EVALUATION_FIXTURE_SUITE_PATH` | `./tests/fixtures/evaluation/benchmark_suite.json` | Path to benchmark test fixtures |
| `TRAFFICMIND_EVALUATION_ARTIFACT_DIR` | `./outputs/evaluation` | Directory for evaluation report artifacts |

### Spatial Analytics

| Variable | Default | Description |
|----------|---------|-------------|
| `TRAFFICMIND_SPATIAL_LOOKBACK_DAYS` | `7` | Days of data for hotspot analysis |
| `TRAFFICMIND_SPATIAL_TOP_N` | `48` | Maximum hotspot results returned |

---

## Map Providers

The dashboard map supports two providers, selected via `NEXT_PUBLIC_MAP_PROVIDER`:

### `coordinate-grid` (default)

Renders camera markers on a coordinate grid. No external tile service required. Suitable for local development and environments without internet access.

### `maplibre`

Uses MapLibre GL for interactive map rendering. Requires:
- `NEXT_PUBLIC_MAP_STYLE_URL` — URL to a MapLibre-compatible style definition.
- `NEXT_PUBLIC_MAP_ACCESS_TOKEN` — Access token for the tile provider (if required by the style URL).

---

## Error States and Troubleshooting

### API server won't start

- **Database connection failure** — Verify `DATABASE_URL` is correct and the database is accessible. Run `python infra/scripts/doctor.py --service api` to diagnose.
- **Strict mode blocking startup** — When `TRAFFICMIND_STRICT_STARTUP_CHECKS=true`, the API will refuse to start if required modules (detection, tracking, OCR) are not ready. Set to `false` for development.
- **Missing model files** — If `YOLO_MODEL_PATH` does not resolve to a valid model file, the vision service will report as unavailable.

### Frontend shows "Unable to reach the server"

- Confirm the API server is running on the expected port.
- Verify `TRAFFICMIND_API_BASE_URL` and `NEXT_PUBLIC_TRAFFICMIND_API_BASE_URL` in `frontend/.env.local` match the API's actual address.
- Check `TRAFFICMIND_ALLOWED_ORIGINS` includes the frontend's origin for CORS.

### Cases page shows "The case review feeds could not be reached"

- The violations or events API endpoint is unreachable. Confirm the API is running and responsive: `curl http://localhost:8000/api/v1/health`.

### Map shows "No mapped cameras yet"

- No cameras have GPS coordinates assigned. Cameras need latitude/longitude values to appear on the map.

### Evaluation dashboard shows "Evaluation data could not be loaded"

- The evaluation fixture path (`TRAFFICMIND_EVALUATION_FIXTURE_SUITE_PATH`) may not exist or contain valid data.
- The evaluation artifact directory (`TRAFFICMIND_EVALUATION_ARTIFACT_DIR`) may be empty.

---

## Limitations

- **No authentication layer.** The frontend does not implement login or session management. Access control policies exist in the settings page but enforcement is at the API level via `access_role` query parameters, not user sessions.
- **Alert actions not in UI.** The backend supports acknowledge, resolve, suppress, and escalate operations on alerts, but the frontend alerts page is read-only.
- **Export creation not in UI.** The backend supports creating case export bundles, but the frontend reports page only lists existing exports.
- **No bulk operations.** Violation review is per-item only. There is no batch confirm/dismiss interface.
- **Workflow checkpointing is in-memory.** Workflow state is lost on service restart. Durable checkpoint backends are not yet implemented.
- **Docker not yet available.** There are no Dockerfiles in the repository. The `infra/docker/` directory is reserved for future containerization.
- **REDIS_URL is reserved.** The environment variable exists in templates but Redis integration is not yet active.
- **SQLite for development only.** The default SQLite database is suitable for local development and testing. Production deployments should use PostgreSQL.
