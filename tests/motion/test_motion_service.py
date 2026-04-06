from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.motion import (
    CalibrationMode,
    EstimateQuality,
    LaneRelativeDirection,
    MotionCalibrationProfile,
    ReliabilityBand,
    SpeedUnit,
    detect_overspeed_candidate,
    detect_wrong_way_candidate,
    estimate_track_motion,
    load_motion_calibration,
)
from services.motion.schemas import (
    DirectionSemantics,
    FlowDirection,
    HomographyCalibration,
    ScaleApproximation,
    Vector2D,
)
from services.tracking.schemas import Point2D, TrackedObject, TrajectoryPoint
from services.vision.schemas import BBox, ObjectCategory


def _make_track(
    points: list[tuple[float, float]],
    *,
    start: datetime | None = None,
    spacing_seconds: float | None = 1.0,
    frame_step: int = 1,
) -> TrackedObject:
    start = start or datetime(2026, 4, 5, 12, 0, 0, tzinfo=timezone.utc)
    trajectory: list[TrajectoryPoint] = []
    for index, (x, y) in enumerate(points):
        timestamp = None if spacing_seconds is None else start + timedelta(seconds=spacing_seconds * index)
        trajectory.append(
            TrajectoryPoint(
                point=Point2D(x=x, y=y),
                frame_index=index * frame_step,
                timestamp=timestamp,
            )
        )
    return TrackedObject(
        track_id="track-001",
        class_name="car",
        category=ObjectCategory.VEHICLE,
        bbox=BBox(x1=0, y1=0, x2=10, y2=10),
        confidence=0.95,
        first_seen_at=trajectory[0].timestamp if trajectory[0].timestamp else None,
        last_seen_at=trajectory[-1].timestamp if trajectory[-1].timestamp else None,
        frame_count=len(trajectory),
        trajectory=trajectory,
    )


def test_rough_pixel_speed_uses_timestamps():
    track = _make_track([(0, 0), (10, 0)])

    result = estimate_track_motion(track)

    assert result.estimate_quality is EstimateQuality.ROUGH
    assert result.speed_unit is SpeedUnit.PX_PER_SECOND
    assert result.estimated_speed == pytest.approx(10.0)
    assert result.scene_direction_label == "eastbound"
    assert result.cardinal_direction.value == "east"
    assert result.enforcement_grade is False


def test_approximate_scale_estimate_returns_physical_speed_and_scene_labels():
    track = _make_track([(0, 0), (10, 0)])
    calibration = MotionCalibrationProfile(
        mode=CalibrationMode.SCALE_APPROXIMATION,
        scale=ScaleApproximation(meters_per_pixel=0.5),
        direction=DirectionSemantics(
            scene_direction_map={"east": "northbound"},
            inbound_vector=Vector2D(dx=1.0, dy=0.0),
            lane_direction_vector=Vector2D(dx=1.0, dy=0.0),
            lane_name="lane-a",
        ),
    )

    result = estimate_track_motion(track, calibration=calibration)

    assert result.estimate_quality is EstimateQuality.APPROXIMATE
    assert result.speed_unit is SpeedUnit.KM_PER_H
    assert result.estimated_speed == pytest.approx(18.0)
    assert result.scene_direction_label == "northbound"
    assert result.inbound_outbound is FlowDirection.INBOUND
    assert result.lane_relative_direction is LaneRelativeDirection.WITH_FLOW
    assert result.enforcement_grade is False


def test_calibrated_homography_can_be_high_reliability_when_validated():
    track = _make_track([(0, 0), (10, 0), (20, 0)])
    calibration = MotionCalibrationProfile(
        mode=CalibrationMode.PLANAR_HOMOGRAPHY,
        homography=HomographyCalibration(
            homography_matrix=[[0.5, 0.0, 0.0], [0.0, 0.5, 0.0], [0.0, 0.0, 1.0]],
        ),
        direction=DirectionSemantics(
            inbound_vector=Vector2D(dx=1.0, dy=0.0),
            lane_direction_vector=Vector2D(dx=1.0, dy=0.0),
        ),
        enforcement_validated=True,
    )

    result = estimate_track_motion(track, calibration=calibration)

    assert result.estimate_quality is EstimateQuality.CALIBRATED
    assert result.speed_unit is SpeedUnit.KM_PER_H
    assert result.estimated_speed == pytest.approx(18.0)
    assert result.reliability is ReliabilityBand.HIGH
    assert result.enforcement_grade is True


def test_frame_only_fallback_reports_pixels_per_frame():
    track = _make_track([(0, 0), (10, 0)], spacing_seconds=None, frame_step=5)

    result = estimate_track_motion(track)

    assert result.speed_unit is SpeedUnit.PX_PER_FRAME
    assert result.estimated_speed == pytest.approx(2.0)
    assert result.time_basis.value == "frame_only"


def test_fps_hint_can_recover_time_basis_without_timestamps():
    track = _make_track([(0, 0), (20, 0)], spacing_seconds=None, frame_step=10)

    result = estimate_track_motion(track, fps_hint=10.0)

    assert result.speed_unit is SpeedUnit.PX_PER_SECOND
    assert result.time_basis.value == "fps_hint"
    assert result.estimated_speed == pytest.approx(20.0)


