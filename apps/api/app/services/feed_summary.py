"""Lightweight event/violation count summaries grouped by camera.

Returns simple aggregated counts without the full hotspot analytics
overhead, suitable for dashboard stat cards and incident feed badges.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from apps.api.app.db.enums import ViolationSeverity
from apps.api.app.db.models import Camera, DetectionEvent, ViolationEvent

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession


async def event_counts_by_camera(
    session: AsyncSession,
    *,
    camera_ids: list[uuid.UUID] | None = None,
    occurred_after: datetime | None = None,
    occurred_before: datetime | None = None,
    limit: int = 50,
) -> list[dict]:
    """Return ``{camera_id, camera_name, location_name, event_count}`` rows."""
    stmt = (
        select(
            DetectionEvent.camera_id,
            Camera.name.label("camera_name"),
            Camera.location_name,
            func.count(DetectionEvent.id).label("event_count"),
        )
        .join(DetectionEvent.camera)
        .group_by(DetectionEvent.camera_id, Camera.name, Camera.location_name)
        .order_by(func.count(DetectionEvent.id).desc())
        .limit(limit)
    )

    if camera_ids:
        stmt = stmt.where(DetectionEvent.camera_id.in_(camera_ids))
    if occurred_after is not None:
        stmt = stmt.where(DetectionEvent.occurred_at >= occurred_after)
    if occurred_before is not None:
        stmt = stmt.where(DetectionEvent.occurred_at <= occurred_before)

    rows = (await session.execute(stmt)).all()
    return [
        {
            "camera_id": str(row.camera_id),
            "camera_name": row.camera_name,
            "location_name": row.location_name,
            "event_count": row.event_count,
        }
        for row in rows
    ]


async def violation_counts_by_camera(
    session: AsyncSession,
    *,
    camera_ids: list[uuid.UUID] | None = None,
    occurred_after: datetime | None = None,
    occurred_before: datetime | None = None,
    limit: int = 50,
) -> list[dict]:
    """Return ``{camera_id, camera_name, location_name, violation_count, severity_counts}`` rows."""
    stmt = (
        select(
            ViolationEvent.camera_id,
            Camera.name.label("camera_name"),
            Camera.location_name,
            func.count(ViolationEvent.id).label("violation_count"),
        )
        .join(ViolationEvent.camera)
        .group_by(ViolationEvent.camera_id, Camera.name, Camera.location_name)
        .order_by(func.count(ViolationEvent.id).desc())
        .limit(limit)
    )

    if camera_ids:
        stmt = stmt.where(ViolationEvent.camera_id.in_(camera_ids))
    if occurred_after is not None:
        stmt = stmt.where(ViolationEvent.occurred_at >= occurred_after)
    if occurred_before is not None:
        stmt = stmt.where(ViolationEvent.occurred_at <= occurred_before)

    rows = (await session.execute(stmt)).all()

    camera_ids_found = [row.camera_id for row in rows]
    severity_map: dict[str, dict[str, int]] = {}
    if camera_ids_found:
        sev_stmt = (
            select(
                ViolationEvent.camera_id,
                ViolationEvent.severity,
                func.count(ViolationEvent.id).label("cnt"),
            )
            .where(ViolationEvent.camera_id.in_(camera_ids_found))
            .group_by(ViolationEvent.camera_id, ViolationEvent.severity)
        )
        if occurred_after is not None:
            sev_stmt = sev_stmt.where(ViolationEvent.occurred_at >= occurred_after)
        if occurred_before is not None:
            sev_stmt = sev_stmt.where(ViolationEvent.occurred_at <= occurred_before)

        sev_rows = (await session.execute(sev_stmt)).all()
        for sev_row in sev_rows:
            cid = str(sev_row.camera_id)
            severity_map.setdefault(cid, {})[sev_row.severity] = sev_row.cnt

    return [
        {
            "camera_id": str(row.camera_id),
            "camera_name": row.camera_name,
            "location_name": row.location_name,
            "violation_count": row.violation_count,
            "severity_counts": severity_map.get(str(row.camera_id), {}),
        }
        for row in rows
    ]
