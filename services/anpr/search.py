"""ANPR plate search service.

Provides async query helpers that build efficient SQLAlchemy selects
against the ``plate_reads`` table.  All public functions accept an
``AsyncSession`` — they never own the transaction.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import joinedload

from apps.api.app.db.enums import PlateReadStatus
from apps.api.app.db.models import Camera, DetectionEvent, PlateRead
from services.ocr.normalizer import normalize_plate_text

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession


async def search_plates(
    session: AsyncSession,
    *,
    plate_text: str | None = None,
    partial: bool | None = None,
    normalized: bool = True,
    camera_id: uuid.UUID | None = None,
    camera_query: str | None = None,
    stream_id: uuid.UUID | None = None,
    detection_event_id: uuid.UUID | None = None,
    track_id: str | None = None,
    country_code: str | None = None,
    normalization_country_code: str | None = None,
    region_code: str | None = None,
    status: PlateReadStatus | None = None,
    occurred_after: datetime | None = None,
    occurred_before: datetime | None = None,
    has_evidence: bool | None = None,
    min_confidence: float | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[PlateRead], int]:
    """Search plate reads with flexible filtering.

    Returns a ``(items, total_count)`` tuple.
    """
    base = select(PlateRead)
    count_q = select(func.count()).select_from(PlateRead)
    use_partial = partial if partial is not None else not normalized

    if track_id is not None:
        base = base.join(PlateRead.detection_event)
        count_q = count_q.join(PlateRead.detection_event)

    if camera_query is not None:
        base = base.join(PlateRead.camera)
        count_q = count_q.join(PlateRead.camera)

        search_term = f"%{camera_query.strip().lower()}%"
        camera_clause = or_(
            func.lower(Camera.camera_code).like(search_term),
            func.lower(Camera.name).like(search_term),
            func.lower(Camera.location_name).like(search_term),
        )
        base = base.where(camera_clause)
        count_q = count_q.where(camera_clause)

    if plate_text is not None:
        if normalized:
            search_text = normalize_plate_text(
                plate_text,
                country_code=normalization_country_code,
            )
            column = PlateRead.normalized_plate_text
        else:
            search_text = plate_text.strip()
            column = PlateRead.plate_text

        if not search_text:
            return [], 0

        if use_partial:
            clause = column.like(f"%{search_text}%") if normalized else column.ilike(f"%{search_text}%")
        elif normalized:
            clause = column == search_text
        else:
            clause = func.upper(column) == search_text.upper()

        base = base.where(clause)
        count_q = count_q.where(clause)

    if camera_id is not None:
        base = base.where(PlateRead.camera_id == camera_id)
        count_q = count_q.where(PlateRead.camera_id == camera_id)

    if stream_id is not None:
        base = base.where(PlateRead.stream_id == stream_id)
        count_q = count_q.where(PlateRead.stream_id == stream_id)

    if detection_event_id is not None:
        base = base.where(PlateRead.detection_event_id == detection_event_id)
        count_q = count_q.where(PlateRead.detection_event_id == detection_event_id)

    if track_id is not None:
        trimmed_track_id = track_id.strip()
        if trimmed_track_id:
            base = base.where(DetectionEvent.track_id == trimmed_track_id)
            count_q = count_q.where(DetectionEvent.track_id == trimmed_track_id)

    if country_code is not None:
        normalized_country_code = country_code.upper()
        base = base.where(func.upper(PlateRead.country_code) == normalized_country_code)
        count_q = count_q.where(func.upper(PlateRead.country_code) == normalized_country_code)

    if region_code is not None:
        normalized_region_code = region_code.upper()
        base = base.where(func.upper(PlateRead.region_code) == normalized_region_code)
        count_q = count_q.where(func.upper(PlateRead.region_code) == normalized_region_code)

    if status is not None:
        base = base.where(PlateRead.status == status)
        count_q = count_q.where(PlateRead.status == status)

    if occurred_after is not None:
        base = base.where(PlateRead.occurred_at >= occurred_after)
        count_q = count_q.where(PlateRead.occurred_at >= occurred_after)

    if occurred_before is not None:
        base = base.where(PlateRead.occurred_at <= occurred_before)
        count_q = count_q.where(PlateRead.occurred_at <= occurred_before)

    if has_evidence is not None:
        evidence_clause = or_(
            PlateRead.crop_image_uri.is_not(None),
            PlateRead.source_frame_uri.is_not(None),
        )
        if has_evidence:
            base = base.where(evidence_clause)
            count_q = count_q.where(evidence_clause)
        else:
            no_evidence_clause = and_(
                PlateRead.crop_image_uri.is_(None),
                PlateRead.source_frame_uri.is_(None),
            )
            base = base.where(no_evidence_clause)
            count_q = count_q.where(no_evidence_clause)

    if min_confidence is not None:
        base = base.where(PlateRead.confidence >= min_confidence)
        count_q = count_q.where(PlateRead.confidence >= min_confidence)

    total = (await session.scalar(count_q)) or 0

    items_q = (
        base
        .options(joinedload(PlateRead.camera), joinedload(PlateRead.detection_event))
        .order_by(PlateRead.occurred_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(items_q)
    items = list(result.scalars().unique().all())

    return items, total


async def get_plate_read(
    session: AsyncSession,
    plate_read_id: uuid.UUID,
) -> PlateRead | None:
    """Fetch a single plate read by ID."""
    result = await session.execute(
        select(PlateRead)
        .options(joinedload(PlateRead.camera))
        .where(PlateRead.id == plate_read_id)
    )
    return result.scalars().first()
