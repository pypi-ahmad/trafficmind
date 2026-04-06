# Hotspot Analytics

This module provides deterministic hotspot aggregation and spatial trend analysis over stored records.

Current scope:

- in-memory aggregation over normalized event records
- ranking by raw event count with optional operator-supplied severity weighting
- heatmap buckets, time-series slices, recurring-issue summaries, and period-over-period trend deltas
- support for grouping by camera, zone, lane, event type, violation type, severity, and source kind

Design constraints:

- pure aggregation functions only; callers fetch and normalize records first
- ranking stays transparent and reproducible
- output is designed for API responses, dashboards, and reporting workflows