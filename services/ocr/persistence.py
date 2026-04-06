"""Persistence helpers for saving OCR results into the PlateRead model.

This module bridges the OCR service's ``PlateOcrResult`` schema to the
API layer's SQLAlchemy ``PlateRead`` ORM model.  It lives in the OCR
service rather than the API layer so that any pipeline worker can
persist plate reads without importing the full API application.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from services.model_registry import (
    ModelRegistryService,
    build_model_registry_provenance_snapshot,
    build_ocr_registry_spec,
)
from services.ocr.schemas import PlateOcrResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def plate_result_to_orm_kwargs(
    result: PlateOcrResult,
    *,
    camera_id: uuid.UUID,
    stream_id: uuid.UUID | None = None,
    detection_event_id: uuid.UUID | None = None,
    ocr_registry_id: uuid.UUID | None = None,
    ocr_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a dict of keyword arguments for ``PlateRead(**kwargs)``.

    This is a pure function — it never touches the database.  The caller
    is responsible for constructing the ORM instance and committing.
    """
    base = result.to_plate_read_dict()
    base["camera_id"] = camera_id
    base["stream_id"] = stream_id
    base["detection_event_id"] = detection_event_id
    base["ocr_registry_id"] = ocr_registry_id

    metadata = dict(base.get("ocr_metadata") or {})
    if ocr_provenance is not None:
        metadata["provenance"] = {
            "ocr": ocr_provenance,
        }
    base["ocr_metadata"] = metadata

    if base.get("occurred_at") is None:
        base["occurred_at"] = datetime.now(timezone.utc)

    return base


async def save_plate_read(
    session: AsyncSession,
    result: PlateOcrResult,
    *,
    camera_id: uuid.UUID,
    stream_id: uuid.UUID | None = None,
    detection_event_id: uuid.UUID | None = None,
    match_watchlist: bool = True,
    emit_watchlist_alerts: bool = True,
    ocr_registry_id: uuid.UUID | None = None,
) -> Any:
    """Persist a ``PlateOcrResult`` as a ``PlateRead`` row.

    Returns the created ``PlateRead`` instance (not yet committed — the
    caller controls the transaction boundary). When watchlist matching is
    enabled, the save path also promotes matching reads to ``MATCHED`` and
    can emit persistent alert records.
    """
    from apps.api.app.db.models import PlateRead
    from services.anpr.watchlist import create_watchlist_alerts_for_plate_read

    registry_service = ModelRegistryService()
    resolved_registry_id = ocr_registry_id
    ocr_entry = None
    if resolved_registry_id is None:
        ocr_entry = await registry_service.ensure_entry(session, build_ocr_registry_spec())
        resolved_registry_id = ocr_entry.id
    else:
        ocr_entry = await registry_service.get_entry(session, resolved_registry_id)

    kwargs = plate_result_to_orm_kwargs(
        result,
        camera_id=camera_id,
        stream_id=stream_id,
        detection_event_id=detection_event_id,
        ocr_registry_id=resolved_registry_id,
        ocr_provenance=build_model_registry_provenance_snapshot(ocr_entry),
    )
    plate_read = PlateRead(**kwargs)
    session.add(plate_read)
    await session.flush()

    if match_watchlist:
        await create_watchlist_alerts_for_plate_read(
            session,
            plate_read,
            emit_alerts=emit_watchlist_alerts,
        )

    return plate_read
