"""Calibration-aware speed estimation and motion analytics."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from services.motion.schemas import (
    CalibrationMode,
    EstimateQuality,
    FlowDirection,
    LaneRelativeDirection,
    MotionAnalytics,
    MotionCalibrationProfile,
    ReliabilityBand,
    SpeedUnit,
    TimeBasis,
    Vector2D,
)
from services.tracking.schemas import (
    CardinalDirection,
    MotionVector,
    TrackedObject,
    TrajectoryPoint,
)
from services.tracking.utils import estimate_direction


def estimate_track_motion(
    track: TrackedObject,
    *,
    calibration: MotionCalibrationProfile | None = None,
    fps_hint: float | None = None,
    lookback: int = 5,
    preferred_unit: SpeedUnit | None = None,
    stationary_epsilon_px: float = 1.0,
) -> MotionAnalytics:
    """Estimate track speed and motion semantics conservatively."""

    profile = calibration or MotionCalibrationProfile()
    unit = preferred_unit or (
        SpeedUnit.KM_PER_H if profile.mode is not CalibrationMode.NONE else SpeedUnit.PX_PER_SECOND
    )
    samples = list(track.trajectory[-lookback:]) if track.trajectory else []
    heading = estimate_direction(track.trajectory, lookback=lookback, stationary_epsilon=stationary_epsilon_px)
    if heading is None:
        heading = track.direction

    assumptions: list[str] = []
    warnings: list[str] = []
    frame_delta = _frame_delta(samples)
    elapsed_seconds, time_basis = _elapsed_seconds(samples, track, fps_hint)
    distance_px = _path_length_px(samples)
    distance_m = _distance_m(samples, profile)

    estimated_speed = 0.0
    speed_unit = unit
    estimate_quality = _quality_from_profile(profile)

    if elapsed_seconds is not None and elapsed_seconds > 0:
        if profile.mode is CalibrationMode.NONE or distance_m is None:
            estimated_speed = distance_px / elapsed_seconds
            speed_unit = SpeedUnit.PX_PER_SECOND
            estimate_quality = EstimateQuality.ROUGH
            assumptions.append("No physical calibration available; speed is reported in pixels per second.")
        else:
            meters_per_second = distance_m / elapsed_seconds
            estimated_speed = _convert_from_mps(meters_per_second, unit)
            speed_unit = unit
            if profile.mode is CalibrationMode.SCALE_APPROXIMATION:
                assumptions.append("Physical speed is based on an approximate meters-per-pixel scale.")
            else:
                assumptions.append("Physical speed is based on a calibrated ground-plane transform.")
    elif frame_delta is not None and frame_delta > 0:
        estimated_speed = distance_px / frame_delta
        speed_unit = SpeedUnit.PX_PER_FRAME
        estimate_quality = EstimateQuality.ROUGH
        warnings.append("No timestamp basis was available; speed fell back to pixels per frame.")
        time_basis = TimeBasis.FRAME_ONLY
    else:
        estimated_speed = 0.0
        speed_unit = SpeedUnit.PX_PER_SECOND
        estimate_quality = EstimateQuality.ROUGH
        warnings.append("Insufficient trajectory history for a meaningful speed estimate.")

    if profile.mode is CalibrationMode.NONE:
        assumptions.append("Calibration-aware distance conversion is unavailable.")

    reliability_score = _reliability_score(
        profile=profile,
        sample_count=len(samples),
        elapsed_seconds=elapsed_seconds,
        distance_px=distance_px,
        time_basis=time_basis,
    )
    reliability = _band_from_score(reliability_score)
    enforcement_grade = bool(
        profile.mode is CalibrationMode.PLANAR_HOMOGRAPHY
        and profile.enforcement_validated
        and reliability is ReliabilityBand.HIGH
        and speed_unit in {SpeedUnit.M_PER_S, SpeedUnit.KM_PER_H, SpeedUnit.MPH}
    )
    if not enforcement_grade:
        warnings.append("This estimate should be treated as analytics / screening support, not an automatic enforcement claim.")

    scene_direction_label = _scene_direction_label(
        heading.direction if heading else CardinalDirection.STATIONARY,
        profile,
    )
    inbound_outbound = _classify_relative_flow(
        heading,
        profile.direction.inbound_vector,
        positive=FlowDirection.INBOUND,
        negative=FlowDirection.OUTBOUND,
    )
    lane_relative_direction = _classify_lane_direction(heading, profile.direction.lane_direction_vector)

    return MotionAnalytics(
        track_id=track.track_id,
        estimated_speed=round(estimated_speed, 3),
        speed_unit=speed_unit,
        estimate_quality=estimate_quality,
        calibration_mode=profile.mode,
        time_basis=time_basis,
        reliability=reliability,
        reliability_score=round(reliability_score, 3),
        enforcement_grade=enforcement_grade,
        heading=heading,
        cardinal_direction=heading.direction if heading else CardinalDirection.STATIONARY,
        scene_direction_label=scene_direction_label,
        inbound_outbound=inbound_outbound,
        lane_relative_direction=lane_relative_direction,
        distance_px=round(distance_px, 3),
        distance_m=round(distance_m, 3) if distance_m is not None else None,
        elapsed_seconds=round(elapsed_seconds, 3) if elapsed_seconds is not None else None,
        frame_delta=frame_delta,
        assumptions=assumptions,
        warnings=warnings,
    )


def _frame_delta(samples: Sequence[TrajectoryPoint]) -> int | None:
    if len(samples) < 2:
        return None
    if samples[0].frame_index is not None and samples[-1].frame_index is not None:
        return max(samples[-1].frame_index - samples[0].frame_index, 0)
    return max(len(samples) - 1, 0)


def _elapsed_seconds(
    samples: Sequence[TrajectoryPoint],
    track: TrackedObject,
    fps_hint: float | None,
) -> tuple[float | None, TimeBasis]:
    if len(samples) >= 2 and samples[0].timestamp is not None and samples[-1].timestamp is not None:
        return max((samples[-1].timestamp - samples[0].timestamp).total_seconds(), 0.0), TimeBasis.TIMESTAMP
    # Do NOT fall back to track.first_seen_at / last_seen_at here: the lookback
    # window may be shorter than the full track lifetime, which would over-state
    # elapsed time and under-state speed.
    frame_delta = _frame_delta(samples)
    if fps_hint and fps_hint > 0 and frame_delta is not None:
        return frame_delta / fps_hint, TimeBasis.FPS_HINT
    return None, TimeBasis.FRAME_ONLY


def _path_length_px(samples: Sequence[TrajectoryPoint]) -> float:
    if len(samples) < 2:
        return 0.0
    distance = 0.0
    for previous, current in zip(samples[:-1], samples[1:], strict=False):
        dx = current.point.x - previous.point.x
        dy = current.point.y - previous.point.y
        distance += math.hypot(dx, dy)
    return distance


def _distance_m(samples: Sequence[TrajectoryPoint], profile: MotionCalibrationProfile) -> float | None:
    if len(samples) < 2:
        return None
    if profile.mode is CalibrationMode.SCALE_APPROXIMATION and profile.scale is not None:
        return _path_length_px(samples) * profile.scale.meters_per_pixel
    if profile.mode is CalibrationMode.PLANAR_HOMOGRAPHY and profile.homography is not None:
        transformed = [_apply_homography(point.point.x, point.point.y, profile) for point in samples]
        distance = 0.0
        for previous, current in zip(transformed[:-1], transformed[1:], strict=False):
            dx = current[0] - previous[0]
            dy = current[1] - previous[1]
            distance += math.hypot(dx, dy)
        return distance
    return None


def _apply_homography(x: float, y: float, profile: MotionCalibrationProfile) -> tuple[float, float]:
    assert profile.homography is not None
    h = np.asarray(profile.homography.homography_matrix, dtype=np.float64)
    vec = np.asarray([x, y, 1.0], dtype=np.float64)
    projected = h @ vec
    w = projected[2] if abs(projected[2]) > 1e-9 else 1.0
    world_x = (projected[0] / w) * profile.homography.meters_per_world_unit
    world_y = (projected[1] / w) * profile.homography.meters_per_world_unit
    return float(world_x), float(world_y)


def _quality_from_profile(profile: MotionCalibrationProfile) -> EstimateQuality:
    if profile.mode is CalibrationMode.PLANAR_HOMOGRAPHY:
        return EstimateQuality.CALIBRATED
    if profile.mode is CalibrationMode.SCALE_APPROXIMATION:
        return EstimateQuality.APPROXIMATE
    return EstimateQuality.ROUGH


def _reliability_score(
    *,
    profile: MotionCalibrationProfile,
    sample_count: int,
    elapsed_seconds: float | None,
    distance_px: float,
    time_basis: TimeBasis,
) -> float:
    if profile.mode is CalibrationMode.PLANAR_HOMOGRAPHY:
        score = 0.8
    elif profile.mode is CalibrationMode.SCALE_APPROXIMATION:
        score = 0.62
    else:
        score = 0.4

    if sample_count < 3:
        score -= 0.15
    if elapsed_seconds is None or elapsed_seconds <= 0:
        score -= 0.2
    elif elapsed_seconds < 0.4:
        score -= 0.1
    if distance_px < 5.0:
        score -= 0.15
    if time_basis is TimeBasis.FPS_HINT:
        score -= 0.05
    if time_basis is TimeBasis.FRAME_ONLY:
        score -= 0.2
    if profile.mode is CalibrationMode.NONE:
        score = min(score, 0.65)
    if profile.mode is CalibrationMode.SCALE_APPROXIMATION:
        score = min(score, 0.74)
    if not profile.enforcement_validated:
        score = min(score, 0.85)
    return max(0.0, min(score, 1.0))


def _band_from_score(score: float) -> ReliabilityBand:
    if score >= 0.75:
        return ReliabilityBand.HIGH
    if score >= 0.45:
        return ReliabilityBand.MEDIUM
    return ReliabilityBand.LOW


def _scene_direction_label(direction: CardinalDirection, profile: MotionCalibrationProfile) -> str | None:
    if direction is CardinalDirection.STATIONARY:
        return "stationary"
    scene_map = profile.direction.scene_direction_map
    if direction.value in scene_map:
        return scene_map[direction.value]
    return f"{direction.value}bound"


def _classify_relative_flow(
    heading: MotionVector | None,
    reference: Vector2D | None,
    *,
    positive: FlowDirection,
    negative: FlowDirection,
) -> FlowDirection:
    if heading is None or reference is None or heading.magnitude <= 0:
        return FlowDirection.UNKNOWN
    cosine = _cosine_similarity(heading.dx, heading.dy, reference.dx, reference.dy)
    if cosine >= 0.5:
        return positive
    if cosine <= -0.5:
        return negative
    return FlowDirection.CROSSING


def _classify_lane_direction(
    heading: MotionVector | None,
    reference: Vector2D | None,
) -> LaneRelativeDirection:
    if heading is None or reference is None or heading.magnitude <= 0:
        return LaneRelativeDirection.UNKNOWN
    cosine = _cosine_similarity(heading.dx, heading.dy, reference.dx, reference.dy)
    if cosine >= 0.5:
        return LaneRelativeDirection.WITH_FLOW
    if cosine <= -0.5:
        return LaneRelativeDirection.AGAINST_FLOW
    return LaneRelativeDirection.CROSS_TRAFFIC


def _cosine_similarity(ax: float, ay: float, bx: float, by: float) -> float:
    denom = math.hypot(ax, ay) * math.hypot(bx, by)
    if denom <= 1e-9:
        return 0.0
    return max(-1.0, min(1.0, ((ax * bx) + (ay * by)) / denom))


def _convert_from_mps(value_mps: float, unit: SpeedUnit) -> float:
    if unit is SpeedUnit.M_PER_S:
        return value_mps
    if unit is SpeedUnit.KM_PER_H:
        return value_mps * 3.6
    if unit is SpeedUnit.MPH:
        return value_mps * 2.2369362921
    msg = f"Cannot convert m/s to non-physical speed unit {unit.value!r}"
    raise ValueError(msg)
