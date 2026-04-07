"""Calibration profile parsing for motion analytics."""

from __future__ import annotations

from typing import Any

from services.motion.schemas import (
    DirectionSemantics,
    HomographyCalibration,
    MotionCalibrationProfile,
    ScaleApproximation,
    Vector2D,
)


def load_motion_calibration(calibration_config: dict[str, Any] | None) -> MotionCalibrationProfile:
    """Parse the motion-specific portion of a camera calibration config.

    Accepted shapes:
    - {"motion": {...}}
    - {"speed_estimation": {...}}
    - direct motion payload at the root
    """

    if not calibration_config:
        return MotionCalibrationProfile()

    payload = (
        calibration_config.get("motion")
        or calibration_config.get("speed_estimation")
        or calibration_config
    )

    scale_payload = payload.get("scale")
    if scale_payload is None and payload.get("meters_per_pixel") is not None:
        scale_payload = {
            "meters_per_pixel": payload.get("meters_per_pixel"),
            "source_note": payload.get("scale_source_note"),
        }

    homography_payload = payload.get("homography")
    if homography_payload is None and payload.get("homography_matrix") is not None:
        homography_payload = {
            "homography_matrix": payload.get("homography_matrix"),
            "meters_per_world_unit": payload.get("meters_per_world_unit", 1.0),
            "source_note": payload.get("homography_source_note"),
        }

    direction_payload = payload.get("direction") or {}
    if not direction_payload and any(
        key in payload
        for key in ("scene_direction_map", "scene_direction_labels", "inbound_vector", "lane_direction_vector")
    ):
        direction_payload = {
            "scene_direction_map": payload.get("scene_direction_map")
            or payload.get("scene_direction_labels")
            or {},
            "inbound_vector": payload.get("inbound_vector"),
            "lane_direction_vector": payload.get("lane_direction_vector"),
            "lane_name": payload.get("lane_name"),
        }

    return MotionCalibrationProfile(
        mode=payload.get("mode", "none"),
        scale=ScaleApproximation(**scale_payload) if scale_payload else None,
        homography=HomographyCalibration(**homography_payload) if homography_payload else None,
        direction=DirectionSemantics(
            scene_direction_map=direction_payload.get("scene_direction_map", {}),
            inbound_vector=_load_vector(direction_payload.get("inbound_vector")),
            lane_direction_vector=_load_vector(direction_payload.get("lane_direction_vector")),
            lane_name=direction_payload.get("lane_name"),
        ),
        enforcement_validated=bool(payload.get("enforcement_validated", False)),
        notes=payload.get("notes"),
    )


def _load_vector(value: Any) -> Vector2D | None:
    if value is None:
        return None
    if isinstance(value, Vector2D):
        return value
    if isinstance(value, dict):
        if "dx" in value or "dy" in value:
            return Vector2D(dx=float(value.get("dx", 0.0)), dy=float(value.get("dy", 0.0)))
        if "x" in value or "y" in value:
            return Vector2D(dx=float(value.get("x", 0.0)), dy=float(value.get("y", 0.0)))
    msg = "Reference vectors must be mappings with dx/dy or x/y keys."
    raise ValueError(msg)
