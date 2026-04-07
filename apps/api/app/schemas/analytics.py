"""Request and response schemas for hotspot analytics endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from services.hotspot.schemas import (
    HotspotQuery,
    HotspotRankingMetric,
    HotspotResult,
    RecurringIssue,
    TrendComparison,
)


class HotspotAnalyticsRequest(HotspotQuery):
    """HTTP request body for hotspot analytics."""


class HotspotRankingRow(BaseModel):
    """Flat hotspot row for tables and cards."""

    model_config = ConfigDict(extra="forbid")

    rank: int
    source_kind: str | None = None
    camera_id: str | None = None
    camera_name: str | None = None
    location_name: str | None = None
    zone_id: str | None = None
    zone_name: str | None = None
    lane_id: str | None = None
    event_type: str | None = None
    violation_type: str | None = None
    severity: str | None = None
    object_class: str | None = None
    event_count: int
    weighted_score: float
    latitude: float | None = None
    longitude: float | None = None
    count_delta: int | None = None
    pct_change: float | None = None
    weighted_delta: float | None = None
    weighted_pct_change: float | None = None


class HotspotHeatmapPoint(BaseModel):
    """Map-friendly hotspot point."""

    model_config = ConfigDict(extra="forbid")

    source_kind: str | None = None
    camera_id: str | None = None
    camera_name: str | None = None
    location_name: str | None = None
    zone_id: str | None = None
    zone_name: str | None = None
    lane_id: str | None = None
    event_type: str | None = None
    violation_type: str | None = None
    severity: str | None = None
    object_class: str | None = None
    event_count: int
    weighted_score: float
    latitude: float | None = None
    longitude: float | None = None


class HotspotTimeSeriesPoint(BaseModel):
    """Time-series point for charting without chart-library assumptions."""

    model_config = ConfigDict(extra="forbid")

    period_start: datetime
    event_count: int
    weighted_score: float


class HotspotAnalyticsResponse(BaseModel):
    """Frontend- and map-friendly hotspot analytics payload."""

    model_config = ConfigDict(extra="forbid")

    query_echo: HotspotAnalyticsRequest
    total_events: int
    ranking_metric: HotspotRankingMetric
    ranking: list[HotspotRankingRow] = Field(default_factory=list)
    heatmap: list[HotspotHeatmapPoint] = Field(default_factory=list)
    time_series: list[HotspotTimeSeriesPoint] = Field(default_factory=list)
    recurring_issues: list[RecurringIssue] = Field(default_factory=list)
    trend: TrendComparison | None = None
    methodology: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @classmethod
    def from_result(
        cls,
        query: HotspotAnalyticsRequest,
        result: HotspotResult,
    ) -> HotspotAnalyticsResponse:
        ranking = [HotspotRankingRow.model_validate(row) for row in result.to_ranking_list()]
        heatmap = [HotspotHeatmapPoint.model_validate(row) for row in result.to_heatmap_list()]
        time_series = [HotspotTimeSeriesPoint.model_validate(row) for row in result.to_time_series_list()]
        return cls(
            query_echo=query,
            total_events=result.total_events,
            ranking_metric=result.ranking_metric,
            ranking=ranking,
            heatmap=heatmap,
            time_series=time_series,
            recurring_issues=result.recurring_issues,
            trend=result.trend,
            methodology=result.methodology,
            warnings=result.warnings,
        )
