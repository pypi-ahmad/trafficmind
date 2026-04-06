from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.api.app.db.enums import ZoneType
from services.flow import (
    LaneAnalyticsEngine,
    analyze_lane_snapshot,
    load_lane_analytics_config,
)
from services.flow.schemas import CongestionLevel, QueueAnchorSource
from services.rules.schemas import LineGeometry, PolygonGeometry, ZoneConfig
from services.tracking.schemas import (
    Point2D,
    TrackedObject,
    TrackingResult,
    TrajectoryPoint,
)
from services.vision.schemas import BBox, ObjectCategory

T0 = datetime(2026, 4, 5, 12, 0, 0, tzinfo=UTC)


def _make_track(
    track_id: str,
    points: list[tuple[float, float]],
    *,
    start: datetime = T0,
    spacing_seconds: float = 1.0,
    class_name: str = "car",
) -> TrackedObject:
    trajectory = [
        TrajectoryPoint(
            point=Point2D(x=x, y=y),
            frame_index=index,
            timestamp=start + timedelta(seconds=index * spacing_seconds),
        )
        for index, (x, y) in enumerate(points)
    ]
    return TrackedObject(
        track_id=track_id,
        class_name=class_name,
        category=ObjectCategory.VEHICLE,
        bbox=BBox(x1=0, y1=0, x2=10, y2=10),
        confidence=0.9,
        first_seen_at=trajectory[0].timestamp,
        last_seen_at=trajectory[-1].timestamp,
        frame_count=len(trajectory),
        trajectory=trajectory,
    )


def _lane_zone() -> ZoneConfig:
    return ZoneConfig(
        zone_id="lane-1",
        name="Lane 1",
        zone_type=ZoneType.LANE,
        geometry=PolygonGeometry(
            points=[
                Point2D(x=0, y=0),
                Point2D(x=300, y=0),
                Point2D(x=300, y=120),
                Point2D(x=0, y=120),
            ]
        ),
    )


def _stop_line_zone() -> ZoneConfig:
    return ZoneConfig(
        zone_id="stop-1",
        name="Stop Line 1",
        zone_type=ZoneType.STOP_LINE,
        geometry=LineGeometry(
            start=Point2D(x=10, y=60),
            end=Point2D(x=10, y=100),
        ),
    )


def test_load_lane_analytics_config_from_camera_config_and_zones():
    configs = load_lane_analytics_config(
        {
            "lane_analytics": {
                "defaults": {
                    "window_seconds": 90.0,
                    "nominal_capacity_count": 5,
                },
                "lanes": [
                    {
                        "lane_zone_id": "lane-1",
                        "stop_line_zone_id": "stop-1",
                        "min_queue_count": 3,
                    }
                ],
            }
        },
        [_lane_zone(), _stop_line_zone()],
    )

    assert len(configs) == 1
    config = configs[0]
    assert config.lane_id == "lane-1"
    assert config.stop_line is not None
    assert config.window_seconds == 90.0
    assert config.nominal_capacity_count == 5
    assert config.min_queue_count == 3


def test_lane_occupancy_over_time_and_utilization():
    config = load_lane_analytics_config(
        {
            "lane_analytics": {
                "defaults": {
                    "window_seconds": 60.0,
                    "nominal_capacity_count": 4,
                },
            }
        },
        [_lane_zone()],
    )[0]
    engine = LaneAnalyticsEngine([config])

    occupied_tracks = [
        _make_track("t1", [(30, 60), (32, 60), (33, 60)]),
        _make_track("t2", [(90, 60), (92, 60), (94, 60)]),
    ]
    result_a = engine.evaluate(TrackingResult(tracks=occupied_tracks, timestamp=T0))[0]
    result_b = engine.evaluate(TrackingResult(tracks=[], timestamp=T0 + timedelta(seconds=30)))[0]
    result_c = engine.evaluate(TrackingResult(tracks=[], timestamp=T0 + timedelta(seconds=60)))[0]

    assert result_a.occupancy.active_track_count == 2
    assert result_c.occupancy.occupancy_ratio == pytest.approx(0.5, rel=1e-3)
    assert result_c.occupancy.average_active_track_count == pytest.approx(1.0, rel=1e-3)
    assert result_c.occupancy.utilization_ratio == pytest.approx(0.25, rel=1e-3)
    assert result_b.congestion_level in {
        CongestionLevel.HEAVY,
        CongestionLevel.CONGESTED,
        CongestionLevel.FREE_FLOW,
    }


