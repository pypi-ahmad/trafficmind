"""Adapters that map other analytics outputs into hotspot event records."""

from __future__ import annotations

from collections.abc import Sequence

from services.flow.schemas import CongestionLevel, LaneAnalytics
from services.hotspot.schemas import EventRecord, HotspotSourceKind


_DEFAULT_INCLUDED_LEVELS = {
    CongestionLevel.HEAVY,
    CongestionLevel.QUEUED,
    CongestionLevel.CONGESTED,
}


def lane_analytics_to_event_records(
    analytics: Sequence[LaneAnalytics],
    *,
    camera_id: str,
    camera_name: str | None = None,
    location_name: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    included_levels: set[CongestionLevel] | None = None,
) -> list[EventRecord]:
    """Convert lane-congestion snapshots into hotspot event records.

    Each returned record represents one lane snapshot whose congestion level is
    operationally significant. The hotspot score remains a raw count of such
    snapshots over time.
    """

    levels = included_levels or _DEFAULT_INCLUDED_LEVELS
    records: list[EventRecord] = []
    for item in analytics:
        if item.congestion_level not in levels:
            continue
        records.append(
            EventRecord(
                event_id=f"{camera_id}:{item.lane_id}:{item.observed_at.isoformat()}",
                source_kind=HotspotSourceKind.CONGESTION,
                occurred_at=item.observed_at,
                camera_id=camera_id,
                camera_name=camera_name,
                location_name=location_name,
                latitude=latitude,
                longitude=longitude,
                zone_id=item.lane_id,
                zone_name=item.lane_name,
                lane_id=item.lane_id,
                event_type=item.congestion_level.value,
            )
        )
    return records