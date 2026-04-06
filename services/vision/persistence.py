"""Persistence helpers for storing detector output with provenance references."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from apps.api.app.db.enums import DetectionEventType
from services.model_registry import (
    ModelRegistryService,
    build_model_registry_provenance_snapshot,
    build_detector_registry_spec,
    build_tracking_registry_spec,
)
from services.vision.schemas import Detection


def detection_to_orm_kwargs(
    detection: Detection,
    *,
    camera_id: uuid.UUID,
    stream_id: uuid.UUID | None = None,
    zone_id: uuid.UUID | None = None,
    event_type: DetectionEventType = DetectionEventType.DETECTION,
    event_payload: dict[str, Any] | None = None,
    detector_registry_id: uuid.UUID | None = None,
    tracker_registry_id: uuid.UUID | None = None,
    detector_provenance: dict[str, Any] | None = None,
    tracker_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = detection.to_event_dict()
    payload = dict(event_payload or {})
    if detector_provenance is not None or tracker_provenance is not None:
        payload["provenance"] = {
            "detector": detector_provenance,
            "tracker": tracker_provenance,
        }

    base.update(
        {
            "camera_id": camera_id,
            "stream_id": stream_id,
            "zone_id": zone_id,
            "event_type": event_type,
            "event_payload": payload,
            "detector_registry_id": detector_registry_id,
            "tracker_registry_id": tracker_registry_id,
        }
    )
    if base.get("occurred_at") is None:
        base["occurred_at"] = datetime.now(timezone.utc)
    return base


async def save_detection_event(
    session: Any,
    detection: Detection,
    *,
    camera_id: uuid.UUID,
    stream_id: uuid.UUID | None = None,
    zone_id: uuid.UUID | None = None,
    event_type: DetectionEventType | str = DetectionEventType.DETECTION,
    event_payload: dict[str, Any] | None = None,
    detector_registry_id: uuid.UUID | None = None,
    tracker_registry_id: uuid.UUID | None = None,
) -> Any:
    from apps.api.app.db.models import DetectionEvent

    registry_service = ModelRegistryService()
    detector_entry = None
    tracker_entry = None
    detector_id = detector_registry_id
    tracker_id = tracker_registry_id

    if detector_id is None:
        detector_entry = await registry_service.ensure_entry(session, build_detector_registry_spec())
        detector_id = detector_entry.id
    else:
        detector_entry = await registry_service.get_entry(session, detector_id)
    if tracker_id is None and detection.track_id is not None:
        tracker_entry = await registry_service.ensure_entry(session, build_tracking_registry_spec())
        tracker_id = tracker_entry.id
    elif tracker_id is not None:
        tracker_entry = await registry_service.get_entry(session, tracker_id)

    kwargs = detection_to_orm_kwargs(
        detection,
        camera_id=camera_id,
        stream_id=stream_id,
        zone_id=zone_id,
        event_type=DetectionEventType(event_type),
        event_payload=event_payload,
        detector_registry_id=detector_id,
        tracker_registry_id=tracker_id,
        detector_provenance=build_model_registry_provenance_snapshot(detector_entry),
        tracker_provenance=build_model_registry_provenance_snapshot(tracker_entry),
    )
    event = DetectionEvent(**kwargs)
    session.add(event)
    await session.flush()
    return event