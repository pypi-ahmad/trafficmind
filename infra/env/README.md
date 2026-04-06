# Environment Profiles

TrafficMind is still a local-first repository, but it now ships commit-safe profile templates for the run modes the code actually understands.

- `../../.env.example` — local baseline that preserves the current single-machine developer flow
- `dev.env.example` — CI and shared-development baseline
- `staging.env.example` — single-host pre-production planning template
- `prod.env.example` — single-host production planning template

These files are templates, not live secrets.

- Copy one into `.env`, or
- Render one with `python infra/scripts/render_env.py --profile <profile> --output .env`

The staging and prod templates are intentionally honest: they still leave the workflow service on in-memory checkpoints because the repository does not yet ship a persistent checkpoint backend. The readiness probes will report that gap instead of pretending the deployment is fully production-ready.