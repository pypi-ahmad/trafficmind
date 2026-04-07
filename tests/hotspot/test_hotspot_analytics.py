"""Tests for hotspot and spatial trend analytics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.flow.schemas import (
    CongestionLevel,
    LaneAnalytics,
    LaneOccupancyMetrics,
    LaneQueueMetrics,
)
from services.hotspot import (
    aggregate_hotspots,
    compute_trend,
    lane_analytics_to_event_records,
)
from services.hotspot.schemas import (
    AggregationAxis,
    EventRecord,
    HotspotQuery,
    HotspotRankingMetric,
    HotspotSourceKind,
    TimeGranularity,
)

T0 = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)
T7 = T0 + timedelta(days=7)
T14 = T0 + timedelta(days=14)


def _event(
    event_id: str,
    occurred_at: datetime,
    *,
    source_kind: HotspotSourceKind = HotspotSourceKind.DETECTION_EVENT,
    camera_id: str = "cam-1",
    camera_name: str = "Camera 1",
    location_name: str = "Main St",
    latitude: float = 40.0,
    longitude: float = -74.0,
    zone_id: str | None = None,
    zone_name: str | None = None,
    event_type: str = "detection",
    violation_type: str | None = None,
    severity: str | None = None,
    object_class: str = "car",
) -> EventRecord:
    return EventRecord(
        event_id=event_id,
        source_kind=source_kind,
        occurred_at=occurred_at,
        camera_id=camera_id,
        camera_name=camera_name,
        location_name=location_name,
        latitude=latitude,
        longitude=longitude,
        zone_id=zone_id,
        zone_name=zone_name,
        event_type=event_type,
        violation_type=violation_type,
        severity=severity,
        object_class=object_class,
    )


# ---------------------------------------------------------------------------
# Tests: compute_trend
# ---------------------------------------------------------------------------


class TestComputeTrend:
    def test_basic_increase(self):
        td = compute_trend(10, 5, 20.0, 10.0)
        assert td.count_delta == 5
        assert td.pct_change == 100.0
        assert td.weighted_delta == 10.0
        assert td.weighted_pct_change == 100.0

    def test_decrease(self):
        td = compute_trend(3, 10)
        assert td.count_delta == -7
        assert td.pct_change == -70.0

    def test_previous_zero(self):
        td = compute_trend(5, 0)
        assert td.pct_change is None

    def test_both_zero(self):
        td = compute_trend(0, 0)
        assert td.count_delta == 0
        assert td.pct_change is None


# ---------------------------------------------------------------------------
# Tests: aggregate_hotspots
# ---------------------------------------------------------------------------


class TestAggregateBasic:
    def test_group_by_camera_ranks_by_count(self):
        events = [
            _event("e1", T0 + timedelta(days=0), camera_id="cam-1"),
            _event("e2", T0 + timedelta(days=1), camera_id="cam-1"),
            _event("e3", T0 + timedelta(days=1), camera_id="cam-1"),
            _event("e4", T0 + timedelta(days=2), camera_id="cam-2", camera_name="Camera 2"),
        ]
        query = HotspotQuery(
            period_start=T0,
            period_end=T7,
            group_by=[AggregationAxis.CAMERA],
            compare_previous=False,
        )
        result = aggregate_hotspots(query, events)

        assert result.total_events == 4
        assert len(result.ranking) == 2
        assert result.ranking[0].rank == 1
        assert result.ranking[0].bucket.group_key["camera_id"] == "cam-1"
        assert result.ranking[0].bucket.event_count == 3
        assert result.ranking[1].bucket.group_key["camera_id"] == "cam-2"
        assert result.ranking[1].bucket.event_count == 1

    def test_group_by_zone(self):
        events = [
            _event("e1", T0, zone_id="z1", zone_name="Zone A"),
            _event("e2", T0, zone_id="z1", zone_name="Zone A"),
            _event("e3", T0, zone_id="z2", zone_name="Zone B"),
        ]
        query = HotspotQuery(
            period_start=T0,
            period_end=T7,
            group_by=[AggregationAxis.ZONE],
            compare_previous=False,
        )
        result = aggregate_hotspots(query, events)

        assert result.ranking[0].bucket.group_key["zone_id"] == "z1"
        assert result.ranking[0].bucket.group_key["zone_name"] == "Zone A"

    def test_group_by_violation_type(self):
        events = [
            _event("e1", T0, violation_type="red_light", severity="high"),
            _event("e2", T0, violation_type="red_light", severity="high"),
            _event("e3", T0, violation_type="speeding", severity="medium"),
        ]
        query = HotspotQuery(
            period_start=T0,
            period_end=T7,
            group_by=[AggregationAxis.VIOLATION_TYPE],
            compare_previous=False,
        )
        result = aggregate_hotspots(query, events)
        assert result.ranking[0].bucket.group_key["violation_type"] == "red_light"

    def test_multi_axis_grouping(self):
        events = [
            _event("e1", T0, camera_id="cam-1", violation_type="red_light"),
            _event("e2", T0, camera_id="cam-1", violation_type="red_light"),
            _event("e3", T0, camera_id="cam-1", violation_type="speeding"),
        ]
        query = HotspotQuery(
            period_start=T0,
            period_end=T7,
            group_by=[AggregationAxis.CAMERA, AggregationAxis.VIOLATION_TYPE],
            compare_previous=False,
        )
        result = aggregate_hotspots(query, events)
        assert len(result.ranking) == 2
        top = result.ranking[0]
        assert top.bucket.group_key["camera_id"] == "cam-1"
        assert top.bucket.group_key["violation_type"] == "red_light"
        assert top.bucket.event_count == 2


class TestSeverityWeights:
    def test_weighted_score_ranks_by_severity(self):
        events = [
            _event("e1", T0, camera_id="cam-low", severity="low"),
            _event("e2", T0, camera_id="cam-low", severity="low"),
            _event("e3", T0, camera_id="cam-low", severity="low"),
            _event("e4", T0, camera_id="cam-hi", severity="critical"),
        ]
        query = HotspotQuery(
            period_start=T0,
            period_end=T7,
            group_by=[AggregationAxis.CAMERA],
            compare_previous=False,
            severity_weights={"low": 1.0, "critical": 10.0},
        )
        result = aggregate_hotspots(query, events)

        # cam-hi has 1 event but weighted_score=10, cam-low has 3 events but weighted_score=3
        assert result.ranking[0].bucket.group_key["camera_id"] == "cam-hi"
        assert result.ranking[0].bucket.weighted_score == 10.0
        assert result.ranking[1].bucket.weighted_score == 3.0
        assert result.ranking_metric is HotspotRankingMetric.WEIGHTED_SCORE


class TestFilters:
    def test_source_kind_filter(self):
        events = [
            _event("e1", T0, source_kind=HotspotSourceKind.DETECTION_EVENT),
            _event("e2", T0, source_kind=HotspotSourceKind.VIOLATION_EVENT),
        ]
        query = HotspotQuery(
            period_start=T0,
            period_end=T7,
            source_kinds=[HotspotSourceKind.VIOLATION_EVENT],
            compare_previous=False,
        )
        result = aggregate_hotspots(query, events)
        assert result.total_events == 1

    def test_camera_id_filter(self):
        events = [
            _event("e1", T0, camera_id="cam-1"),
            _event("e2", T0, camera_id="cam-2"),
        ]
        query = HotspotQuery(
            period_start=T0,
            period_end=T7,
            camera_ids=["cam-1"],
            compare_previous=False,
        )
        result = aggregate_hotspots(query, events)
        assert result.total_events == 1

    def test_violation_type_filter(self):
        events = [
            _event("e1", T0, violation_type="red_light"),
            _event("e2", T0, violation_type="speeding"),
            _event("e3", T0, violation_type=None),
        ]
        query = HotspotQuery(
            period_start=T0,
            period_end=T7,
            violation_types=["red_light"],
            compare_previous=False,
        )
        result = aggregate_hotspots(query, events)
        assert result.total_events == 1

    def test_severity_filter(self):
        events = [
            _event("e1", T0, severity="high"),
            _event("e2", T0, severity="low"),
        ]
        query = HotspotQuery(
            period_start=T0,
            period_end=T7,
            severity_levels=["high"],
            compare_previous=False,
        )
        result = aggregate_hotspots(query, events)
        assert result.total_events == 1


class TestTimeSeries:
    def test_daily_time_series(self):
        events = [
            _event("e1", T0 + timedelta(hours=1)),
            _event("e2", T0 + timedelta(hours=2)),
            _event("e3", T0 + timedelta(days=2, hours=3)),
        ]
        query = HotspotQuery(
            period_start=T0,
            period_end=T7,
            granularity=TimeGranularity.DAY,
            compare_previous=False,
        )
        result = aggregate_hotspots(query, events)

        assert len(result.time_series) == 7
        assert result.time_series[0].event_count == 2  # day 0
        assert result.time_series[1].event_count == 0  # day 1
        assert result.time_series[2].event_count == 1  # day 2

    def test_weekly_granularity(self):
        events = [_event("e1", T0 + timedelta(days=i)) for i in range(14)]
        query = HotspotQuery(
            period_start=T0,
            period_end=T14,
            granularity=TimeGranularity.WEEK,
            compare_previous=False,
        )
        result = aggregate_hotspots(query, events)
        assert len(result.time_series) == 2
        assert result.time_series[0].event_count == 7
        assert result.time_series[1].event_count == 7

    def test_monthly_granularity_uses_calendar_months(self):
        start = datetime(2026, 1, 31, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)
        events = [
            _event("e1", start + timedelta(hours=1)),
            _event("e2", datetime(2026, 2, 28, 1, 0, 0, tzinfo=timezone.utc)),
            _event("e3", datetime(2026, 3, 28, 1, 0, 0, tzinfo=timezone.utc)),
        ]
        query = HotspotQuery(
            period_start=start,
            period_end=end,
            granularity=TimeGranularity.MONTH,
            compare_previous=False,
        )
        result = aggregate_hotspots(query, events)

        assert len(result.time_series) == 3
        assert [point.event_count for point in result.time_series] == [1, 1, 1]

    def test_previous_period_for_monthly_window_is_granularity_aligned(self):
        query = HotspotQuery(
            period_start=datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc),
            period_end=datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc),
            granularity=TimeGranularity.MONTH,
            compare_previous=True,
        )

        previous_start, previous_end = query.previous_period
        assert previous_start == datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert previous_end == datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

    def test_to_time_series_list_has_iso_strings(self):
        events = [_event("e1", T0)]
        query = HotspotQuery(
            period_start=T0,
            period_end=T7,
            granularity=TimeGranularity.DAY,
            compare_previous=False,
        )
        result = aggregate_hotspots(query, events)
        ts_list = result.to_time_series_list()
        assert isinstance(ts_list[0]["period_start"], str)


class TestTrendComparison:
    def test_trend_delta_current_vs_previous(self):
        current = [
            _event("c1", T7 + timedelta(days=0)),
            _event("c2", T7 + timedelta(days=1)),
            _event("c3", T7 + timedelta(days=2)),
        ]
        previous = [
            _event("p1", T0 + timedelta(days=0)),
        ]
        query = HotspotQuery(
            period_start=T7,
            period_end=T14,
            compare_previous=True,
        )
        result = aggregate_hotspots(query, current, previous)

        assert result.trend is not None
        assert result.trend.current_total == 3
        assert result.trend.previous_total == 1
        assert result.trend.delta.count_delta == 2
        assert result.trend.delta.pct_change == 200.0

    def test_per_bucket_trend(self):
        current = [
            _event("c1", T7, camera_id="cam-1"),
            _event("c2", T7, camera_id="cam-1"),
        ]
        previous = [
            _event("p1", T0, camera_id="cam-1"),
            _event("p2", T0, camera_id="cam-1"),
            _event("p3", T0, camera_id="cam-1"),
        ]
        query = HotspotQuery(
            period_start=T7,
            period_end=T14,
            group_by=[AggregationAxis.CAMERA],
            compare_previous=True,
        )
        result = aggregate_hotspots(query, current, previous)
        assert result.ranking[0].trend is not None
        assert result.ranking[0].trend.count_delta == -1

    def test_no_trend_when_compare_previous_false(self):
        events = [_event("e1", T0)]
        query = HotspotQuery(
            period_start=T0,
            period_end=T7,
            compare_previous=False,
        )
        result = aggregate_hotspots(query, events)
        assert result.trend is None


class TestRecurringIssues:
    def test_recurring_issue_detected_when_active_in_majority_of_slices(self):
        # Events in 5 of 7 days for cam-1 → recurring
        events = [
            _event(f"e{i}", T0 + timedelta(days=i), camera_id="cam-1")
            for i in range(5)
        ] + [
            # cam-2 only in 1 day
            _event("e-other", T0, camera_id="cam-2", camera_name="Camera 2"),
        ]
        query = HotspotQuery(
            period_start=T0,
            period_end=T7,
            granularity=TimeGranularity.DAY,
            group_by=[AggregationAxis.CAMERA],
            compare_previous=False,
        )
        result = aggregate_hotspots(query, events)

        assert len(result.recurring_issues) == 1
        issue = result.recurring_issues[0]
        assert issue.group_key["camera_id"] == "cam-1"
        assert issue.slices_active == 5
        assert issue.total_slices == 7
        assert issue.recurrence_ratio == pytest.approx(5 / 7, rel=1e-2)
        assert "5/7" in issue.description


class TestOutputHelpers:
    def test_heatmap_output_is_not_limited_by_top_n(self):
        events = [
            _event(f"e{i}", T0 + timedelta(hours=i), camera_id=f"cam-{i}", camera_name=f"Camera {i}")
            for i in range(5)
        ]
        query = HotspotQuery(
            period_start=T0,
            period_end=T7,
            top_n=2,
            compare_previous=False,
        )
        result = aggregate_hotspots(query, events)

        assert len(result.ranking) == 2
        assert len(result.to_heatmap_list()) == 5

    def test_to_ranking_list_is_flat(self):
        events = [
            _event("e1", T0, camera_id="cam-1"),
            _event("e2", T0, camera_id="cam-2", camera_name="Camera 2"),
        ]
        query = HotspotQuery(
            period_start=T0,
            period_end=T7,
            compare_previous=False,
        )
        result = aggregate_hotspots(query, events)
        rows = result.to_ranking_list()
        assert len(rows) == 2
        assert rows[0]["rank"] == 1
        assert "camera_id" in rows[0]
        assert "event_count" in rows[0]
        assert "latitude" in rows[0]
        assert "weighted_delta" in rows[0]

    def test_to_heatmap_list_has_coordinates(self):
        events = [_event("e1", T0, latitude=40.1, longitude=-74.2)]
        query = HotspotQuery(
            period_start=T0,
            period_end=T7,
            compare_previous=False,
        )
        result = aggregate_hotspots(query, events)
        heatmap = result.to_heatmap_list()
        assert len(heatmap) == 1
        assert heatmap[0]["latitude"] == 40.1
        assert heatmap[0]["longitude"] == -74.2

    def test_methodology_is_present_and_transparent(self):
        events = [_event("e1", T0)]
        query = HotspotQuery(
            period_start=T0,
            period_end=T7,
            compare_previous=False,
        )
        result = aggregate_hotspots(query, events)
        assert len(result.methodology) > 0
        assert any("raw event count" in m for m in result.methodology)
        assert any("No opaque" in m for m in result.methodology)

    def test_heatmap_dict_on_bucket(self):
        events = [_event("e1", T0, zone_id="z1", zone_name="Zone A")]
        query = HotspotQuery(
            period_start=T0,
            period_end=T7,
            group_by=[AggregationAxis.ZONE],
            compare_previous=False,
        )
        result = aggregate_hotspots(query, events)
        hm = result.ranking[0].bucket.to_heatmap_dict()
        assert "zone_id" in hm
        assert "event_count" in hm


class TestAdapters:
    def test_lane_analytics_to_event_records_emits_congestion_records(self):
        analytics = [
            LaneAnalytics(
                lane_id="lane-1",
                lane_name="Lane 1",
                observed_at=T0,
                congestion_level=CongestionLevel.CONGESTED,
                occupancy=LaneOccupancyMetrics(
                    active_track_count=3,
                    occupied=True,
                    occupancy_ratio=0.8,
                    average_active_track_count=2.4,
                    peak_active_track_count=3,
                    window_seconds=60.0,
                ),
                queue=LaneQueueMetrics(
                    queue_detected=True,
                    queue_track_count=3,
                    queue_extent_px=90.0,
                    queue_duration_seconds=45.0,
                ),
            )
        ]

        records = lane_analytics_to_event_records(
            analytics,
            camera_id="cam-1",
            camera_name="Camera 1",
            location_name="Main St",
            latitude=40.0,
            longitude=-74.0,
        )

        assert len(records) == 1
        assert records[0].source_kind is HotspotSourceKind.CONGESTION
        assert records[0].event_type == "congested"
        assert records[0].lane_id == "lane-1"


class TestTopNLimit:
    def test_top_n_limits_ranking(self):
        events = [
            _event(f"e{i}", T0, camera_id=f"cam-{i}", camera_name=f"Camera {i}")
            for i in range(10)
        ]
        query = HotspotQuery(
            period_start=T0,
            period_end=T7,
            top_n=3,
            compare_previous=False,
        )
        result = aggregate_hotspots(query, events)
        assert len(result.ranking) == 3
        assert result.total_events == 10  # total not affected by top_n
        assert len(result.to_heatmap_list()) == 10


class TestEmptyInput:
    def test_empty_events(self):
        query = HotspotQuery(
            period_start=T0,
            period_end=T7,
            compare_previous=False,
        )
        result = aggregate_hotspots(query, [])
        assert result.total_events == 0
        assert result.ranking == []
        assert result.recurring_issues == []
