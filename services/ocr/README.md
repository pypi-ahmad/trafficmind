# OCR Service

Purpose:

- OCR for number plates and evidence crops
- OCR-specific preprocessing and normalization
- downstream plate-text extraction for event records

Plate OCR should only run once a reliable plate-localization path is available.

Runtime defaults:

- request Paddle CUDA by default via `OCR_USE_GPU=true`
- automatically fall back to CPU when the installed Paddle runtime has no CUDA support
- optional model directories can still be supplied through `OCR_MODEL_DIR`

## Plate Normalization

TrafficMind keeps normalization conservative and geography-agnostic by default.

- apply Unicode NFKC normalization
- uppercase letters
- strip spaces and punctuation
- canonicalize Unicode decimal digits to ASCII digits
- retain Unicode letters and digits instead of forcing Latin-only text
- apply country-specific formatting only when an explicit formatter is registered

The service stores both raw OCR text and normalized text. Exact search should prefer normalized values. Partial investigations can still use raw text search when operators need to inspect OCR output more literally.

Search callers should treat country-format hints separately from country filters:

- use a normalization hint when you want the query text normalized with a country-specific formatter
- use a country filter when you only want persisted reads tagged with that country

## Limitations

The current normalizer does not guess OCR ambiguities such as `O` versus `0`, does not enforce a single national template, and does not transliterate between scripts. That is intentional to avoid overfitting to one country at the cost of false positives elsewhere.

See `docs/anpr.md` for the persistence and watchlist behavior.
