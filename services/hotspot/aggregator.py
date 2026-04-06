"""Hotspot aggregation and trend computation.

Pure functions — no DB access, no side-effects.  Callers are responsible
for fetching ``EventRecord`` rows from the database and passing them in.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta

from services.hotspot.schemas import (
    AggregationAxis,
    EventRecord,
    HotspotBucket,
    HotspotQuery,
    HotspotRankingMetric,
    HotspotRanking,
    HotspotResult,
    RecurringIssue,
    TimeGranularity,
    TimeSlice,
    TrendComparison,
    TrendDelta,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def aggregate_hotspots(
    query: HotspotQuery,
    current_events: Sequence[EventRecord],
    previous_events: Sequence[EventRecord] | None = None,
) -> HotspotResult:
    """Build a complete hotspot result from pre-fetched event records.

    Args:
        query: Operator query controlling grouping, filtering, and trend.
        current_events: Events falling inside ``[query.period_start, query.period_end)``.
        previous_events: Events for the preceding period of equal length.
            Required when ``query.compare_previous`` is True.  Ignored otherwise.
    """
    filtered = _apply_filters(
        query,
        current_events,
        period_start=query.period_start,
        period_end=query.period_end,
    )
    buckets = _group_into_buckets(query, filtered)
    ordered_buckets = _ordered_buckets(buckets)
    ranked = ordered_buckets[: query.top_n]
    heatmap_buckets = [bucket for bucket in ordered_buckets if _has_location(bucket)]
    time_series = _build_time_series(query, filtered)
    recurring = _find_recurring_issues(query, filtered, time_series)
    warnings: list[str] = []

    if ordered_buckets and len(heatmap_buckets) < len(ordered_buckets):
        warnings.append(
            f"Heatmap output excludes {len(ordered_buckets) - len(heatmap_buckets)} bucket(s) without usable latitude/longitude.",
        )

    trend: TrendComparison | None = None
    per_bucket_trends: dict[str, TrendDelta] = {}
    if query.compare_previous and previous_events is not None:
        prev_start, prev_end = query.previous_period
        prev_filtered = _apply_filters(
            query,
            previous_events,
            period_start=prev_start,
            period_end=prev_end,
        )
        prev_buckets = _group_into_buckets(query, prev_filtered)
        trend = _build_trend_comparison(query, filtered, prev_filtered)
        per_bucket_trends = _per_bucket_trends(query, buckets, prev_buckets)

    ranking = [
        HotspotRanking(
            rank=idx + 1,
            bucket=bucket,
            trend=per_bucket_trends.get(_bucket_key_str(bucket.group_key)),
        )
        for idx, bucket in enumerate(ranked)
    ]

    return HotspotResult(
        query_echo=query,
        period_start=query.period_start,
        period_end=query.period_end,
        granularity=query.granularity,
        ranking_metric=_ranking_metric(query),
        total_events=len(filtered),
        ranking=ranking,
        heatmap_buckets=heatmap_buckets,
        time_series=time_series,
        trend=trend,
        recurring_issues=recurring,
        warnings=warnings,
    )


def compute_trend(
    current_count: int,
    previous_count: int,
    current_weighted: float = 0.0,
    previous_weighted: float = 0.0,
) -> TrendDelta:
    """Compute a single trend delta between two periods."""
    count_delta = current_count - previous_count
    pct = _pct_change(current_count, previous_count)
    weighted_delta = current_weighted - previous_weighted
    weighted_pct = _pct_change(current_weighted, previous_weighted)
    return TrendDelta(
        current_count=current_count,
        previous_count=previous_count,
        count_delta=count_delta,
        pct_change=pct,
        current_weighted=current_weighted,
        previous_weighted=previous_weighted,
        weighted_delta=weighted_delta,
        weighted_pct_change=weighted_pct,
    )


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def _apply_filters(
    query: HotspotQuery,
    events: Sequence[EventRecord],
    *,
    period_start: datetime,
    period_end: datetime,
) -> list[EventRecord]:
    result: list[EventRecord] = []
    for ev in events:
        if ev.occurred_at < period_start or ev.occurred_at >= period_end:
            continue
        if query.source_kinds and ev.source_kind not in query.source_kinds:
            continue
        if query.camera_ids and ev.camera_id not in query.camera_ids:
            continue
        if query.zone_ids and (ev.zone_id is None or ev.zone_id not in query.zone_ids):
            continue
        if query.event_types and (ev.event_type is None or ev.event_type not in query.event_types):
            continue
        if query.violation_types and (ev.violation_type is None or ev.violation_type not in query.violation_types):
            continue
        if query.severity_levels and (ev.severity is None or ev.severity not in query.severity_levels):
            continue
        result.append(ev)
    return result


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------

_AXIS_TO_FIELD: dict[AggregationAxis, str] = {
    AggregationAxis.SOURCE_KIND: "source_kind",
    AggregationAxis.CAMERA: "camera_id",
    AggregationAxis.ZONE: "zone_id",
    AggregationAxis.LANE: "lane_id",
    AggregationAxis.EVENT_TYPE: "event_type",
    AggregationAxis.VIOLATION_TYPE: "violation_type",
    AggregationAxis.SEVERITY: "severity",
    AggregationAxis.OBJECT_CLASS: "object_class",
}

# Extra label fields per axis (for human-readable output)
_AXIS_LABEL_FIELDS: dict[AggregationAxis, list[str]] = {
    AggregationAxis.CAMERA: ["camera_name", "location_name"],
    AggregationAxis.ZONE: ["zone_name"],
}


def _extract_group_key(
    query: HotspotQuery,
    event: EventRecord,
) -> dict[str, str | None]:
    key: dict[str, str | None] = {}
    for axis in query.group_by:
        field = _AXIS_TO_FIELD[axis]
        value = getattr(event, field, None)
        key[field] = value.value if hasattr(value, "value") else value
        for label_field in _AXIS_LABEL_FIELDS.get(axis, []):
            key[label_field] = getattr(event, label_field, None)
    return key


def _group_into_buckets(
    query: HotspotQuery,
    events: Sequence[EventRecord],
) -> dict[str, HotspotBucket]:
    buckets: dict[str, HotspotBucket] = {}
    for ev in events:
        gk = _extract_group_key(query, ev)
        key_str = _bucket_key_str(gk)
        weight = _event_weight(query, ev)

        if key_str not in buckets:
            buckets[key_str] = HotspotBucket(
                group_key=gk,
                event_count=0,
                weighted_score=0.0,
                first_event_at=ev.occurred_at,
                last_event_at=ev.occurred_at,
                representative_location={
                    "latitude": ev.latitude,
                    "longitude": ev.longitude,
                },
            )

        bucket = buckets[key_str]
        bucket.event_count += 1
        bucket.weighted_score = round(bucket.weighted_score + weight, 6)
        if bucket.first_event_at is None or ev.occurred_at < bucket.first_event_at:
            bucket.first_event_at = ev.occurred_at
        if bucket.last_event_at is None or ev.occurred_at > bucket.last_event_at:
            bucket.last_event_at = ev.occurred_at
        # Keep first non-null location
        if bucket.representative_location.get("latitude") is None and ev.latitude is not None:
            bucket.representative_location = {
                "latitude": ev.latitude,
                "longitude": ev.longitude,
            }

    return buckets


def _bucket_key_str(group_key: dict[str, str | None]) -> str:
    return "|".join(f"{k}={v}" for k, v in sorted(group_key.items()))


def _event_weight(query: HotspotQuery, event: EventRecord) -> float:
    if query.severity_weights and event.severity:
        return query.severity_weights.get(event.severity, 1.0)
    return 1.0


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


def _rank_buckets(
    buckets: dict[str, HotspotBucket],
    *,
    top_n: int,
) -> list[HotspotBucket]:
    return _ordered_buckets(buckets)[:top_n]


def _ordered_buckets(
    buckets: dict[str, HotspotBucket],
) -> list[HotspotBucket]:
    ordered = sorted(
        buckets.values(),
        key=lambda b: (b.weighted_score, b.event_count),
        reverse=True,
    )
    return ordered


# ---------------------------------------------------------------------------
# Time series
# ---------------------------------------------------------------------------


def _build_time_series(
    query: HotspotQuery,
    events: Sequence[EventRecord],
) -> list[TimeSlice]:
    boundaries = _time_boundaries(query.period_start, query.period_end, query.granularity)
    if not boundaries:
        return []

    slot_counts: dict[int, int] = defaultdict(int)
    slot_weights: dict[int, float] = defaultdict(float)

    for ev in events:
        idx = _slot_index(ev.occurred_at, boundaries)
        if idx is not None:
            slot_counts[idx] += 1
            slot_weights[idx] += _event_weight(query, ev)

    return [
        TimeSlice(
            period_start=boundaries[i],
            event_count=slot_counts.get(i, 0),
            weighted_score=round(slot_weights.get(i, 0.0), 6),
        )
        for i in range(len(boundaries))
    ]


def _time_boundaries(
    start: datetime,
    end: datetime,
    granularity: TimeGranularity,
) -> list[datetime]:
    boundaries: list[datetime] = []
    current = start
    while current < end:
        boundaries.append(current)
        current = _advance(current, granularity)
    return boundaries


def _advance(dt: datetime, granularity: TimeGranularity) -> datetime:
    if granularity == TimeGranularity.HOUR:
        return dt + timedelta(hours=1)
    if granularity == TimeGranularity.DAY:
        return dt + timedelta(days=1)
    if granularity == TimeGranularity.WEEK:
        return dt + timedelta(weeks=1)
    year = dt.year + (1 if dt.month == 12 else 0)
    month = 1 if dt.month == 12 else dt.month + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def _slot_index(
    occurred_at: datetime,
    boundaries: list[datetime],
) -> int | None:
    if not boundaries:
        return None
    for i in range(len(boundaries) - 1, -1, -1):
        if occurred_at >= boundaries[i]:
            return i
    return None


# ---------------------------------------------------------------------------
# Trend comparison
# ---------------------------------------------------------------------------


def _build_trend_comparison(
    query: HotspotQuery,
    current_events: Sequence[EventRecord],
    previous_events: Sequence[EventRecord],
) -> TrendComparison:
    cur_count = len(current_events)
    prev_count = len(previous_events)
    cur_weighted = sum(_event_weight(query, ev) for ev in current_events)
    prev_weighted = sum(_event_weight(query, ev) for ev in previous_events)

    return TrendComparison(
        current_total=cur_count,
        previous_total=prev_count,
        delta=compute_trend(cur_count, prev_count, cur_weighted, prev_weighted),
    )


def _per_bucket_trends(
    query: HotspotQuery,
    current_buckets: dict[str, HotspotBucket],
    previous_buckets: dict[str, HotspotBucket],
) -> dict[str, TrendDelta]:
    all_keys = set(current_buckets) | set(previous_buckets)
    trends: dict[str, TrendDelta] = {}
    for key in all_keys:
        cur = current_buckets.get(key)
        prev = previous_buckets.get(key)
        trends[key] = compute_trend(
            cur.event_count if cur else 0,
            prev.event_count if prev else 0,
            cur.weighted_score if cur else 0.0,
            prev.weighted_score if prev else 0.0,
        )
    return trends


# ---------------------------------------------------------------------------
# Recurring issues
# ---------------------------------------------------------------------------


def _find_recurring_issues(
    query: HotspotQuery,
    events: Sequence[EventRecord],
    time_series: Sequence[TimeSlice],
) -> list[RecurringIssue]:
    if not time_series:
        return []

    boundaries = [ts.period_start for ts in time_series]
    total_slices = len(boundaries)
    half = total_slices / 2.0

    # For each group-key, track which time slices had at least one event.
    key_slices: dict[str, set[int]] = defaultdict(set)
    key_gk: dict[str, dict[str, str | None]] = {}
    key_counts: dict[str, int] = defaultdict(int)

    for ev in events:
        gk = _extract_group_key(query, ev)
        key_str = _bucket_key_str(gk)
        key_gk[key_str] = gk
        key_counts[key_str] += 1
        idx = _slot_index(ev.occurred_at, boundaries)
        if idx is not None:
            key_slices[key_str].add(idx)

    recurring: list[RecurringIssue] = []
    for key_str, slices in key_slices.items():
        active = len(slices)
        if active > half:
            ratio = round(active / total_slices, 3)
            gk = key_gk[key_str]
            label_parts = [f"{k}={v}" for k, v in gk.items() if v is not None and not k.endswith("_name")]
            recurring.append(
                RecurringIssue(
                    group_key=gk,
                    occurrences=key_counts[key_str],
                    slices_active=active,
                    total_slices=total_slices,
                    recurrence_ratio=ratio,
                    description=f"Active in {active}/{total_slices} periods ({', '.join(label_parts)})",
                )
            )

    recurring.sort(key=lambda r: (r.recurrence_ratio, r.occurrences), reverse=True)
    return recurring


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pct_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return round((current - previous) / previous * 100.0, 2)


def _ranking_metric(query: HotspotQuery) -> HotspotRankingMetric:
    return HotspotRankingMetric.WEIGHTED_SCORE if query.severity_weights else HotspotRankingMetric.EVENT_COUNT


def _has_location(bucket: HotspotBucket) -> bool:
    return (
        bucket.representative_location.get("latitude") is not None
        and bucket.representative_location.get("longitude") is not None
    )
