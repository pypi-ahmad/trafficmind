# Evidence Packaging Foundation

TrafficMind now persists a structured evidence manifest for each packaged violation or detection event. The goal is to make review evidence auditable and deterministic without forcing a full clip-rendering pipeline yet.

## What Gets Stored

Each manifest is persisted in `evidence_manifests` and linked back to the source subject with:

- `subject_kind` and `subject_id` to identify whether the manifest belongs to a detection event or a violation event
- supporting links to camera, stream, zone, detection, violation, and plate records when available
- `evidence_registry_id` to identify which evidence-builder and privacy-policy bundle generated the manifest
- `manifest_key` and `build_revision` for stable identity plus refresh history
- `manifest_data` JSON containing the review-ready evidence document

## Evidence Document Shape

Each stored document includes:

- `subject`: the source record, camera code, linked IDs, and high-level context like plate text or violation type
- `selection_policy`: deterministic frame-window rules and the reason the event frame was chosen
- `timeline`: pre-event, event, and post-event frames plus the clip window metadata
- `assets`: structured references for key frame snapshots, object crops, plate crops, clip windows, and timeline metadata
- `audit`: generator name, build revision, timestamps, and source-record identifiers
- `audit.provenance`: the model-registry entry id and config hash for the evidence builder bundle used at packaging time

## Provenance And Reproducibility

Evidence packaging is now part of the broader model/config provenance foundation.

- each manifest stores `evidence_registry_id` as a direct foreign key to `model_registry_entries`
- the embedded manifest document also records the evidence registry id and config hash under `audit.provenance`
- this makes later reviews and exports able to distinguish changes in evidence packaging defaults from changes in detector, OCR, or rules behavior

The current foundation tracks deployed runtime configuration only. It does not claim clip-rendering provenance for every downstream export artifact or a full lineage graph across offline experiments.

## Deterministic Selection Rules

Current frame selection is intentionally simple and stable:

- Violation manifests prefer `ViolationEvent.rule_metadata.frame_index`
- Detection manifests prefer `DetectionEvent.frame_index`
- Both fall back to linked records when necessary, and finally to timestamp-only manifests when no frame index exists
- Review timelines always select 2 pre-event frames, the event frame, and 2 post-event frames with a stride of 1
- Clip windows currently use a placeholder range of 12 lead frames and 12 tail frames around the event frame

## Asset Keys And Storage References

Asset keys are organized by camera, date, subject type, subject ID, and build revision:

```text
cameras/{camera_code}/{yyyy}/{mm}/{dd}/{events|violations}/{subject_id}/r{revision}/...
```

This keeps filenames traceable even before the final cloud-storage design exists.

- If an existing stored asset already exists, the manifest points to that real URI and marks `storage_state=available`
- If an asset still needs to be rendered later, the manifest emits a planned URI using the requested storage namespace, such as `evidence://...`, and marks `storage_state=planned`
- If asset data is embedded inline in the manifest metadata dict (e.g., timeline metadata), `storage_state=inline` — no external fetch is needed
- Manifests themselves are addressable internally through `evidence-manifest://{manifest_id}`

## Overlay-Ready Metadata

The packaging layer is ready for later rendering and export workflows. Render hints are scoped per asset kind:

- **Key-frame snapshots and clip windows** carry full overlay hints: detection/plate bounding boxes, zone geometry, signal-state annotations, and track paths
- **Object crops and plate crops** carry empty overlay hints — the crop region is the asset itself, so overlays are not applicable
- **Timeline metadata** carries no overlay hints — it is a JSON document, not a renderable image

Overlay payloads already preserve:

- detection and plate bounding boxes
- zone metadata and geometry from stored rule explanations
- signal-state annotations such as `signal_state_at_decision`
- track-path hooks when upstream metadata includes a path payload

The current foundation stores those hints; it does not yet rasterize them onto images or clips.

## Current Limitations

- Clip generation is placeholder-only unless a source clip URI is already present on the detection or violation record
- Object crops are planned assets unless an upstream crop URI is supplied in event metadata
- Event and violation list endpoints remain scaffolded; only per-record manifest build and fetch routes are implemented so far