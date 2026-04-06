"""Typed schemas for hotspot and spatial trend analytics.

Hotspot Score
=============
The hotspot score for a bucket is simply the **total event count** in that
bucket for the queried period.  No opaque weighting or "AI score" is applied.

When ``severity_weights`` are supplied in the query, the *weighted_score* is
the sum of ``severity_weights[event.severity]`` for each event, providing
an operator-controlled way to emphasise critical incidents without hiding
the raw count.

Trend
=====
A trend delta compares a *current* period to a *previous* period of equal
length (e.g. this week vs last week).  The delta is the signed difference
in count or score; the ``pct_change`` is the percentage change or ``None``
when the previous value is zero.
"""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TimeGranularity(StrEnum):
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class HotspotSourceKind(StrEnum):
    DETECTION_EVENT = "detection_event"
    VIOLATION_EVENT = "violation_event"
    WATCHLIST_ALERT = "watchlist_alert"
    CONGESTION = "congestion"


class HotspotRankingMetric(StrEnum):
    EVENT_COUNT = "event_count"
    WEIGHTED_SCORE = "weighted_score"


class AggregationAxis(StrEnum):
    SOURCE_KIND = "source_kind"
    CAMERA = "camera"
    ZONE = "zone"
    LANE = "lane"
    EVENT_TYPE = "event_type"
    VIOLATION_TYPE = "violation_type"
    SEVERITY = "severity"
    OBJECT_CLASS = "object_class"


# ---------------------------------------------------------------------------
# Input / query
# ---------------------------------------------------------------------------


class HotspotQuery(BaseModel):
    """Operator-facing query that drives aggregation.

    All filter lists use OR semantics (any match passes).
    An empty list means "no filter on that axis".
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    period_start: datetime
    period_end: datetime
    granularity: TimeGranularity = TimeGranularity.DAY
    group_by: list[AggregationAxis] = Field(
        default_factory=lambda: [AggregationAxis.CAMERA],
    )
    compare_previous: bool = Field(
        default=True,
        description="When True, compute trend delta vs the immediately preceding period of equal length.",
    )
    source_kinds: list[HotspotSourceKind] = Field(default_factory=list)
    camera_ids: list[str] = Field(default_factory=list)
    zone_ids: list[str] = Field(default_factory=list)
    event_types: list[str] = Field(default_factory=list)
    violation_types: list[str] = Field(default_factory=list)
    severity_levels: list[str] = Field(default_factory=list)
    severity_weights: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Optional operator-controlled weights keyed by severity value. "
            "E.g. {'low': 1, 'medium': 2, 'high': 5, 'critical': 10}."
        ),
    )
    top_n: int = Field(default=20, ge=1, le=500)

    @property
    def period_seconds(self) -> float:
        return max((self.period_end - self.period_start).total_seconds(), 0.0)

    @property
    def previous_period(self) -> tuple[datetime, datetime]:
        step_count = self.period_step_count
        previous_start = self.period_start
        for _ in range(step_count):
            previous_start = _shift_datetime(previous_start, self.granularity, direction=-1)
        return (previous_start, self.period_start)

    @property
    def period_step_count(self) -> int:
        current = self.period_start
        count = 0
        while current < self.period_end:
            count += 1
            current = _shift_datetime(current, self.granularity, direction=1)
        return count

    @model_validator(mode="after")
    def _validate_period(self) -> HotspotQuery:
        if self.period_end <= self.period_start:
            msg = "period_end must be later than period_start"
            raise ValueError(msg)
        if not self.group_by:
            msg = "group_by must include at least one aggregation axis"
            raise ValueError(msg)
        return self


# ---------------------------------------------------------------------------
# Normalised event record (thin row from DB query)
# ---------------------------------------------------------------------------


class EventRecord(BaseModel):
    """Flat event record suitable for in-memory aggregation.

    This is the common shape that both DetectionEvent and ViolationEvent
    rows are mapped into before hotspot logic runs.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str
    source_kind: HotspotSourceKind
    occurred_at: datetime
    camera_id: str
    camera_name: str | None = None
    location_name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    zone_id: str | None = None
    zone_name: str | None = None
    lane_id: str | None = None
    event_type: str | None = None
    violation_type: str | None = None
    severity: str | None = None
    object_class: str | None = None


# ---------------------------------------------------------------------------
# Aggregation output
# ---------------------------------------------------------------------------


class HotspotBucket(BaseModel):
    """One aggregation bucket — a unique combination of group-by keys."""

    model_config = ConfigDict(extra="forbid")

    group_key: dict[str, str | None]
    event_count: int = 0
    weighted_score: float = 0.0
    first_event_at: datetime | None = None
    last_event_at: datetime | None = None
    representative_location: dict[str, float | None] = Field(
        default_factory=lambda: {"latitude": None, "longitude": None},
    )

    def to_heatmap_dict(self) -> dict[str, Any]:
        """Flat dict ready for map/heatmap rendering."""
        return {
            **self.group_key,
            "event_count": self.event_count,
            "weighted_score": self.weighted_score,
            "latitude": self.representative_location.get("latitude"),
            "longitude": self.representative_location.get("longitude"),
        }