def test_load_motion_calibration_from_camera_config():
    calibration = load_motion_calibration(
        {
            "motion": {
                "mode": "scale_approximation",
                "meters_per_pixel": 0.25,
                "scene_direction_labels": {"east": "northbound"},
                "inbound_vector": {"x": 1.0, "y": 0.0},
                "lane_direction_vector": {"dx": 1.0, "dy": 0.0},
                "lane_name": "lane-a",
            }
        }
    )

    assert calibration.mode is CalibrationMode.SCALE_APPROXIMATION
    assert calibration.scale is not None
    assert calibration.scale.meters_per_pixel == pytest.approx(0.25)
    assert calibration.direction.scene_direction_map["east"] == "northbound"
    assert calibration.direction.inbound_vector is not None
    assert calibration.direction.lane_direction_vector is not None


def test_direction_categories_support_outbound_and_against_flow():
    track = _make_track([(10, 0), (0, 0)])
    calibration = MotionCalibrationProfile(
        mode=CalibrationMode.SCALE_APPROXIMATION,
        scale=ScaleApproximation(meters_per_pixel=0.5),
        direction=DirectionSemantics(
            inbound_vector=Vector2D(dx=1.0, dy=0.0),
            lane_direction_vector=Vector2D(dx=1.0, dy=0.0),
        ),
    )

    result = estimate_track_motion(track, calibration=calibration)

    assert result.inbound_outbound is FlowDirection.OUTBOUND
    assert result.lane_relative_direction is LaneRelativeDirection.AGAINST_FLOW


def test_overspeed_candidate_requires_physical_speed():
    track = _make_track([(0, 0), (30, 0)])
    result = estimate_track_motion(track)

    overspeed = detect_overspeed_candidate(result, speed_limit=50.0)

    assert overspeed.is_candidate is False
    assert "pixel-space" in overspeed.reason


def test_overspeed_candidate_supports_approximate_screening():
    track = _make_track([(0, 0), (20, 0)])
    calibration = MotionCalibrationProfile(
        mode=CalibrationMode.SCALE_APPROXIMATION,
        scale=ScaleApproximation(meters_per_pixel=1.0),
    )
    result = estimate_track_motion(track, calibration=calibration)

    overspeed = detect_overspeed_candidate(result, speed_limit=50.0)

    assert result.estimated_speed == pytest.approx(72.0)
    assert overspeed.is_candidate is True
    assert overspeed.requires_manual_review is True


def test_wrong_way_candidate_detects_against_lane_flow():
    track = _make_track([(10, 0), (0, 0)])
    calibration = MotionCalibrationProfile(
        mode=CalibrationMode.SCALE_APPROXIMATION,
        scale=ScaleApproximation(meters_per_pixel=0.5),
        direction=DirectionSemantics(
            lane_direction_vector=Vector2D(dx=1.0, dy=0.0),
        ),
    )
    result = estimate_track_motion(track, calibration=calibration)

    wrong_way = detect_wrong_way_candidate(result)

    assert wrong_way.is_candidate is True
    assert wrong_way.lane_relative_direction is LaneRelativeDirection.AGAINST_FLOW


def test_motion_summary_dict_exposes_core_outputs():
    track = _make_track([(0, 0), (10, 0)])
    result = estimate_track_motion(track)

    summary = result.to_summary_dict()

    assert summary["track_id"] == "track-001"
    assert summary["speed_unit"] == "px/s"
    assert summary["estimate_quality"] == "rough"
    assert summary["cardinal_direction"] == "east"


def test_scale_approximation_never_reaches_high_reliability():
    """Scale-based estimates must stay below HIGH band to avoid overclaiming."""
    track = _make_track([(0, 0), (10, 0), (20, 0), (30, 0), (40, 0)])
    calibration = MotionCalibrationProfile(
        mode=CalibrationMode.SCALE_APPROXIMATION,
        scale=ScaleApproximation(meters_per_pixel=0.5),
        enforcement_validated=True,
    )

    result = estimate_track_motion(track, calibration=calibration)

    assert result.estimate_quality is EstimateQuality.APPROXIMATE
    assert result.reliability is not ReliabilityBand.HIGH
    assert result.enforcement_grade is False


def test_overspeed_candidate_carries_enforcement_grade():
    """Enforcement-grade motion analytics should propagate to the overspeed candidate."""
    track = _make_track([(0, 0), (30, 0), (60, 0)])
    calibration = MotionCalibrationProfile(
        mode=CalibrationMode.PLANAR_HOMOGRAPHY,
        homography=HomographyCalibration(
            homography_matrix=[[0.5, 0, 0], [0, 0.5, 0], [0, 0, 1]],
        ),
        enforcement_validated=True,
    )
    result = estimate_track_motion(track, calibration=calibration)
    assert result.enforcement_grade is True

    overspeed = detect_overspeed_candidate(result, speed_limit=10.0)

    assert overspeed.is_candidate is True
    assert overspeed.enforcement_grade is True
    assert overspeed.requires_manual_review is False


def test_wrong_way_none_label_not_flagged_by_allowed_set():
    """When no scene direction semantics are configured, allowed_scene_directions must
    not false-positive flag the track."""
    track = _make_track([(0, 0), (10, 0)])

    result = estimate_track_motion(track)
    # No calibration → scene_direction_label defaults to "eastbound" (not None).
    # Now simulate a None label scenario by overriding.
    no_label = result.model_copy(update={"scene_direction_label": None})

    wrong_way = detect_wrong_way_candidate(no_label, allowed_scene_directions={"northbound"})

    assert wrong_way.is_candidate is False


def test_convert_from_mps_rejects_pixel_unit():
    """Requesting a pixel-space unit for a calibrated speed must raise."""
    from services.motion.estimator import _convert_from_mps

    with pytest.raises(ValueError, match="non-physical"):
        _convert_from_mps(10.0, SpeedUnit.PX_PER_SECOND)