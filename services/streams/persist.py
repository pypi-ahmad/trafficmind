"""Persist FrameResult artifacts to the database.

Converts pipeline output (detection events, plate reads, violations) into
ORM model instances and writes them in a single session.  Designed to be
called once per processed frame by the worker's ``on_frame`` callback.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.db.enums import (
    DetectionEventStatus,
    DetectionEventType,
    PlateReadStatus,
    ViolationStatus,
)
from apps.api.app.db.models import DetectionEvent, PlateRead, ViolationEvent
from services.streams.events import TrackedObjectEvent, TrackedObjectEventType
from services.streams.pipeline import FrameResult

logger = logging.getLogger(__name__)

_TRACK_EVENT_TO_DETECTION_TYPE: dict[TrackedObjectEventType, DetectionEventType] = {
    TrackedObjectEventType.TRACK_STARTED: DetectionEventType.DETECTION,
    TrackedObjectEventType.TRACK_OBSERVED: DetectionEventType.DETECTION,
    TrackedObjectEventType.TRACK_LOST: DetectionEventType.DETECTION,
    TrackedObjectEventType.TRACK_REMOVED: DetectionEventType.DETECTION,
}


@dataclass
class PersistenceSummary:
    """Counts of rows written for one frame."""

    detection_events: int = 0
    plate_reads: int = 0
    violation_events: int = 0


async def persist_frame_result(
    session: AsyncSession,
    result: FrameResult,
    *,
    camera_id: uuid.UUID,
    stream_id: uuid.UUID | None = None,
) -> PersistenceSummary:
    """Write detection events, plate reads, and violations from one frame.

    The caller is responsible for committing or rolling back the session.
    """
    summary = PersistenceSummary()

    # ── 1. Checkpoint tracked-object events → DetectionEvent rows ───
    track_to_detection: dict[str, DetectionEvent] = {}
    if result.event_batch is not None:
        for event in result.event_batch.persistable_events():
            det = _detection_event_from_tracked_object(
                event,
                camera_id=camera_id,
                stream_id=stream_id,
                frame_index=result.frame_index,
                occurred_at=result.timestamp,
            )
            session.add(det)
            track_to_detection[event.track_id] = det
            summary.detection_events += 1

    # Flush to materialise PKs for FK linkage
    if track_to_detection:
        await session.flush()

    # ── 2. Plate reads → PlateRead rows ────────────────────────────
    for plate in result.plate_reads:
        pr = _plate_read_from_ocr(
            plate,
            camera_id=camera_id,
            stream_id=stream_id,
        )
        session.add(pr)
        summary.plate_reads += 1

    # ── 3. Violations → ViolationEvent rows ─────────────────────────
    # Ensure every violation has a linked DetectionEvent.  When the
    # track's only checkpoint was on an earlier frame (TRACK_STARTED),
    # the current batch may have no CHECKPOINT for it — create one.
    needs_flush = False
    for violation in result.violations:
        linked_det = track_to_detection.get(violation.track_id)
        if linked_det is None:
            linked_det = _detection_event_for_violation(
                violation,
                camera_id=camera_id,
                stream_id=stream_id,
                frame_index=result.frame_index,
                occurred_at=result.timestamp,
            )
            session.add(linked_det)
            track_to_detection[violation.track_id] = linked_det
            summary.detection_events += 1
            needs_flush = True

    if needs_flush:
        await session.flush()

    for violation in result.violations:
        linked_det = track_to_detection.get(violation.track_id)
        ve = _violation_event_from_record(
            violation,
            camera_id=camera_id,
            stream_id=stream_id,
            detection_event_id=linked_det.id if linked_det else None,
        )
        session.add(ve)
        summary.violation_events += 1

    return summary


# ---------------------------------------------------------------------------
# Internal mapping helpers
# ---------------------------------------------------------------------------


def _detection_event_from_tracked_object(
    event: TrackedObjectEvent,
    *,
    camera_id: uuid.UUID,
    stream_id: uuid.UUID | None,
    frame_index: int,
    occurred_at: datetime,
) -> DetectionEvent:
    return DetectionEvent(
        camera_id=camera_id,
        stream_id=stream_id,
        event_type=_TRACK_EVENT_TO_DETECTION_TYPE.get(
            event.event_type, DetectionEventType.DETECTION
        ),
        status=DetectionEventStatus.NEW,
        occurred_at=occurred_at,
        frame_index=frame_index,
        track_id=event.track_id,
        object_class=event.class_name,
        confidence=event.confidence,
        bbox=event.bbox.to_dict(),
        event_payload={
            "tracked_object_event_type": event.event_type.value,
            "category": event.category,
            "centroid": {"x": event.centroid.x, "y": event.centroid.y},
        },
    )


def _detection_event_for_violation(
    violation: Any,
    *,
    camera_id: uuid.UUID,
    stream_id: uuid.UUID | None,
    frame_index: int,
    occurred_at: datetime,
) -> DetectionEvent:
    """Create a DetectionEvent to anchor a violation when no checkpoint exists."""
    return DetectionEvent(
        camera_id=camera_id,
        stream_id=stream_id,
        event_type=DetectionEventType.LINE_CROSSING,
        status=DetectionEventStatus.NEW,
        occurred_at=occurred_at,
        frame_index=frame_index,
        track_id=violation.track_id,
        object_class="unknown",
        confidence=violation.certainty,
        bbox={},
        event_payload={
            "source": "violation_anchor",
            "rule_type": violation.rule_type.value,
            "zone_id": violation.zone_id,
        },
    )


def _plate_read_from_ocr(
    plate: Any,
    *,
    camera_id: uuid.UUID,
    stream_id: uuid.UUID | None,
) -> PlateRead:
    cols = plate.to_plate_read_dict()
    cols["camera_id"] = camera_id
    cols["stream_id"] = stream_id
    cols["status"] = PlateReadStatus.OBSERVED
    return PlateRead(**cols)


def _violation_event_from_record(
    violation: Any,
    *,
    camera_id: uuid.UUID,
    stream_id: uuid.UUID | None,
    detection_event_id: uuid.UUID | None,
) -> ViolationEvent:
    cols = violation.to_orm_kwargs()
    cols["camera_id"] = camera_id
    cols["stream_id"] = stream_id
    cols["detection_event_id"] = detection_event_id
    cols["status"] = ViolationStatus.OPEN
    return ViolationEvent(**cols)
