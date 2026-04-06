# Flow Analytics

This module provides deterministic lane occupancy, queue, congestion, and utilization analytics.

Current scope:

- per-lane rolling-window occupancy analysis
- queue detection from stop-line or configured queue-anchor geometry
- congestion classification from occupancy and queue persistence
- dashboard-friendly and hotspot-friendly typed outputs
- no phase timing, cycle length, split-failure, queue-clearance, or adaptive signal-optimization metrics yet

Design constraints:

- no opaque scoring; thresholds and assumptions stay explicit
- works from tracked-object inputs and configured lane geometry
- suitable for live/local analytics, review tooling, and caller-owned trend summaries when persisted elsewhere

Metric definitions:

- `occupancy_ratio` is the time-weighted fraction of the observed window during which at least one tracked object occupied the lane polygon
- `utilization_ratio` is `average_active_track_count / nominal_capacity_count` when nominal capacity is configured; it is a lane-load heuristic, not a calibrated saturation, LOS, or throughput metric
- `queue_duration_seconds` is the elapsed time for the current uninterrupted detected queue episode; it resets when the queue breaks
- `congestion_level` is a threshold bucket derived from occupancy and queue persistence; it is not a travel-time, delay, or optimization score
- queue distance and queue extent remain pixel-space values unless a caller maps them through external calibration

Not in scope:

- controller-plan analytics such as cycle length, green split, or phase duration
- split-failure, queue-clearance, or progression scoring
- adaptive timing recommendations or closed-loop optimization claims