# Deployment And CI Foundations

TrafficMind is still a local-first repository, but it now includes a small deployment hardening layer that is useful for CI, shared development, and honest single-host dry runs.

This is not a claim of full production infrastructure.

## What is supported now

### Local workstation mode

- Root `.env.example` remains the default local profile
- SQLite is the default database
- The workflow service uses the deterministic `heuristic` provider
- Worker startup and service readiness checks stay permissive enough to preserve the current local developer flow

### Dev and CI mode

- Commit-safe env templates live under `infra/env/`
- `python infra/scripts/render_env.py --profile dev --output .env --force` renders a usable dev profile
- `python infra/scripts/doctor.py` validates API, workflow, stream-worker, and frontend configuration
- `python infra/scripts/doctor.py --env-file <path>` validates a specific rendered profile and lets that file win over conflicting shell env vars for the diagnostic run
- `python infra/scripts/run_checks.py --suite all` runs the repeatable validation surface used by CI and, when `.env` or `frontend/.env.local` exists, uses those rendered files instead of conflicting shell env values
- GitHub Actions runs backend lint/tests and frontend lint/build

### Staging and prod planning mode

- `infra/env/staging.env.example` and `infra/env/prod.env.example` provide minimal single-host planning templates
- API and workflow services now expose readiness probes that report configuration gaps directly
- `TRAFFICMIND_STRICT_STARTUP_CHECKS=true` causes the API and workflow services to fail startup when readiness checks report errors

## What the readiness checks cover

### API

- Database backend suitability for the configured environment
- Database connectivity
- Debug mode in production-like environments
- CORS configuration drift
- Missing vision model file warnings
- Missing evaluation fixture-suite warnings

### Workflow service

- Database backend suitability for the configured environment
- Database connectivity
- Debug mode in production-like environments
- In-memory checkpoint backend in staging/prod-like environments
- Unused `OPENAI_API_KEY` warnings while the service still supports only the deterministic heuristic provider

### Stream worker

- Detection-enabled runs without a present YOLO model file
- Tracking enabled without detection in the CLI path
- OCR enabled without upstream detection crops
- Production-like environment warnings for the still-local CLI worker mode

### Frontend

- API base URL presence and shape
- Localhost API URLs in production-like environments
- Legacy `NEXT_PUBLIC_API_BASE_URL` usage
- MapLibre requested without a configured style URL

## Health and readiness probes

### Liveness

- API: `GET /api/v1/health`
- Workflow: `GET /api/v1/health`

These are intentionally lightweight and only confirm that the process is responding.

### Readiness

- API: `GET /api/v1/health/ready`
- Workflow: `GET /api/v1/health/ready`

These return detailed readiness reports and use `503` when the service is not ready.

## Environment profiles

Available templates:

- Local: `.env.example`
- Dev: `infra/env/dev.env.example`
- Staging: `infra/env/staging.env.example`
- Prod: `infra/env/prod.env.example`

Render one into a concrete file:

```bash
python infra/scripts/render_env.py --profile local --output .env
python infra/scripts/render_env.py --profile dev --output .env --force
python infra/scripts/render_env.py --profile prod --output .env --force
```

The templates contain placeholders only. Do not commit real credentials.

## Secrets and config handling

- Commit-safe templates live in source control; live `.env` files do not.
- Use environment variables or a platform secret store for real credentials in non-local deployments.
- `OPENAI_API_KEY` remains reserved for a future provider backend. The current workflow service does not use it.
- Frontend builds should prefer `TRAFFICMIND_API_BASE_URL` or `NEXT_PUBLIC_TRAFFICMIND_API_BASE_URL`; `NEXT_PUBLIC_API_BASE_URL` is treated only as a legacy fallback.

## CI behavior

The GitHub Actions workflow runs:

- Backend config doctor checks
- `ruff check` across the maintained deployment-hardening files for API/workflow health, stream startup, shared runtime helpers, and validation scripts
- Backend `pytest` with GPU-marked `integration` tests excluded
- Frontend config doctor checks against the rendered `frontend/.env.local`
- Frontend `npm run lint`
- Frontend `npm run build`

The backend CI suite currently excludes one known failing test:

- `tests/api/test_demo_seed.py::test_demo_seed_surfaces_in_camera_and_observability_apis`

That exclusion is intentional and documented. The test currently depends on a time-sensitive observability expectation in the demo-seed path and should be fixed separately rather than hidden behind a vague “green” claim.

Repo-wide Ruff enforcement is not enabled yet. The repository still carries substantial pre-existing lint debt outside the maintained deployment-hardening files above, so CI scopes linting to the backend files that this foundation keeps healthy today.

## What is still not production-ready

- No Dockerfiles or container orchestration manifests are shipped yet
- No persistent LangGraph checkpoint backend is wired
- No cloud-specific deployment manifests or secret-manager integration are included
- No identity-backed auth or session management exists yet
- No hardened multi-process worker supervisor or deployment packaging is provided for stream workers

Those gaps are deliberate. The current foundation is meant to make CI, local validation, and small pre-production dry runs safer without overstating infrastructure maturity.