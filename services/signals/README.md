# Traffic-Light Signal Module

> `services/signals/` — classifies traffic-light colour from detector crops
> and produces temporally-smoothed signal state for the rules engine.

This module now also includes a vendor-neutral controller integration foundation.
Controller-fed state is kept separate from vision-derived state, then merged
conservatively into the rules-facing `SceneContext`.

## Architecture

```
YOLO detector                     ┌─────────────────────┐
 ─ ObjectCategory.TRAFFIC_LIGHT ──▶  SignalClassifier    │  (per-crop colour vote)
                                  │  (HSV histogram)     │
                                  └────────┬────────────┘
                                           │
                                  ┌────────▼────────────┐
                                  │  SignalStateTracker  │  (per-head hysteresis)
                                  │  (majority vote +    │
                                  │   transition thresh) │
                                  └────────┬────────────┘
                                           │
                           ┌───────────────┼─────────────────┐
                           ▼               ▼                 ▼
                  SignalSceneSnapshot   SceneContext      PerceptionEventBatch
                  (all heads & obs)   (for rules engine) (embedded in batch)
```

## How signal state connects to rule evaluation

The rules engine (`services/rules/`) evaluates traffic violations against a
`SceneContext` that now includes both phase-specific primary states and a
typed per-head `signal_states` list. Three evaluators depend on it:

| Rule | What it checks |
|------|----------------|
| `evaluate_red_light` | Vehicle crosses stop-line when `traffic_light_state == RED` |
| `evaluate_stop_line_crossing` | Stop-line crossing (optionally requires red light) |
| `evaluate_pedestrian_on_red` | Pedestrian in crosswalk when `traffic_light_state == RED` |

Before this module, `SceneContext.traffic_light_state` was always injected
externally (hardcoded or manual).  Now the pipeline automatically populates
it from the live camera feed:

1. **Detection**: YOLO detects bounding boxes with `category=TRAFFIC_LIGHT`.
2. **Classification**: `SignalClassifier.classify(crop)` → `SignalColor` + confidence.
3. **Smoothing**: `SignalStateTracker` applies majority-vote + hysteresis over
   a configurable window (default: 5 frames, transition threshold: 3).
4. **Output**: `SignalStateTracker.to_scene_context()` → `SceneContext` with the
  smoothed vehicle state, the smoothed pedestrian state, and per-head linked
  signal states ready for `RulesEngine.evaluate()`.

`to_scene_context()` only uses an explicitly configured `phase=VEHICLE`
signal head. If a head is unlabeled or pedestrian-phase, the scene context
stays `UNKNOWN` so vehicle rules do not run off ambiguous signal evidence.

Pedestrian-on-red evaluation is resolved separately from vehicle red-light
evaluation. A vehicle red signal does not automatically imply a pedestrian
red signal.

## External controller integration foundation

The module also supports normalized controller-fed signal input through
`services/signals/integration.py`.

Supported integration patterns:

- file feed payloads (JSON or JSONL)
- polling endpoint fetches
- webhook/event push input
- mock/local simulator cycles

Normalized controller records carry:

- `camera_id` and optional `junction_id`
- `controller_id`
- `phase_id`
- `phase` and `state`
- `timestamp`
- `source_type`
- `confidence` and `trust_score`
- optional `stop_line_id`, `crosswalk_id`, `lane_id`, or `head_id`

These controller records are current-state observations, not timing analytics.
TrafficMind preserves `phase_id` for provenance and linkage, but it does not
yet derive cycle length, phase duration, green splits, split failure,
queue-clearance rates, or adaptive timing recommendations from controller
state.

The merge boundary is still `SceneContext`:

- `vision_signal_states` keep raw vision-derived state
- `controller_signal_states` keep raw controller-fed state
- `signal_states` is the resolved rules-facing view
- `signal_conflicts` records disagreements instead of hiding them

Supported arbitration modes:

- `vision_only`
- `controller_only`
- `hybrid`

Hybrid mode is conservative by default:

