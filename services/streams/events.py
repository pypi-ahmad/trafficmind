"""Structured perception events emitted by the real-time stream pipeline."""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from services.signals.schemas import SignalSceneSnapshot
from services.tracking.schemas import Point2D, TrackedObject, TrackingResult, TrackLifecycleStatus
from services.vision.schemas import BBox, DetectionResult


class EventPersistenceHint(StrEnum):
    """Durability hint for downstream persistence decisions."""

    TRANSIENT = "transient"
    CHECKPOINT = "checkpoint"


class TrackedObjectEventType(StrEnum):
    """Lifecycle events emitted for tracked objects."""

    TRACK_STARTED = "track_started"
    TRACK_OBSERVED = "track_observed"
    TRACK_LOST = "track_lost"
    TRACK_REMOVED = "track_removed"


class FrameMetadata(BaseModel):
    """Per-frame metadata shared across all emitted events."""

    model_config = ConfigDict(frozen=True)

    source_id: str
    stream_id: uuid.UUID | None = None
    camera_id: uuid.UUID | None = None
    frame_index: int
    timestamp: datetime
    processing_latency_ms: float = Field(ge=0.0)
    inference_latency_ms: float | None = Field(default=None, ge=0.0)
    source_width: int | None = Field(default=None, gt=0)
    source_height: int | None = Field(default=None, gt=0)


class EvidenceHint(BaseModel):
    """Minimal evidence metadata for crop/excerpt generation later."""

    model_config = ConfigDict(frozen=True)

    bbox: BBox
    centroid: Point2D
    crop_hint: dict[str, float]


class TrackedObjectEvent(BaseModel):
    """Structured event for one tracked object on one processed frame."""

    event_type: TrackedObjectEventType
    persistence_hint: EventPersistenceHint
    track_id: str
    class_name: str
    category: str
    confidence: float = Field(ge=0.0, le=1.0)
    status: TrackLifecycleStatus
    bbox: BBox
    centroid: Point2D
    track_snapshot: dict[str, Any] = Field(default_factory=dict)
    evidence_hint: EvidenceHint


class PerceptionFrameSummary(BaseModel):
    """Small analytics summary for one processed frame."""

    detection_count: int = 0
    active_track_count: int = 0
    new_track_count: int = 0
    lost_track_count: int = 0
    removed_track_count: int = 0
    category_counts: dict[str, int] = Field(default_factory=dict)
    signal_head_count: int = 0
    signal_observations: int = 0


class PerceptionEventBatch(BaseModel):
    """One batch of perception events and snapshots for a processed frame."""

    frame: FrameMetadata
    summary: PerceptionFrameSummary
    tracked_object_events: list[TrackedObjectEvent] = Field(default_factory=list)
    active_tracks: list[dict[str, Any]] = Field(default_factory=list)
    lost_tracks: list[dict[str, Any]] = Field(default_factory=list)
    removed_tracks: list[dict[str, Any]] = Field(default_factory=list)
    signal_snapshot: SignalSceneSnapshot | None = None

    @property
    def event_count(self) -> int:
        return len(self.tracked_object_events)

    @property
    def checkpoint_event_count(self) -> int:
        return sum(1 for event in self.tracked_object_events if event.persistence_hint == EventPersistenceHint.CHECKPOINT)

    def persistable_events(self) -> list[TrackedObjectEvent]:
        return [event for event in self.tracked_object_events if event.persistence_hint == EventPersistenceHint.CHECKPOINT]


def _event_from_track(
    *,
    track: TrackedObject,
    event_type: TrackedObjectEventType,
) -> TrackedObjectEvent:
    centroid = track.centroid
    return TrackedObjectEvent(
        event_type=event_type,
        persistence_hint=(
            EventPersistenceHint.TRANSIENT
            if event_type == TrackedObjectEventType.TRACK_OBSERVED
            else EventPersistenceHint.CHECKPOINT
        ),
        track_id=track.track_id,
        class_name=track.class_name,
        category=track.category.value,
        confidence=track.confidence,
        status=track.status,
        bbox=track.bbox,
        centroid=centroid,
        track_snapshot=track.to_event_dict(),
        evidence_hint=EvidenceHint(
            bbox=track.bbox,
            centroid=centroid,
            crop_hint=track.bbox.to_dict(),
        ),
    )


