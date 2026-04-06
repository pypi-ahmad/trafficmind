"""Ultralytics YOLO detection backend — real inference.

This backend loads a YOLO v8/v10/v11/YOLO26 model via the ``ultralytics``
library and runs actual GPU/CPU inference. It maps COCO (or custom) class
names into the vision service's ``ObjectCategory`` taxonomy so downstream
consumers (tracking, OCR, rules) get a uniform schema.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import numpy as np
from ultralytics import YOLO

from services.vision.config import VisionSettings
from services.vision.interface import Detector
from services.vision.schemas import (
    BBox,
    COCO_CATEGORY_MAP,
    Detection,
    DetectionResult,
    ObjectCategory,
)

logger = logging.getLogger(__name__)


class YoloDetector(Detector):
    """Real Ultralytics YOLO inference backend."""

    def __init__(self, settings: VisionSettings) -> None:
        self._settings = settings
        self._model: YOLO | None = None
        self._device = settings.resolve_device()

    @property
    def _use_half_precision(self) -> bool:
        return self._settings.half_precision and self._device.startswith("cuda")

    def _resolve_class_name(self, class_id: int) -> str:
        if self._model is None:
            msg = "Model not loaded."
            raise RuntimeError(msg)

        names = self._model.names
        if isinstance(names, dict):
            return str(names.get(class_id, f"class_{class_id}"))
        if 0 <= class_id < len(names):
            return str(names[class_id])
        return f"class_{class_id}"

    def load_model(self) -> None:
        model_path = self._settings.yolo_model_path
        if not model_path.exists():
            msg = f"YOLO model not found at {model_path}"
            raise FileNotFoundError(msg)

        logger.info("Loading YOLO model from %s on device=%s", model_path, self._device)
        self._model = YOLO(str(model_path))

        dummy = np.zeros((640, 640, 3), dtype=np.uint8)
        self._model.predict(
            dummy,
            device=self._device,
            imgsz=self._settings.image_size,
            half=self._use_half_precision,
            verbose=False,
        )
        logger.info("YOLO model loaded and warmed up (%d classes)", len(self._model.names))

    def unload(self) -> None:
        self._model = None
        logger.info("YOLO model unloaded")

    def detect(
        self,
        image: np.ndarray,
        *,
        frame_index: int | None = None,
        timestamp: datetime | None = None,
        confidence: float | None = None,
    ) -> DetectionResult:
        if self._model is None:
            msg = "Model not loaded. Call load_model() or use as context manager."
            raise RuntimeError(msg)

        conf = confidence if confidence is not None else self._settings.confidence_threshold
        capture_timestamp = timestamp or datetime.now(timezone.utc)
        height, width = image.shape[:2]

        started_at = time.perf_counter()
        results = self._model.predict(
            image,
            device=self._device,
            imgsz=self._settings.image_size,
            conf=conf,
            iou=self._settings.iou_threshold,
            half=self._use_half_precision,
            max_det=self._settings.max_detections,
            verbose=False,
        )
        elapsed_ms = (time.perf_counter() - started_at) * 1000

        detections: list[Detection] = []
        for result in results:
            boxes = result.boxes
            if boxes is None or len(boxes) == 0:
                continue
            for index in range(len(boxes)):
                class_id = int(boxes.cls[index].item())
                class_name = self._resolve_class_name(class_id)
                category = COCO_CATEGORY_MAP.get(class_name, ObjectCategory.OTHER)
                x1, y1, x2, y2 = boxes.xyxy[index].tolist()

                detections.append(
                    Detection(
                        class_name=class_name,
                        category=category,
                        class_id=class_id,
                        confidence=round(float(boxes.conf[index].item()), 4),
                        bbox=BBox(x1=x1, y1=y1, x2=x2, y2=y2),
                        track_id=None,
                        frame_index=frame_index,
                        timestamp=capture_timestamp,
                    )
                )

        return DetectionResult(
            detections=detections,
            frame_index=frame_index,
            timestamp=capture_timestamp,
            source_width=width,
            source_height=height,
            inference_ms=round(elapsed_ms, 2),
        )
