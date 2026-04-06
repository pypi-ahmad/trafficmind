# Workflows

TrafficMind uses [LangGraph](https://langchain-ai.github.io/langgraph/) for cold-path orchestration. Workflows operate on stored database records — they never touch raw frames or live inference state.

## Workflow Inventory

| Name | Type | Human Gate | Purpose |
|---|---|---|---|
| `incident_triage` | triage | Optional | Classify incident severity, recommend actions |
| `violation_review` | review | Required (configurable) | Recommend violation disposition, capture approval |
| `multimodal_review` | assist | No | Advisory operator copilot grounded in stored review metadata, manifests, and attached media |
| `daily_summary` | report | Optional | Summarize recent activity into a narrative report |
| `weekly_summary` | report | Optional | Weekly trend analysis over stored events |
| `hotspot_report` | report | Optional | Spatial analysis of recurring incident clusters |
| `operator_assist` | assist | No | Deterministic investigation search and grounded Q&A over stored records |

## Architecture

### Boundary Rule

**No workflow logic runs inside the per-frame inference loop.** The hot path (detection → tracking → rules → evidence) is fully deterministic. Workflows consume the output of the hot path after events are persisted.

### Components

| Component | File | Responsibility |
|---|---|---|
| Graph definitions | `apps/workflow/app/workflows/graphs.py` | LangGraph `StateGraph` builders for each workflow |
| State schemas | `apps/workflow/app/workflows/state.py` | TypedDict state models per workflow |
| Typed schemas | `apps/workflow/app/workflows/schemas.py` | Pydantic models for context, output, and trace |
| Workflow service | `apps/workflow/app/workflows/service.py` | Execution, resumption, graph registry |
| Repository | `apps/workflow/app/workflows/repository.py` | Load stored events/violations/workflows from DB |
| Reasoning provider | `apps/workflow/app/workflows/providers.py` | Deterministic heuristic reasoning backend |
| Multimodal review helpers | `apps/workflow/app/workflows/multimodal_review.py` | Advisory boundary, modality-aware grounding, and operator-action helpers |
| Quality checks | `apps/workflow/app/workflows/quality.py` | Post-generation validation |
| Operator assist | `apps/workflow/app/workflows/operator_assist.py` | Query planning and retrieval |

### API

Workflows are triggered through the workflow service API:

```
GET  /api/v1/health
GET  /api/v1/health/ready
GET  /api/v1/info
POST /api/v1/workflows/incident-triage
POST /api/v1/workflows/violation-review
POST /api/v1/workflows/multimodal-review
POST /api/v1/workflows/daily-summary
POST /api/v1/workflows/weekly-summary
POST /api/v1/workflows/hotspot-report
POST /api/v1/workflows/operator-assist
GET  /api/v1/workflows/runs/{run_id}
POST /api/v1/workflows/runs/{run_id}/resume
```

## Workflow Details

### Incident Triage

Classifies an incident (detection or violation) and recommends actions.

**Nodes:**
1. `analyze_incident` — Provider analyzes stored context, produces priority and recommended actions
2. `human_gate` — Optional interrupt for human review (skipped if request and recommendation both say no review needed)
3. `finalize` — Applies human decision (approve, reject, or approve-with-note); rejection escalates priority

**Input:** `IncidentTriageRequest` with camera, detection event, violation event, plate read, and evidence references

**Output:** `IncidentTriageOutput` with priority (low/medium/high/critical), summary, recommended actions, and operator brief

### Violation Review

Recommends a disposition for a reviewable violation with human-in-the-loop approval.

**Nodes:**
1. `analyze_review` — Provider examines stored violation context and evidence, recommends disposition
2. `approval_gate` — Human interrupt for approve/reject/override (configurable)
3. `finalize` — Applies human decision; rejection defaults to supervisor escalation; override uses human-provided disposition

**Input:** `ViolationReviewRequest` with violation record, detection event, plate read, evidence references, and review context

**Output:** `ViolationReviewOutput` with disposition (confirm_violation, dismiss_false_positive, need_more_evidence, escalate_supervisor), confidence, summary, evidence notes, and operator brief

### Multimodal Review

Advisory operator copilot for a stored violation. The workflow is grounded in persisted violation metadata, linked detection and plate records, evidence manifest references, prior review history, and any actually attached images or clips.

**Nodes:**
1. `prepare_grounding` — Build a modality-aware review packet from stored metadata, attached media references, manifests, and prior review history
2. `compose_review` — Provider produces an advisory review summary, likely cause, confidence caveats, recommended operator action, and escalation guidance

**Input:** `MultimodalReviewRequest` with `violation_event_id`, optional operator notes, and a toggle for prior review history

**Output:** `MultimodalReviewOutput` with `review_summary`, `likely_cause`, `confidence_caveats`, `recommended_operator_action`, `escalation_suggestion`, and separate `metadata_references`, `image_references`, `clip_references`, and `manifest_references`

Reference interpretation:
- `metadata_references` are non-rendered grounding inputs such as violation metadata, rule explanation fields, review notes, and timeline metadata
- `image_references` and `clip_references` can come from either direct source-record attachments or manifest-derived assets; inspect each reference's `source` and `available` fields before treating it as directly attached evidence
- `manifest_references` identify the persisted evidence manifests that link the operator back to the full structured evidence package

**Safe Usage Rules:**
- The workflow is advisory only and does not write a disposition back to `ViolationEvent`
- It never replaces deterministic rule evaluation or live perception logic
- It must call out when the review is metadata-only, or when only manifest-linked media exists and no direct attached images or clips are available
- It is violation-anchored: linked detection metadata is included when present, but the workflow does not infer a violation from raw detections alone

### Daily Summary

Aggregates recent activity into a narrative report.

**Nodes:**
1. `generate_summary` — Provider generates the daily narrative from repository-built context
2. `approval_gate` — Optional human publication gate
3. `finalize` — Applies reviewer note or publication hold when needed

**Input:** `DailySummaryRequest` with date and optional camera filter

**Output:** `DailySummaryOutput` with markdown report, date, camera scope, and statistics

### Weekly Summary

Weekly trend analysis with statistical comparison to the prior period.

**Nodes:**
1. `generate_summary` — Provider generates the weekly narrative from repository-built context
2. `approval_gate` — Optional human publication gate
3. `finalize` — Applies reviewer note or publication hold when needed

**Input:** `WeeklySummaryRequest` with week start date and optional scope

**Output:** `WeeklySummaryOutput` with markdown report, period boundaries, and trend statistics

### Hotspot Report

Identifies spatial clusters of recurring incidents.

**Nodes:**
1. `generate_report` — Provider generates the hotspot narrative from repository-built context
2. `approval_gate` — Optional human publication gate
3. `finalize` — Applies reviewer note or publication hold when needed

**Input:** `HotspotReportRequest` with time window and optional area filter

**Output:** `HotspotReportOutput` with markdown report, identified hotspots, and supporting statistics

### Operator Assist

Retrieval-first investigation workflow for operators. It converts narrow natural-language requests into explicit typed filters, executes structured searches over stored records, and answers only from the retrieved results.

Examples:

- `show trucks stopped in restricted zone last night`
- `find all red-light violations near Junction 4 this morning`
- `show plate reads similar to AB12 in the last 24 hours`

**Nodes:**
1. `plan_query` — Analyze the operator's question and map it to a deterministic retrieval plan
2. `retrieve_grounding` — Load records from the repository based on that plan
3. `compose_answer` — Provider composes a grounded response from retrieved records only

**Supported intents:**

- stored detection-event search
- stored violation search
- stored plate-read search
- explanation of a specific stored violation
- repeated-incident summary for a camera or junction scope

**Planner behavior:**

- extracts camera or junction hints from phrases such as `from`, `at`, and `near`
- resolves relative time windows such as `today`, `this morning`, `last night`, and `last/past N hours` or `days`
- supports typed filters for event type/status, violation type/status, plate status, object class, zone type, and exact or partial plate text
- maps stop-related phrases conservatively to stored stop-oriented violation types; it does not use vector search or free-form semantic inference

**Input:** `OperatorAssistRequest` with the operator's question and optional scope hints

**Output:** `OperatorAssistOutput` with answer text, interpretation notes, explicit record references, supporting evidence references, and grounding metadata

**Safe Usage Rules:**

- retrieval-first grounding is mandatory; the workflow does not invent telemetry or infer facts outside stored records
- vague requests that lack a concrete anchor, such as a `violation_event_id`, should escalate back to human review or the UI for clarification
- the workflow is not a replacement for live CV inference, detection, OCR, tracking, or rule evaluation

## State Management

Each workflow uses a TypedDict state model with:

- `request` — Input parameters
- `context` — Gathered data from the repository
- `trace` — Accumulated trace entries (uses an `Annotated[list, operator.add]` reducer for automatic append)
- `output` — Final workflow output
- Workflow-specific intermediate state (e.g., `recommendation`, `human_decision`)

## Human-in-the-Loop

Workflows that need human review use LangGraph's `interrupt()` mechanism:

1. The workflow reaches a gate node.
2. `interrupt()` halts execution and returns a `HumanReviewPrompt` with context and available options.
3. The caller resumes the workflow by submitting a `HumanReviewDecision` with the reviewer's choice.
4. The finalize node applies the decision to the output.

Human decisions include:
- `approved` — Boolean, whether the recommendation was accepted
- `reviewer` — Who made the decision
- `note` — Optional free-text comment
- `overrides` — Optional field-level overrides (e.g., alternate disposition)

## Trace and Audit

Every node appends structured trace entries:

```python
WorkflowTraceEntry(
    node="analyze_incident",
    message="Generated triage recommendation from stored incident context.",
    metadata={"priority": "high"},
)
```

The complete trace is available in the workflow output for audit and debugging.

## Quality Checks

Report-quality validation exists as a separate utility in `quality.py` and is covered by tests. It is not currently a node in the compiled workflow graphs.

The validator checks:

- Minimum length requirements
- Structure validation (expected sections present)
- Grounding check (output references stored records, not hallucinated data)

The validator is exercised in tests and can be run alongside generated outputs, but it is not automatically appended to workflow traces today.

## Repository Layer

`WorkflowRepository` loads stored records for workflow context:

- Camera metadata and configuration
- Detection events with optional filters (camera, time range, type)
- Violation events with review status
- Plate reads associated with events
- Shared detection-event, violation, and plate search helpers used by the API layer
- Evidence manifests
- Prior workflow runs

The repository uses the same async SQLAlchemy queries and search helpers as the API layer. This ensures workflows operate on the same data visible through the REST API.

## Reasoning Provider

`WorkflowReasoningProvider` defines the cold-path reasoning boundary:

- The only implemented backend today is `HeuristicWorkflowProvider`
- It is deterministic and local-first: no network model calls, no credentials required
- It receives structured Pydantic context objects and returns typed output schemas
- The provider boundary remains explicit so a model-backed backend can be introduced later without changing the graph shapes

## Current Limitations

- **Checkpoint persistence is in-memory.** Interrupted workflows survive within a process session but not across restarts.
- **No workflow queue.** Execution is synchronous within request handling. A proper task queue (e.g., Celery, Dramatiq) is planned for production.
- **No model-backed provider is wired.** The workflow abstraction exists, but only the deterministic `heuristic` backend is implemented.
- **Multimodal review is reference-based.** The workflow distinguishes metadata, manifests, attached images, and attached clips, but it does not decode pixels or render overlays itself.

## Golden-Path Walkthrough

Exercise the three core starter workflows locally (triage → review with interrupt/resume → daily summary):

```bash
# prerequisites: both services running, database seeded
python -m apps.api.app.demo.seed --create-schema
uvicorn apps.api.app.main:app --reload --port 8000 &
uvicorn apps.workflow.app.main:app --reload --port 8010 &

# grab a demo violation id
VID=$(curl -s http://localhost:8000/api/v1/violations | python -c "import sys,json;print(json.load(sys.stdin)['items'][0]['id'])")

# 1. triage — auto-completes, no human gate
curl -s -X POST http://localhost:8010/api/v1/workflows/incident-triage \
  -H "Content-Type: application/json" \
  -d "{\"violation_event_id\":\"$VID\",\"require_human_review\":false}" | python -m json.tool

# 2. violation review — pauses at approval gate
REVIEW=$(curl -s -X POST http://localhost:8010/api/v1/workflows/violation-review \
  -H "Content-Type: application/json" \
  -d "{\"violation_event_id\":\"$VID\",\"requested_by\":\"ops.lead\"}")
RUN_ID=$(echo "$REVIEW" | python -c "import sys,json;print(json.load(sys.stdin)['run_id'])")

# 3. resume the review
curl -s -X POST "http://localhost:8010/api/v1/workflows/runs/${RUN_ID}/resume" \
  -H "Content-Type: application/json" \
  -d '{"approved":true,"reviewer":"analyst.a","note":"Evidence looks consistent."}' | python -m json.tool

# 4. daily summary — runs to completion
curl -s -X POST http://localhost:8010/api/v1/workflows/daily-summary \
  -H "Content-Type: application/json" \
  -d '{"report_date":"2026-04-04","require_human_approval":false}' | python -m json.tool
```

See [apps/workflow/README.md](../apps/workflow/README.md) for the PowerShell equivalents.
