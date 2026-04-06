# Model And Config Provenance

TrafficMind now has a lightweight registry for the exact model or configuration bundle that produced persisted pipeline outputs. The goal is reproducibility and auditability for stored detections, OCR reads, rule-derived violations, and evidence manifests without pretending the repo is a full experiment platform.

## Goals

- capture the detector, tracker, OCR, rules, and evidence-builder configuration used for each stored output
- make later review and export flows able to answer "what produced this record?"
- support comparison of active versus retired configs without adding training orchestration or benchmark leaderboards
- keep the implementation small enough to stay honest about what the repo does today

## What The Registry Stores

Each `model_registry_entries` row represents one immutable versioned bundle with:

- `task_type` for the broad pipeline stage (`detection_model`, `tracking_config`, `ocr_model`, `rules_config`, `evidence_config`)
- `model_family` for the backend or logical family name
- `version_name` for the specific runtime version or bundle label
- `config_bundle` for thresholds, backend settings, and rule/evidence options
- `config_hash` for deduplication of identical bundles
- `is_active` for the currently preferred bundle in that scope
- `notes` and `entry_metadata` for audit-friendly annotations

The registry is intentionally runtime-oriented. It tracks what was deployed or configured, not how a model was trained.

## Output Provenance Links

Persisted outputs now carry direct foreign keys to the registry:

- `detection_events.detector_registry_id`
- `detection_events.tracker_registry_id`
- `plate_reads.ocr_registry_id`
- `violation_events.rules_registry_id`
- `evidence_manifests.evidence_registry_id`

That gives every major stored artifact a stable link back to the bundle that produced it.

For audit readability, the write paths also embed a compact provenance snapshot alongside those foreign keys in the persisted JSON payloads. That snapshot includes the registry id, task type, model family, version name, and config hash, so basic review and export flows do not need an extra join just to interpret what produced a record.

## Runtime-Derived Entries

The current foundation auto-registers entries from the active runtime settings when records are persisted:

- detector entries come from the current vision settings and resolved YOLO device/model path
- tracker entries come from the active tracking backend settings
- OCR entries come from the active OCR backend settings
- rules entries come from rules-engine settings plus the concrete rule config attached to the emitted violation
- evidence entries come from evidence-manifest defaults and the privacy policy used to package the manifest

This keeps provenance aligned with what the system actually used at write time.

## API Surface

The admin/audit surface is intentionally small:

- `GET /api/v1/model-registry` lists entries for audit-capable roles
- `GET /api/v1/model-registry/{id}` fetches one entry
- `POST /api/v1/model-registry` creates or resolves a versioned entry for admin roles
- `PATCH /api/v1/model-registry/{id}` updates admin-facing status or notes

Write access requires the `manage_model_registry` permission. Audit-oriented reads reuse the sensitive-audit permission boundary.

## What This Does Not Claim

This foundation does not implement:

- model training pipelines
- experiment run scheduling
- metrics dashboards or leaderboard reporting
- automatic A/B traffic splitting
- full lineage across datasets, checkpoints, and offline evaluation jobs

Those can be added later if the product needs them. Today the registry is deliberately scoped to deployed runtime provenance and reproducible stored outputs.