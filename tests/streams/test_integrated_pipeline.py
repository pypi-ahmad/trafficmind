"""Integration tests — full detection → tracking → OCR → rules pipeline.

These tests verify that ``FramePipeline.process_frame()`` correctly chains
all stages using stub backends, exercising the same code paths a real
stream worker would hit.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pytest

from services.ocr.interface import OcrEngine
from services.ocr.schemas import OcrContext, OcrResult, PlateOcrResult
from services.rules.schemas import (
    LineCrossingRuleConfig,
    LineGeometry,
    RuleType,
    ZoneConfig,
)
from services.streams.pipeline import FramePipeline, FrameResult
from services.streams.schemas import PipelineFlags
from services.tracking.interface import Tracker
from services.tracking.schemas import (
    Point2D,
    TrackedObject,
    TrackingResult,
    TrajectoryPoint,
)
from services.vision.interface import Detector
from services.vision.schemas import BBox, Detection, DetectionResult, ObjectCategory


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 6, 10, 0, 0, tzinfo=UTC)
CAMERA_ID = uuid.uuid4()
STREAM_ID = uuid.uuid4()


def _make_detection(
    *,
    class_name: str = "car",
    category: ObjectCategory = ObjectCategory.VEHICLE,
    bbox: BBox = BBox(x1=100, y1=100, x2=200, y2=200),
    confidence: float = 0.9,
    frame_index: int = 0,
) -> Detection:
    return Detection(
        class_name=class_name,
        category=category,
        class_id=2,
        confidence=confidence,
        bbox=bbox,
        frame_index=frame_index,
        timestamp=NOW + timedelta(milliseconds=frame_index * 33),
    )


def _make_plate_detection(*, frame_index: int = 0) -> Detection:
    return _make_detection(
        class_name="license_plate",
        category=ObjectCategory.PLATE,
        bbox=BBox(x1=120, y1=180, x2=190, y2=200),
        confidence=0.85,
        frame_index=frame_index,
    )


def _make_track(
    track_id: str,
    pts: list[tuple[float, float]],
    *,
    category: ObjectCategory = ObjectCategory.VEHICLE,
    class_name: str = "car",
    frame_offset: int = 0,
) -> TrackedObject:
    traj = [
        TrajectoryPoint(
            point=Point2D(x=x, y=y),
            frame_index=frame_offset + i,
            timestamp=NOW + timedelta(milliseconds=(frame_offset + i) * 33),
        )
        for i, (x, y) in enumerate(pts)
    ]
    last = pts[-1]
    return TrackedObject(
        track_id=track_id,
        class_name=class_name,
        category=category,
        bbox=BBox(x1=last[0] - 10, y1=last[1] - 10, x2=last[0] + 10, y2=last[1] + 10),
        confidence=0.9,
        first_seen_at=NOW + timedelta(milliseconds=frame_offset * 33),
        last_seen_at=NOW + timedelta(milliseconds=(frame_offset + len(pts) - 1) * 33),
        first_seen_frame=frame_offset,
        last_seen_frame=frame_offset + len(pts) - 1,
        frame_count=len(pts),
        trajectory=traj,
    )


# ---------------------------------------------------------------------------
# Stub backends
# ---------------------------------------------------------------------------


class StubDetector(Detector):
    """Returns canned detections — optionally includes a plate detection."""

    def __init__(self, *, include_plate: bool = False) -> None:
        self._include_plate = include_plate
        self._call_count = 0

    def load_model(self) -> None:
        pass

    def unload(self) -> None:
        pass

    def detect(
        self,
        image: np.ndarray,
        *,
        frame_index: int | None = None,
        timestamp: datetime | None = None,
        confidence: float | None = None,
    ) -> DetectionResult:
        fi = frame_index or 0
        dets = [_make_detection(frame_index=fi)]
        if self._include_plate:
            dets.append(_make_plate_detection(frame_index=fi))
        self._call_count += 1
        return DetectionResult(
            detections=dets,
            frame_index=fi,
            timestamp=timestamp or NOW,
            source_width=640,
            source_height=480,
            inference_ms=5.0,
        )


class StubTracker(Tracker):
    """Stateful tracker returning tracks that move across frames.

    Returns a single track whose centroid follows a canned trajectory.
    """

    def __init__(self, trajectory: list[tuple[float, float]] | None = None) -> None:
        self._trajectory = trajectory or [(150, 280), (150, 310), (150, 340)]
        self._frame = 0
        self._first_call = True

    def update(self, detections: DetectionResult) -> TrackingResult:
        fi = detections.frame_index or 0
        # Build a track with all trajectory points seen so far
        pts_so_far = self._trajectory[: self._frame + 1]
        track = _make_track("track-1", pts_so_far, frame_offset=max(0, fi - len(pts_so_far) + 1))
        new = ["track-1"] if self._first_call else []
        self._first_call = False
        self._frame = min(self._frame + 1, len(self._trajectory) - 1)
        return TrackingResult(
            tracks=[track],
            frame_index=fi,
            timestamp=detections.timestamp,
            new_track_ids=new,
        )

    def reset(self) -> None:
        self._frame = 0
        self._first_call = True

    def get_active_tracks(self) -> list[TrackedObject]:
        return []

    def snapshot(self, *, include_inactive: bool = False) -> list[TrackedObject]:
        return []


class StubOcrEngine(OcrEngine):
    """Returns a canned plate text for any crop."""

    def __init__(self) -> None:
        self._call_count = 0

    def load_model(self) -> None:
        pass

    def unload(self) -> None:
        pass

    def recognize(
        self,
        image: np.ndarray,
        *,
        context: OcrContext | None = None,
    ) -> list[OcrResult]:
        self._call_count += 1
        return [
            OcrResult(
                recognized_text="ABC1234",
                confidence=0.92,
                bbox=BBox(x1=0, y1=0, x2=image.shape[1], y2=image.shape[0]),
            ),
        ]


# ---------------------------------------------------------------------------
# Zone fixtures
# ---------------------------------------------------------------------------


def _crossing_line_zone(
    *,
    y: float = 300.0,
    cooldown: float = 0.0,
) -> ZoneConfig:
    """Horizontal line at y — track moving downward will cross it."""
    return ZoneConfig(
        zone_id="zone-stopline",
        name="Test Stop Line",
        zone_type="stop_line",
        geometry=LineGeometry(
            start=Point2D(x=50.0, y=y),
            end=Point2D(x=600.0, y=y),
        ),
        rules=[LineCrossingRuleConfig(cooldown_seconds=cooldown)],
    )


# ═══════════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestDetectionToTracking:
    """Baseline: detection + tracking integrated through the pipeline."""

    def test_single_frame_produces_detection_and_tracking(self) -> None:
        pipeline = FramePipeline(
            PipelineFlags(detection=True, tracking=True, signals=False, ocr=False, rules=False),
            detector_factory=lambda: StubDetector(),
            tracker_factory=lambda: StubTracker(),
        )
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        with pipeline:
            result = pipeline.process_frame(
                frame,
                frame_index=0,
                source_id="test",
                camera_id=CAMERA_ID,
                timestamp=NOW,
            )

        assert result.detection_result is not None
        assert result.detection_count == 1
        assert result.tracking_result is not None
        assert result.active_tracks == 1
        assert result.event_batch is not None


class TestOcrIntegration:
    """OCR stage runs on plate detections when enabled."""

    def test_ocr_reads_plate_from_detection(self) -> None:
        ocr = StubOcrEngine()
        pipeline = FramePipeline(
            PipelineFlags(detection=True, tracking=True, signals=False, ocr=True, rules=False),
            detector_factory=lambda: StubDetector(include_plate=True),
            tracker_factory=lambda: StubTracker(),
            ocr_engine_factory=lambda: ocr,
        )
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        with pipeline:
            result = pipeline.process_frame(
                frame,
                frame_index=0,
                source_id="test",
                camera_id=CAMERA_ID,
                timestamp=NOW,
            )

        assert len(result.plate_reads) == 1
        plate = result.plate_reads[0]
        assert isinstance(plate, PlateOcrResult)
        assert plate.normalized_text == "ABC1234"
        assert plate.confidence >= 0.60
        assert plate.frame_index == 0
        assert ocr._call_count == 1

    def test_ocr_skips_non_plate_detections(self) -> None:
        ocr = StubOcrEngine()
        pipeline = FramePipeline(
            PipelineFlags(detection=True, tracking=True, signals=False, ocr=True, rules=False),
            detector_factory=lambda: StubDetector(include_plate=False),
            tracker_factory=lambda: StubTracker(),
            ocr_engine_factory=lambda: ocr,
        )
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        with pipeline:
            result = pipeline.process_frame(
                frame,
                frame_index=0,
                source_id="test",
                camera_id=CAMERA_ID,
                timestamp=NOW,
            )

        assert result.plate_reads == []
        assert ocr._call_count == 0

    def test_ocr_disabled_when_flag_off(self) -> None:
        ocr = StubOcrEngine()
        pipeline = FramePipeline(
            PipelineFlags(detection=True, tracking=True, signals=False, ocr=False, rules=False),
            detector_factory=lambda: StubDetector(include_plate=True),
            tracker_factory=lambda: StubTracker(),
            ocr_engine_factory=lambda: ocr,
        )
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        with pipeline:
            result = pipeline.process_frame(
                frame,
                frame_index=0,
                source_id="test",
                camera_id=CAMERA_ID,
                timestamp=NOW,
            )

        assert result.plate_reads == []
        assert ocr._call_count == 0


class TestRulesIntegration:
    """Rules engine runs after tracking and produces ViolationRecords."""

    def test_line_crossing_violation_fires_across_frames(self) -> None:
        """Track crosses a horizontal line over two frames → violation."""
        zone = _crossing_line_zone(y=300.0, cooldown=0.0)
        # Track moves from y=280 → y=310 (crosses the line at y=300)
        trajectory = [(150, 280), (150, 310)]

        pipeline = FramePipeline(
            PipelineFlags(detection=True, tracking=True, signals=False, ocr=False, rules=True),
            detector_factory=lambda: StubDetector(),
            tracker_factory=lambda: StubTracker(trajectory=trajectory),
            zone_configs=[zone],
        )
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        with pipeline:
            r0 = pipeline.process_frame(
                frame, frame_index=0, source_id="test", timestamp=NOW,
            )
            r1 = pipeline.process_frame(
                frame, frame_index=1, source_id="test",
                timestamp=NOW + timedelta(milliseconds=33),
            )

        # First frame: track at y=280, no crossing yet
        assert r0.violations == []
        # Second frame: track crossed y=300 → violation
        assert len(r1.violations) == 1
        v = r1.violations[0]
        assert v.rule_type == RuleType.LINE_CROSSING
        assert v.track_id == "track-1"
        assert v.zone_id == "zone-stopline"

    def test_no_violations_without_zones(self) -> None:
        pipeline = FramePipeline(
            PipelineFlags(detection=True, tracking=True, signals=False, ocr=False, rules=True),
            detector_factory=lambda: StubDetector(),
            tracker_factory=lambda: StubTracker(),
            zone_configs=[],
        )
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        with pipeline:
            result = pipeline.process_frame(
                frame, frame_index=0, source_id="test", timestamp=NOW,
            )

        assert result.violations == []

    def test_rules_disabled_when_flag_off(self) -> None:
        zone = _crossing_line_zone(y=300.0, cooldown=0.0)
        trajectory = [(150, 280), (150, 310)]

        pipeline = FramePipeline(
            PipelineFlags(detection=True, tracking=True, signals=False, ocr=False, rules=False),
            detector_factory=lambda: StubDetector(),
            tracker_factory=lambda: StubTracker(trajectory=trajectory),
            zone_configs=[zone],
        )
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        with pipeline:
            pipeline.process_frame(
                frame, frame_index=0, source_id="test", timestamp=NOW,
            )
            r1 = pipeline.process_frame(
                frame, frame_index=1, source_id="test",
                timestamp=NOW + timedelta(milliseconds=33),
            )

        assert r1.violations == []


class TestFullIntegratedPipeline:
    """End-to-end: detection → tracking → OCR → rules in one pass."""

    def test_full_pipeline_produces_all_outputs(self) -> None:
        """Two frames with plate detection + line-crossing zone.

        Frame 0: track starts at y=280, plate detected → OCR reads plate
        Frame 1: track at y=310, crosses y=300 line → violation fires
        Both frames produce plate reads.
        """
        zone = _crossing_line_zone(y=300.0, cooldown=0.0)
        trajectory = [(150, 280), (150, 310)]
        ocr = StubOcrEngine()

        pipeline = FramePipeline(
            PipelineFlags(detection=True, tracking=True, signals=False, ocr=True, rules=True),
            detector_factory=lambda: StubDetector(include_plate=True),
            tracker_factory=lambda: StubTracker(trajectory=trajectory),
            ocr_engine_factory=lambda: ocr,
            zone_configs=[zone],
        )
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        with pipeline:
            r0 = pipeline.process_frame(
                frame, frame_index=0, source_id="test",
                camera_id=CAMERA_ID, stream_id=STREAM_ID, timestamp=NOW,
            )
            r1 = pipeline.process_frame(
                frame, frame_index=1, source_id="test",
                camera_id=CAMERA_ID, stream_id=STREAM_ID,
                timestamp=NOW + timedelta(milliseconds=33),
            )

        # --- Frame 0 ---
        # Detection: car + plate
        assert r0.detection_count == 2
        # Tracking: one vehicle track
        assert r0.active_tracks == 1
        # OCR: plate read from the plate detection
        assert len(r0.plate_reads) == 1
        assert r0.plate_reads[0].normalized_text == "ABC1234"
        # Rules: no crossing yet
        assert r0.violations == []
        # Event batch present
        assert r0.event_batch is not None

        # --- Frame 1 ---
        # OCR: second plate read
        assert len(r1.plate_reads) == 1
        # Rules: line crossing fires
        assert len(r1.violations) == 1
        assert r1.violations[0].rule_type == RuleType.LINE_CROSSING
        assert r1.violations[0].track_id == "track-1"

    def test_violation_record_has_orm_kwargs(self) -> None:
        """ViolationRecord.to_orm_kwargs() returns persistable dict."""
        zone = _crossing_line_zone(y=300.0, cooldown=0.0)
        trajectory = [(150, 280), (150, 310)]

        pipeline = FramePipeline(
            PipelineFlags(detection=True, tracking=True, signals=False, ocr=False, rules=True),
            detector_factory=lambda: StubDetector(),
            tracker_factory=lambda: StubTracker(trajectory=trajectory),
            zone_configs=[zone],
        )
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        with pipeline:
            pipeline.process_frame(
                frame, frame_index=0, source_id="test", timestamp=NOW,
            )
            r1 = pipeline.process_frame(
                frame, frame_index=1, source_id="test",
                timestamp=NOW + timedelta(milliseconds=33),
            )

        v = r1.violations[0]
        orm = v.to_orm_kwargs()
        assert "violation_type" in orm
        assert "severity" in orm
        assert "occurred_at" in orm
        assert "rule_metadata" in orm
        assert orm["rule_metadata"]["track_id"] == "track-1"


class TestMultiFrameWorkerSimulation:
    """Simulate a multi-frame stream processing run."""

    def test_ten_frame_run_accumulates_results(self) -> None:
        """Process 10 frames; track crosses line around frame 1."""
        zone = _crossing_line_zone(y=300.0, cooldown=0.0)
        # Track descends: 280, 290, 300, 310, 320, ...
        trajectory = [(150, 280 + i * 10) for i in range(10)]
        ocr = StubOcrEngine()

        pipeline = FramePipeline(
            PipelineFlags(detection=True, tracking=True, signals=False, ocr=True, rules=True),
            detector_factory=lambda: StubDetector(include_plate=True),
            tracker_factory=lambda: StubTracker(trajectory=trajectory),
            ocr_engine_factory=lambda: ocr,
            zone_configs=[zone],
        )
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        results: list[FrameResult] = []
        with pipeline:
            for i in range(10):
                r = pipeline.process_frame(
                    frame,
                    frame_index=i,
                    source_id="test",
                    timestamp=NOW + timedelta(milliseconds=i * 33),
                )
                results.append(r)

        # Every frame should produce exactly 1 plate read
        assert all(len(r.plate_reads) == 1 for r in results)

        # At least one frame should fire a violation (when track crosses y=300)
        all_violations = [v for r in results for v in r.violations]
        assert len(all_violations) >= 1
        assert all(v.rule_type == RuleType.LINE_CROSSING for v in all_violations)

        # Metadata is present on every frame
        assert all(r.metadata["source_id"] == "test" for r in results)
        assert all(r.elapsed_ms >= 0 for r in results)


class TestPipelineLifecycle:
    """Start/stop and context-manager lifecycle."""

    def test_start_stop_loads_and_releases_ocr_engine(self) -> None:
        loaded = {"ocr": False}

        class TrackingOcrEngine(OcrEngine):
            def load_model(self) -> None:
                loaded["ocr"] = True

            def unload(self) -> None:
                loaded["ocr"] = False

            def recognize(self, image, *, context=None):
                return []

        pipeline = FramePipeline(
            PipelineFlags(detection=True, tracking=True, signals=False, ocr=True, rules=False),
            detector_factory=lambda: StubDetector(),
            tracker_factory=lambda: StubTracker(),
            ocr_engine_factory=TrackingOcrEngine,
        )

        assert not loaded["ocr"]
        pipeline.start()
        assert loaded["ocr"]
        pipeline.stop()
        assert not loaded["ocr"]

    def test_rules_engine_created_with_zone_configs(self) -> None:
        zone = _crossing_line_zone()
        pipeline = FramePipeline(
            PipelineFlags(detection=True, tracking=True, signals=False, ocr=False, rules=True),
            detector_factory=lambda: StubDetector(),
            tracker_factory=lambda: StubTracker(),
            zone_configs=[zone],
        )
        pipeline.start()
        assert pipeline._rules_engine is not None
        assert len(pipeline._rules_engine.zones) == 1
        pipeline.stop()
        assert pipeline._rules_engine is None

    def test_rules_engine_not_created_without_tracking(self) -> None:
        pipeline = FramePipeline(
            PipelineFlags(detection=True, tracking=False, signals=False, ocr=False, rules=True),
            detector_factory=lambda: StubDetector(),
        )
        pipeline.start()
        assert pipeline._rules_engine is None
        pipeline.stop()
