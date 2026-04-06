"""Tests for the PlateDetector backend.

Validates that the heuristic plate-detection backend:
- conforms to the Detector ABC,
- returns DetectionResult with category=PLATE detections,
- correctly handles edge cases (blank images, tiny images),
- is registered and discoverable through the DetectorRegistry.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

import cv2
import numpy as np
import pytest

from services.vision.config import VisionSettings
from services.vision.interface import Detector, DetectorRegistry
from services.vision.schemas import DetectionResult, ObjectCategory


def _make_plate_like_image(width: int = 640, height: int = 480) -> np.ndarray:
    """Synthesise an image with a bright rectangle that looks plate-like."""
    img = np.zeros((height, width, 3), dtype=np.uint8)

    # Draw a bright rectangle with plate-like aspect ratio (~3:1).
    plate_w, plate_h = 120, 36
    px, py = width // 2 - plate_w // 2, height // 2 - plate_h // 2
    cv2.rectangle(img, (px, py), (px + plate_w, py + plate_h), (255, 255, 255), -1)

    # Add some internal edges to mimic text (horizontal lines).
    for row_offset in range(5, plate_h - 5, 6):
        y = py + row_offset
        cv2.line(img, (px + 8, y), (px + plate_w - 8, y), (0, 0, 0), 1)

    # Add a contrasting border.
    cv2.rectangle(img, (px - 2, py - 2), (px + plate_w + 2, py + plate_h + 2), (80, 80, 80), 2)

    return img


class TestPlateDetectorInterface:
    """Plate detector correctly implements the ABC."""

    def test_is_detector_subclass(self) -> None:
        from services.vision.backends.plate_detector import PlateDetector

        assert issubclass(PlateDetector, Detector)

    def test_context_manager_protocol(self) -> None:
        from services.vision.backends.plate_detector import PlateDetector

        settings = VisionSettings()
        with PlateDetector(settings) as detector:
            assert isinstance(detector, Detector)

    def test_registry_lazy_loading(self) -> None:
        sys.modules.pop("services.vision.backends.plate_detector", None)
        assert "plate" in DetectorRegistry.available()

    def test_registry_create(self) -> None:
        settings = VisionSettings()
        detector = DetectorRegistry.create("plate", settings)
        assert isinstance(detector, Detector)


class TestPlateDetectorInference:
    """Core detection behaviour."""

    def test_returns_detection_result(self) -> None:
        from services.vision.backends.plate_detector import PlateDetector

        img = _make_plate_like_image()
        detector = PlateDetector(VisionSettings())
        result = detector.detect(img, frame_index=0)

        assert isinstance(result, DetectionResult)
        assert result.frame_index == 0
        assert result.source_width == 640
        assert result.source_height == 480
        assert result.inference_ms is not None

    def test_detections_have_plate_category(self) -> None:
        from services.vision.backends.plate_detector import PlateDetector

        img = _make_plate_like_image()
        detector = PlateDetector(VisionSettings(confidence_threshold=0.0))
        result = detector.detect(img, frame_index=1)

        for det in result.detections:
            assert det.category == ObjectCategory.PLATE
            assert det.class_name == "license_plate"

    def test_blank_image_returns_empty(self) -> None:
        from services.vision.backends.plate_detector import PlateDetector

        blank = np.zeros((480, 640, 3), dtype=np.uint8)
        detector = PlateDetector(VisionSettings())
        result = detector.detect(blank)
        assert result.count == 0

    def test_respects_confidence_override(self) -> None:
        from services.vision.backends.plate_detector import PlateDetector

        img = _make_plate_like_image()
        detector = PlateDetector(VisionSettings())

        # Very high threshold → likely no candidates pass.
        high = detector.detect(img, confidence=0.99)
        # Very low threshold → more candidates.
        low = detector.detect(img, confidence=0.0)

        assert low.count >= high.count

    def test_timestamp_forwarded(self) -> None:
        from services.vision.backends.plate_detector import PlateDetector

        ts = datetime(2026, 4, 6, 12, 0, 0, tzinfo=timezone.utc)
        detector = PlateDetector(VisionSettings())
        result = detector.detect(np.zeros((100, 100, 3), dtype=np.uint8), timestamp=ts)
        assert result.timestamp == ts

    def test_small_image_does_not_crash(self) -> None:
        from services.vision.backends.plate_detector import PlateDetector

        tiny = np.zeros((10, 10, 3), dtype=np.uint8)
        detector = PlateDetector(VisionSettings())
        result = detector.detect(tiny)
        assert isinstance(result, DetectionResult)

    def test_all_detections_have_valid_bbox(self) -> None:
        from services.vision.backends.plate_detector import PlateDetector

        img = _make_plate_like_image()
        detector = PlateDetector(VisionSettings(confidence_threshold=0.0))
        result = detector.detect(img)

        for det in result.detections:
            assert det.bbox.x2 > det.bbox.x1
            assert det.bbox.y2 > det.bbox.y1
            assert det.bbox.area > 0
