# Local Development

This guide documents the clean local developer path for TrafficMind on this repo as it exists today.

It is intentionally explicit and local-first:

- install the repo
- render the right env files
- migrate the database
- seed meaningful demo data
- start the API, workflow service, and frontend
- run one live smoke check against the started services

It does not pretend the repo has one-command orchestration for all services.

## What The Golden Path Proves

The documented flow proves all of the following on one machine:

- Python dependencies install correctly for the API, workflow service, and deterministic services.
- Frontend dependencies install and the Next.js app starts locally.
- Alembic migrations apply to the configured database.
- Demo seed data can be written into the migrated database.
- The API starts and reports readiness.
- The workflow service starts and reports readiness.
- The real API list and feed routes respond with JSON.
- The workflow service can execute a grounded workflow request.
- The frontend renders against the live local backend.

## What The Golden Path Does Not Prove

- Browser-only interactions such as map pan, zoom, and click behavior.
- GPU-backed model inference on real streams.
- Long-running worker jobs under real load.
- External integrations such as webhook, SMTP, Slack, or object storage.
- Production orchestration or remote deployment.

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.12+ (3.13 recommended) | The repo currently works on Python 3.13.12 in `.venv/`. |
| Node.js | 18+ | Required for the frontend. |
| npm | Bundled with Node.js | Used for frontend install, dev, build, and lint commands. |
| GPU + CUDA | Optional | Not required for the documented smoke path. |

## Environment Model

There are two local env files in the honest golden path:

- Root `.env`: used by Python services and helper scripts.
- `frontend/.env.local`: used by Next.js during local frontend development.

Important detail: Next.js does not automatically read the repo-root `.env` when you run `npm run dev` inside `frontend/`. That is why the golden path renders both files from the same profile.

## Golden Path

Run every command below from the repo root unless the step says otherwise.

### 1. Clone And Enter The Repo

```bash
git clone https://github.com/pypi-ahmad/trafficmind.git
cd trafficmind
```

Expected result:

- You are in the repo root.
- Files such as `pyproject.toml`, `alembic.ini`, `frontend/package.json`, and `infra/scripts/` are present.

### 2. Create And Activate A Python Virtual Environment

```bash
python -m venv .venv

# Windows PowerShell
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate
```

Expected result:

- Your shell prompt shows the virtual environment is active.
- Python commands resolve inside `.venv`.

### 3. Install Python Dependencies

```bash
pip install -r requirements-dev.lock
pip install --no-deps -e .
```

Optional CV extras:

```bash
pip install -e ".[cv]"
```

Use the optional CV install only when you need local model-backed inference work. It is not required for the documented smoke path.

Expected result:

- FastAPI, SQLAlchemy, Alembic, pytest, and workflow dependencies are installed.
- The repo is importable in editable mode.

### 4. Install Frontend Dependencies

```bash
cd frontend
npm install
cd ..
```

Expected result:

- `frontend/node_modules` exists.
- `npm run dev`, `npm run build`, and `npm run lint` are available.

### 5. Render Local Env Files

```bash
python infra/scripts/render_env.py --profile local --output .env --frontend-output frontend/.env.local --force
```

Expected result:

- `.env` is created or updated in the repo root.
- `frontend/.env.local` is created or updated for Next.js.
- Both files are derived from the same local profile.

This is the command the golden path expects. It removes ambiguity between the Python runtime config and the Next.js runtime config.

### 6. Run Database Migrations

```bash
alembic upgrade head
```

Expected result:

- Alembic exits with code `0`.
- The configured local database schema is at the latest revision.
- On the default local setup, this operates on `trafficmind.db`.

Important detail: the Alembic environment reads `DATABASE_URL` from TrafficMind settings, so the migration target follows your configured env, not just `alembic.ini`.

### 7. Seed The Demo Dataset Used By The Live Smoke Path

```bash
python -m apps.api.app.demo.seed
```

Expected result:

- The local database contains synthetic cameras, streams, zones, events, violations, and workflows.
- The command exits with code `0`.
- The dataset is clearly labeled as demo data and is safe for local walkthroughs.

This step is part of the golden path on purpose. Without it, the services still start, but the live product smoke is less meaningful because the UI and feed routes would mostly prove empty-state behavior.

### 8. Start The Services In Separate Terminals

Use four terminals total: three to run services, one to run the smoke command.

#### Terminal A: API Service

```bash
uvicorn apps.api.app.main:app --reload --port 8000
```

Expected result:

- The API binds to `http://127.0.0.1:8000`.
- OpenAPI docs are available at `http://127.0.0.1:8000/api/v1/docs`.
- Readiness is available at `http://127.0.0.1:8000/api/v1/health/ready`.

#### Terminal B: Workflow Service

```bash
uvicorn apps.workflow.app.main:app --reload --port 8010
```

Expected result:

- The workflow service binds to `http://127.0.0.1:8010`.
- Readiness is available at `http://127.0.0.1:8010/api/v1/health/ready`.
- The service runs with the deterministic `heuristic` provider by default.

#### Terminal C: Frontend

```bash
cd frontend
npm run dev
```

Expected result:

- The frontend binds to `http://127.0.0.1:3000`.
- The home page renders the operations dashboard against the live API.

### 9. Run The Live Local Smoke Check

In Terminal D:

```bash
python infra/scripts/local_smoke.py --env-file .env --expect-demo-data
```

Expected result:

- The script prints `PASS` lines for API readiness, workflow readiness, API feeds, workflow execution, and frontend rendering.
- The script exits with code `0`.

Representative output shape:

