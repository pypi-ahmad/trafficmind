# Workflow App

This app hosts LangGraph-based cold-path workflows for TrafficMind.

Implemented workflows:

- `IncidentTriageWorkflow` — triages stored detection or violation records into operator-friendly summaries
- `ViolationReviewWorkflow` — reviews stored violation evidence and pauses for human approval before final disposition
- `MultimodalReviewWorkflow` — advisory operator copilot grounded in stored violation metadata, prior review history, evidence manifests, and attached media references
- `DailySummaryWorkflow` — produces a report-style daily summary over stored detections and violations
- `WeeklySummaryWorkflow` — 7-day aggregation covering totals, top locations, review backlog, watchlist matches, and camera health
- `HotspotReportWorkflow` — ranks cameras or zones by violation density over a configurable lookback window
- `OperatorAssistWorkflow` — deterministic natural-language planning over stored violations, cameras, detections, and evidence references

Scope for this service:

- incident triage
- false-positive review
- advisory multimodal review copilot
- operator assist
- report generation
- human-in-the-loop approval handling
- grounded natural-language query over stored events

Non-scope:

- per-frame detection
- object tracking
- OCR inference
- low-latency rule evaluation

The workflow layer consumes stored events, clips, metadata, and review context from the database. It must never sit in the real-time frame inference loop.

## Daily Summary

`DailySummaryWorkflow` produces a concise operator handoff report for a single day. It is grounded in stored detections, violations, review state, watchlist alerts, and camera health.

Graph nodes: `generate_summary` → `approval_gate` (optional interrupt) → `finalize`

Example invocation:

```json
POST /api/v1/workflows/daily-summary
{
  "report_date": "2026-04-04",
  "camera_id": null,
  "require_human_approval": false
}
```

Output includes:

- headline, narrative, `generated_at`, and export-ready `markdown`
- key totals for detections, violations, and open violations
- top violation categories and top cameras/junctions
- review backlog summary
- watchlist section when alerts are present
- camera health concerns and data gaps
- recommended follow-ups
- scope notes that explain current-state sections

## Multimodal Review

`MultimodalReviewWorkflow` assists a human reviewer on a single stored violation. It is violation-anchored and only uses persisted review data:

- violation metadata and linked detection metadata
- rule explanation fields from stored `ViolationEvent.rule_metadata`
- evidence manifest references and any asset URIs already attached to the record
- existing operator notes and prior workflow history when requested

Graph nodes: `prepare_grounding` → `compose_review`

Example invocation:

```json
POST /api/v1/workflows/multimodal-review
{
  "violation_event_id": "c7d96874-72dd-4dab-9f1e-e3421f385df4",
  "requested_by": "ops.lead",
  "operator_notes": "Check whether the clip confirms the stop-line crossing.",
  "include_prior_review_history": true,
  "prior_review_limit": 5
}
```

Output includes:

- `review_summary` and `likely_cause`
- `confidence_caveats` that explicitly call out metadata-only reviews or missing media
- `recommended_operator_action` and optional `escalation_suggestion`
- separate `metadata_references`, `image_references`, `clip_references`, and `manifest_references`
- `prior_review_history` and `audit_notes`

Reference semantics:

- `metadata_references` are non-rendered grounding inputs such as rule explanation fields, review notes, and timeline metadata
- `image_references` and `clip_references` may point to direct source-record attachments or manifest-derived assets; use each item's `source` and `available` fields to tell which is actually attached and openable
- `manifest_references` point back to the persisted evidence package for the violation

Boundary rules:

- advisory only: this workflow does not confirm, dismiss, or rewrite a violation disposition
- grounded only: it cannot invent scene facts beyond stored metadata and referenced evidence
- explicit modality split: metadata is separate from media references, and the workflow calls out when media is direct attachment versus manifest-linked evidence
- cold path only: it never runs in the live perception or rules hot path

## Weekly Summary

`WeeklySummaryWorkflow` aggregates a 7-day window of stored detections, violations, review backlog, watchlist alerts, and camera health into an operations-ready report.

Graph nodes: `generate_summary` → `approval_gate` (optional interrupt) → `finalize`

Example invocation:

```json
POST /api/v1/workflows/weekly-summary
{
  "week_ending": "2026-04-04",
  "require_human_approval": true
}
```

Output includes:

- headline, narrative summary, `generated_at`, and export-ready `markdown`
- total detections, violations, and open violations
- top violation types
- per-camera location summaries
- review backlog (open/under-review counts, oldest open, avg review hours)
- watchlist section (total alerts, open alerts, top reasons)
- camera health concerns (maintenance/disabled cameras)
- recommended follow-ups, scope notes, and data gaps

