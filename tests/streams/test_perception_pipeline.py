from __future__ import annotations

import uuid
from datetime import datetime, timezone

import numpy as np
import pytest

from services.streams.events import (
    EventPersistenceHint,
    TrackedObjectEventType,
    build_perception_event_batch,
)
from services.streams.pipeline import FramePipeline, FrameResult
from services.streams.schemas import JobSpec, PipelineFlags, SourceKind
from services.streams.worker import StreamWorker
from services.tracking.interface import Tracker
from services.tracking.schemas import (
    Point2D,
    TrackedObject,
    TrackingResult,
    TrackLifecycleStatus,
    TrajectoryPoint,
)
from services.vision.config import VisionSettings
from services.vision.interface import Detector
from services.vision.schemas import BBox, Detection, DetectionResult, ObjectCategory


def _make_track(
    track_id: str,
    *,
    timestamp: datetime,
    frame_index: int,
    status: TrackLifecycleStatus = TrackLifecycleStatus.ACTIVE,
    class_name: str = "car",
) -> TrackedObject:
    bbox = BBox(x1=10, y1=20, x2=50, y2=60)
    x, y = bbox.center
    return TrackedObject(
        track_id=track_id,
        class_name=class_name,
        category=ObjectCategory.VEHICLE,
        class_id=2,
        bbox=bbox,
        confidence=0.95,
        first_seen_at=timestamp,
        last_seen_at=timestamp,
        first_seen_frame=frame_index,
        last_seen_frame=frame_index,
        frame_count=1,
        trajectory=[TrajectoryPoint(point=Point2D(x=x, y=y), frame_index=frame_index, timestamp=timestamp)],
        status=status,
    )


def _make_detection_result(*, frame_index: int, timestamp: datetime) -> DetectionResult:
    return DetectionResult(
        detections=[
            Detection(
                class_name="car",
                category=ObjectCategory.VEHICLE,
                class_id=2,
                confidence=0.92,
                bbox=BBox(x1=10, y1=20, x2=50, y2=60),
                frame_index=frame_index,
                timestamp=timestamp,
            )
        ],
        frame_index=frame_index,
        timestamp=timestamp,
        source_width=640,
        source_height=480,
        inference_ms=12.5,
    )


def test_build_perception_event_batch_emits_lifecycle_events() -> None:
    ts = datetime(2026, 4, 5, 12, 0, 0, tzinfo=timezone.utc)
    active_new = _make_track("track-new", timestamp=ts, frame_index=12)
    active_existing = _make_track("track-live", timestamp=ts, frame_index=12)
    lost_track = _make_track("track-lost", timestamp=ts, frame_index=11, status=TrackLifecycleStatus.LOST)
    removed_track = _make_track("track-removed", timestamp=ts, frame_index=10, status=TrackLifecycleStatus.REMOVED)

    batch = build_perception_event_batch(
        source_id="stream-demo-1",
        stream_id=uuid.uuid4(),
        camera_id=uuid.uuid4(),
        frame_index=12,
        timestamp=ts,
        processing_latency_ms=18.2,
        detection_result=_make_detection_result(frame_index=12, timestamp=ts),
        tracking_result=TrackingResult(
            tracks=[active_new, active_existing],
            frame_index=12,
            timestamp=ts,
            new_track_ids=["track-new"],
            lost_track_ids=["track-lost"],
            lost_tracks=[lost_track],
            removed_track_ids=["track-removed"],
            removed_tracks=[removed_track],
        ),
        source_width=640,
        source_height=480,
    )

    assert batch.frame.source_id == "stream-demo-1"
    assert batch.frame.frame_index == 12
    assert batch.frame.processing_latency_ms == 18.2
    assert batch.summary.detection_count == 1
    assert batch.summary.active_track_count == 2
    assert batch.summary.new_track_count == 1
    assert batch.summary.lost_track_count == 1
    assert batch.summary.removed_track_count == 1
    assert batch.summary.category_counts["vehicle"] == 2
    assert len(batch.active_tracks) == 2
    assert len(batch.lost_tracks) == 1
    assert len(batch.removed_tracks) == 1

    event_types = {event.event_type for event in batch.tracked_object_events}
    assert TrackedObjectEventType.TRACK_STARTED in event_types
    assert TrackedObjectEventType.TRACK_OBSERVED in event_types
    assert TrackedObjectEventType.TRACK_LOST in event_types
    assert TrackedObjectEventType.TRACK_REMOVED in event_types
    assert batch.checkpoint_event_count == 3
    observed = next(event for event in batch.tracked_object_events if event.event_type == TrackedObjectEventType.TRACK_OBSERVED)
    assert observed.persistence_hint == EventPersistenceHint.TRANSIENT


class _StubDetector(Detector):
    def __init__(self, _settings: VisionSettings) -> None:
        self.loaded = False

    def load_model(self) -> None:
        self.loaded = True

    def unload(self) -> None:
        self.loaded = False

    def detect(
        self,
        image: np.ndarray,
        *,
        frame_index: int | None = None,
        timestamp: datetime | None = None,
        confidence: float | None = None,
    ) -> DetectionResult:
        del image, confidence
        assert frame_index is not None
        assert timestamp is not None
        return _make_detection_result(frame_index=frame_index, timestamp=timestamp)


