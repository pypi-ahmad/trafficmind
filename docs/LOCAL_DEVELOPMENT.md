# Local Development

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.12+ (3.13 recommended) | venv at `.venv/` |
| Node.js | 18+ | For frontend only |
| GPU + CUDA | Optional | Required for real-time CV inference |

## Python Environment

```bash
# create venv (if not already present)
python -m venv .venv

# activate
.venv\Scripts\activate           # Windows
source .venv/bin/activate        # Linux/macOS

# install core + dev dependencies
pip install -e ".[dev]"

# install CV dependencies (requires CUDA-capable PyTorch)
pip install -e ".[cv]"

# install workflow dependencies
pip install -e ".[workflow]"

# install everything
pip install -e ".[dev,cv,workflow]"
```

## Environment Profiles

The repo stays local-first by default, but commit-safe profile templates now exist for local, dev, staging, and prod planning.

```bash
# render the local baseline into .env
python infra/scripts/render_env.py --profile local --output .env

# overwrite .env with the dev profile
python infra/scripts/render_env.py --profile dev --output .env --force
```

Available templates:

- Local: `.env.example`
- Dev: `infra/env/dev.env.example`
- Staging: `infra/env/staging.env.example`
- Prod: `infra/env/prod.env.example`

## Environment Variables

Copy `.env.example` to `.env` and adjust as needed:

| Variable | Default | Description |
|---|---|---|
| `TRAFFICMIND_ENV` | `local` | Environment identifier |
| `TRAFFICMIND_STRICT_STARTUP_CHECKS` | `false` | Fail API/workflow startup when readiness checks report errors |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `DATABASE_URL` | `sqlite+aiosqlite:///./trafficmind.db` | Database connection string |
| `TRAFFICMIND_ALLOWED_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Comma-separated API CORS origins |
| `MODEL_DIR` | `./models` | Directory for ML model weights |
| `YOLO_MODEL_PATH` | `./models/yolo26x.pt` | Path to YOLO model file |
| `VISION_DEVICE` | `auto` | Inference device (`auto`, `cuda`, `cpu`) |
| `VISION_HALF_PRECISION` | `true` | Enable FP16 inference |
| `OCR_USE_GPU` | `true` | GPU acceleration for PaddleOCR |
| `API_PORT` | `8000` | Backend API port |
| `WORKFLOW_PORT` | `8010` | Workflow service port |
| `WEB_PORT` | `3000` | Frontend dev server port |
| `TRAFFICMIND_API_BASE_URL` | `http://127.0.0.1:8000/api/v1` | Canonical API URL for server-rendered frontend fetches |
| `NEXT_PUBLIC_TRAFFICMIND_API_BASE_URL` | `http://127.0.0.1:8000/api/v1` | Public frontend API URL alias |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection (future use) |
| `WORKFLOW_PROVIDER_BACKEND` | `heuristic` | Current workflow provider backend; only `heuristic` is supported today |
| `WORKFLOW_CHECKPOINT_BACKEND` | `memory` | Current workflow checkpoint backend |
| `OPENAI_API_KEY` | _(empty)_ | Reserved for a future workflow provider backend and currently unused |

Legacy note: `NEXT_PUBLIC_API_BASE_URL` is still accepted as a fallback in the frontend config for compatibility, but `NEXT_PUBLIC_TRAFFICMIND_API_BASE_URL` is the canonical name.

## Database Setup

### SQLite (Default for Local Development)

No setup required. The database file `trafficmind.db` is created automatically.

```bash
# create tables via Alembic
alembic upgrade head

# or create tables and seed demo data in one step
python -m apps.api.app.demo.seed --create-schema
```

### PostgreSQL

Set `DATABASE_URL` in your `.env`:

```
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/trafficmind
```

Then run migrations:

```bash
alembic upgrade head
```

## Running Services

### Backend API

```bash
uvicorn apps.api.app.main:app --reload --port 8000
```

The API serves at `http://localhost:8000`. OpenAPI docs are available at `/api/v1/docs`.

Health probes:

- Liveness: `GET /api/v1/health`
- Readiness: `GET /api/v1/health/ready`

### Workflow Service