def test_queue_detection_by_count_and_spatial_extent():
    config = load_lane_analytics_config(
        {
            "lane_analytics": {
                "lanes": [
                    {
                        "lane_zone_id": "lane-1",
                        "stop_line_zone_id": "stop-1",
                        "queue_anchor_radius_px": 40.0,
                        "max_queue_gap_px": 50.0,
                        "min_queue_count": 2,
                    }
                ]
            }
        },
        [_lane_zone(), _stop_line_zone()],
    )[0]

    tracks = [
        _make_track("q1", [(18, 80), (18, 80), (18, 80)], spacing_seconds=2.0),
        _make_track("q2", [(58, 80), (58, 80), (58, 80)], spacing_seconds=2.0),
        _make_track("q3", [(98, 80), (98, 80), (98, 80)], spacing_seconds=2.0),
    ]
    analytics, _, _ = analyze_lane_snapshot(config, tracks, timestamp=T0)

    assert analytics.queue.anchor_source is QueueAnchorSource.STOP_LINE
    assert analytics.queue.queue_detected is True
    assert analytics.queue.queue_track_count == 3
    assert analytics.queue.queue_extent_px > 80.0
    assert analytics.congestion_level is CongestionLevel.QUEUED


def test_moving_vehicle_near_stop_line_does_not_form_queue():
    config = load_lane_analytics_config(
        {
            "lane_analytics": {
                "lanes": [
                    {
                        "lane_zone_id": "lane-1",
                        "stop_line_zone_id": "stop-1",
                        "queue_anchor_radius_px": 40.0,
                        "max_queue_gap_px": 50.0,
                        "min_queue_count": 2,
                    }
                ]
            }
        },
        [_lane_zone(), _stop_line_zone()],
    )[0]

    tracks = [
        _make_track("lead", [(18, 80), (26, 80), (34, 80), (42, 80)], spacing_seconds=2.0),
        _make_track("follower", [(58, 80), (58, 80), (58, 80), (58, 80)], spacing_seconds=2.0),
    ]
    analytics, _, _ = analyze_lane_snapshot(config, tracks, timestamp=T0)

    assert analytics.queue.queue_detected is False
    assert analytics.queue.queue_track_count == 0


def test_moving_track_further_from_anchor_does_not_veto_queue():
    """Only the nearest track to the anchor can veto the queue, not a further one."""
    config = load_lane_analytics_config(
        {
            "lane_analytics": {
                "lanes": [
                    {
                        "lane_zone_id": "lane-1",
                        "stop_line_zone_id": "stop-1",
                        "queue_anchor_radius_px": 40.0,
                        "max_queue_gap_px": 60.0,
                        "min_queue_count": 2,
                    }
                ]
            }
        },
        [_lane_zone(), _stop_line_zone()],
    )[0]

    tracks = [
        # Nearest to anchor — stationary — should NOT veto
        _make_track("q1", [(18, 80), (18, 80), (18, 80)], spacing_seconds=2.0),
        # Second queued track — stationary
        _make_track("q2", [(58, 80), (58, 80), (58, 80)], spacing_seconds=2.0),
        # Third track is moving but further away — should not affect queue
        _make_track("mover", [(100, 80), (108, 80), (116, 80)], spacing_seconds=2.0),
    ]
    analytics, _, _ = analyze_lane_snapshot(config, tracks, timestamp=T0)

    assert analytics.queue.queue_detected is True
    assert analytics.queue.queue_track_count == 2


def test_queue_persistence_duration_and_congestion_upgrade():
    config = load_lane_analytics_config(
        {
            "lane_analytics": {
                "lanes": [
                    {
                        "lane_zone_id": "lane-1",
                        "stop_line_zone_id": "stop-1",
                        "queue_anchor_radius_px": 40.0,
                        "max_queue_gap_px": 50.0,
                        "min_queue_count": 2,
                        "congestion_queue_duration_seconds": 10.0,
                    }
                ]
            }
        },
        [_lane_zone(), _stop_line_zone()],
    )[0]
    engine = LaneAnalyticsEngine([config])
    tracks = [
        _make_track("q1", [(18, 80), (18, 80), (18, 80)], spacing_seconds=2.0),
        _make_track("q2", [(58, 80), (58, 80), (58, 80)], spacing_seconds=2.0),
    ]

    result_a = engine.evaluate(TrackingResult(tracks=tracks, timestamp=T0))[0]
    result_b = engine.evaluate(
        TrackingResult(tracks=tracks, timestamp=T0 + timedelta(seconds=12))
    )[0]

    assert result_a.queue.queue_duration_seconds == 0.0
    assert result_b.queue.queue_duration_seconds == 12.0
    assert result_b.congestion_level is CongestionLevel.CONGESTED


