"""Tests for the traffic-light signal perception and state module."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import numpy as np
import pytest
from pydantic import ValidationError

from services.rules.schemas import TrafficLightState
from services.signals.classifier import HsvHistogramClassifier, SignalClassifierRegistry
from services.signals.config import SignalSettings
from services.signals.schemas import (
    SignalClassification,
    SignalColor,
    SignalHeadConfig,
    SignalHeadObservation,
    SignalHeadState,
    SignalPhase,
    SignalSceneSnapshot,
)
from services.signals.state import (
    SignalStateTracker,
    _iou,
    _majority_color,
    signal_color_to_traffic_light_state,
)
from services.vision.schemas import BBox, Detection, DetectionResult, ObjectCategory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TS = datetime(2026, 4, 5, 12, 0, 0, tzinfo=UTC)


def _red_crop(size: int = 32) -> np.ndarray:
    """BGR image that is bright red — should classify as RED."""
    img = np.zeros((size, size, 3), dtype=np.uint8)
    img[:, :] = (0, 0, 255)  # BGR: pure red
    return img


def _green_crop(size: int = 32) -> np.ndarray:
    """BGR image that is bright green — should classify as GREEN."""
    img = np.zeros((size, size, 3), dtype=np.uint8)
    img[:, :] = (0, 255, 0)  # BGR: pure green
    return img


def _yellow_crop(size: int = 32) -> np.ndarray:
    """BGR image that is bright yellow — should classify as YELLOW."""
    img = np.zeros((size, size, 3), dtype=np.uint8)
    img[:, :] = (0, 255, 255)  # BGR: pure yellow
    return img


def _dark_crop(size: int = 32) -> np.ndarray:
    """Dim/dark image — should classify as UNKNOWN."""
    img = np.full((size, size, 3), 20, dtype=np.uint8)
    return img


def _tiny_crop() -> np.ndarray:
    """Crop smaller than min_crop_pixels — should reject."""
    return np.zeros((4, 4, 3), dtype=np.uint8)


def _default_bbox() -> BBox:
    return BBox(x1=100, y1=50, x2=130, y2=110)


def _make_tl_detection(
    *,
    bbox: BBox | None = None,
    frame_index: int = 0,
    timestamp: datetime = _TS,
) -> Detection:
    return Detection(
        class_name="traffic light",
        category=ObjectCategory.TRAFFIC_LIGHT,
        class_id=9,
        confidence=0.85,
        bbox=bbox or _default_bbox(),
        frame_index=frame_index,
        timestamp=timestamp,
    )


def _make_detection_result(
    detections: list[Detection] | None = None,
    *,
    frame_index: int = 0,
    timestamp: datetime = _TS,
) -> DetectionResult:
    return DetectionResult(
        detections=detections
        or [_make_tl_detection(frame_index=frame_index, timestamp=timestamp)],
        frame_index=frame_index,
        timestamp=timestamp,
        source_width=640,
        source_height=480,
    )


def _make_frame_with_color(
    color: tuple[int, int, int],
    bbox: BBox | None = None,
) -> np.ndarray:
    """Return a 640x480 black frame with a coloured rectangle at `bbox`."""
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    bbox = bbox or _default_bbox()
    x1, y1 = int(bbox.x1), int(bbox.y1)
    x2, y2 = int(bbox.x2), int(bbox.y2)
    frame[y1:y2, x1:x2] = color
    return frame


def _vehicle_head_config(
    bbox: BBox | None = None,
    *,
    head_id: str = "tl-main-1",
) -> SignalHeadConfig:
    return SignalHeadConfig(
        head_id=head_id,
        phase=SignalPhase.VEHICLE,
        anchor_bbox=bbox or _default_bbox(),
        lane_id="lane-1",
        stop_line_id="sl-1",
        crosswalk_id="cw-1",
    )


# ===========================================================================
# HSV Histogram Classifier
# ===========================================================================


class TestHsvHistogramClassifier:
    def setup_method(self) -> None:
        self.settings = SignalSettings()
        self.classifier = HsvHistogramClassifier(self.settings)

    def test_red_crop(self) -> None:
        result = self.classifier.classify(_red_crop())
        assert result.color == SignalColor.RED
        assert result.confidence > 0.5
        assert "red" in result.color_scores

    def test_green_crop(self) -> None:
        result = self.classifier.classify(_green_crop())
        assert result.color == SignalColor.GREEN
        assert result.confidence > 0.5

    def test_yellow_crop(self) -> None:
        result = self.classifier.classify(_yellow_crop())
        assert result.color == SignalColor.YELLOW
        assert result.confidence > 0.5

    def test_dark_crop_returns_unknown(self) -> None:
        result = self.classifier.classify(_dark_crop())
        assert result.color == SignalColor.UNKNOWN

    def test_tiny_crop_returns_unknown(self) -> None:
        result = self.classifier.classify(_tiny_crop())
        assert result.color == SignalColor.UNKNOWN
        assert result.confidence == 0.0

    def test_confidence_threshold_respected(self) -> None:
        # Mixed colour image — low confidence for any single colour
        img = np.zeros((32, 32, 3), dtype=np.uint8)
        img[:11, :] = (0, 0, 255)  # red top third
        img[11:22, :] = (0, 255, 0)  # green mid third
        img[22:, :] = (0, 255, 255)  # yellow bottom third
        result = self.classifier.classify(img)
        # Each colour gets ~33%, below the default 35% threshold
        assert result.color == SignalColor.UNKNOWN or result.confidence < 0.5


class TestSignalClassifierRegistry:
    def test_hsv_histogram_registered(self) -> None:
        assert "hsv_histogram" in SignalClassifierRegistry.available()

    def test_create_returns_instance(self) -> None:
        cls = SignalClassifierRegistry.create("hsv_histogram", SignalSettings())
        assert isinstance(cls, HsvHistogramClassifier)

    def test_unknown_backend_raises(self) -> None:
        with pytest.raises(KeyError, match="nonexistent"):
            SignalClassifierRegistry.create("nonexistent", SignalSettings())


# ===========================================================================
# Utility functions
# ===========================================================================


class TestIoU:
    def test_identical_boxes(self) -> None:
        box = BBox(x1=0, y1=0, x2=10, y2=10)
        assert _iou(box, box) == pytest.approx(1.0)

    def test_no_overlap(self) -> None:
        a = BBox(x1=0, y1=0, x2=10, y2=10)
        b = BBox(x1=20, y1=20, x2=30, y2=30)
        assert _iou(a, b) == pytest.approx(0.0)

    def test_partial_overlap(self) -> None:
        a = BBox(x1=0, y1=0, x2=10, y2=10)
        b = BBox(x1=5, y1=5, x2=15, y2=15)
        # intersection = 5x5 = 25, union = 100+100-25 = 175
        assert _iou(a, b) == pytest.approx(25 / 175)

    def test_zero_area_box(self) -> None:
        a = BBox(x1=5, y1=5, x2=5, y2=5)
        b = BBox(x1=0, y1=0, x2=10, y2=10)
        assert _iou(a, b) == pytest.approx(0.0)


class TestMajorityColor:
    def test_clear_majority(self) -> None:
        from collections import deque

        history = deque([SignalColor.RED, SignalColor.RED, SignalColor.GREEN])
        assert _majority_color(history) == SignalColor.RED

    def test_empty_returns_unknown(self) -> None:
        from collections import deque

        assert _majority_color(deque()) == SignalColor.UNKNOWN

    def test_tie_with_unknown_prefers_unknown(self) -> None:
        from collections import deque

        history = deque([SignalColor.RED, SignalColor.UNKNOWN])
        assert _majority_color(history) == SignalColor.UNKNOWN


class TestSignalColorMapping:
    def test_red(self) -> None:
        assert signal_color_to_traffic_light_state(SignalColor.RED) == TrafficLightState.RED

    def test_yellow(self) -> None:
        assert signal_color_to_traffic_light_state(SignalColor.YELLOW) == TrafficLightState.YELLOW

    def test_green(self) -> None:
        assert signal_color_to_traffic_light_state(SignalColor.GREEN) == TrafficLightState.GREEN

    def test_unknown(self) -> None:
        assert (
            signal_color_to_traffic_light_state(SignalColor.UNKNOWN) == TrafficLightState.UNKNOWN
        )


# ===========================================================================
# Signal State Tracker
# ===========================================================================


class TestSignalStateTracker:
    def setup_method(self) -> None:
        self.settings = SignalSettings(
            smoothing_window=3,
            transition_threshold=2,
            unknown_after_missed_frames=5,
            min_crop_pixels=8,
        )
        self.classifier = HsvHistogramClassifier(self.settings)

    def test_single_frame_creates_head(self) -> None:
        tracker = SignalStateTracker(self.classifier, self.settings)
        bbox = BBox(x1=100, y1=50, x2=130, y2=110)
        det = _make_detection_result(frame_index=0)
        frame = _make_frame_with_color((0, 0, 255), bbox)  # red

        snapshot = tracker.update(det, frame, 0, _TS)

        assert tracker.head_count == 1
        assert len(snapshot.observations) == 1
        assert snapshot.observations[0].classification.color == SignalColor.RED
        assert len(snapshot.head_states) == 1

    def test_hysteresis_prevents_immediate_transition(self) -> None:
        """Confirmed colour should NOT flip after a single opposing frame."""
        bbox = BBox(x1=100, y1=50, x2=130, y2=110)
        tracker = SignalStateTracker(
            self.classifier,
            self.settings,
            head_configs=[_vehicle_head_config(bbox)],
        )

        # 2 red frames → confirmed=RED (threshold=2)
        for i in range(2):
            frame = _make_frame_with_color((0, 0, 255), bbox)
            tracker.update(_make_detection_result(frame_index=i), frame, i, _TS)

        ctx = tracker.to_scene_context(1, _TS)
        assert ctx.traffic_light_state == TrafficLightState.RED

        # 1 green frame → should still be RED (not enough votes to transition)
        frame_g = _make_frame_with_color((0, 255, 0), bbox)
        tracker.update(_make_detection_result(frame_index=2), frame_g, 2, _TS)

        ctx = tracker.to_scene_context(2, _TS)
        assert ctx.traffic_light_state == TrafficLightState.RED

    def test_transition_after_threshold_met(self) -> None:
        """Confirmed colour flips after transition_threshold consecutive new-majority frames."""
        bbox = BBox(x1=100, y1=50, x2=130, y2=110)
        tracker = SignalStateTracker(
            self.classifier,
            self.settings,
            head_configs=[_vehicle_head_config(bbox)],
        )

        # Seed with red
        for i in range(2):
            frame = _make_frame_with_color((0, 0, 255), bbox)
            tracker.update(_make_detection_result(frame_index=i), frame, i, _TS)

        # 3 green frames (window=3, threshold=2)
        for i in range(2, 5):
            frame = _make_frame_with_color((0, 255, 0), bbox)
            tracker.update(_make_detection_result(frame_index=i), frame, i, _TS)

        ctx = tracker.to_scene_context(4, _TS)
        assert ctx.traffic_light_state == TrafficLightState.GREEN

    def test_unknown_on_stale_head(self) -> None:
        """Signal reverts to UNKNOWN if not observed for unknown_after_missed_frames."""
        bbox = BBox(x1=100, y1=50, x2=130, y2=110)
        tracker = SignalStateTracker(
            self.classifier,
            self.settings,
            head_configs=[_vehicle_head_config(bbox)],
        )

        # Seed: 2 red frames
        for i in range(2):
            frame = _make_frame_with_color((0, 0, 255), bbox)
            tracker.update(_make_detection_result(frame_index=i), frame, i, _TS)

        # Skip 10 frames (no detections)
        for i in range(2, 12):
            empty_det = DetectionResult(
                detections=[],
                frame_index=i,
                timestamp=_TS,
                source_width=640,
                source_height=480,
            )
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            tracker.update(empty_det, frame, i, _TS)

        ctx = tracker.to_scene_context(11, _TS)
        assert ctx.traffic_light_state == TrafficLightState.UNKNOWN

    def test_multiple_heads_tracked_independently(self) -> None:
        """Two non-overlapping detections create two independent heads."""
        tracker = SignalStateTracker(self.classifier, self.settings)
        bbox1 = BBox(x1=100, y1=50, x2=130, y2=110)
        bbox2 = BBox(x1=400, y1=50, x2=430, y2=110)

        det1 = _make_tl_detection(bbox=bbox1, frame_index=0)
        det2 = _make_tl_detection(bbox=bbox2, frame_index=0)
        det_result = DetectionResult(
            detections=[det1, det2],
            frame_index=0,
            timestamp=_TS,
            source_width=640,
            source_height=480,
        )

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[50:110, 100:130] = (0, 0, 255)  # head 1: red
        frame[50:110, 400:430] = (0, 255, 0)  # head 2: green

        snapshot = tracker.update(det_result, frame, 0, _TS)

        assert tracker.head_count == 2
        assert len(snapshot.observations) == 2

        colors = {obs.classification.color for obs in snapshot.observations}
        assert SignalColor.RED in colors
        assert SignalColor.GREEN in colors

    def test_multiple_vehicle_heads_do_not_force_ambiguous_primary_scene_state(self) -> None:
        bbox1 = BBox(x1=100, y1=50, x2=130, y2=110)
        bbox2 = BBox(x1=400, y1=50, x2=430, y2=110)
        tracker = SignalStateTracker(
            self.classifier,
            self.settings,
            head_configs=[
                _vehicle_head_config(bbox1, head_id="veh-a"),
                _vehicle_head_config(bbox2, head_id="veh-b"),
            ],
        )

        det1 = _make_tl_detection(bbox=bbox1, frame_index=0)
        det2 = _make_tl_detection(bbox=bbox2, frame_index=0)
        det_result = DetectionResult(
            detections=[det1, det2],
            frame_index=0,
            timestamp=_TS,
            source_width=640,
            source_height=480,
        )
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[50:110, 100:130] = (0, 0, 255)
        frame[50:110, 400:430] = (0, 255, 0)

        tracker.update(det_result, frame, 0, _TS)
        tracker.update(det_result, frame, 1, _TS)

        ctx = tracker.to_scene_context(1, _TS)
        assert len(ctx.signal_states) == 2
        assert ctx.traffic_light_state == TrafficLightState.UNKNOWN
        assert ctx.vehicle_signal_state == TrafficLightState.UNKNOWN

    def test_iou_matching_reuses_head(self) -> None:
        """Same bbox reappearing should match the same head, not create a new one."""
        tracker = SignalStateTracker(self.classifier, self.settings)
        bbox = BBox(x1=100, y1=50, x2=130, y2=110)

        for i in range(3):
            frame = _make_frame_with_color((0, 0, 255), bbox)
            tracker.update(_make_detection_result(frame_index=i), frame, i, _TS)

        assert tracker.head_count == 1

    def test_scene_context_unknown_when_no_heads(self) -> None:
        tracker = SignalStateTracker(self.classifier, self.settings)
        ctx = tracker.to_scene_context(0, _TS)
        assert ctx.traffic_light_state == TrafficLightState.UNKNOWN

    def test_unknown_phase_head_does_not_drive_vehicle_scene_context(self) -> None:
        tracker = SignalStateTracker(self.classifier, self.settings)
        bbox = BBox(x1=100, y1=50, x2=130, y2=110)

        for i in range(2):
            frame = _make_frame_with_color((0, 0, 255), bbox)
            tracker.update(_make_detection_result(frame_index=i), frame, i, _TS)

        ctx = tracker.to_scene_context(1, _TS)
        assert ctx.traffic_light_state == TrafficLightState.UNKNOWN

    def test_preconfigured_head(self) -> None:
        """Pre-configured heads carry their zone linkage through to SceneContext."""
        bbox = BBox(x1=100, y1=50, x2=130, y2=110)
        config = _vehicle_head_config(bbox)
        tracker = SignalStateTracker(
            self.classifier,
            self.settings,
            head_configs=[config],
        )

        assert tracker.head_count == 1

        # Feed red frames
        for i in range(2):
            frame = _make_frame_with_color((0, 0, 255), bbox)
            tracker.update(_make_detection_result(frame_index=i), frame, i, _TS)

        ctx = tracker.to_scene_context(1, _TS)
        assert ctx.traffic_light_state == TrafficLightState.RED
        assert ctx.traffic_light_zone_name == "sl-1"

    def test_reset_clears_all_state(self) -> None:
        tracker = SignalStateTracker(self.classifier, self.settings)
        bbox = BBox(x1=100, y1=50, x2=130, y2=110)
        frame = _make_frame_with_color((0, 0, 255), bbox)
        tracker.update(_make_detection_result(), frame, 0, _TS)
        assert tracker.head_count == 1

        tracker.reset()
        assert tracker.head_count == 0

    def test_reset_preserves_configured_heads(self) -> None:
        bbox = BBox(x1=100, y1=50, x2=130, y2=110)
        tracker = SignalStateTracker(
            self.classifier,
            self.settings,
            head_configs=[_vehicle_head_config(bbox)],
        )

        frame = _make_frame_with_color((0, 0, 255), bbox)
        tracker.update(_make_detection_result(), frame, 0, _TS)
        assert tracker.head_count == 1

        tracker.reset()
        assert tracker.head_count == 1


# ===========================================================================
# Schema smoke tests
# ===========================================================================


class TestSignalSchemas:
    def test_signal_classification_frozen(self) -> None:
        sc = SignalClassification(color=SignalColor.RED, confidence=0.9)
        with pytest.raises(ValidationError):
            sc.color = SignalColor.GREEN  # type: ignore[misc]

    def test_signal_head_observation_to_event_dict(self) -> None:
        obs = SignalHeadObservation(
            head_id="tl-1",
            phase=SignalPhase.VEHICLE,
            bbox=BBox(x1=10, y1=20, x2=30, y2=40),
            classification=SignalClassification(color=SignalColor.RED, confidence=0.85),
            frame_index=5,
            timestamp=_TS,
            source_id="source-1",
            stream_id=uuid.uuid4(),
            camera_id=uuid.uuid4(),
            lane_id="lane-1",
            stop_line_id="sl-1",
        )
        d = obs.to_event_dict()
        assert d["color"] == "red"
        assert d["head_id"] == "tl-1"
        assert d["source_id"] == "source-1"
        assert d["lane_id"] == "lane-1"
        assert d["stop_line_id"] == "sl-1"

    def test_signal_scene_snapshot_primary_vehicle(self) -> None:
        snapshot = SignalSceneSnapshot(
            frame_index=10,
            timestamp=_TS,
            head_states=[
                SignalHeadState(
                    head_id="ped-1", phase=SignalPhase.PEDESTRIAN, confirmed_color=SignalColor.RED
                ),
                SignalHeadState(
                    head_id="veh-1", phase=SignalPhase.VEHICLE, confirmed_color=SignalColor.GREEN
                ),
            ],
        )
        primary = snapshot.primary_vehicle_signal()
        assert primary is not None
        assert primary.head_id == "veh-1"
        assert primary.confirmed_color == SignalColor.GREEN

    def test_signal_scene_snapshot_primary_vehicle_is_none_without_vehicle_phase(self) -> None:
        snapshot = SignalSceneSnapshot(
            frame_index=10,
            timestamp=_TS,
            head_states=[
                SignalHeadState(
                    head_id="ped-1", phase=SignalPhase.PEDESTRIAN, confirmed_color=SignalColor.RED
                ),
                SignalHeadState(
                    head_id="unk-1", phase=SignalPhase.UNKNOWN, confirmed_color=SignalColor.GREEN
                ),
            ],
        )
        assert snapshot.primary_vehicle_signal() is None

    def test_signal_scene_snapshot_by_head_id(self) -> None:
        snapshot = SignalSceneSnapshot(
            frame_index=10,
            timestamp=_TS,
            head_states=[
                SignalHeadState(head_id="tl-1", confirmed_color=SignalColor.RED),
                SignalHeadState(head_id="tl-2", confirmed_color=SignalColor.GREEN),
            ],
        )
        assert snapshot.by_head_id("tl-2") is not None
        assert snapshot.by_head_id("tl-2").confirmed_color == SignalColor.GREEN
        assert snapshot.by_head_id("nonexistent") is None


# ===========================================================================
# Pipeline integration
# ===========================================================================


class TestPipelineSignalIntegration:
    """Verify signal classification is wired into FramePipeline end-to-end."""

    def test_pipeline_produces_signal_snapshot(self) -> None:
        from services.streams.pipeline import FramePipeline
        from services.streams.schemas import PipelineFlags
        from services.vision.config import VisionSettings
        from services.vision.interface import Detector

        stream_id = uuid.uuid4()
        camera_id = uuid.uuid4()

        class _TlDetector(Detector):
            def __init__(self, _s: VisionSettings) -> None:
                pass

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
                return DetectionResult(
                    detections=[
                        Detection(
                            class_name="traffic light",
                            category=ObjectCategory.TRAFFIC_LIGHT,
                            class_id=9,
                            confidence=0.9,
                            bbox=BBox(x1=100, y1=50, x2=130, y2=110),
                            frame_index=frame_index,
                            timestamp=timestamp,
                        )
                    ],
                    frame_index=frame_index,
                    timestamp=timestamp,
                    source_width=640,
                    source_height=480,
                    inference_ms=5.0,
                )

        flags = PipelineFlags(
            detection=True,
            tracking=False,
            signals=True,
            ocr=False,
            rules=False,
        )
        pipeline = FramePipeline(
            flags,
            signal_settings=SignalSettings(smoothing_window=1, transition_threshold=1),
            signal_head_configs=[_vehicle_head_config()],
            detector_factory=lambda: _TlDetector(VisionSettings()),
        )

        # Frame with red light in the bbox region
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[50:110, 100:130] = (0, 0, 255)

        with pipeline:
            result = pipeline.process_frame(
                frame,
                frame_index=0,
                source_id="demo-source",
                stream_id=stream_id,
                camera_id=camera_id,
                timestamp=_TS,
            )

        assert result.signal_snapshot is not None
        assert result.signal_snapshot.source_id == "demo-source"
        assert result.signal_snapshot.stream_id == stream_id
        assert result.signal_snapshot.camera_id == camera_id
        assert result.signal_snapshot.observation_count == 1
        assert result.signal_snapshot.observations[0].classification.color == SignalColor.RED
        assert result.signal_snapshot.observations[0].source_id == "demo-source"
        assert result.signal_snapshot.observations[0].stream_id == stream_id
        assert result.signal_snapshot.observations[0].camera_id == camera_id
        assert result.scene_context is not None
        assert result.scene_context.traffic_light_state == TrafficLightState.RED
        assert result.scene_context.vehicle_signal_state == TrafficLightState.RED
        assert result.scene_context.pedestrian_signal_state == TrafficLightState.UNKNOWN
        assert len(result.scene_context.signal_states) == 1
        assert result.scene_context.signal_states[0].state == TrafficLightState.RED
        assert result.scene_context.signal_states[0].stop_line_id == "sl-1"
        assert result.event_batch is not None
        assert result.event_batch.signal_snapshot is not None
        assert result.event_batch.summary.signal_observations == 1

    def test_pipeline_no_signals_when_disabled(self) -> None:
        from services.streams.pipeline import FramePipeline
        from services.streams.schemas import PipelineFlags

        flags = PipelineFlags(
            detection=False,
            tracking=False,
            signals=False,
            ocr=False,
            rules=False,
        )
        pipeline = FramePipeline(flags)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        with pipeline:
            result = pipeline.process_frame(frame, frame_index=0, timestamp=_TS)

        assert result.signal_snapshot is None
        assert result.scene_context is None
