"""Bridge between rules-engine violation records and the ORM layer."""

from __future__ import annotations

import uuid
from typing import Any

from services.model_registry import (
    ModelRegistryService,
    build_model_registry_provenance_snapshot,
    build_rules_registry_spec,
)
from services.rules.schemas import PreViolationRecord, ViolationRecord


def pre_violation_to_event_dict(
    record: PreViolationRecord,
    *,
    camera_id: uuid.UUID,
    stream_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Build a serialisable dict from a pre-violation for downstream queues.

    Pre-violations are not persisted to the ``ViolationEvent`` table (they
    are not confirmed yet).  This helper packages them for review-queue
    consumers, WebSocket broadcasts, or in-memory caches.
    """
    base = record.to_event_dict()
    base.update({"camera_id": camera_id, "stream_id": stream_id})
    return base


def violation_to_orm_kwargs(
    record: ViolationRecord,
    *,
    camera_id: uuid.UUID,
    stream_id: uuid.UUID | None = None,
    zone_id: uuid.UUID | None = None,
    detection_event_id: uuid.UUID | None = None,
    plate_read_id: uuid.UUID | None = None,
    rules_registry_id: uuid.UUID | None = None,
    rules_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a dict suitable for ``ViolationEvent(**kwargs)`` construction.

    If *zone_id* is not given explicitly the function attempts to parse
    ``record.zone_id`` as a UUID (synthetic / demo zone-ids are ignored).
    """
    base = record.to_orm_kwargs()

    if zone_id is None and record.zone_id:
        try:
            zone_id = uuid.UUID(record.zone_id)
        except ValueError:
            zone_id = None

    base.update(
        {
            "camera_id": camera_id,
            "stream_id": stream_id,
            "zone_id": zone_id,
            "detection_event_id": detection_event_id,
            "plate_read_id": plate_read_id,
            "rules_registry_id": rules_registry_id,
        }
    )
    if rules_provenance is not None:
        metadata = dict(base.get("rule_metadata") or {})
        metadata["provenance"] = {
            "rules": rules_provenance,
        }
        base["rule_metadata"] = metadata
    return base


async def save_violation(
    session: Any,  # AsyncSession — typed loosely to avoid hard SQLAlchemy import
    record: ViolationRecord,
    *,
    camera_id: uuid.UUID,
    stream_id: uuid.UUID | None = None,
    zone_id: uuid.UUID | None = None,
    detection_event_id: uuid.UUID | None = None,
    plate_read_id: uuid.UUID | None = None,
    rules_registry_id: uuid.UUID | None = None,
) -> Any:
    """Create and add a ``ViolationEvent`` to *session* (not yet committed)."""
    from apps.api.app.db.models import ViolationEvent

    registry_service = ModelRegistryService()
    resolved_registry_id = rules_registry_id
    rules_entry = None
    if resolved_registry_id is None:
        rules_entry = await registry_service.ensure_entry(session, build_rules_registry_spec(record))
        resolved_registry_id = rules_entry.id
    else:
        rules_entry = await registry_service.get_entry(session, resolved_registry_id)

    kwargs = violation_to_orm_kwargs(
        record,
        camera_id=camera_id,
        stream_id=stream_id,
        zone_id=zone_id,
        detection_event_id=detection_event_id,
        plate_read_id=plate_read_id,
        rules_registry_id=resolved_registry_id,
        rules_provenance=build_model_registry_provenance_snapshot(rules_entry),
    )
    event = ViolationEvent(**kwargs)
    session.add(event)
    return event
