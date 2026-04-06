"""Higher-level analytics helpers built on motion estimates."""

from __future__ import annotations

from services.motion.schemas import (
    EstimateQuality,
    LaneRelativeDirection,
    MotionAnalytics,
    OverspeedCandidate,
    ReliabilityBand,
    SpeedUnit,
    WrongWayCandidate,
)


def detect_overspeed_candidate(
    motion: MotionAnalytics,
    *,
    speed_limit: float,
    speed_limit_unit: SpeedUnit = SpeedUnit.KM_PER_H,
    tolerance_ratio: float = 0.05,
    min_reliability: ReliabilityBand = ReliabilityBand.MEDIUM,
) -> OverspeedCandidate:
    """Return a conservative overspeed screening result."""

    if motion.estimate_quality is EstimateQuality.ROUGH:
        return OverspeedCandidate(
            is_candidate=False,
            estimated_speed=motion.estimated_speed,
            estimated_speed_unit=motion.speed_unit,
            speed_limit=speed_limit,
            speed_limit_unit=speed_limit_unit,
            reliability=motion.reliability,
            enforcement_grade=False,
            reason="rough pixel-space speed cannot support physical overspeed screening",
        )

    if _reliability_rank(motion.reliability) < _reliability_rank(min_reliability):
        return OverspeedCandidate(
            is_candidate=False,
            estimated_speed=motion.estimated_speed,
            estimated_speed_unit=motion.speed_unit,
            speed_limit=speed_limit,
            speed_limit_unit=speed_limit_unit,
            reliability=motion.reliability,
            enforcement_grade=motion.enforcement_grade,
            reason="speed estimate reliability is too low for overspeed screening",
        )

    estimated_in_limit_unit = _convert_speed(motion.estimated_speed, motion.speed_unit, speed_limit_unit)
    threshold = speed_limit * (1.0 + tolerance_ratio)
    if estimated_in_limit_unit <= threshold:
        return OverspeedCandidate(
            is_candidate=False,
            estimated_speed=motion.estimated_speed,
            estimated_speed_unit=motion.speed_unit,
            speed_limit=speed_limit,
            speed_limit_unit=speed_limit_unit,
            reliability=motion.reliability,
            enforcement_grade=motion.enforcement_grade,
            reason="estimated speed is below the overspeed screening threshold",
        )

    excess = estimated_in_limit_unit - speed_limit
    return OverspeedCandidate(
        is_candidate=True,
        estimated_speed=motion.estimated_speed,
        estimated_speed_unit=motion.speed_unit,
        speed_limit=speed_limit,
        speed_limit_unit=speed_limit_unit,
        excess_speed=round(excess, 3),
        reliability=motion.reliability,
        enforcement_grade=motion.enforcement_grade,
        requires_manual_review=not motion.enforcement_grade,
        reason=(
            "estimated speed exceeds the configured screening threshold"
            if motion.enforcement_grade
            else "estimated speed exceeds the configured screening threshold; manual validation required"
        ),
    )


def detect_wrong_way_candidate(
    motion: MotionAnalytics,
    *,
    expected_lane_direction: LaneRelativeDirection = LaneRelativeDirection.WITH_FLOW,
    allowed_scene_directions: set[str] | None = None,
) -> WrongWayCandidate:
    """Return a conservative wrong-way screening result."""

    if motion.lane_relative_direction not in {LaneRelativeDirection.UNKNOWN, expected_lane_direction}:
        return WrongWayCandidate(
            is_candidate=True,
            lane_relative_direction=motion.lane_relative_direction,
            scene_direction_label=motion.scene_direction_label,
            reliability=motion.reliability,
            requires_manual_review=True,
            reason="motion opposes the configured lane flow direction",
        )

    if (
        allowed_scene_directions
        and motion.scene_direction_label is not None
        and motion.scene_direction_label not in allowed_scene_directions
    ):
        return WrongWayCandidate(
            is_candidate=True,
            lane_relative_direction=motion.lane_relative_direction,
            scene_direction_label=motion.scene_direction_label,
            reliability=motion.reliability,
            requires_manual_review=True,
            reason="scene-direction label is outside the allowed movement set",
        )

    return WrongWayCandidate(
        is_candidate=False,
        lane_relative_direction=motion.lane_relative_direction,
        scene_direction_label=motion.scene_direction_label,
        reliability=motion.reliability,
        reason="motion does not indicate a wrong-way candidate",
    )


def _convert_speed(value: float, from_unit: SpeedUnit, to_unit: SpeedUnit) -> float:
    if from_unit == to_unit:
        return value
    mps = _to_mps(value, from_unit)
    return _from_mps(mps, to_unit)


def _to_mps(value: float, unit: SpeedUnit) -> float:
    if unit is SpeedUnit.M_PER_S:
        return value
    if unit is SpeedUnit.KM_PER_H:
        return value / 3.6
    if unit is SpeedUnit.MPH:
        return value / 2.2369362921
    msg = f"Cannot convert non-physical speed unit {unit.value!r} to m/s"
    raise ValueError(msg)


def _from_mps(value: float, unit: SpeedUnit) -> float:
    if unit is SpeedUnit.M_PER_S:
        return value
    if unit is SpeedUnit.KM_PER_H:
        return value * 3.6
    if unit is SpeedUnit.MPH:
        return value * 2.2369362921
    msg = f"Cannot convert m/s to non-physical speed unit {unit.value!r}"
    raise ValueError(msg)


def _reliability_rank(band: ReliabilityBand) -> int:
    if band is ReliabilityBand.HIGH:
        return 3
    if band is ReliabilityBand.MEDIUM:
        return 2
    return 1