# Evaluation

This package provides a deterministic, fixture-driven evaluation foundation for TrafficMind.

It is intentionally conservative:

- it does not claim model quality from synthetic fixtures
- it does not replace full dataset evaluation or production telemetry
- it provides typed metrics and a repeatable harness for regression checks

Current coverage:

- **Detection** — IoU-based output matching with precision, recall, and mean IoU
- **Tracking** — assignment coverage, ID-switch counting, fragmentation, and continuity scoring
- **OCR / plate reads** — exact-match rate and Levenshtein character accuracy
- **Rule sanity** — keyed comparison of expected vs actual pre-violations and confirmed violations
- **Signal classification** — per-class accuracy, confusion pair reporting for HSV state classification

Run the sample suite:

```bash
python -m services.evaluation tests/fixtures/evaluation/benchmark_suite.json
```

Treat these results as a benchmark foundation, not a product-performance claim.