class _StubTracker(Tracker):
    def update(self, detections: DetectionResult) -> TrackingResult:
        assert detections.frame_index is not None
        assert detections.timestamp is not None
        return TrackingResult(
            tracks=[_make_track("track-1", timestamp=detections.timestamp, frame_index=detections.frame_index)],
            frame_index=detections.frame_index,
            timestamp=detections.timestamp,
            new_track_ids=["track-1"],
        )

    def reset(self) -> None:
        return None

    def get_active_tracks(self) -> list[TrackedObject]:
        return []

    def snapshot(self, *, include_inactive: bool = False) -> list[TrackedObject]:
        del include_inactive
        return []


def test_frame_pipeline_emits_perception_event_batch() -> None:
    ts = datetime(2026, 4, 5, 12, 30, 0, tzinfo=timezone.utc)
    stream_id = uuid.uuid4()
    camera_id = uuid.uuid4()
    pipeline = FramePipeline(
        PipelineFlags(detection=True, tracking=True, ocr=False, rules=False),
        detector_factory=lambda: _StubDetector(VisionSettings()),
        tracker_factory=lambda: _StubTracker(),
    )
    frame = np.zeros((480, 640, 3), dtype=np.uint8)

    with pipeline:
        result = pipeline.process_frame(
            frame,
            frame_index=7,
            source_id="demo-source",
            stream_id=stream_id,
            camera_id=camera_id,
            timestamp=ts,
            source_width=640,
            source_height=480,
        )

    assert result.event_batch is not None
    assert result.event_batch.frame.source_id == "demo-source"
    assert result.event_batch.frame.stream_id == stream_id
    assert result.event_batch.frame.camera_id == camera_id
    assert result.event_batch.summary.new_track_count == 1
    assert result.event_batch.event_count == 1
    assert result.event_batch.tracked_object_events[0].event_type == TrackedObjectEventType.TRACK_STARTED
    assert result.metadata["source_width"] == 640
    assert result.metadata["source_height"] == 480


@pytest.mark.asyncio
async def test_worker_respects_max_processing_fps() -> None:
    from services.streams.config import StreamSettings

    spec = JobSpec(
        source_kind=SourceKind.TEST,
        source_uri="test://pattern",
        source_config={"max_frames": 8, "fps": 20.0},
        frame_step=1,
        max_processing_fps=5.0,
        pipeline=PipelineFlags(detection=False, tracking=False, ocr=False, rules=False),
    )
    settings = StreamSettings(
        max_concurrent_jobs=1,
        metrics_window_size=10,
        max_reconnect_attempts=1,
        file_loop=False,
    )

    worker = StreamWorker(spec, settings)
    state = await worker.run()

    assert state.status.name == "COMPLETED"
    assert state.metrics.frames_read == 8
    assert state.metrics.frames_processed == 2
    assert state.metrics.frames_skipped == 6
    assert state.metrics.frames_skipped_cadence == 6


class _LiveCounterSource:
    def __init__(self, *, fps: float = 20.0, max_frames: int = 20) -> None:
        self._fps = fps
        self._max_frames = max_frames
        self._index = 0

    def open(self) -> None:
        self._index = 0

    def read(self) -> tuple[bool, np.ndarray | None]:
        if self._index >= self._max_frames:
            return False, None
        self._index += 1
        return True, np.zeros((64, 64, 3), dtype=np.uint8)

    def release(self) -> None:
        return None

    @property
    def fps_hint(self) -> float:
        return self._fps

    @property
    def resolution(self) -> tuple[int, int]:
        return (64, 64)

    @property
    def is_live(self) -> bool:
        return True


class _SlowPipeline:
    def __init__(self, *_args, **_kwargs) -> None:
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def process_frame(
        self,
        frame: np.ndarray,
        *,
        frame_index: int,
        source_id: str,
        stream_id=None,
        camera_id=None,
        timestamp: datetime | None = None,
        source_width: int | None = None,
        source_height: int | None = None,
    ) -> FrameResult:
        del frame, stream_id, camera_id, source_width, source_height
        return FrameResult(
            frame_index=frame_index,
            timestamp=timestamp or datetime.now(timezone.utc),
            elapsed_ms=250.0,
            metadata={"source_id": source_id},
        )


@pytest.mark.asyncio
async def test_worker_drops_frames_when_live_source_falls_behind(monkeypatch) -> None:
    from services.streams import worker as worker_module
    from services.streams.config import StreamSettings

    monkeypatch.setattr(worker_module, "create_frame_source", lambda *args, **kwargs: _LiveCounterSource())
    monkeypatch.setattr(worker_module, "FramePipeline", _SlowPipeline)

    spec = JobSpec(
        source_kind=SourceKind.TEST,
        source_uri="test://pattern",
        max_frames=1,
        pipeline=PipelineFlags(detection=False, tracking=False, ocr=False, rules=False),
    )
    settings = StreamSettings(
        max_concurrent_jobs=1,
        metrics_window_size=10,
        max_reconnect_attempts=1,
        file_loop=False,
        max_backpressure_frame_drops=3,
        drop_frames_when_behind=True,
    )

    worker = StreamWorker(spec, settings)
    state = await worker.run()

    assert state.status.name == "COMPLETED"
    assert state.metrics.frames_processed == 1
    assert state.metrics.frames_dropped_backpressure == 3
    assert state.metrics.frames_read == 4
