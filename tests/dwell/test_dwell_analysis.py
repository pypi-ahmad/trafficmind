"""Tests for stationary-object and dwell-time analysis."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.dwell import (
    DwellAnalysis,
    DwellOutcome,
    DwellScenario,
    DwellThresholds,
    StationarityAssessment,
    analyze_dwell,
    assess_stationarity,
)
from services.dwell.schemas import DwellThresholds as _DT
from services.tracking.schemas import Point2D, TrackedObject, TrajectoryPoint
from services.vision.schemas import BBox, ObjectCategory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_T0 = datetime(2026, 4, 5, 12, 0, 0, tzinfo=timezone.utc)


def _make_track(
    points: list[tuple[float, float]],
    *,
    start: datetime = _T0,
    spacing: float = 1.0,
    category: ObjectCategory = ObjectCategory.VEHICLE,
    track_id: str = "track-001",
) -> TrackedObject:
    trajectory: list[TrajectoryPoint] = []
    for i, (x, y) in enumerate(points):
        trajectory.append(
            TrajectoryPoint(
                point=Point2D(x=x, y=y),
                frame_index=i * 10,
                timestamp=start + timedelta(seconds=spacing * i),
            )
        )
    return TrackedObject(
        track_id=track_id,
        class_name="car" if category == ObjectCategory.VEHICLE else "person",
        category=category,
        bbox=BBox(x1=0, y1=0, x2=10, y2=10),
        confidence=0.9,
        first_seen_at=trajectory[0].timestamp,
        last_seen_at=trajectory[-1].timestamp,
        frame_count=len(trajectory),
        trajectory=trajectory,
    )


def _parking_thresholds(**overrides) -> DwellThresholds:
    return _DT.illegal_parking(**overrides)


def _no_stopping_thresholds(**overrides) -> DwellThresholds:
    return _DT.no_stopping(**overrides)


# ---------------------------------------------------------------------------
# Stationarity assessment tests
# ---------------------------------------------------------------------------


class TestAssessStationarity:
    def test_fully_stationary_track(self):
        """All points at (5, 5) → 100% stationary."""
        pts = [
            TrajectoryPoint(point=Point2D(x=5, y=5), frame_index=i * 10,
                            timestamp=_T0 + timedelta(seconds=i))
            for i in range(10)
        ]
        result = assess_stationarity(pts,  stationary_speed_px=2.0)

        assert result.stationary_ratio == 1.0
        assert result.is_currently_stationary is True
        assert result.longest_stationary_streak_samples == 9
        assert result.current_speed_px == 0.0
        assert result.average_speed_px == 0.0

    def test_fully_moving_track(self):
        """3 px displacement per step → 0% stationary at 2.0 px threshold."""
        pts = [
            TrajectoryPoint(point=Point2D(x=i * 3.0, y=0), frame_index=i * 10,
                            timestamp=_T0 + timedelta(seconds=i))
            for i in range(10)
        ]
        result = assess_stationarity(pts, stationary_speed_px=2.0)

        assert result.stationary_ratio == 0.0
        assert result.is_currently_stationary is False
        assert result.longest_stationary_streak_samples == 0

    def test_intermittent_stops(self):
        """Stop → move → stop pattern gives partial ratio."""
        pts = []
        for i in range(3):
            pts.append(TrajectoryPoint(point=Point2D(x=0, y=0), frame_index=i * 10,
                                       timestamp=_T0 + timedelta(seconds=i)))
        for i in range(3, 6):
            pts.append(TrajectoryPoint(point=Point2D(x=(i - 2) * 5.0, y=0), frame_index=i * 10,
                                       timestamp=_T0 + timedelta(seconds=i)))
        for i in range(6, 10):
            pts.append(TrajectoryPoint(point=Point2D(x=15, y=0), frame_index=i * 10,
                                       timestamp=_T0 + timedelta(seconds=i)))

        result = assess_stationarity(pts, stationary_speed_px=2.0)

        # 2 stationary segments (0→1, 1→2) + 3 moving + 3 stationary (6→7..9→—)
        assert 0.0 < result.stationary_ratio < 1.0
        assert result.is_currently_stationary is True

    def test_lookback_limits_window(self):
        """Only the last N points should be analysed when lookback is set."""
        pts = [
            TrajectoryPoint(point=Point2D(x=i * 10.0, y=0), frame_index=i * 10,
                            timestamp=_T0 + timedelta(seconds=i))
            for i in range(20)
        ]
        # Append stationary tail
        for i in range(20, 25):
            pts.append(TrajectoryPoint(point=Point2D(x=190, y=0), frame_index=i * 10,
                                       timestamp=_T0 + timedelta(seconds=i)))

        result = assess_stationarity(pts, stationary_speed_px=2.0, lookback=5)

        # Last 5 points are all at x=190 → fully stationary
        assert result.stationary_ratio == 1.0

    def test_single_point_trajectory(self):
        pts = [TrajectoryPoint(point=Point2D(x=5, y=5), frame_index=0, timestamp=_T0)]

        result = assess_stationarity(pts, stationary_speed_px=2.0)

        assert result.samples_analyzed == 1
        assert result.stationary_ratio == 1.0
        assert result.is_currently_stationary is True

    def test_streak_duration_uses_timestamps(self):
        """Longest streak seconds should use actual timestamps, not just sample count."""
        pts = [
            TrajectoryPoint(point=Point2D(x=0, y=0), frame_index=i * 10,
                            timestamp=_T0 + timedelta(seconds=i * 2.0))
            for i in range(6)
        ]
        result = assess_stationarity(pts, stationary_speed_px=2.0)

        # 5 segments, 2 seconds each → 10 seconds total streak
        assert result.longest_stationary_streak_seconds == 10.0


# ---------------------------------------------------------------------------
# Dwell analysis tests
# ---------------------------------------------------------------------------


class TestAnalyzeDwell:
    def test_violation_after_threshold(self):
        """Stationary vehicle past max_dwell_seconds → VIOLATION."""
        track = _make_track([(5, 5)] * 20, spacing=5.0)
        entered_at = _T0
        timestamp = _T0 + timedelta(seconds=130)

        result = analyze_dwell(
            track,
            thresholds=_parking_thresholds(max_dwell_seconds=120.0),
            entered_at=entered_at,
            timestamp=timestamp,
            zone_id="zone-1",
            zone_name="No Parking Zone",
        )

        assert result.outcome is DwellOutcome.VIOLATION
        assert result.scenario is DwellScenario.ILLEGAL_PARKING
        assert result.threshold_exceeded_by > 0
        assert result.dwell_seconds >= 120.0
        assert "zone-1" in (result.zone_id or "")

    def test_grace_period_suppresses_short_dwell(self):
        """Dwell within grace period → GRACE_PERIOD, not a violation."""
        track = _make_track([(5, 5)] * 5, spacing=1.0)
        entered_at = _T0
        timestamp = _T0 + timedelta(seconds=3)

        result = analyze_dwell(
            track,
            thresholds=_parking_thresholds(grace_period_seconds=10.0),
            entered_at=entered_at,
            timestamp=timestamp,
        )

        assert result.outcome is DwellOutcome.GRACE_PERIOD

    def test_intermittent_motion_prevents_trigger(self):
        """Vehicle that keeps moving intermittently → BELOW_THRESHOLD due to low stationary ratio."""
        # Alternating stationary and large moves
        points = []
        for i in range(20):
            x = 0.0 if i % 2 == 0 else (i * 5.0)
            points.append((x, 0.0))

        track = _make_track(points, spacing=5.0)
        entered_at = _T0
        timestamp = _T0 + timedelta(seconds=200)

        result = analyze_dwell(
            track,
            thresholds=_parking_thresholds(
                max_dwell_seconds=60.0,
                min_stationary_ratio=0.7,
            ),
            entered_at=entered_at,
            timestamp=timestamp,
        )

        assert result.outcome is DwellOutcome.BELOW_THRESHOLD
        assert len(result.warnings) > 0

    def test_moving_vehicle_not_flagged(self):
        """A vehicle that is consistently moving → BELOW_THRESHOLD."""
        track = _make_track([(i * 5.0, 0) for i in range(20)], spacing=5.0)
        entered_at = _T0
        timestamp = _T0 + timedelta(seconds=200)

        result = analyze_dwell(
            track,
            thresholds=_parking_thresholds(max_dwell_seconds=60.0),
            entered_at=entered_at,
            timestamp=timestamp,
        )

        assert result.outcome is DwellOutcome.BELOW_THRESHOLD

    def test_non_vehicle_category_filtered(self):
        """Pedestrians should not trigger illegal parking."""
        track = _make_track([(5, 5)] * 20, spacing=5.0, category=ObjectCategory.PERSON)
        entered_at = _T0
        timestamp = _T0 + timedelta(seconds=200)

        result = analyze_dwell(
            track,
            thresholds=_parking_thresholds(max_dwell_seconds=60.0),
            entered_at=entered_at,
            timestamp=timestamp,
        )

        assert result.outcome is DwellOutcome.BELOW_THRESHOLD
        assert "not applicable" in result.reason

    def test_candidate_before_threshold(self):
        """Stationary vehicle before threshold but past grace period → CANDIDATE."""
        track = _make_track([(5, 5)] * 10, spacing=5.0)
        entered_at = _T0
        timestamp = _T0 + timedelta(seconds=50)

        result = analyze_dwell(
            track,
            thresholds=_parking_thresholds(
                max_dwell_seconds=120.0,
                grace_period_seconds=10.0,
            ),
            entered_at=entered_at,
            timestamp=timestamp,
        )

        assert result.outcome is DwellOutcome.CANDIDATE

    def test_resumed_motion_clears_candidate(self):
        """If the vehicle resumes motion recently, don't flag it."""
        # Stationary then a big move at the end
        points: list[tuple[float, float]] = [(5, 5)] * 15
        points.append((50, 50))

        track = _make_track(points, spacing=5.0)
        entered_at = _T0
        timestamp = _T0 + timedelta(seconds=200)

        result = analyze_dwell(
            track,
            thresholds=_parking_thresholds(max_dwell_seconds=60.0),
            entered_at=entered_at,
            timestamp=timestamp,
        )

        assert result.outcome is DwellOutcome.BELOW_THRESHOLD
        assert any("resumed motion" in w for w in result.warnings)

    def test_no_stopping_scenario_shorter_threshold(self):
        """No-stopping zones have tighter thresholds."""
        track = _make_track([(5, 5)] * 15, spacing=3.0)
        entered_at = _T0
        timestamp = _T0 + timedelta(seconds=35)

        result = analyze_dwell(
            track,
            thresholds=_no_stopping_thresholds(max_dwell_seconds=30.0),
            entered_at=entered_at,
            timestamp=timestamp,
        )

        assert result.outcome is DwellOutcome.VIOLATION
        assert result.scenario is DwellScenario.NO_STOPPING

    def test_stalled_vehicle_high_stationary_ratio(self):
        """Stalled vehicle scenario requires very high stationary ratio."""
        # 80% stationary — below 85% threshold for stalled_vehicle
        points: list[tuple[float, float]] = [(5, 5)] * 16
        for i in range(4):
            points.append((5 + (i + 1) * 5.0, 5))

        track = _make_track(points, spacing=3.0)
        entered_at = _T0
        timestamp = _T0 + timedelta(seconds=100)

        result = analyze_dwell(
            track,
            thresholds=DwellThresholds.stalled_vehicle(max_dwell_seconds=45.0),
            entered_at=entered_at,
            timestamp=timestamp,
        )

        # Should fail the stationarity ratio check
        assert result.outcome is DwellOutcome.BELOW_THRESHOLD

    def test_to_detail_dict_is_serialisable(self):
        """The detail dict should be JSON-friendly."""
        track = _make_track([(5, 5)] * 20, spacing=5.0)
        result = analyze_dwell(
            track,
            thresholds=_parking_thresholds(max_dwell_seconds=60.0),
            entered_at=_T0,
            timestamp=_T0 + timedelta(seconds=200),
            zone_id="z1",
            zone_name="Test Zone",
            zone_type="restricted",
        )

        detail = result.to_detail_dict()

        assert isinstance(detail, dict)
        assert detail["scenario"] == "illegal_parking"
        assert detail["zone_id"] == "z1"
        assert detail["zone_type"] == "restricted"
        assert detail["object_class"] == "car"
        assert isinstance(detail["dwell_seconds"], float)
        assert isinstance(detail["stationary_ratio"], float)
        assert "motion_summary" in detail

    def test_missing_timing_data(self):
        """When no timing is available, analysis should safely return BELOW_THRESHOLD."""
        track = TrackedObject(
            track_id="t1",
            class_name="car",
            category=ObjectCategory.VEHICLE,
            bbox=BBox(x1=0, y1=0, x2=10, y2=10),
            confidence=0.9,
        )

        result = analyze_dwell(
            track,
            thresholds=_parking_thresholds(),
        )

        assert result.outcome is DwellOutcome.BELOW_THRESHOLD

    def test_bus_stop_thresholds_preset(self):
        """Bus-stop occupation preset should have correct defaults."""
        thresholds = DwellThresholds.bus_stop_occupation()

        assert thresholds.scenario is DwellScenario.BUS_STOP_OCCUPATION
        assert thresholds.max_dwell_seconds == 90.0
        assert thresholds.grace_period_seconds == 20.0
        assert thresholds.excluded_class_names == ["bus"]

    def test_creeping_motion_is_not_treated_as_stationary(self):
        """Slow creeping with tiny per-step motion should still be rejected."""
        points = [(index * 1.5, 0.0) for index in range(12)]
        track = _make_track(points, spacing=2.0)

        result = analyze_dwell(
            track,
            thresholds=_parking_thresholds(
                max_dwell_seconds=15.0,
                stationary_speed_px=2.0,
                max_stationary_displacement_px=10.0,
            ),
            entered_at=_T0,
            timestamp=_T0 + timedelta(seconds=40),
        )

        assert result.outcome is DwellOutcome.BELOW_THRESHOLD
        assert result.stationarity.net_displacement_px > 10.0
        assert any("creeping" in warning for warning in result.warnings)

    def test_zone_based_analysis_requires_entry_timing_when_lifetime_fallback_disabled(self):
        """Zone dwell logic should not infer dwell from total track lifetime when entry time is unknown."""
        track = _make_track([(5, 5)] * 20, spacing=5.0)

        result = analyze_dwell(
            track,
            thresholds=_parking_thresholds(max_dwell_seconds=30.0),
            zone_id="z1",
            zone_name="No Parking",
            zone_type="restricted",
            allow_track_lifetime_fallback=False,
        )

        assert result.outcome is DwellOutcome.BELOW_THRESHOLD
        assert "Insufficient timing data" in result.reason

    def test_bus_stop_analysis_exempts_bus_class(self):
        """Bus-stop occupation should exempt actual buses by default."""
        track = _make_track([(5, 5)] * 20, spacing=5.0)
        bus_track = track.model_copy(update={"class_name": "bus"})

        result = analyze_dwell(
            bus_track,
            thresholds=DwellThresholds.bus_stop_occupation(max_dwell_seconds=30.0),
            entered_at=_T0,
            timestamp=_T0 + timedelta(seconds=120),
            zone_id="bus-stop-1",
            zone_name="Bus Stop",
            zone_type="restricted",
        )

        assert result.outcome is DwellOutcome.BELOW_THRESHOLD
        assert "exempt" in result.reason


