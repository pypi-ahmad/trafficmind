"""Config loading for lane occupancy and queue analytics."""

from __future__ import annotations

from typing import Any

from apps.api.app.db.enums import ZoneType
from services.flow.schemas import LaneAnalyticsLaneConfig, LaneAnalyticsTuning
from services.rules.schemas import LineGeometry, PolygonGeometry, ZoneConfig
from services.tracking.schemas import LineSegment, Point2D, PolygonZone


def load_lane_analytics_config(
    calibration_config: dict[str, Any] | None,
    zones: list[ZoneConfig],
) -> list[LaneAnalyticsLaneConfig]:
    """Load per-camera and per-lane flow analytics config.

    Accepted shape:

    {
      "lane_analytics": {
        "defaults": {... LaneAnalyticsTuning ...},
        "lanes": [
          {
            "lane_zone_id": "lane-1",
            "stop_line_zone_id": "sl-1",
            "queue_reference_point": {"x": 10, "y": 20},
            ... tuning overrides ...
          }
        ]
      }
    }

    If no explicit lanes are configured, all `ZoneType.LANE` polygon zones are
    converted into lane configs with the camera defaults only.
    """

    payload = (calibration_config or {}).get("lane_analytics") or {}
    default_payload = payload.get("defaults") or {}
    defaults = LaneAnalyticsTuning.model_validate(default_payload)

    lane_zones = [zone for zone in zones if zone.zone_type == ZoneType.LANE and isinstance(zone.geometry, PolygonGeometry)]
    zone_by_id = {zone.zone_id: zone for zone in zones}
    zone_by_name = {zone.name: zone for zone in zones}

    raw_lanes: list[dict[str, Any]] = list(payload.get("lanes") or [])
    if not raw_lanes:
        raw_lanes = [{"lane_zone_id": lane.zone_id} for lane in lane_zones]

    tuning_keys = set(LaneAnalyticsTuning.model_fields)
    configs: list[LaneAnalyticsLaneConfig] = []
    for raw_lane in raw_lanes:
        lane_zone = _resolve_zone(raw_lane, zone_by_id, zone_by_name, id_key="lane_zone_id", name_key="lane_zone_name")
        if lane_zone is None:
            msg = "lane analytics config references an unknown lane zone"
            raise ValueError(msg)
        if lane_zone.zone_type != ZoneType.LANE or not isinstance(lane_zone.geometry, PolygonGeometry):
            msg = f"Zone {lane_zone.name!r} is not a polygon lane zone"
            raise ValueError(msg)

        stop_line_zone = _resolve_zone(
            raw_lane,
            zone_by_id,
            zone_by_name,
            id_key="stop_line_zone_id",
            name_key="stop_line_zone_name",
        )
        if stop_line_zone is not None and not isinstance(stop_line_zone.geometry, LineGeometry):
            msg = f"Zone {stop_line_zone.name!r} is not a line/stop-line zone"
            raise ValueError(msg)

        lane_tuning_payload = defaults.model_dump(mode="python") | {
            key: value for key, value in raw_lane.items() if key in tuning_keys
        }
        queue_reference_point = raw_lane.get("queue_reference_point")
        config = LaneAnalyticsLaneConfig(
            **lane_tuning_payload,
            lane_id=lane_zone.zone_id,
            lane_name=lane_zone.name,
            lane_polygon=PolygonZone(name=lane_zone.name, points=lane_zone.geometry.points),
            stop_line=_to_line_segment(stop_line_zone.geometry, stop_line_zone.name) if stop_line_zone is not None else None,
            queue_reference_point=Point2D.model_validate(queue_reference_point) if queue_reference_point else None,
            queue_reference_label=raw_lane.get("queue_reference_label") or (stop_line_zone.name if stop_line_zone is not None else None),
        )
        configs.append(config)

    return configs


def _resolve_zone(
    raw_lane: dict[str, Any],
    zone_by_id: dict[str, ZoneConfig],
    zone_by_name: dict[str, ZoneConfig],
    *,
    id_key: str,
    name_key: str,
) -> ZoneConfig | None:
    zone_id = raw_lane.get(id_key)
    if zone_id:
        return zone_by_id.get(zone_id)
    zone_name = raw_lane.get(name_key)
    if zone_name:
        return zone_by_name.get(zone_name)
    return None


def _to_line_segment(geometry: LineGeometry, name: str) -> LineSegment:
    return LineSegment(start=geometry.start, end=geometry.end, name=name)