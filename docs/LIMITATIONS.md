# Limitations

Honest assessment of what TrafficMind does not yet do, where implemented features have known constraints, and what would need to change for production deployment.

## Perception Pipeline

### No dedicated plate detector

OCR currently operates on crops derived from generic vehicle detection bounding boxes. There is no specialized plate-localization model in the hot path. This means plate OCR quality depends entirely on the upstream detector's ability to provide tight vehicle crops that include readable plate regions.

**Impact:** OCR confidence and recall are lower than they would be with a purpose-built plate detector.

**Extension point:** `services/vision/interface.py` supports pluggable detector backends. A plate-detection model could be added alongside the existing YOLO backend.

### Traffic-light classification is HSV-based

Traffic-light state is classified via HSV pixel voting within detected light bounding boxes, with temporal smoothing. This works reliably for standard signal configurations but is not a trained state model.

**Known weaknesses:**
- Arrow signals are not distinguished from circular signals
- LED arrays with unusual color temperature may confuse HSV thresholds
- Partially occluded lights degrade classification accuracy

**Extension point:** `services/signals/classifier.py` is isolated and can be replaced with a learned model without touching the rest of the pipeline.

### Speed estimation is not enforcement-grade

`services/motion/` provides three accuracy tiers:

| Tier | Source | Suitability |
|---|---|---|
| Rough | Pixel-space displacement | Dashboard indicators only |
| Approximate | Operator-supplied scale factor | Analytics and screening |
| Calibrated | Validated camera calibration | Enforcement-ready (with calibration validation) |

Without validated calibration inputs, speed estimates should be used for analytics and candidate screening — not for issuing citations.

### Live perception deployment is foundational

The stream worker, frame pipeline, and perception composition work locally and in tests. Production deployment hardening (container packaging, GPU resource management, multi-node orchestration, crash recovery) is not complete.

## Backend API

### Violation list endpoint returns 501

`GET /api/v1/violations` is scaffolded and returns HTTP 501. Individual violation evidence endpoints (`POST /GET /api/v1/violations/{id}/evidence`) work. A full violation review surface (list, filter, status transitions) is planned but not implemented.

### Alert delivery is not wired

The alerting system implements:
- Policy configuration (source, condition, severity threshold, dedup, cooldown)
- Signal evaluation and dedup
- Escalation ladders with scheduled level-ups
- Delivery planning with target assignment
- Full audit trail

What it does **not** do: actually send outbound notifications. The system records planned `AlertDeliveryAttempt` rows, but no email, webhook, SMS, Slack, or Teams sender integration exists. The delivery state stays at `planned`.

### Case export does not produce binary archives

`POST /api/v1/exports` generates structured bundles in three formats:

| Format | Status |
|---|---|
| `json` | Complete — full structured payload |
| `markdown` | Complete — embedded in the JSON bundle |
| `zip_manifest` | Placeholder — lists archive contents but does not produce a downloadable zip file |

Binary archive generation and PDF rendering are not implemented. The zip manifest is a structured plan for future packaging.

### Evidence asset URIs are references, not served files

Evidence manifests and case exports reference assets via URIs (`evidence://...` for planned assets, direct URIs for available assets). The API does not serve media files. Asset resolution depends on a configured storage backend that does not yet exist in the deployment layer.

## Database

### SQLite limitations in production

Local development uses SQLite via `aiosqlite`. SQLite does not support concurrent writes, advisory locks, or the full range of PostgreSQL features used by Alembic and SQLAlchemy. Production deployment should use PostgreSQL.

### No database connection pooling configuration

The current setup creates an engine with default pool settings. Production deployments need explicit pool sizing, connection timeouts, and health checks.

## Workflows

### Checkpoint persistence is in-memory

LangGraph workflow state lives in process memory. If the workflow service restarts, interrupted workflows are lost. A durable checkpoint backend (e.g., Redis, PostgreSQL) is needed for production.

### No task queue

Workflow execution is synchronous within request handling. Long-running workflows block the HTTP response. A proper async task queue is planned for production.

### No model-backed workflow provider

The workflow service currently runs only with the deterministic `HeuristicWorkflowProvider`. The provider abstraction is in place, but no model-backed backend is wired yet.

## Frontend

### Incomplete operator surface

The frontend contains:
- Operations dashboard with camera markers and hotspot overlays
- Camera detail route with stream health
- Event filtering and navigation

It does **not** contain:
- Violation review and investigation UI
- Workflow monitoring dashboard
- Alert management interface
- Analytics chart rendering (foundation present, rendering incomplete)
- Case export download interface

### Junction grouping is heuristic

Camera markers are grouped into "junctions" by matching `location_name` strings. This is a text-proximity heuristic, not geospatial clustering. Cameras at the same intersection with different location name formats will not be grouped correctly.

## Infrastructure

### No CI/CD pipeline

There is no GitHub Actions, GitLab CI, or equivalent pipeline configured. Tests run locally only.

### No container packaging

Docker assets are placeholder READMEs. No Dockerfiles, docker-compose, or Kubernetes manifests exist.

### No deployment automation

No Terraform, Ansible, CloudFormation, or equivalent deployment configuration exists.

### No observability integration

Application metrics, structured logging, and distributed tracing are not exported to external observability systems (Prometheus, Grafana, Datadog, etc.). Health signals exist internally but are not exposed via standard observability protocols.

## Data and Model Gaps

### No model training infrastructure

The repository consumes pre-trained model weights but does not include dataset management, annotation tooling, or training pipelines.

### No historical lane-snapshot persistence

Lane-flow analytics (`services/flow/`) compute real-time occupancy, queue, and congestion signals. These signals are currently ephemeral — no historical lane snapshot store exists for retrospective analysis or congestion hotspot trending.

### No adaptive signal timing analytics

TrafficMind can classify current traffic-light state and ingest controller-fed
phase/state snapshots, but it does not yet persist signal timing histories or
compute cycle length, phase duration, green splits, split failure,
queue-clearance rate, delay, progression quality, or adaptive timing
recommendations. Signal-related analytics today are limited to current-state
understanding plus lane occupancy, queue, and congestion heuristics.

### Demo data uses placeholder assets

Demo mode seeds realistic records but uses `demo://` URIs for all media assets. No sample images or video clips are bundled. Screenshots of the demo are screenshots of metadata and health dashboards, not rendered evidence frames.

## Security

### No authentication or identity-backed authorization

The API still has no auth or session layer. Sensitive routes now enforce a coarse request-declared role-to-permission matrix, but callers can still self-assert those roles. Production deployment still requires real authentication (for example OAuth2 or API keys) and identity-backed authorization.

### No rate limiting

No request rate limiting is configured on any endpoint.

### Secrets management is environment-only

Secrets (API keys, database credentials) are loaded from environment variables. No vault integration or secret rotation mechanism exists.
