"""Lightweight event/violation count summaries grouped by camera.

Returns simple aggregated counts without the full hotspot analytics
overhead, suitable for dashboard stat cards and incident feed badges.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import case, func, select

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


# ---------------------------------------------------------------------------
# Aggregate totals — flat breakdown for dashboard stat cards
# ---------------------------------------------------------------------------


async def event_summary_totals(
    session: AsyncSession,
    *,
    camera_id: uuid.UUID | None = None,
    occurred_after: datetime | None = None,
    occurred_before: datetime | None = None,
) -> dict:
    """Return ``{total, by_status, by_type}`` from stored detection events."""
    filters = []
    if camera_id is not None:
        filters.append(DetectionEvent.camera_id == camera_id)
    if occurred_after is not None:
        filters.append(DetectionEvent.occurred_at >= occurred_after)
    if occurred_before is not None:
        filters.append(DetectionEvent.occurred_at <= occurred_before)

    total_q = select(func.count(DetectionEvent.id))
    if filters:
        total_q = total_q.where(*filters)
    total = (await session.scalar(total_q)) or 0

    status_q = (
        select(
            DetectionEvent.status,
            func.count(DetectionEvent.id).label("cnt"),
        )
        .group_by(DetectionEvent.status)
    )
    if filters:
        status_q = status_q.where(*filters)
    status_rows = (await session.execute(status_q)).all()
    by_status = {row.status.value if hasattr(row.status, "value") else str(row.status): row.cnt for row in status_rows}

    type_q = (
        select(
            DetectionEvent.event_type,
            func.count(DetectionEvent.id).label("cnt"),
        )
        .group_by(DetectionEvent.event_type)
    )
    if filters:
        type_q = type_q.where(*filters)
    type_rows = (await session.execute(type_q)).all()
    by_type = {row.event_type.value if hasattr(row.event_type, "value") else str(row.event_type): row.cnt for row in type_rows}

    return {"total": total, "by_status": by_status, "by_type": by_type}


async def violation_summary_totals(
    session: AsyncSession,
    *,
    camera_id: uuid.UUID | None = None,
    occurred_after: datetime | None = None,
    occurred_before: datetime | None = None,
) -> dict:
    """Return ``{total, by_severity, by_type, by_status}`` from stored violations."""
    filters = []
    if camera_id is not None:
        filters.append(ViolationEvent.camera_id == camera_id)
    if occurred_after is not None:
        filters.append(ViolationEvent.occurred_at >= occurred_after)
    if occurred_before is not None:
        filters.append(ViolationEvent.occurred_at <= occurred_before)

    total_q = select(func.count(ViolationEvent.id))
    if filters:
        total_q = total_q.where(*filters)
    total = (await session.scalar(total_q)) or 0

    sev_q = (
        select(
            ViolationEvent.severity,
            func.count(ViolationEvent.id).label("cnt"),
        )
        .group_by(ViolationEvent.severity)
    )
    if filters:
        sev_q = sev_q.where(*filters)
    sev_rows = (await session.execute(sev_q)).all()
    by_severity = {row.severity.value if hasattr(row.severity, "value") else str(row.severity): row.cnt for row in sev_rows}

    type_q = (
        select(
            ViolationEvent.violation_type,
            func.count(ViolationEvent.id).label("cnt"),
        )
        .group_by(ViolationEvent.violation_type)
    )
    if filters:
        type_q = type_q.where(*filters)
    type_rows = (await session.execute(type_q)).all()
    by_type = {row.violation_type.value if hasattr(row.violation_type, "value") else str(row.violation_type): row.cnt for row in type_rows}

    status_q = (
        select(
            ViolationEvent.status,
            func.count(ViolationEvent.id).label("cnt"),
        )
        .group_by(ViolationEvent.status)
    )
    if filters:
        status_q = status_q.where(*filters)
    status_rows = (await session.execute(status_q)).all()
    by_status = {row.status.value if hasattr(row.status, "value") else str(row.status): row.cnt for row in status_rows}

    return {
        "total": total,
        "by_severity": by_severity,
        "by_type": by_type,
        "by_status": by_status,
    }
