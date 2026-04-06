"""Unit tests for the vision service foundation.

Tests are split into:
- Schema / data-model tests (pure, fast, no GPU)
- Interface / registry tests (pure, fast)
- YOLO backend integration tests (requires model + GPU, gated by marker)
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

import numpy as np
import pytest

from services.vision.config import VisionSettings
from services.vision.interface import Detector, DetectorRegistry
from services.vision.schemas import (
    BBox,
    COCO_CATEGORY_MAP,
    Detection,
    DetectionResult,
    ObjectCategory,
)


# ── Schema tests ────────────────────────────────────────────────────────────


class TestBBox:
    def test_basic_properties(self) -> None:
        box = BBox(x1=10, y1=20, x2=110, y2=70)
        assert box.width == 100
        assert box.height == 50
        assert box.area == 5000
        assert box.center == (60.0, 45.0)
        assert box.to_xyxy() == (10, 20, 110, 70)

    def test_to_dict(self) -> None:
        box = BBox(x1=1.5, y1=2.5, x2=3.5, y2=4.5)
        assert box.to_dict() == {"x1": 1.5, "y1": 2.5, "x2": 3.5, "y2": 4.5}

    def test_degenerate_box_area(self) -> None:
        box = BBox(x1=50, y1=50, x2=30, y2=40)
        assert box.area == 0.0  # clamps negative


class TestDetection:
    def test_to_event_dict(self) -> None:
        ts = datetime(2026, 4, 4, 12, 0, 0, tzinfo=timezone.utc)
        det = Detection(
            class_name="car",
            category=ObjectCategory.VEHICLE,
            class_id=2,
            confidence=0.92,
            bbox=BBox(x1=10, y1=20, x2=200, y2=150),
            track_id="trk-1",
            frame_index=42,
            timestamp=ts,
        )
        event = det.to_event_dict()
        assert event["object_class"] == "car"
        assert event["confidence"] == 0.92
        assert event["bbox"]["x1"] == 10
        assert event["track_id"] == "trk-1"
        assert event["frame_index"] == 42
        assert event["occurred_at"] == ts

    def test_to_tracking_dict(self) -> None:
        ts = datetime(2026, 4, 4, 12, 0, 0, tzinfo=timezone.utc)
        det = Detection(
            class_name="traffic light",
            category=ObjectCategory.TRAFFIC_LIGHT,
            class_id=9,
            confidence=0.88,
            bbox=BBox(x1=5, y1=6, x2=50, y2=60),
            track_id="light-1",
            frame_index=7,
            timestamp=ts,
        )

        payload = det.to_tracking_dict()
        assert payload["class_name"] == "traffic light"
        assert payload["class_id"] == 9
        assert payload["category"] == "traffic_light"
        assert payload["track_id"] == "light-1"
        assert payload["timestamp"] == ts


class TestDetectionResult:
    def _make_result(self) -> DetectionResult:
        return DetectionResult(
            detections=[
                Detection(
                    class_name="car",
                    category=ObjectCategory.VEHICLE,
                    class_id=2,
                    confidence=0.9,
                    bbox=BBox(x1=0, y1=0, x2=100, y2=100),
                ),
                Detection(
                    class_name="person",
                    category=ObjectCategory.PERSON,
                    class_id=0,
                    confidence=0.85,
                    bbox=BBox(x1=200, y1=200, x2=250, y2=350),
                ),
                Detection(
                    class_name="traffic light",
                    category=ObjectCategory.TRAFFIC_LIGHT,
                    class_id=9,
                    confidence=0.7,
                    bbox=BBox(x1=300, y1=10, x2=330, y2=60),
                ),
                Detection(
                    class_name="truck",
                    category=ObjectCategory.VEHICLE,
                    class_id=7,
                    confidence=0.8,
                    bbox=BBox(x1=400, y1=50, x2=600, y2=200),
                ),
            ],
            frame_index=0,
            source_width=1920,
            source_height=1080,
            inference_ms=12.5,
        )

    def test_count_and_filters(self) -> None:
        r = self._make_result()
        assert r.count == 4
        assert len(r.vehicles) == 2
        assert len(r.people) == 1
        assert len(r.traffic_lights) == 1
        assert len(r.plates) == 0

    def test_as_numpy_xyxy(self) -> None:
        r = self._make_result()
        arr = r.as_numpy_xyxy()
        assert arr.shape == (4, 4)
        assert arr.dtype == np.float32

    def test_as_numpy_confidence(self) -> None:
        r = self._make_result()
        arr = r.as_numpy_confidence()
        assert arr.shape == (4,)
        assert arr.dtype == np.float32

    def test_as_numpy_class_id(self) -> None:
        r = self._make_result()
        arr = r.as_numpy_class_id()
        assert arr.shape == (4,)
        assert arr.dtype == np.int32
        assert arr.tolist() == [2, 0, 9, 7]

    def test_as_tracking_payload(self) -> None:
        r = self._make_result()
        payload = r.as_tracking_payload()
        assert len(payload) == 4
        assert payload[0]["class_name"] == "car"
        assert payload[0]["category"] == "vehicle"

    def test_to_supervision(self) -> None:
        r = self._make_result()
        detections = r.to_supervision()
        assert len(detections) == 4
        assert detections.class_id.tolist() == [2, 0, 9, 7]
        assert detections.data["class_name"].tolist() == [
            "car",
            "person",
            "traffic light",
            "truck",
        ]

    def test_empty_result(self) -> None:
        r = DetectionResult()
        assert r.count == 0
        assert r.as_numpy_xyxy().shape == (0, 4)
        assert r.as_numpy_confidence().shape == (0,)


class TestCOCOCategoryMap:
    def test_known_mappings(self) -> None:
        assert COCO_CATEGORY_MAP["car"] == ObjectCategory.VEHICLE
        assert COCO_CATEGORY_MAP["person"] == ObjectCategory.PERSON
        assert COCO_CATEGORY_MAP["traffic light"] == ObjectCategory.TRAFFIC_LIGHT
        assert COCO_CATEGORY_MAP["truck"] == ObjectCategory.VEHICLE
        assert COCO_CATEGORY_MAP["bus"] == ObjectCategory.VEHICLE

    def test_unmapped_falls_to_other(self) -> None:
        assert COCO_CATEGORY_MAP.get("dog", ObjectCategory.OTHER) == ObjectCategory.OTHER


# ── Interface / registry tests ──────────────────────────────────────────────


class _DummyDetector(Detector):
    """Minimal concrete detector for registry tests."""

    def __init__(self, settings: VisionSettings) -> None:
        self.settings = settings
        self.loaded = False

    def load_model(self) -> None:
        self.loaded = True

    def detect(
        self,
        image: np.ndarray,
        *,
        frame_index: int | None = None,
        timestamp: datetime | None = None,
        confidence: float | None = None,
    ) -> DetectionResult:
        return DetectionResult(frame_index=frame_index, timestamp=timestamp)


class TestDetectorRegistry:
    def setup_method(self) -> None:
        # Snapshot and restore to avoid cross-test pollution.
        self._original = dict(DetectorRegistry._backends)
        self._original_lazy = dict(DetectorRegistry._lazy_backends)

    def teardown_method(self) -> None:
        DetectorRegistry._backends = self._original
        DetectorRegistry._lazy_backends = self._original_lazy

    def test_register_and_create(self) -> None:
        DetectorRegistry.register("dummy", _DummyDetector)
        assert "dummy" in DetectorRegistry.available()
        settings = VisionSettings()
        det = DetectorRegistry.create("dummy", settings)
        assert isinstance(det, _DummyDetector)

    def test_unknown_backend_raises(self) -> None:
        with pytest.raises(KeyError, match="Unknown detector backend"):
            DetectorRegistry.create("nonexistent", VisionSettings())

    def test_context_manager(self) -> None:
        settings = VisionSettings()
        det = _DummyDetector(settings)
        with det:
            assert det.loaded

    def test_register_lazy_and_create(self) -> None:
        DetectorRegistry.register_lazy("lazy-dummy", f"{__name__}:_DummyDetector")
        det = DetectorRegistry.create("lazy-dummy", VisionSettings())
        assert isinstance(det, _DummyDetector)

    def test_builtin_yolo_is_advertised_without_import_side_effect(self) -> None:
        sys.modules.pop("services.vision.backends.yolo_detector", None)
        assert "yolo" in DetectorRegistry.available()


# ── Config tests ────────────────────────────────────────────────────────────


class TestVisionSettings:
    def test_defaults(self) -> None:
        s = VisionSettings()
        assert s.confidence_threshold == 0.25
        assert s.iou_threshold == 0.45
        assert s.image_size == 640
        assert s.max_detections == 300
        assert s.half_precision is True

    def test_device_resolution(self) -> None:
        s = VisionSettings(device="cpu")
        assert s.resolve_device() == "cpu"

    def test_auto_device(self) -> None:
        s = VisionSettings(device="auto")
        resolved = s.resolve_device()
        assert resolved in ("cpu", "cuda")


# ── YOLO integration test (gated) ──────────────────────────────────────────


@pytest.mark.integration
def test_yolo_real_inference() -> None:
    """Load the real YOLO model, run on a synthetic image, verify result shape.

    This test requires:
    - models/yolo26x.pt to exist
    - ultralytics + torch installed
    - ~2-5 seconds on GPU, ~10s on CPU
    """
    from services.vision.backends.yolo_detector import YoloDetector

    settings = VisionSettings()
    if not settings.yolo_model_path.exists():
        pytest.skip(f"Model not found at {settings.yolo_model_path}")

    ts = datetime(2026, 4, 4, 12, 0, 0, tzinfo=timezone.utc)

    with YoloDetector(settings) as detector:
        # Synthetic 640x480 random image — won't have meaningful detections
        # but validates the full pipeline runs without error.
        image = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        result = detector.detect(image, frame_index=0, timestamp=ts)

        assert isinstance(result, DetectionResult)
        assert result.frame_index == 0
        assert result.timestamp == ts
        assert result.source_width == 640
        assert result.source_height == 480
        assert result.inference_ms is not None
        assert result.inference_ms > 0
        # All detections must have valid schema fields.
        for d in result.detections:
            assert d.timestamp == ts
            assert d.confidence >= 0
            assert d.bbox.area >= 0
            assert d.category in ObjectCategory
