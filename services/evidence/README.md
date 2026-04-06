# Evidence

Deterministic evidence manifest packaging for violations and detection events.

## Entry Point

`build_violation_evidence_manifest()` and `build_detection_evidence_manifest()` in [service.py](service.py) — query stored event context and produce a structured manifest with traceable asset keys.

## Manifest Structure

Each `EvidenceManifest` records:

- **Selection policy** — deterministic frame selection around the event (pre-event, event, post-event windows)
- **Asset keys** — key frame snapshots, object crops, plate crops, clip windows, timeline metadata
- **Render hints** — overlay-ready bounding boxes, zone geometry, track-path hooks, and signal-state annotations from stored rule metadata
- **Timeline** — selected frame indices, clip window bounds, and frame roles

## Storage

- Manifests are persisted as JSON documents linked to violation or detection events
- Asset keys follow a traceable naming convention: `cameras/{camera_code}/{yyyy}/{mm}/{dd}/{events|violations}/{subject_id}/r{revision}/{sequence}_{asset_kind}.ext`
- Storage state tracks whether assets are `available` (real URI exists), `planned` (deferred for future rendering), or `inline` (data embedded in manifest metadata)

## API Routes

- `POST /api/v1/violations/{id}/evidence` — build or fetch evidence manifest
- `GET /api/v1/violations/{id}/evidence` — retrieve existing manifest
- `POST /api/v1/events/{id}/evidence` — build or fetch for detection events
- `GET /api/v1/events/{id}/evidence` — retrieve existing manifest

## Limitations

- Clip packaging is foundation-only: if no stored clip exists, the manifest emits a placeholder asset with planned storage reference and explicit clip-window metadata.
- Overlay rasterization is not implemented; render hints are metadata-only.

See `docs/evidence.md` for manifest structure, storage-key conventions, and current limitations.
