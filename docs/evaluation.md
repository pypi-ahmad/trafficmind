# Evaluation And Benchmark Summaries

This project now exposes a practical evaluation summary foundation for debugging model and rule behavior without pretending to be a full experiment platform.

The UI and API are intentionally grounded in two local sources only:

- The checked-in fixture suite at `tests/fixtures/evaluation/benchmark_suite.json`
- Optional stored evaluation artifact files in the configured evaluation artifact directory

If there is no stored artifact carrying model-version tags, camera labels, manual review notes, or workflow summaries, the dashboard shows those gaps explicitly.

## What the evaluation summary includes

- Detection sanity metrics
- Tracking consistency checks
- OCR quality samples
- Rule validation scenarios
- Signal classification checks
- Manual review summaries when an artifact explicitly includes them
- Workflow summaries when an artifact explicitly includes them
- Placeholder sections for categories that are still not available

It does not claim:

- Training orchestration
- Experiment scheduling
- Historical benchmark leaderboards
- Production-wide field accuracy measurements
- Registry linkage unless an artifact explicitly records registry or version metadata

## Backend route

The frontend evaluation page reads from:

- `GET /api/v1/analytics/evaluation`

That route combines:

- A live deterministic report computed from the configured fixture suite path
- Any stored artifact JSON files found in the configured evaluation artifact directory

Relevant backend settings:

- `evaluation_fixture_suite_path`
- `evaluation_artifact_dir`

## Running the fixture suite directly

Run the deterministic benchmark report against the checked-in fixture suite:

```bash
python -m services.evaluation tests/fixtures/evaluation/benchmark_suite.json
```

That command prints a JSON benchmark report to stdout.

## Writing a stored evaluation artifact

Use the CLI output flag when you want the UI and API to discover a persisted local result.

Example:

```bash
python -m services.evaluation tests/fixtures/evaluation/benchmark_suite.json --output outputs/evaluation/fixture-baseline.json --artifact-label fixture-baseline --model-version detector:yolov8n-2026-04-06 --model-version rules:baseline-2026-04-06 --camera-label cam-a-northbound --manual-review-summary "Reviewed against the fixture suite only; no field sample included." --workflow-summary "Cold-path review workflow was not exercised for this artifact."
```

Stored artifact metadata can include:

- Artifact label
- Model version names
- Model registry IDs
- Camera IDs and labels
- Manual review summary
- Workflow summary
- Freeform notes

Those fields are optional. When omitted, the UI leaves the corresponding filters or sections empty instead of fabricating values.

The task-type filter only exposes a manual/workflow-notes option when stored artifacts actually include those notes.

## How to interpret the UI

The evaluation page separates information into three buckets.

### Real measured metrics

These are directly computed from fixture cases or loaded from stored report artifacts.

- Detection cards show detection precision, detection recall, matched IoU, and predicted-versus-expected count mismatches
- Tracking cards show assignment coverage, ID switches, fragmentation notes, and a continuity score derived from observed assignments minus ID switches over expected observations
- OCR cards show exact normalized plate-text match rate, average character accuracy, mean confidence, and sample rows when available
- Rule cards show expected-event match rate, missing keys, unexpected keys, and expected-versus-actual outcome counts
- Signal cards show sample accuracy, per-class accuracy, and confusion entries recorded for misclassified samples

The visible measured-row count in the UI is a count of filtered per-task result rows, not a count of distinct production scenarios.

### Manual review and workflow notes

These are human-authored summaries attached to a stored artifact.

They are not merged into measured metrics, and they should not be read as quantitative benchmark outputs.
The scenario filter does not apply to this notes-only view because those summaries are artifact-level metadata rather than per-scenario measurements.

### Placeholders

These exist to keep the dashboard honest.

If no workflow evaluation summaries, manual notes, model-version tags, or camera tags exist in the local artifact set, the UI says that directly instead of simulating a fully populated benchmark console.

Date filters apply to `observed_at` when an artifact provides it, and fall back to `generated_at` otherwise.

## Recommended workflow

1. Use the fixture suite to validate regression-sensitive logic changes.
2. Write stored artifacts when you want to preserve a local result with model or camera metadata.
3. Open the frontend evaluation page to compare measured scenario rows with any attached manual notes.
4. Treat the page as a debugging and trust surface, not as a claim of deployment-wide model performance.