# ---------------------------------------------------------------------------
# Rule evaluator integration tests
# ---------------------------------------------------------------------------


class TestDwellRuleEvaluators:
    def test_illegal_parking_evaluator_uses_dwell_analyzer(self):
        """The updated evaluator should use the dwell analyzer internally."""
        from services.rules.evaluators import evaluate_illegal_parking
        from services.rules.schemas import IllegalParkingRuleConfig, PolygonGeometry, ZoneConfig

        zone = ZoneConfig(
            zone_id="z1",
            name="No Parking",
            zone_type="polygon",
            geometry=PolygonGeometry(points=[
                Point2D(x=0, y=0), Point2D(x=100, y=0),
                Point2D(x=100, y=100), Point2D(x=0, y=100),
            ]),
        )
        rule = IllegalParkingRuleConfig(max_stationary_seconds=60.0)
        track = _make_track([(50, 50)] * 20, spacing=5.0)
        entered_at = _T0
        timestamp = _T0 + timedelta(seconds=120)

        violation = evaluate_illegal_parking(track, zone, rule, timestamp, entered_at)

        assert violation is not None
        assert violation.rule_type.value == "illegal_parking"
        assert "dwell_seconds" in violation.explanation.details

    def test_no_stopping_evaluator_fires(self):
        from services.rules.evaluators import evaluate_no_stopping
        from services.rules.schemas import NoStoppingRuleConfig, PolygonGeometry, ZoneConfig

        zone = ZoneConfig(
            zone_id="z2",
            name="No Stopping",
            zone_type="restricted",
            geometry=PolygonGeometry(points=[
                Point2D(x=0, y=0), Point2D(x=100, y=0),
                Point2D(x=100, y=100), Point2D(x=0, y=100),
            ]),
        )
        rule = NoStoppingRuleConfig(max_stationary_seconds=30.0)
        track = _make_track([(50, 50)] * 15, spacing=3.0)
        entered_at = _T0
        timestamp = _T0 + timedelta(seconds=35)

        violation = evaluate_no_stopping(track, zone, rule, timestamp, entered_at)

        assert violation is not None
        assert violation.rule_type.value == "no_stopping"

    def test_stalled_vehicle_evaluator_fires(self):
        from services.rules.evaluators import evaluate_stalled_vehicle
        from services.rules.schemas import PolygonGeometry, StalledVehicleRuleConfig, ZoneConfig

        zone = ZoneConfig(
            zone_id="z3",
            name="Active Lane",
            zone_type="lane",
            geometry=PolygonGeometry(points=[
                Point2D(x=0, y=0), Point2D(x=100, y=0),
                Point2D(x=100, y=100), Point2D(x=0, y=100),
            ]),
        )
        rule = StalledVehicleRuleConfig(max_stationary_seconds=45.0)
        track = _make_track([(50, 50)] * 30, spacing=3.0)
        entered_at = _T0
        timestamp = _T0 + timedelta(seconds=100)

        violation = evaluate_stalled_vehicle(track, zone, rule, timestamp, entered_at)

        assert violation is not None
        assert violation.rule_type.value == "stalled_vehicle"

    def test_bus_stop_evaluator_exempts_bus_class(self):
        from services.rules.evaluators import evaluate_bus_stop_occupation
        from services.rules.schemas import BusStopOccupationRuleConfig, PolygonGeometry, ZoneConfig

        zone = ZoneConfig(
            zone_id="z4",
            name="Bus Stop",
            zone_type="restricted",
            geometry=PolygonGeometry(points=[
                Point2D(x=0, y=0), Point2D(x=100, y=0),
                Point2D(x=100, y=100), Point2D(x=0, y=100),
            ]),
        )
        rule = BusStopOccupationRuleConfig(max_stationary_seconds=30.0)
        track = _make_track([(50, 50)] * 20, spacing=5.0).model_copy(update={"class_name": "bus"})
        entered_at = _T0
        timestamp = _T0 + timedelta(seconds=120)

        violation = evaluate_bus_stop_occupation(track, zone, rule, timestamp, entered_at)

        assert violation is None

    def test_parking_evaluator_no_violation_for_moving_vehicle(self):
        """Moving vehicle should not trigger illegal parking even past time threshold."""
        from services.rules.evaluators import evaluate_illegal_parking
        from services.rules.schemas import IllegalParkingRuleConfig, PolygonGeometry, ZoneConfig

        zone = ZoneConfig(
            zone_id="z1",
            name="No Parking",
            zone_type="polygon",
            geometry=PolygonGeometry(points=[
                Point2D(x=0, y=0), Point2D(x=100, y=0),
                Point2D(x=100, y=100), Point2D(x=0, y=100),
            ]),
        )
        rule = IllegalParkingRuleConfig(max_stationary_seconds=60.0)
        track = _make_track([(i * 5.0, 50) for i in range(20)], spacing=5.0)
        entered_at = _T0
        timestamp = _T0 + timedelta(seconds=200)

        violation = evaluate_illegal_parking(track, zone, rule, timestamp, entered_at)

        assert violation is None

    def test_rule_configs_parse_from_json(self):
        """New rule types should be parsable via the discriminated union."""
        from services.rules.schemas import parse_zone_config

        config = parse_zone_config(
            zone_id="z1",
            name="Test",
            zone_type="polygon",
            geometry={"points": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}]},
            rules_config={
                "rules": [
                    {"rule_type": "no_stopping", "max_stationary_seconds": 25},
                    {"rule_type": "bus_stop_occupation", "max_stationary_seconds": 60},
                    {"rule_type": "stalled_vehicle", "max_stationary_seconds": 40},
                    {"rule_type": "illegal_parking", "max_stationary_seconds": 90, "grace_period_seconds": 20},
                ]
            },
        )

        assert len(config.rules) == 4
        rule_types = [r.rule_type for r in config.rules]
        assert "no_stopping" in rule_types
        assert "bus_stop_occupation" in rule_types
        assert "stalled_vehicle" in rule_types
        assert "illegal_parking" in rule_types
