# Documentation

## Architecture & Design

- [ARCHITECTURE.md](ARCHITECTURE.md) — System layers, hot/cold path boundary, design decisions, data flow
- [DATA_MODEL.md](DATA_MODEL.md) — All 22 ORM models, relationships, enums, migration history
- [INTEGRATIONS.md](INTEGRATIONS.md) — Core product vs advanced adapter foundations vs future enterprise integration points
- [evaluation.md](evaluation.md) — Fixture-backed evaluation summaries, stored artifact workflow, and interpretation guidance
- [PROVENANCE.md](PROVENANCE.md) — Model/config registry goals, runtime provenance links, and current scope limits
- [WORKFLOWS.md](WORKFLOWS.md) — LangGraph workflow definitions, human-in-the-loop, state management

## Operations

- [DEPLOYMENT.md](DEPLOYMENT.md) — Supported run modes, env profiles, readiness probes, CI scope, and remaining deployment gaps
- [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md) — Setup guide, environment variables, running services, demo data
- [LIMITATIONS.md](LIMITATIONS.md) — Known gaps, honest constraints, extension points

## Domain

- [camera-health.md](camera-health.md) — Health signal definitions, alert severities, configurable thresholds
- [evidence.md](evidence.md) — Evidence manifest structure, asset-key conventions, current limitations
- [anpr.md](anpr.md) — Plate search behavior, normalization rules, watchlist matching
- [SIGNAL_INTEGRATION.md](SIGNAL_INTEGRATION.md) — External controller patterns, arbitration strategy, API surface, limitations
- [notebooks.md](notebooks.md) — Colab MCP setup and local fallback

## Root-Level Documents

- `README.md` — Project overview, capabilities, quickstart
- `ROADMAP.md` — Phase-based development roadmap
- `CURRENT_STATE.md` — Implementation status audit
- `IMPLEMENTATION_PLAN.md` — Original architecture plan
