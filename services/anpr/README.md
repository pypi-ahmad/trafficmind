# ANPR

Plate search, normalization-aware matching, and watchlist helpers.

## Entry Points

- `search_plates()` in [search.py](search.py) — async SQLAlchemy query builder for plate reads with support for exact search, partial search, camera filtering, time-range filtering, confidence thresholds, track-ID filtering, and pagination
- `watchlist.py` — watchlist entry management and matching logic

## Normalization

Plate text normalization is handled by `services.ocr.normalizer.normalize_plate_text()`. The normalizer is intentionally conservative:

- Strips whitespace, hyphens, dots
- Uppercases Latin characters
- Transliterates Arabic-Indic and fullwidth characters
- Does not enforce a single country-specific format

Both raw and normalized text are persisted in `PlateRead` records. Searches against normalized text use exact or prefix matching.

## Watchlist

- Watchlist entries are stored separately from plate reads
- Matching is performed against normalized plate text during the save path
- Matching plates are promoted to `matched` status
- Entries with `alert_enabled=true` emit persistent alert rows

## Limitations

- Upstream plate detection is not yet integrated into the live hot path. ANPR quality depends on the quality of plate crops provided by the detection pipeline.
- Normalization does not handle all regional plate formats. It is designed to be safe (no false-positive normalization) rather than complete.

See `docs/anpr.md` for full normalization assumptions, search behavior, and watchlist limitations.