- if both sources agree and are usable, the resolved state is accepted
- if only one source is fresh and above threshold, that source is used
- if both usable sources conflict, the resolved state becomes `UNKNOWN` and a conflict record is emitted
- stale or low-confidence controller data is kept visible in raw state but does not silently drive red-light logic
- a linked stop-line or crosswalk signal does not silently fall back to another unrelated linked signal when an exact infrastructure match is missing
- when multiple same-phase signals are present, TrafficMind does not invent a single primary state unless the linkage is unambiguous

## Signal head linkage

Each signal head can be linked to infrastructure via `SignalHeadConfig`:

| Field | Links to |
|-------|----------|
| `lane_id` | A lane zone (for lane-specific signal logic) |
| `stop_line_id` | A stop-line zone (for red-light violation targeting) |
| `crosswalk_id` | A crosswalk zone (for pedestrian-on-red targeting) |
| `phase` | `VEHICLE` vs `PEDESTRIAN` (never conflated) |

When no configuration is provided, heads are auto-discovered via spatial
matching (IoU against previously-seen bounding boxes) and assigned temporary
IDs. Those anonymous heads are still emitted in `SignalSceneSnapshot` and in
`SceneContext.signal_states`, but they do not drive vehicle-rule or
pedestrian-rule state until a `SignalHeadConfig` labels the relevant head and
links it to the proper stop-line or crosswalk.

Runtime configuration can be supplied per job via `JobSpec.source_config`:

```json
{
  "signal_heads": [
    {
      "head_id": "main-nb-veh",
      "phase": "vehicle",
      "anchor_bbox": {"x1": 820, "y1": 140, "x2": 860, "y2": 260},
      "lane_id": "lane-nb-1",
      "stop_line_id": "stopline-nb",
      "crosswalk_id": "crosswalk-nb"
    }
  ]
}
```

## Configuration (`SIGNAL_` env prefix)

| Variable | Default | Description |
|----------|---------|-------------|
| `SIGNAL_BACKEND` | `hsv_histogram` | Classifier backend |
| `SIGNAL_CONFIDENCE_THRESHOLD` | `0.35` | Min confidence to accept a colour |
| `SIGNAL_MIN_CROP_PIXELS` | `12` | Min crop dimension to attempt classification |
| `SIGNAL_SMOOTHING_WINDOW` | `5` | Frames in the majority-vote window |
| `SIGNAL_TRANSITION_THRESHOLD` | `3` | Consecutive votes required to change state |
| `SIGNAL_UNKNOWN_AFTER_MISSED_FRAMES` | `10` | Revert to UNKNOWN if unobserved |

## Limitations (honest)

- **HSV classifier only**: The built-in backend uses HSV pixel voting.  It
  works well for tightly-cropped, well-lit signal heads but struggles with
  heavy glare, night washout, occluded or arrow-shaped signals.
- **No arrow/phase detection**: The classifier sees colour, not shape.
  Left-turn arrows, flashing signals, and multi-aspect heads are not
  distinguished.
- **Depends on detector quality**: If YOLO delivers poor bounding boxes
  (too large, partially occluded, wrong object), classification degrades.
- **SceneContext requires explicit vehicle labeling**: if no signal head is
  configured as `phase=VEHICLE`, the rules-facing state remains `UNKNOWN` on
  purpose. Multi-intersection or multi-approach scenes need explicit
  `SignalHeadConfig` per approach.
- **Controller integration is foundation-only**: TrafficMind does not yet ship
  vendor-specific protocol adapters or durable controller-state persistence.
- **Hybrid conflict handling is conservative**: conflicting fresh controller
  and vision states resolve to `UNKNOWN` rather than silently preferring one.
- **No canonical junction model exists yet**: controller feeds can carry a
  `junction_id`, but the main API data model still anchors infrastructure on
  cameras and zones.

See `docs/SIGNAL_INTEGRATION.md` for integration patterns, arbitration, API
endpoints, and current limitations.

## Extending with an ML classifier

Register a new backend:

```python
from services.signals.classifier import SignalClassifier, SignalClassifierRegistry

class MyModelClassifier(SignalClassifier):
    def __init__(self, settings):
        # load your model
        ...
    def classify(self, crop):
        # run inference
        ...

SignalClassifierRegistry.register("my_model", MyModelClassifier)
```

Then set `SIGNAL_BACKEND=my_model`.
