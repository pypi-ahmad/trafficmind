# Scripts

Place repeatable local automation here.

Examples for later:

- environment bootstrap scripts
- model download and verification scripts
- database setup helpers
- local run orchestration

Current repeatable helper:

- `python -m apps.api.app.demo.seed --create-schema` — seed the local database with clearly labeled synthetic demo cameras, streams, zones, events, plate reads, violations, workflows, and observability-friendly heartbeats.
- `python -m apps.api.app.demo.seed --report-path demo-seed-report.json` — emit a JSON walkthrough report alongside the seeded synthetic dataset.
- `python infra/scripts/render_env.py --profile local --output .env` — materialize a commit-safe env profile into a working `.env` file.
- `python infra/scripts/doctor.py` — run cross-service configuration and readiness diagnostics for API, workflow, streams, and frontend. When `--env-file` is provided, that file overrides conflicting shell env vars for the diagnostic run.
- `python infra/scripts/run_checks.py --suite all` — run the repeatable local/CI validation surface. When rendered env files are present, the runner uses them instead of conflicting shell env values. Backend linting is intentionally scoped to the maintained deployment/runtime paths until broader repo-wide Ruff cleanup is completed, and the frontend suite validates `frontend/.env.local` before lint/build.
