"""Plate read search endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status

from apps.api.app.api.dependencies import DbSession
from apps.api.app.db.enums import PlateReadStatus
from apps.api.app.schemas.domain import PlateReadRead, PlateSearchResult
from services.anpr.search import get_plate_read, search_plates

router = APIRouter(prefix="/plates", tags=["plates"])


@router.get("/", response_model=PlateSearchResult)
async def search_plate_reads(
    db: DbSession,
    plate_text: str | None = Query(None, description="Exact or partial plate text"),
    partial: bool = Query(False, description="Use contains-style matching instead of exact matching"),
    normalized: bool = Query(True, description="Normalize query before search"),
    camera_id: uuid.UUID | None = Query(None),
    camera_query: str | None = Query(None, description="Camera code, name, or location filter"),
    stream_id: uuid.UUID | None = Query(None),
    detection_event_id: uuid.UUID | None = Query(None),
    track_id: str | None = Query(None, max_length=64),
    country_code: str | None = Query(None, max_length=8),
    normalization_country_code: str | None = Query(None, max_length=8),
    region_code: str | None = Query(None, max_length=16),
    plate_status: PlateReadStatus | None = Query(None, alias="status"),
    occurred_after: datetime | None = Query(None),
    occurred_before: datetime | None = Query(None),
    has_evidence: bool | None = Query(None),
    min_confidence: float | None = Query(None, ge=0.0, le=1.0),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> PlateSearchResult:
    """Search plate reads with flexible filtering."""
    items, total = await search_plates(
        db,
        plate_text=plate_text,
        partial=partial,
        normalized=normalized,
        camera_id=camera_id,
        camera_query=camera_query,
        stream_id=stream_id,
        detection_event_id=detection_event_id,
        track_id=track_id,
        country_code=country_code,
        normalization_country_code=normalization_country_code,
        region_code=region_code,
        status=plate_status,
        occurred_after=occurred_after,
        occurred_before=occurred_before,
        has_evidence=has_evidence,
        min_confidence=min_confidence,
        limit=limit,
        offset=offset,
    )
    return PlateSearchResult(
        items=[PlateReadRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{plate_read_id}", response_model=PlateReadRead)
async def get_plate_read_detail(
    db: DbSession,
    plate_read_id: uuid.UUID,
) -> PlateReadRead:
    """Fetch a single plate read by ID."""
    row = await get_plate_read(db, plate_read_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plate read not found")
    return PlateReadRead.model_validate(row)
