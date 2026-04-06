# ANPR Persistence, Search, and Watchlist Behavior

This document describes how TrafficMind currently stores, normalizes, searches, and flags automatic number plate recognition data.

## What Is Persisted

Each plate read stores both OCR output and operator-facing evidence fields:

- raw OCR text in `plate_text`
- conservative normalized text in `normalized_plate_text`
- OCR confidence
- occurrence timestamp
- camera id
- optional stream id
- optional detection event linkage
- bounding box and OCR metadata
- optional crop and source-frame asset references

When a persisted read hits the watchlist, the save path can also emit a `watchlist_alerts` row with:

- the matching plate read id
- the matched watchlist entry id when still present
- camera id and occurred-at timestamp
- snapshot plate text and normalized text
- watchlist reason and description
- alert metadata for downstream workflows

## Search Behavior

The API supports these operational search patterns:

- exact plate search
- partial plate search
- search by camera id
- search by stream id
- search by detection event id
- search by tracked-object id when a linked detection event exists
- search by time range
- search by country and region
- search by confidence threshold
- search by evidence availability
- pagination for UI grids

Exact normalized search is the fast path and is backed by `normalized_plate_text, occurred_at` indexing.

Raw-text and operator-entered partial search is supported for investigations, but contains-style matching is broader and can be slower than exact normalized lookup. The API therefore keeps exact and partial modes explicit.

`country_code` filtering and normalization hints are separate concerns:

- `country_code` filters stored plate reads already tagged with that country
- `normalization_country_code` is only a hint used to normalize the investigator's search text before exact or partial normalized matching

This avoids the common mistake of accidentally narrowing a query just because the operator wanted a formatter hint.

## Watchlist Matching Path

The intended hot-path flow is:

1. OCR produces a `PlateOcrResult`.
2. `save_plate_read()` persists the `plate_reads` row.
3. The same save path checks active, non-expired watchlist entries against `normalized_plate_text`.
4. Matching reads are promoted from `observed` to `matched`.
5. If the matching entry has `alert_enabled=true`, a persistent `watchlist_alerts` row is created.

This keeps watchlist detection near the source of truth instead of relying on a later polling step.

Watchlist entries are also editable. Operators can correct raw plate text and country hints on an existing entry, and the normalized plate text is recalculated server-side.

## Normalization Assumptions

Normalization is deliberately conservative:

- Unicode text is normalized with NFKC.
- Letters are uppercased.
- Punctuation, spaces, hyphens, and dots are stripped.
- Unicode decimal digits are canonicalized to ASCII digits.
- Unicode letters and digits are retained; the system is not Latin-only.
- Country-specific formatters are optional and registry-based.
- No single national plate format is mandatory.

TrafficMind always stores both raw OCR text and normalized text. Investigators can inspect the raw OCR output even when the normalized form is what powers exact matching.

## Current Limitations

Normalization intentionally does not do aggressive inference. Today it does not:

- guess ambiguous OCR substitutions such as `O` vs `0` or `I` vs `1`
- transliterate one script into another
- enforce a mandatory country template
- infer missing separators or region codes
- deduplicate semantically similar watchlist entries across different reasons

These are product decisions, not bugs. Aggressive normalization can improve recall in one geography while creating false positives in another.

## API Summary

- `GET /api/v1/plates/` supports exact and partial lookups plus camera, time, and confidence filters.
- `GET /api/v1/plates/` also supports stream, detection-event, track-id, region, and evidence filters.
- `GET /api/v1/plates/{plate_read_id}` returns one persisted read.
- `POST /api/v1/watchlist/` creates a watchlist entry from raw plate text.
- `GET /api/v1/watchlist/` lists watchlist entries for UI tables.
- duplicate watchlist entries for the same normalized plate and reason are rejected with a conflict instead of surfacing as a server error
- `GET /api/v1/watchlist/check` performs an on-demand match check without waiting for OCR persistence.

For implementation details, see the OCR service notes in `services/ocr/README.md` and the API/ORM definitions under `apps/api/app/`.