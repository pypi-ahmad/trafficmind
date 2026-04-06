"""Dedicated plate detector backend — zero heavy dependencies.

This backend implements the ``Detector`` protocol with a focused pipeline
for license-plate detection.  It accepts a BGR/RGB numpy image, applies
lightweight spatial heuristics to candidate vehicle-like regions, and
emits ``Detection`` objects with ``category=PLATE``.

The algorithm is intentionally simple so it can serve as:

* a **second proof** that the ``Detector`` abstraction is sound,
* a **placeholder** until a real ANPR model (WPOD-NET, YOLO-plate, etc.)
  is trained and slotted in through the same registry, and
* a zero-external-dependency alternative for integration tests and
  offline pipelines where GPU inference is unnecessary.

Detection strategy (per-frame):
    1. Convert to grayscale, apply bilateral filter (noise reduction).
    2. Canny edge detection → dilate → find contours.
    3. Approximate each contour to a polygon; keep quadrilaterals whose
       aspect ratio is plate-like (2:1 – 6:1) and whose area is within
       a configurable fraction of the source image.
    4. Score each candidate by edge density inside the bounding rect.
    5. Return the top-N candidates as ``Detection(category=PLATE)``.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import cv2
import numpy as np

from services.vision.config import VisionSettings
from services.vision.interface import Detector
from services.vision.schemas import BBox, Detection, DetectionResult, ObjectCategory

logger = logging.getLogger(__name__)

# Plate aspect-ratio bounds (width / height).
_MIN_ASPECT = 1.8
_MAX_ASPECT = 6.5

# Candidate area as fraction of image area.
_MIN_AREA_FRACTION = 0.0005
_MAX_AREA_FRACTION = 0.05

# Maximum candidates returned per frame.
_MAX_CANDIDATES = 10


def _edge_density(gray: np.ndarray, edges: np.ndarray, x: int, y: int, w: int, h: int) -> float:
    """Fraction of edge pixels inside a bounding rectangle."""
    roi = edges[y : y + h, x : x + w]
    if roi.size == 0:
        return 0.0
    return float(np.count_nonzero(roi)) / roi.size


class PlateDetector(Detector):
    """Heuristic plate-region detector — no ML model required.

    Suitable as a lightweight placeholder in pipelines where the full
    ANPR model is unavailable, or as a fast pre-filter before OCR.
    """

    def __init__(self, settings: VisionSettings) -> None:
        self._settings = settings

    def detect(
        self,
        image: np.ndarray,
        *,
        frame_index: int | None = None,
        timestamp: datetime | None = None,
        confidence: float | None = None,
    ) -> DetectionResult:
        capture_ts = timestamp or datetime.now(timezone.utc)
        height, width = image.shape[:2]
        image_area = width * height

        started = time.perf_counter()

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        filtered = cv2.bilateralFilter(gray, 11, 17, 17)
        edges = cv2.Canny(filtered, 30, 200)

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        dilated = cv2.dilate(edges, kernel, iterations=1)

        contours, _ = cv2.findContours(dilated, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

        candidates: list[tuple[float, BBox]] = []
        for contour in contours:
            perimeter = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.018 * perimeter, True)

            if len(approx) < 4 or len(approx) > 6:
                continue

            x, y, w, h = cv2.boundingRect(approx)
            if h == 0:
                continue

            aspect = w / h
            area = w * h
            area_frac = area / image_area

            if not (_MIN_ASPECT <= aspect <= _MAX_ASPECT):
                continue
            if not (_MIN_AREA_FRACTION <= area_frac <= _MAX_AREA_FRACTION):
                continue

            score = _edge_density(gray, edges, x, y, w, h)
            candidates.append((score, BBox(x1=float(x), y1=float(y), x2=float(x + w), y2=float(y + h))))

        candidates.sort(key=lambda pair: pair[0], reverse=True)
        top = candidates[:_MAX_CANDIDATES]

        elapsed_ms = (time.perf_counter() - started) * 1000

        min_conf = confidence if confidence is not None else self._settings.confidence_threshold
        detections: list[Detection] = []
        for score, bbox in top:
            if score < min_conf:
                continue
            detections.append(
                Detection(
                    class_name="license_plate",
                    category=ObjectCategory.PLATE,
                    class_id=None,
                    confidence=round(min(score, 1.0), 4),
                    bbox=bbox,
                    track_id=None,
                    frame_index=frame_index,
                    timestamp=capture_ts,
                )
            )

        return DetectionResult(
            detections=detections,
            frame_index=frame_index,
            timestamp=capture_ts,
            source_width=width,
            source_height=height,
            inference_ms=round(elapsed_ms, 2),
        )