def test_queue_metrics_require_anchor_configuration():
    config = load_lane_analytics_config({}, [_lane_zone()])[0]
    tracks = [_make_track("t1", [(30, 60), (30, 60), (30, 60)], spacing_seconds=2.0)]
    analytics, _, _ = analyze_lane_snapshot(config, tracks, timestamp=T0)

    assert analytics.queue.anchor_source is QueueAnchorSource.NONE
    assert analytics.queue.queue_detected is False
    assert any("Queue analytics require" in warning for warning in analytics.warnings)


def test_dashboard_hotspot_and_incident_outputs_are_practical():
    config = load_lane_analytics_config(
        {
            "lane_analytics": {
                "defaults": {"nominal_capacity_count": 4},
                "lanes": [{"lane_zone_id": "lane-1", "stop_line_zone_id": "stop-1"}],
            }
        },
        [_lane_zone(), _stop_line_zone()],
    )[0]
    tracks = [
        _make_track("q1", [(18, 80), (18, 80), (18, 80)], spacing_seconds=2.0),
        _make_track("q2", [(58, 80), (58, 80), (58, 80)], spacing_seconds=2.0),
    ]
    analytics, _, _ = analyze_lane_snapshot(config, tracks, timestamp=T0)

    dashboard = analytics.to_dashboard_dict()
    hotspot = analytics.to_hotspot_dict()
    incident = analytics.to_incident_dict()

    assert dashboard["lane_id"] == "lane-1"
    assert isinstance(dashboard["observed_at"], str)  # ISO string, not datetime
    assert "occupancy_ratio" in dashboard
    assert "window_seconds" in dashboard
    assert dashboard["queue_anchor_source"] == "stop_line"
    assert "average_queue_track_count" in dashboard
    assert "peak_queue_track_count" in dashboard
    assert "assumptions" in dashboard
    assert len(dashboard["assumptions"]) > 0
    assert isinstance(hotspot["observed_at"], str)
    assert hotspot["lane_name"] == "Lane 1"
    assert hotspot["queue_anchor_source"] == "stop_line"
    assert "average_queue_track_count" in hotspot
    assert "peak_queue_track_count" in hotspot
    assert incident["queue_detected"] is True
    assert incident["queue_anchor_source"] == "stop_line"


def test_metric_assumptions_and_warmup_warning_are_explicit():
    config = load_lane_analytics_config(
        {
            "lane_analytics": {
                "defaults": {
                    "window_seconds": 60.0,
                    "nominal_capacity_count": 4,
                },
                "lanes": [{"lane_zone_id": "lane-1", "stop_line_zone_id": "stop-1"}],
            }
        },
        [_lane_zone(), _stop_line_zone()],
    )[0]
    tracks = [
        _make_track("q1", [(18, 80), (18, 80), (18, 80)], spacing_seconds=2.0),
        _make_track("q2", [(58, 80), (58, 80), (58, 80)], spacing_seconds=2.0),
    ]

    analytics, _, _ = analyze_lane_snapshot(config, tracks, timestamp=T0)

    assert any("Queue duration seconds" in item for item in analytics.assumptions)
    assert any("Utilization ratio" in item for item in analytics.assumptions)
    assert any("Congestion level" in item for item in analytics.assumptions)
    assert any("warming up" in warning for warning in analytics.warnings)


def test_high_occupancy_without_queue_escalates_to_congested():
    """Sustained high occupancy_ratio alone (no queue anchor) → CONGESTED."""
    config = load_lane_analytics_config(
        {
            "lane_analytics": {
                "defaults": {
                    "window_seconds": 30.0,
                    "congestion_occupancy_ratio": 0.65,
                },
            }
        },
        [_lane_zone()],
    )[0]
    engine = LaneAnalyticsEngine([config])

    # Every frame is occupied for the entire window → occupancy_ratio ≈ 1.0
    tracks = [
        _make_track("t1", [(30, 60), (32, 60), (33, 60)]),
        _make_track("t2", [(90, 60), (92, 60), (94, 60)]),
    ]
    engine.evaluate(TrackingResult(tracks=tracks, timestamp=T0))
    result = engine.evaluate(
        TrackingResult(tracks=tracks, timestamp=T0 + timedelta(seconds=30)),
    )[0]

    assert result.congestion_level is CongestionLevel.CONGESTED
    assert result.queue.queue_detected is False  # no anchor configured