```bash
uvicorn apps.workflow.app.main:app --reload --port 8010
```

The workflow service runs with the deterministic `heuristic` provider by default. No API key is required for local execution today.

Health probes:

- Liveness: `GET /api/v1/health`
- Readiness: `GET /api/v1/health/ready`

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Serves at `http://localhost:3000`. Expects the backend API at the URL configured in `TRAFFICMIND_API_BASE_URL` or `NEXT_PUBLIC_TRAFFICMIND_API_BASE_URL`.

## Demo Data

Seed the database with realistic synthetic data for local walkthroughs:

```bash
# create schema + seed (fresh database)
python -m apps.api.app.demo.seed --create-schema

# seed only (tables already exist)
python -m apps.api.app.demo.seed

# list available scenarios
python -m apps.api.app.demo.seed --list-scenarios

# write a JSON walkthrough report
python -m apps.api.app.demo.seed --report-path demo-seed-report.json
```

The seeder is idempotent. It replaces existing demo records on each run.

**What gets seeded:** 3 cameras, 4 streams, 5 zones, 4 detection events, 3 plate reads, 3 violations, 3 evidence manifests, 3 workflows. Cameras are configured for online, degraded, and offline health states.

**After seeding, try:**

- `GET http://localhost:8000/api/v1/cameras` — list demo cameras
- `GET http://localhost:8000/api/v1/observability/dashboard` — health dashboard
- `GET http://localhost:8000/api/v1/plates` — plate reads
- `POST http://localhost:8000/api/v1/exports` — create a case export bundle

## Perception Pipeline

### Test mode (no GPU needed)

```bash
python -m services.streams --source-kind test --max-frames 60 --disable-detection --disable-tracking
```

### Local video file

```bash
python -m services.streams --source-kind file --source-uri path/to/video.mp4 --max-processing-fps 10
```

### Evaluation suite

```bash
python -m services.evaluation tests/fixtures/evaluation/benchmark_suite.json
```

### Worker startup preflight only

```bash
python -m services.streams --check-config-only
```

## Running Tests

```bash
# full suite
python -m pytest tests/ -q

# specific module
python -m pytest tests/rules/ -v
python -m pytest tests/api/ -v

# with coverage report
python -m pytest tests/ --cov=apps --cov=services --cov-report=term-missing

# skip GPU-dependent integration tests
python -m pytest tests/ -m "not integration"

# repeatable local/CI validation surface
python infra/scripts/run_checks.py --suite all
```

## Linting

```bash
# repeatable backend validation surface used by CI
python infra/scripts/run_checks.py --suite backend

# repeatable frontend validation surface used by CI
python infra/scripts/run_checks.py --suite frontend

# config and readiness diagnostics
python infra/scripts/doctor.py
```

Repo-wide `ruff check .` is not the current CI contract yet. The repeatable backend check runner uses the maintained deployment-hardening file scope that is documented in the deployment guide.

## Project Layout Quick Reference

| Path | Purpose |
|---|---|
| `apps/api/` | FastAPI backend (routes, schemas, services, ORM) |
| `apps/workflow/` | LangGraph cold-path workflow service |
| `services/` | Deterministic domain services (vision, tracking, rules, etc.) |
| `frontend/` | Next.js operations dashboard |
| `alembic/` | Database migration scripts |
| `tests/` | Test suite (mirrors source layout) |
| `models/` | ML model weights (gitignored) |
| `docs/` | Extended documentation |
| `infra/` | Docker and automation (placeholder) |

## Troubleshooting

### `ModuleNotFoundError` on imports

Ensure the package is installed in editable mode:

```bash
pip install -e ".[dev]"
```

### CUDA not detected

```bash
python -c "import torch; print(torch.cuda.is_available())"
```

If `False`, reinstall PyTorch with CUDA support from [pytorch.org](https://pytorch.org).

### Alembic migration conflicts

```bash
alembic history --verbose
alembic upgrade head
```

### Frontend can't reach API

Check `TRAFFICMIND_API_BASE_URL` or `NEXT_PUBLIC_TRAFFICMIND_API_BASE_URL` in `.env` and ensure the backend is running on the expected port.
