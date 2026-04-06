# Tests

This directory contains the repository regression surface for the deterministic services, backend API flows, and workflow service.

Current layout:

- `workflow/` — LangGraph workflow service tests, including grounded reporting and operator-assist flows.
- `rules/` — deterministic rule-engine tests, including flagship temporal rule coverage.
- `api/` — backend route, persistence, ANPR, evidence, observability, and hotspot analytics tests.
- `ocr/` — OCR service and normalization behavior.
- `tracking/` — tracking service behavior and continuity expectations.
- `motion/` — calibration-aware speed estimation, direction analytics, and screening helper tests.
- `flow/` — lane occupancy, queue, congestion, and utilization analytics.
- `hotspot/` — hotspot aggregation, trend deltas, recurring issues, severity weighting, and output helpers.
- `vision/` — detection-facing schemas and service behavior.
- `signals/` — signal classifier, state tracker, and HSV pipeline tests.
- `streams/` — stream orchestration, worker lifecycle, and perception pipeline tests.
- `health/` — health assessor, alert thresholds, and dashboard aggregation tests.
- `evaluation/` — fixture-driven evaluation foundation and metrics edge-case tests.
- `reid/` — multi-camera re-identification schemas, backends, and pipeline tests.
- `fixtures/` — reusable JSON sample data for evaluation and critical-logic regression checks.

Useful commands:

- `python -m pytest tests/workflow`
- `python -m pytest tests/rules tests/api/test_anpr.py tests/api/test_evidence.py`
- `python -m pytest tests/api/test_hotspot_api.py -q`
- `.\.venv\Scripts\python -m pytest tests/motion -q`
- `.\.venv\Scripts\python -m pytest tests/flow -q`
- `.\.venv\Scripts\python -m pytest tests/hotspot -q`
- `python -m pytest tests/evaluation/test_benchmarking_foundation.py`
- `python -m services.evaluation tests/fixtures/evaluation/benchmark_suite.json`

The JSON fixtures under `fixtures/` are intentionally deterministic. They are meant to support regression checks and benchmarking hygiene, not to stand in for production-scale ground-truth datasets.
