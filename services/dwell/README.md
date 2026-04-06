# Dwell Analytics

This module provides deterministic stationary-object and dwell-time analysis.

Current scope:

- stationarity assessment from tracked-object trajectories
- scenario-specific dwell thresholds for illegal parking, no-stopping, bus-stop occupation, and stalled vehicles
- structured outputs that explain why a track is below threshold, in grace period, a candidate, or a violation

Design constraints:

- pure analysis only; no database access or side effects
- reusable from the rules engine and offline analytics
- thresholds stay explicit and tunable per deployment, camera, or zone