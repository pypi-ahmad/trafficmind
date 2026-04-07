"""Service layer for storage-backed hotspot analytics."""

from __future__ import annotations

from datetime import timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.db.enums import ZoneType
from apps.api.app.db.models import (
    Camera,
    DetectionEvent,
    PlateRead,
    ViolationEvent,
    WatchlistAlert,
    Zone,
)
from apps.api.app.schemas.analytics import HotspotAnalyticsRequest
from services.hotspot import aggregate_hotspots
from services.hotspot.schemas import EventRecord, HotspotResult, HotspotSourceKind


class HotspotAnalyticsService:
    """Load persisted records and aggregate them into hotspot analytics."""

    _stored_sources = {
        HotspotSourceKind.DETECTION_EVENT,
        HotspotSourceKind.VIOLATION_EVENT,
        HotspotSourceKind.WATCHLIST_ALERT,
    }

    async def build_hotspots(
        self,
        session: AsyncSession,
        query: HotspotAnalyticsRequest,
    ) -> HotspotResult:
        requested_sources = set(query.source_kinds or self._stored_sources)
        warnings: list[str] = []

        if HotspotSourceKind.CONGESTION in requested_sources:
            warnings.append(
                "The DB-backed hotspot API does not yet include persisted congestion history; congestion records must be supplied separately from lane analytics snapshots.",
            )
            requested_sources.discard(HotspotSourceKind.CONGESTION)

        if any(axis.value == "lane" for axis in query.group_by):
            warnings.append(
                "Lane hotspots depend on stored lane_id values or lane-zone associations in event payloads and rule metadata.",
            )

        current = await self._load_records(
            session,
            period_start=query.period_start,
            period_end=query.period_end,
            source_kinds=requested_sources,
        )

        previous: list[EventRecord] | None = None
        if query.compare_previous:
            previous_start, previous_end = query.previous_period
            previous = await self._load_records(
                session,
                period_start=previous_start,
                period_end=previous_end,
                source_kinds=requested_sources,
            )

        result = aggregate_hotspots(query, current, previous)
        if warnings:
            result = result.model_copy(update={"warnings": [*result.warnings, *warnings]})
        return result

    async def _load_records(
        self,
        session: AsyncSession,
        *,
        period_start,
        period_end,
        source_kinds: set[HotspotSourceKind],
    ) -> list[EventRecord]:
        records: list[EventRecord] = []
        if HotspotSourceKind.DETECTION_EVENT in source_kinds:
            records.extend(await self._load_detection_records(session, period_start=period_start, period_end=period_end))
        if HotspotSourceKind.VIOLATION_EVENT in source_kinds:
            records.extend(await self._load_violation_records(session, period_start=period_start, period_end=period_end))
        if HotspotSourceKind.WATCHLIST_ALERT in source_kinds:
            records.extend(await self._load_watchlist_alert_records(session, period_start=period_start, period_end=period_end))
        return records

    async def _load_detection_records(self, session: AsyncSession, *, period_start, period_end) -> list[EventRecord]:
        statement = (
            select(
                DetectionEvent.id,
                DetectionEvent.occurred_at,
                Camera.id,
                Camera.name,
                Camera.location_name,
                Camera.latitude,
                Camera.longitude,
                Zone.id,
                Zone.name,
                Zone.zone_type,
                DetectionEvent.event_type,
                DetectionEvent.object_class,
                DetectionEvent.event_payload,
            )
            .join(Camera, DetectionEvent.camera_id == Camera.id)
            .outerjoin(Zone, DetectionEvent.zone_id == Zone.id)
            .where(DetectionEvent.occurred_at >= period_start, DetectionEvent.occurred_at < period_end)
        )
        rows = (await session.execute(statement)).all()
        records: list[EventRecord] = []
        for row in rows:
            lane_id = _lane_id_from_payload(row[12], zone_id=row[7], zone_type=row[9])
            records.append(
                EventRecord(
                    event_id=str(row[0]),
                    source_kind=HotspotSourceKind.DETECTION_EVENT,
                    occurred_at=_ensure_utc(row[1]),
                    camera_id=str(row[2]),
                    camera_name=row[3],
                    location_name=row[4],
                    latitude=row[5],
                    longitude=row[6],
                    zone_id=str(row[7]) if row[7] is not None else None,
                    zone_name=row[8],
                    lane_id=lane_id,
                    event_type=row[10].value,
                    object_class=row[11],
                )
            )
        return records

    async def _load_violation_records(self, session: AsyncSession, *, period_start, period_end) -> list[EventRecord]:
        statement = (
            select(
                ViolationEvent.id,
                ViolationEvent.occurred_at,
                Camera.id,
                Camera.name,
                Camera.location_name,
                Camera.latitude,
                Camera.longitude,
                Zone.id,
                Zone.name,
                Zone.zone_type,
                ViolationEvent.violation_type,
                ViolationEvent.severity,
                ViolationEvent.rule_metadata,
            )
            .join(Camera, ViolationEvent.camera_id == Camera.id)
            .outerjoin(Zone, ViolationEvent.zone_id == Zone.id)
            .where(ViolationEvent.occurred_at >= period_start, ViolationEvent.occurred_at < period_end)
        )
        rows = (await session.execute(statement)).all()
        records: list[EventRecord] = []
        for row in rows:
            lane_id = _lane_id_from_payload(row[12], zone_id=row[7], zone_type=row[9])
            records.append(
                EventRecord(
                    event_id=str(row[0]),
                    source_kind=HotspotSourceKind.VIOLATION_EVENT,
                    occurred_at=_ensure_utc(row[1]),
                    camera_id=str(row[2]),
                    camera_name=row[3],
                    location_name=row[4],
                    latitude=row[5],
                    longitude=row[6],
                    zone_id=str(row[7]) if row[7] is not None else None,
                    zone_name=row[8],
                    lane_id=lane_id,
                    violation_type=row[10].value,
                    severity=row[11].value,
                )
            )
        return records

    async def _load_watchlist_alert_records(self, session: AsyncSession, *, period_start, period_end) -> list[EventRecord]:
        statement = (
            select(
                WatchlistAlert.id,
                WatchlistAlert.occurred_at,
                Camera.id,
                Camera.name,
                Camera.location_name,
                Camera.latitude,
                Camera.longitude,
                Zone.id,
                Zone.name,
                Zone.zone_type,
                DetectionEvent.event_payload,
            )
            .join(Camera, WatchlistAlert.camera_id == Camera.id)
            .join(PlateRead, WatchlistAlert.plate_read_id == PlateRead.id)
            .outerjoin(DetectionEvent, PlateRead.detection_event_id == DetectionEvent.id)
            .outerjoin(Zone, DetectionEvent.zone_id == Zone.id)
            .where(WatchlistAlert.occurred_at >= period_start, WatchlistAlert.occurred_at < period_end)
        )
        rows = (await session.execute(statement)).all()
        records: list[EventRecord] = []
        for row in rows:
            lane_id = _lane_id_from_payload(row[10], zone_id=row[7], zone_type=row[9])
            records.append(
                EventRecord(
                    event_id=str(row[0]),
                    source_kind=HotspotSourceKind.WATCHLIST_ALERT,
                    occurred_at=_ensure_utc(row[1]),
                    camera_id=str(row[2]),
                    camera_name=row[3],
                    location_name=row[4],
                    latitude=row[5],
                    longitude=row[6],
                    zone_id=str(row[7]) if row[7] is not None else None,
                    zone_name=row[8],
                    lane_id=lane_id,
                    event_type="watchlist_match",
                    object_class="vehicle",
                )
            )
        return records


def _lane_id_from_payload(
    payload: dict[str, Any] | None,
    *,
    zone_id,
    zone_type,
) -> str | None:
    if isinstance(payload, dict):
        direct = payload.get("lane_id") or payload.get("linked_lane_id")
        if isinstance(direct, str) and direct:
            return direct

        lane_ids = payload.get("lane_ids")
        if isinstance(lane_ids, list):
            for item in lane_ids:
                if isinstance(item, str) and item:
                    return item

    if zone_id is not None and zone_type == ZoneType.LANE:
        return str(zone_id)
    return None


def _ensure_utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
