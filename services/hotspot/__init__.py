"""TrafficMind hotspot and spatial trend analytics package."""

from services.hotspot.adapters import lane_analytics_to_event_records
from services.hotspot.aggregator import aggregate_hotspots, compute_trend
from services.hotspot.schemas import (
    AggregationAxis,
    EventRecord,
    HotspotBucket,
    HotspotQuery,
    HotspotRanking,
    HotspotResult,
    HotspotSourceKind,
    RecurringIssue,
    TimeGranularity,
    TrendComparison,
    TrendDelta,
)

__all__ = [
    "AggregationAxis",
    "EventRecord",
    "HotspotBucket",
    "HotspotQuery",
    "HotspotRanking",
    "HotspotResult",
    "HotspotSourceKind",
    "RecurringIssue",
    "TimeGranularity",
    "TrendComparison",
    "TrendDelta",
    "aggregate_hotspots",
    "compute_trend",
    "lane_analytics_to_event_records",
]
