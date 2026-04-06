# Signal Integration Foundation

TrafficMind supports a vendor-neutral foundation for external traffic-signal controller data. The design goal is to improve red-light and pedestrian-signal rule quality where controller-fed phase/state data exists, without hiding disagreement with vision-derived signal understanding.

## Separation Of Sources

TrafficMind keeps the two signal sources distinct:

- `vision_signal_states` — traffic-light state derived from detector crops plus temporal smoothing
- `controller_signal_states` — normalized external controller-fed phase/state records
- `signal_states` — resolved rules-facing state after arbitration
- `signal_conflicts` — explicit disagreements between fresh controller and vision sources

This means controller data never silently overwrites vision state in storage or review payloads.

## Supported Integration Patterns

The current foundation supports four integration patterns without assuming a vendor protocol:

1. File feed payloads
2. Polling endpoint fetches
3. Webhook or direct event push
4. Mock/local simulator cycles

All four normalize into the same controller event shape before arbitration.

## Normalized Controller Event Shape

Each normalized controller event can carry:

- `camera_id` — optional camera linkage when one controller feed is tied to one camera or approach
- `junction_id` — optional intersection/junction identifier when the feed is junction-scoped
- `controller_id` — stable external controller identifier
- `phase_id` — external phase identifier
- `phase` — `vehicle`, `pedestrian`, or `unknown`
- `state` — `red`, `yellow`, `green`, or `unknown`
- `timestamp` — event time used for staleness checks
- `source_type` — `file_feed`, `polling_endpoint`, `webhook_event`, or `mock_simulator`
- `confidence` — source-provided confidence when available
- `trust_score` — operator/service trust weighting used conservatively during arbitration
- optional infrastructure links: `stop_line_id`, `crosswalk_id`, `lane_id`, `head_id`

Because TrafficMind does not yet have a dedicated junction/controller schema in the database, `junction_id`, `controller_id`, and `phase_id` remain normalized application-layer fields for now.

## Arbitration Strategy

TrafficMind supports three rules-facing modes:

### `vision_only`

- Uses only vision-derived signal state
- Ignores controller-fed state for resolution
- Still allows controller data to be inspected separately through API responses if present

### `controller_only`

- Uses only controller-fed signal state
- Useful when signal heads are hard to see, occluded, or not configured in vision
- Still keeps controller provenance explicit in rule explanations and evidence metadata

### `hybrid`

- Uses both sources where available
- Agreement between usable controller and vision sources strengthens the resolved state
- If only one source is usable, that source is used
- If both usable sources conflict, the resolved state becomes `UNKNOWN` and a conflict record is emitted

## Conservative Rules

TrafficMind handles uncertainty conservatively:

- stale controller data does not silently drive red-light logic
- low-confidence controller data remains visible in raw controller state, but does not silently become resolved signal state
- conflicting fresh controller and vision states do not silently prefer controller or vision in hybrid mode
- explicitly linked stop-line or crosswalk signals do not backfill unrelated zones when an exact match is missing
- phase-level primary signal aliases are withheld when multiple same-phase signals are present and no exact linkage resolves the ambiguity
- rules continue to treat `UNKNOWN` as non-actionable for flagship red-light logic

This protects against false positives while still allowing controller-only deployments where vision signal understanding is unavailable.

## API Surface

Current backend endpoints:

- `POST /api/v1/signals/controller/events` — ingest a normalized controller batch
- `POST /api/v1/signals/controller/file-feed` — parse and ingest JSON/JSONL file payloads
- `POST /api/v1/signals/controller/poll` — fetch and ingest one polling endpoint payload
- `POST /api/v1/signals/controller/mock/simulate` — build or ingest a mock controller snapshot
- `GET /api/v1/signals/controller/snapshot` — inspect normalized controller-fed state
- `POST /api/v1/signals/resolve` — preview the resolved rules-facing `SceneContext`

`POST /api/v1/signals/resolve` is intentionally scope-sensitive. If no `camera_id` or `junction_id` is supplied, the service does not automatically merge every controller state currently held in memory into the preview.

## Pipeline Integration

`FramePipeline` can now operate in:

- vision-only mode (existing behavior)
- controller-only mode when controller state is supplied without visible signal heads
- hybrid mode when both vision and controller state are available

The pipeline keeps the raw vision snapshot separate from any controller snapshot. The rules engine still consumes only the resolved `SceneContext`.

## Provenance In Rule And Evidence Output

Where signal-dependent violations are created, TrafficMind now carries signal provenance in rule metadata, including:

- signal source kind
- observed source list
- controller id
- junction id
- phase id
- integration mode
- conflict reason when relevant

Evidence manifests surface those details through signal overlay metadata so review tooling can show whether a red-light determination came from vision, controller, or a resolved hybrid state.

## Current Limitations

- The controller state store is in-memory only.
- No vendor-specific controller adapters are bundled yet.
- No durable polling scheduler or inbound event queue is included yet.
- No canonical database model exists yet for junctions, controllers, phases, or signal plans.
- Hybrid conflict handling is intentionally conservative and may yield `UNKNOWN` more often than an operator would choose manually.

This is intentional. The current goal is a safe, explicit integration foundation rather than pretending a production controller ecosystem is already finished.