class TimeSlice(BaseModel):
    """Event count for one granularity step (e.g. one day)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    period_start: datetime
    event_count: int = 0
    weighted_score: float = 0.0


class TrendDelta(BaseModel):
    """Signed comparison between current and previous period."""

    model_config = ConfigDict(extra="forbid")

    current_count: int = 0
    previous_count: int = 0
    count_delta: int = 0
    pct_change: float | None = None
    current_weighted: float = 0.0
    previous_weighted: float = 0.0
    weighted_delta: float = 0.0
    weighted_pct_change: float | None = None


class RecurringIssue(BaseModel):
    """A pattern that repeats across multiple time slices."""

    model_config = ConfigDict(extra="forbid")

    group_key: dict[str, str | None]
    occurrences: int = 0
    slices_active: int = 0
    total_slices: int = 0
    recurrence_ratio: float = 0.0
    description: str = ""


class HotspotRanking(BaseModel):
    """One entry in the ranked hotspot list."""

    model_config = ConfigDict(extra="forbid")

    rank: int
    bucket: HotspotBucket
    trend: TrendDelta | None = None


class TrendComparison(BaseModel):
    """Overall period-vs-period comparison."""

    model_config = ConfigDict(extra="forbid")

    current_total: int = 0
    previous_total: int = 0
    delta: TrendDelta = Field(default_factory=TrendDelta)


class HotspotResult(BaseModel):
    """Complete hotspot analytics response."""

    model_config = ConfigDict(extra="forbid")

    query_echo: HotspotQuery
    period_start: datetime
    period_end: datetime
    granularity: TimeGranularity
    ranking_metric: HotspotRankingMetric = HotspotRankingMetric.EVENT_COUNT
    total_events: int = 0
    ranking: list[HotspotRanking] = Field(default_factory=list)
    heatmap_buckets: list[HotspotBucket] = Field(default_factory=list)
    time_series: list[TimeSlice] = Field(default_factory=list)
    trend: TrendComparison | None = None
    recurring_issues: list[RecurringIssue] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    methodology: list[str] = Field(
        default_factory=lambda: [
            "Hotspot score equals the raw event count in each bucket.",
            "Weighted score is the sum of operator-supplied severity weights per event (defaults to 1.0 per event when no weights are provided).",
            "Ranking uses weighted_score only when severity weights are supplied; otherwise ranking uses event_count.",
            "Trend delta compares the queried period to the immediately preceding period of equal length.",
            "Recurring issues are group-by buckets that appear in more than half the time slices.",
            "Heatmap output includes all geolocated buckets, not only the ranked top_n subset.",
            "No opaque scoring or machine learning ranking is applied.",
        ],
    )

    def to_ranking_list(self) -> list[dict[str, Any]]:
        """Flat ranked list for frontend tables."""
        return [
            {
                "rank": entry.rank,
                **entry.bucket.group_key,
                "event_count": entry.bucket.event_count,
                "weighted_score": entry.bucket.weighted_score,
                "latitude": entry.bucket.representative_location.get("latitude"),
                "longitude": entry.bucket.representative_location.get("longitude"),
                "count_delta": entry.trend.count_delta if entry.trend else None,
                "pct_change": entry.trend.pct_change if entry.trend else None,
                "weighted_delta": entry.trend.weighted_delta if entry.trend else None,
                "weighted_pct_change": entry.trend.weighted_pct_change if entry.trend else None,
            }
            for entry in self.ranking
        ]

    def to_heatmap_list(self) -> list[dict[str, Any]]:
        """List of heatmap-ready dicts for all ranked buckets."""
        buckets = self.heatmap_buckets or [entry.bucket for entry in self.ranking]
        return [bucket.to_heatmap_dict() for bucket in buckets]

    def to_time_series_list(self) -> list[dict[str, Any]]:
        """Flat time-series list for charting."""
        return [
            {
                "period_start": ts.period_start.isoformat(),
                "event_count": ts.event_count,
                "weighted_score": ts.weighted_score,
            }
            for ts in self.time_series
        ]


def _shift_datetime(
    dt: datetime,
    granularity: TimeGranularity,
    *,
    direction: int,
) -> datetime:
    if granularity == TimeGranularity.HOUR:
        return dt + timedelta(hours=direction)
    if granularity == TimeGranularity.DAY:
        return dt + timedelta(days=direction)
    if granularity == TimeGranularity.WEEK:
        return dt + timedelta(weeks=direction)

    month_index = (dt.year * 12 + (dt.month - 1)) + direction
    year, month_zero_based = divmod(month_index, 12)
    month = month_zero_based + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)