```text
[PASS] api readiness: ready in local environment
[PASS] workflow readiness: ready in local environment
[PASS] api cameras: /cameras responded with total=3
[PASS] api events feed: /events responded with total=4
[PASS] api violations feed: /violations responded with total=3
[PASS] api summary totals: /events/summary/totals responded with total=4
[PASS] workflow operator-assist: operator-assist succeeded with run_id=...
[PASS] frontend home page: home page rendered with live camera content for ...
[PASS] frontend events page: events page rendered with live camera context for ...
```

### 10. Optional: Run The Heavier Foundation Regression

```bash
python infra/scripts/run_checks.py --suite golden-path
```

What this verifies:

- Alembic migration chain on a disposable SQLite database.
- Deterministic `tests/smoke` coverage for detection, tracking, OCR, rules, and persistence.
- API foundation tests.
- Workflow HTTP execution tests.
- Frontend production build.

This is not a replacement for the live smoke. It is the deeper non-live regression suite for local validation and CI.

## One-Page Command Summary

```bash
git clone https://github.com/pypi-ahmad/trafficmind.git
cd trafficmind
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.lock
pip install --no-deps -e .
cd frontend && npm install && cd ..
python infra/scripts/render_env.py --profile local --output .env --frontend-output frontend/.env.local --force
alembic upgrade head
python -m apps.api.app.demo.seed
```

Then start:

```bash
uvicorn apps.api.app.main:app --reload --port 8000
uvicorn apps.workflow.app.main:app --reload --port 8010
cd frontend && npm run dev
```

Then verify:

```bash
python infra/scripts/local_smoke.py --env-file .env --expect-demo-data
```

## Additional Useful Commands

### Demo Data

```bash
python -m apps.api.app.demo.seed --report-path demo-seed-report.json
python -m apps.api.app.demo.seed --list-scenarios
```

### Stream Pipeline Preflight

```bash
python -m services.streams --check-config-only
```

### Stream Pipeline On Test Input

```bash
python -m services.streams --source-kind test --max-frames 60
```

### Evaluation Fixture Suite

```bash
python -m services.evaluation tests/fixtures/evaluation/benchmark_suite.json
```

### Doctor Checks

```bash
python infra/scripts/doctor.py --env-file .env
```

### Repeatable Validation Suites

```bash
python infra/scripts/run_checks.py --suite backend
python infra/scripts/run_checks.py --suite frontend
python infra/scripts/run_checks.py --suite smoke
python infra/scripts/run_checks.py --suite golden-path
python infra/scripts/run_checks.py --suite all
```

## GPU And Device Notes

Two separate runtime stacks exist:

- Vision and detection use PyTorch.
- OCR uses PaddlePaddle and PaddleOCR.

Local smoke does not require either stack to resolve to GPU.

On a typical machine:

- Linux + NVIDIA + CUDA: PyTorch can use CUDA; OCR can use CUDA only when `paddlepaddle-gpu` is installed.
- Windows + NVIDIA + CUDA: PyTorch can use CUDA; OCR falls back to CPU because PaddlePaddle does not publish Windows CUDA wheels.
- CPU-only or CI: both stacks resolve to CPU and the local smoke still works.

Useful checks:

```bash
python -c "import torch; print('vision:', 'cuda' if torch.cuda.is_available() else 'cpu')"
python -c "import paddle; print('ocr:', 'gpu:0' if paddle.device.is_compiled_with_cuda() else 'cpu')"
```

## Troubleshooting

### Frontend cannot reach the API

Use the documented env rendering command:

```bash
python infra/scripts/render_env.py --profile local --output .env --frontend-output frontend/.env.local --force
```

Then restart `npm run dev`.

The important detail is that the frontend reads `frontend/.env.local`, not the repo-root `.env`, unless you exported variables into the shell yourself.

### `ModuleNotFoundError` or import issues

Re-run:

```bash
pip install -r requirements-dev.lock
pip install --no-deps -e .
```

### Migrations fail or drift from the configured DB

Check the active database URL:

```bash
python -c "from apps.api.app.core.config import get_settings; print(get_settings().database_url)"
alembic history --verbose
alembic upgrade head
```

### Port 8000 is already in use

On this machine, port `8000` is already occupied by another local process. When that happens, keep the workflow service on `8010`, keep the frontend on `3000`, and move only the API to `8001`.

Start the API on `8001`:

```bash
uvicorn apps.api.app.main:app --reload --port 8001
```

Start the frontend pointed at the alternate API URL:

```bash
cd frontend
$env:TRAFFICMIND_API_BASE_URL='http://127.0.0.1:8001/api/v1'
$env:NEXT_PUBLIC_TRAFFICMIND_API_BASE_URL='http://127.0.0.1:8001/api/v1'
npm run dev -- --hostname 127.0.0.1 --port 3000
```

Run the smoke check with the override:

```bash
python infra/scripts/local_smoke.py --env-file .env --api-base-url http://127.0.0.1:8001/api/v1 --expect-demo-data
```

### Smoke script fails because services are still starting

The smoke script already waits for readiness, but it still expects all three services to be running.

Re-check:

- API terminal is running on port `8000`
- Workflow terminal is running on port `8010`
- Frontend terminal is running on port `3000`

Then re-run:

```bash
python infra/scripts/local_smoke.py --env-file .env --expect-demo-data
```

### Need a stricter regression than the live smoke

Run:

```bash
python infra/scripts/run_checks.py --suite golden-path
```

That suite is the current one-command critical-path regression, but it is intentionally a foundation check rather than a live-service smoke.
