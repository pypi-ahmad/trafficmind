# Re-Identification Service (`services/reid/`)

Multi-camera re-identification subsystem for TrafficMind.  This module
associates tracked objects observed on **different** cameras into
cross-camera identities.  It is explicitly separate from per-camera MOT
tracking (`services/tracking/`) and operates as a higher-level association
layer.

## Key concepts

| Term | Description |
|------|-------------|
| **Sighting** | A single per-camera track observation (camera + track_id + embedding + optional linked entity id). |
| **AppearanceDescriptor** | An embedding vector encoding the visual appearance of an object. |
| **ReIdCandidate** | A proposed cross-camera match between two sightings. |
| **CrossCameraEntity** | A confirmed identity that spans multiple cameras. |

## Architecture

```
Image Crop
    │
    ▼
┌──────────────────┐
│ EmbeddingExtractor│  (ABC — pluggable backend)
└────────┬─────────┘
         │ AppearanceDescriptor
         ▼
┌──────────────────┐
│ SimilarityIndex   │  (ABC — in-memory / FAISS / vector DB)
└────────┬─────────┘
         │ SimilaritySearchResult[]
         ▼
┌──────────────────┐
│ CandidateMatcher  │  (threshold + spatio-temporal heuristics)
└────────┬─────────┘
         │ ReIdCandidate[]
         ▼
┌──────────────────┐
│ MatchConfirmer    │  (auto-confirm / human review queue)
└────────┬─────────┘
         │ MatchDecision
         ▼
   CrossCameraEntity
```

## Interfaces (ABCs)

All four pipeline stages are abstract base classes so backends can be swapped
without changing the pipeline logic:

* `EmbeddingExtractor` — extracts an appearance vector from a crop image.
* `SimilarityIndex` — indexes & searches sighting embeddings (nearest-neighbour).
* `CandidateMatcher` — applies rules to produce match candidates.
* `MatchConfirmer` — decides whether candidates are confirmed, rejected, or deferred.

## In-memory backends

For development and testing, `services/reid/backends.py` provides:

* `DummyEmbeddingExtractor` — returns random unit-norm embeddings.
* `InMemorySimilarityIndex` — brute-force cosine similarity (up to ~10 k sightings).
* `ThresholdCandidateMatcher` — confidence-band assignment via config thresholds.
* `AutoConfirmMatchConfirmer` — auto-confirms above threshold, rejects LOW, defers MEDIUM.

## Configuration

`ReIdSettings` is env-driven (`REID_` prefix).  Key settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `REID_EMBEDDING_MODEL` | `resnet50-market1501` | Embedding model name |
| `REID_EMBEDDING_DIMENSION` | `512` | Expected vector dimension |
| `REID_HIGH_CONFIDENCE_THRESHOLD` | `0.85` | HIGH band floor |
| `REID_MEDIUM_CONFIDENCE_THRESHOLD` | `0.70` | MEDIUM band floor |
| `REID_AUTO_CONFIRM_THRESHOLD` | `0.90` | Auto-confirm floor |
| `REID_PERSON_REID_ENABLED` | `false` | Person re-id policy gate |

## Database models

Three new tables (migration `20260405_0007`):

* `cross_camera_entities` — unified identities.
* `reid_sightings` — per-camera sighting records with embedded vectors, local track ids, and an optional representative `detection_event` anchor for audit.
* `reid_matches` — proposed/confirmed match pairs with audit trail and a canonical `pair_key` so reversed sighting pairs cannot be inserted twice.

## Privacy

Person re-id is **disabled by default** (`REID_PERSON_REID_ENABLED=false`).
The subject-type enum is kept separate so policy checks can be enforced at
every interface boundary.

## Uncertainty handling

Re-id is inherently imperfect.  The design encodes this:

* Every match has a `similarity_score` and a `confidence_band` (HIGH / MEDIUM / LOW).
* Same-camera candidates are rejected; re-id is only for cross-camera association.
* Only HIGH-confidence matches above `auto_confirm_threshold` are auto-confirmed.
* MEDIUM matches are left as CANDIDATE for human review.
* LOW matches are auto-rejected.
* Confirmed candidates that would bridge two already-linked entities are escalated for manual review instead of being auto-merged.
* Unresolved candidates expire after `candidate_ttl_seconds`.

## Running tests

```bash
python -m pytest tests/reid/ -v
```
