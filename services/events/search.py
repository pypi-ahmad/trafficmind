"""Detection event search service.

Provides async query helpers that build efficient SQLAlchemy selects
against the ``detection_events`` table. All public functions accept an
``AsyncSession`` and never own the transaction.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import joinedload

from apps.api.app.db.enums import DetectionEventStatus, DetectionEventType, ZoneType
from apps.api.app.db.models import Camera, DetectionEvent, Zone

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession


async def search_detection_events(
    session: AsyncSession,
    *,
    camera_id: uuid.UUID | None = None,
    camera_query: str | None = None,
    stream_id: uuid.UUID | None = None,
    zone_id: uuid.UUID | None = None,
    event_type: DetectionEventType | None = None,
    status: DetectionEventStatus | None = None,
    occurred_after: datetime | None = None,
    occurred_before: datetime | None = None,
    object_class: str | None = None,
    track_id: str | None = None,
    zone_type: ZoneType | None = None,
    has_evidence: bool | None = None,
    min_confidence: float | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[DetectionEvent], int]:
    """Search stored detection events with flexible filtering."""
    base = select(DetectionEvent)
    count_q = select(func.count()).select_from(DetectionEvent)

    if camera_query is not None:
        base = base.join(DetectionEvent.camera)
        count_q = count_q.join(DetectionEvent.camera)

        search_term = f"%{camera_query.strip().lower()}%"
        camera_clause = or_(
            func.lower(Camera.camera_code).like(search_term),
            func.lower(Camera.name).like(search_term),
            func.lower(Camera.location_name).like(search_term),
        )
        base = base.where(camera_clause)
        count_q = count_q.where(camera_clause)

    if zone_type is not None:
        base = base.join(DetectionEvent.zone)
        count_q = count_q.join(DetectionEvent.zone)
        zone_clause = Zone.zone_type == zone_type
        base = base.where(zone_clause)
        count_q = count_q.where(zone_clause)

    if camera_id is not None:
        base = base.where(DetectionEvent.camera_id == camera_id)
        count_q = count_q.where(DetectionEvent.camera_id == camera_id)

    if stream_id is not None:
        base = base.where(DetectionEvent.stream_id == stream_id)
        count_q = count_q.where(DetectionEvent.stream_id == stream_id)

    if zone_id is not None:
        base = base.where(DetectionEvent.zone_id == zone_id)
        count_q = count_q.where(DetectionEvent.zone_id == zone_id)

    if event_type is not None:
        base = base.where(DetectionEvent.event_type == event_type)
        count_q = count_q.where(DetectionEvent.event_type == event_type)

    if status is not None:
        base = base.where(DetectionEvent.status == status)
        count_q = count_q.where(DetectionEvent.status == status)

    if occurred_after is not None:
        base = base.where(DetectionEvent.occurred_at >= occurred_after)
        count_q = count_q.where(DetectionEvent.occurred_at >= occurred_after)

    if occurred_before is not None:
        base = base.where(DetectionEvent.occurred_at <= occurred_before)
        count_q = count_q.where(DetectionEvent.occurred_at <= occurred_before)

    if object_class is not None:
        normalized_object_class = object_class.strip().lower()
        if normalized_object_class:
            object_clause = func.lower(DetectionEvent.object_class) == normalized_object_class
            base = base.where(object_clause)
            count_q = count_q.where(object_clause)

    if track_id is not None:
        trimmed_track_id = track_id.strip()
        if trimmed_track_id:
            track_clause = DetectionEvent.track_id == trimmed_track_id
            base = base.where(track_clause)
            count_q = count_q.where(track_clause)

    if has_evidence is not None:
        evidence_clause = or_(
            DetectionEvent.image_uri.is_not(None),
            DetectionEvent.video_uri.is_not(None),
        )
        if has_evidence:
            base = base.where(evidence_clause)
            count_q = count_q.where(evidence_clause)
        else:
            no_evidence_clause = and_(
                DetectionEvent.image_uri.is_(None),
                DetectionEvent.video_uri.is_(None),
            )
            base = base.where(no_evidence_clause)
            count_q = count_q.where(no_evidence_clause)

    if min_confidence is not None:
        base = base.where(DetectionEvent.confidence >= min_confidence)
        count_q = count_q.where(DetectionEvent.confidence >= min_confidence)

    total = (await session.scalar(count_q)) or 0

    items_q = (
        base
        .options(
            joinedload(DetectionEvent.camera),
            joinedload(DetectionEvent.zone),
        )
        .order_by(DetectionEvent.occurred_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(items_q)
    items = list(result.scalars().unique().all())

    return items, total