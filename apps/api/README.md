# API App

This app hosts the primary FastAPI service for TrafficMind.

Current responsibilities:

- versioned REST APIs under `/api/v1`
- persistence models and storage-backed service logic
- camera, stream, zone, ANPR, evidence, observability, hotspot, alerting, and export endpoints
- workflow-facing storage and review state
- integration with deterministic service modules under `../../services/`

This is the main backend runtime for local development and the current system of record for stored traffic events, violations, watchlist activity, and export bundles.