def build_perception_event_batch(
    *,
    source_id: str,
    stream_id: uuid.UUID | None,
    camera_id: uuid.UUID | None,
    frame_index: int,
    timestamp: datetime,
    processing_latency_ms: float,
    detection_result: DetectionResult | None,
    tracking_result: TrackingResult | None,
    signal_snapshot: SignalSceneSnapshot | None = None,
    source_width: int | None = None,
    source_height: int | None = None,
) -> PerceptionEventBatch:
    """Build downstream-ready tracked-object events from detector/tracker output."""

    category_counts: Counter[str] = Counter()
    if tracking_result is not None:
        for track in tracking_result.tracks:
            category_counts[track.category.value] += 1
    elif detection_result is not None:
        for detection in detection_result.detections:
            category_counts[detection.category.value] += 1

    frame = FrameMetadata(
        source_id=source_id,
        stream_id=stream_id,
        camera_id=camera_id,
        frame_index=frame_index,
        timestamp=timestamp,
        processing_latency_ms=processing_latency_ms,
        inference_latency_ms=detection_result.inference_ms if detection_result is not None else None,
        source_width=source_width or (detection_result.source_width if detection_result is not None else None),
        source_height=source_height or (detection_result.source_height if detection_result is not None else None),
    )

    _signal_head_count = len(signal_snapshot.head_states) if signal_snapshot is not None else 0
    _signal_obs_count = signal_snapshot.observation_count if signal_snapshot is not None else 0

    if tracking_result is None:
        return PerceptionEventBatch(
            frame=frame,
            summary=PerceptionFrameSummary(
                detection_count=detection_result.count if detection_result is not None else 0,
                category_counts=dict(category_counts),
                signal_head_count=_signal_head_count,
                signal_observations=_signal_obs_count,
            ),
            signal_snapshot=signal_snapshot,
        )

    events: list[TrackedObjectEvent] = []
    new_track_ids = set(tracking_result.new_track_ids)

    for track in tracking_result.tracks:
        event_type = (
            TrackedObjectEventType.TRACK_STARTED
            if track.track_id in new_track_ids
            else TrackedObjectEventType.TRACK_OBSERVED
        )
        events.append(_event_from_track(track=track, event_type=event_type))

    for track in tracking_result.lost_tracks:
        events.append(_event_from_track(track=track, event_type=TrackedObjectEventType.TRACK_LOST))

    for track in tracking_result.removed_tracks:
        events.append(_event_from_track(track=track, event_type=TrackedObjectEventType.TRACK_REMOVED))

    return PerceptionEventBatch(
        frame=frame,
        summary=PerceptionFrameSummary(
            detection_count=detection_result.count if detection_result is not None else 0,
            active_track_count=tracking_result.active_count,
            new_track_count=len(tracking_result.new_track_ids),
            lost_track_count=len(tracking_result.lost_track_ids),
            removed_track_count=len(tracking_result.removed_track_ids),
            category_counts=dict(category_counts),
            signal_head_count=_signal_head_count,
            signal_observations=_signal_obs_count,
        ),
        tracked_object_events=events,
        active_tracks=[
            e.track_snapshot for e in events
            if e.event_type in (TrackedObjectEventType.TRACK_STARTED, TrackedObjectEventType.TRACK_OBSERVED)
        ],
        lost_tracks=[e.track_snapshot for e in events if e.event_type == TrackedObjectEventType.TRACK_LOST],
        removed_tracks=[e.track_snapshot for e in events if e.event_type == TrackedObjectEventType.TRACK_REMOVED],
        signal_snapshot=signal_snapshot,
    )
