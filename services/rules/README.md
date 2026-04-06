# Rules Service

Purpose:

- zones, lines, stop-lines, and crosswalk evaluation
- deterministic traffic-rule checking
- violation generation from tracked scene state

This is the source of truth for rule correctness and must remain deterministic.

## Serious violation lifecycle

- `RulesEngine.evaluate_detailed()` now exposes two stages for the flagship signal-aware rules:
	- `pre_violations`: a candidate event was detected, but temporal confirmation is still pending.
	- `violations`: the candidate satisfied the configured confirmation thresholds and is now evidence-worthy.
- `RulesEngine.evaluate()` remains the compatibility API and returns confirmed violations only.
- The stateful candidate/confirmation flow currently applies to:
	- `stop_line_crossing`
	- `red_light`
	- `pedestrian_on_red`
- Confirmation is conservative by design. These rules require both a qualifying signal state and post-event persistence, such as elapsed frames, elapsed time, distance beyond the stop-line, or continued presence inside a linked protected area.
- Unknown or stale signal state does not create candidates for these flagship rules.

## Signal linkage

- Vehicle rules resolve signal state from the stop-line-linked vehicle head when available.
- Pedestrian rules resolve signal state from the crosswalk-linked pedestrian head when available.
- `SceneContext.signal_states` carries the full per-head view so multi-head scenes do not collapse into one ambiguous global colour.