## Hotspot Report

`HotspotReportWorkflow` ranks violation hotspots over a configurable lookback window. It supports `group_by: "camera"` and `group_by: "zone"` so operations can review either camera-level or junction/zone-level concentration.

Graph nodes: `generate_report` → `approval_gate` (optional interrupt) → `finalize`

Example invocation:

```json
POST /api/v1/workflows/hotspot-report
{
  "report_date": "2026-04-04",
  "lookback_days": 7,
  "top_n": 5,
  "group_by": "zone",
  "require_human_approval": false
}
```

Output includes:

- headline, narrative, `generated_at`, and export-ready `markdown`
- ranked list of hotspot entries (camera or zone, violation count, open count, top violation types)
- total violations in window, total ranked groups, and total cameras with violations
- unassigned-zone counts when zone grouping is requested
- recommended follow-ups and data gaps

## Reporting Notes

- JSON output is the primary API response format; each report output also includes a `markdown` field for safe downstream email or document export.
- Camera incident digests are supported by scoping `DailySummaryWorkflow` or `WeeklySummaryWorkflow` to a specific `camera_id`.
- Review queue summary is represented in the structured `review_backlog` section of daily and weekly reports.
- Daily and weekly reports include scope notes because backlog, open-alert, and camera-health sections are current-state snapshots at generation time rather than historical reconstructions.
- LangGraph is used only for cold-path reporting and approval flows. It is not used for live event detection or violation firing.

## Operator Assist

`OperatorAssistWorkflow` is an operations-copilot graph for cold-path investigation only. It is designed for questions such as:

- `show trucks stopped in restricted zone last night`
- `show all red-light violations from Camera A in the last 2 hours`
- `show plate reads similar to AB12 in the last 24 hours`
- `why was this pedestrian-on-red alert fired`
- `summarize repeated incidents at this junction`

The graph has three nodes:

- `plan_query` — deterministically map the request into a typed retrieval plan
- `retrieve_grounding` — query structured backend sources first and collect referenced records
- `compose_answer` — produce a grounded answer with record ids, evidence references, and escalation guidance

Supported intents:

- stored detection-event search
- stored violation search
- stored plate-read search
- explanation of a specific stored violation
- repeated-incident summary for a camera or junction scope

Planner behavior:

- extracts camera or junction hints from `from`, `at`, and `near`
- resolves relative windows such as `today`, `this morning`, `last night`, and `last/past N hours` or `days`
- supports typed filters for event type/status, violation type/status, plate status, object class, zone type, and exact or partial plate text
- maps stop-related phrases conservatively to stored stop-oriented violation types rather than guessing beyond persisted rule outputs

Boundaries:

- retrieval-first grounding is mandatory; the graph does not invent telemetry or infer facts outside stored records
- vague requests that lack a concrete anchor, such as a `violation_event_id`, should escalate back to human review or the UI for clarification
- semantic/vector retrieval is not wired; investigation search remains deterministic and filter-backed
- the graph is not a replacement for live CV inference, detection, OCR, tracking, or rule evaluation

## Local development

Run the service from the repository root:

```bash
e:/Github/trafficmind/.venv/Scripts/python.exe -m apps.workflow.app
```

The default local mode uses:

- deterministic `heuristic` reasoning provider
- LangGraph `InMemorySaver` checkpointing

That means human-interrupt resume works while the process is still running. For cross-process durability, swap in a persistent LangGraph checkpoint backend later.

## HTTP API

With the service running on port `8010` by default:

- `GET /api/v1/health`
- `GET /api/v1/info`
- `POST /api/v1/workflows/incident-triage`
- `POST /api/v1/workflows/violation-review`
- `POST /api/v1/workflows/multimodal-review`
- `POST /api/v1/workflows/daily-summary`
- `POST /api/v1/workflows/weekly-summary`
- `POST /api/v1/workflows/hotspot-report`
- `POST /api/v1/workflows/operator-assist`
- `POST /api/v1/workflows/runs/{run_id}/resume`
- `GET /api/v1/workflows/runs/{run_id}`

## Configuration

See `.env.example` for supported environment variables. The key ones are:

- `WORKFLOW_DATABASE_URL`
- `WORKFLOW_PROVIDER_BACKEND=heuristic`
- `WORKFLOW_CHECKPOINT_BACKEND=memory`

The provider boundary is intentionally abstract so a model-backed backend can be introduced later without changing the graph structure.
