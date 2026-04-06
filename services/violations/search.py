"""Violation event search service.

Provides async query helpers that build efficient SQLAlchemy selects
against the ``violation_events`` table. All public functions accept an
``AsyncSession`` and never own the transaction.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import joinedload

from apps.api.app.db.enums import ViolationStatus, ViolationType, ZoneType
from apps.api.app.db.models import Camera, DetectionEvent, PlateRead, ViolationEvent, Zone
from services.ocr.normalizer import normalize_plate_text

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession


async def search_violation_events(
    session: AsyncSession,
    *,
    camera_id: uuid.UUID | None = None,
    camera_query: str | None = None,
    stream_id: uuid.UUID | None = None,
    zone_id: uuid.UUID | None = None,
    detection_event_id: uuid.UUID | None = None,
    plate_read_id: uuid.UUID | None = None,
    violation_type: ViolationType | None = None,
    violation_types: list[ViolationType] | None = None,
    status: ViolationStatus | None = None,
    occurred_after: datetime | None = None,
    occurred_before: datetime | None = None,
    object_class: str | None = None,
    plate_text: str | None = None,
    partial_plate: bool = False,
    normalization_country_code: str | None = None,
    assigned_to: str | None = None,
    reviewed_by: str | None = None,
    zone_type: ZoneType | None = None,
    has_evidence: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ViolationEvent], int]:
    """Search stored violation events with flexible filtering."""
    base = select(ViolationEvent)
    count_q = select(func.count()).select_from(ViolationEvent)

    if camera_query is not None:
        base = base.join(ViolationEvent.camera)
        count_q = count_q.join(ViolationEvent.camera)

        search_term = f"%{camera_query.strip().lower()}%"
        camera_clause = or_(
            func.lower(Camera.camera_code).like(search_term),
            func.lower(Camera.name).like(search_term),
            func.lower(Camera.location_name).like(search_term),
        )
        base = base.where(camera_clause)
        count_q = count_q.where(camera_clause)

    if zone_type is not None:
        base = base.join(ViolationEvent.zone)
        count_q = count_q.join(ViolationEvent.zone)
        zone_clause = Zone.zone_type == zone_type
        base = base.where(zone_clause)
        count_q = count_q.where(zone_clause)

    if object_class is not None:
        base = base.join(ViolationEvent.detection_event)
        count_q = count_q.join(ViolationEvent.detection_event)
        normalized_object_class = object_class.strip().lower()
        if normalized_object_class:
            object_clause = func.lower(DetectionEvent.object_class) == normalized_object_class
            base = base.where(object_clause)
            count_q = count_q.where(object_clause)

    if plate_text is not None:
        search_text = normalize_plate_text(
            plate_text,
            country_code=normalization_country_code,
        )
        if not search_text:
            return [], 0

        base = base.join(ViolationEvent.plate_read)
        count_q = count_q.join(ViolationEvent.plate_read)
        plate_clause = (
            PlateRead.normalized_plate_text.like(f"%{search_text}%")
            if partial_plate
            else PlateRead.normalized_plate_text == search_text
        )
        base = base.where(plate_clause)
        count_q = count_q.where(plate_clause)

    if camera_id is not None:
        base = base.where(ViolationEvent.camera_id == camera_id)
        count_q = count_q.where(ViolationEvent.camera_id == camera_id)

    if stream_id is not None:
        base = base.where(ViolationEvent.stream_id == stream_id)
        count_q = count_q.where(ViolationEvent.stream_id == stream_id)

    if zone_id is not None:
        base = base.where(ViolationEvent.zone_id == zone_id)
        count_q = count_q.where(ViolationEvent.zone_id == zone_id)

    if detection_event_id is not None:
        base = base.where(ViolationEvent.detection_event_id == detection_event_id)
        count_q = count_q.where(ViolationEvent.detection_event_id == detection_event_id)

    if plate_read_id is not None:
        base = base.where(ViolationEvent.plate_read_id == plate_read_id)
        count_q = count_q.where(ViolationEvent.plate_read_id == plate_read_id)

    if violation_types:
        base = base.where(ViolationEvent.violation_type.in_(violation_types))
        count_q = count_q.where(ViolationEvent.violation_type.in_(violation_types))
    elif violation_type is not None:
        base = base.where(ViolationEvent.violation_type == violation_type)
        count_q = count_q.where(ViolationEvent.violation_type == violation_type)

    if status is not None:
        base = base.where(ViolationEvent.status == status)
        count_q = count_q.where(ViolationEvent.status == status)

    if occurred_after is not None:
        base = base.where(ViolationEvent.occurred_at >= occurred_after)
        count_q = count_q.where(ViolationEvent.occurred_at >= occurred_after)

    if occurred_before is not None:
        base = base.where(ViolationEvent.occurred_at <= occurred_before)
        count_q = count_q.where(ViolationEvent.occurred_at <= occurred_before)

    if assigned_to is not None:
        trimmed_assigned_to = assigned_to.strip().lower()
        if trimmed_assigned_to:
            assigned_clause = func.lower(ViolationEvent.assigned_to) == trimmed_assigned_to
            base = base.where(assigned_clause)
            count_q = count_q.where(assigned_clause)

    if reviewed_by is not None:
        trimmed_reviewed_by = reviewed_by.strip().lower()
        if trimmed_reviewed_by:
            reviewed_clause = func.lower(ViolationEvent.reviewed_by) == trimmed_reviewed_by
            base = base.where(reviewed_clause)
            count_q = count_q.where(reviewed_clause)

    if has_evidence is not None:
        evidence_clause = or_(
            ViolationEvent.evidence_image_uri.is_not(None),
            ViolationEvent.evidence_video_uri.is_not(None),
        )
        if has_evidence:
            base = base.where(evidence_clause)
            count_q = count_q.where(evidence_clause)
        else:
            no_evidence_clause = and_(
                ViolationEvent.evidence_image_uri.is_(None),
                ViolationEvent.evidence_video_uri.is_(None),
            )
            base = base.where(no_evidence_clause)
            count_q = count_q.where(no_evidence_clause)

    total = (await session.scalar(count_q)) or 0

    items_q = (
        base
        .options(
            joinedload(ViolationEvent.camera),
            joinedload(ViolationEvent.zone),
            joinedload(ViolationEvent.detection_event),
            joinedload(ViolationEvent.plate_read),
        )
        .order_by(ViolationEvent.occurred_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(items_q)
    items = list(result.scalars().unique().all())

    return items, total