# Services

This directory contains the deterministic backend service modules used by the API, worker processes, and workflow grounding layers.

These modules should remain free of higher-level workflow orchestration. The workflow graphs live under `apps/workflow/`; the code here should stay focused on deterministic behavior, typed contracts, and testable business logic.

Current service areas:

- `vision/` — detection-facing schemas and service logic.
- `tracking/` — multi-object tracking abstractions and tracking service behavior.
- `signals/` — traffic-light perception, temporal smoothing, and controller-feed arbitration foundation.
- `rules/` — deterministic scene/rule evaluation and flagship temporal rules.
- `dwell/` — stationary-object and dwell-time analysis for scenarios such as illegal parking and stalled vehicles.
- `ocr/` — OCR invocation and plate-text normalization helpers.
- `anpr/` — persisted plate-search logic and watchlist-facing helpers.
- `evidence/` — evidence-manifest packaging and render metadata assembly.
- `health/` — camera and stream health assessment.
- `motion/` — calibration-aware speed estimation, direction labeling, and screening helpers.
- `flow/` — lane occupancy, queue-length, congestion, and utilization analytics.
- `hotspot/` — hotspot aggregation, ranking, trend deltas, and recurring-issue summaries.
- `reid/` — cross-camera entity association and re-identification planning.
- `streams/` — stream ingestion/orchestration foundations and runtime metrics.
- `evaluation/` — fixture-driven benchmarking helpers for detection, tracking, OCR, rule sanity, and signal classification regression checks.

Important limitations:

- `ocr/` does not imply a complete live plate-detection pipeline by itself; upstream crop generation is still a separate concern.
- `signals/` provides deterministic state inference, but it is not a substitute for a dedicated trained signal-state model.
- `evaluation/` is for repeatable local comparison and regression control. It does not justify external benchmark claims beyond the supplied fixtures.
