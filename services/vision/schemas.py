"""Typed result schemas for vision inference output.

These schemas are the contract between the vision service and all downstream
consumers (tracking, OCR, rules engine, API persistence layer).  They are
intentionally decoupled from SQLAlchemy models and API response schemas so
that the vision service remains a standalone, importable library.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field


class ObjectCategory(StrEnum):
    """High-level semantic category for detected objects.

    The vision service maps raw COCO (or custom) class names into these
    categories so that downstream consumers never need to know the mapping.
    """

    VEHICLE = "vehicle"
    PERSON = "person"
    TRAFFIC_LIGHT = "traffic_light"
    PLATE = "plate"
    OTHER = "other"


# Map well-known COCO names → ObjectCategory.
COCO_CATEGORY_MAP: dict[str, ObjectCategory] = {
    "person": ObjectCategory.PERSON,
    "bicycle": ObjectCategory.VEHICLE,
    "car": ObjectCategory.VEHICLE,
    "motorcycle": ObjectCategory.VEHICLE,
    "bus": ObjectCategory.VEHICLE,
    "train": ObjectCategory.VEHICLE,
    "truck": ObjectCategory.VEHICLE,
    "traffic light": ObjectCategory.TRAFFIC_LIGHT,
}


class BBox(BaseModel):
    """Axis-aligned bounding box in pixel coordinates (x1 y1 x2 y2)."""

    model_config = ConfigDict(frozen=True)

    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)

    def to_xyxy(self) -> tuple[float, float, float, float]:
        return (self.x1, self.y1, self.x2, self.y2)

    def to_dict(self) -> dict[str, float]:
        """Flat dict matching the API's ``DetectionEventBase.bbox`` shape."""
        return {"x1": self.x1, "y1": self.y1, "x2": self.x2, "y2": self.y2}


class Detection(BaseModel):
    """Single object detection produced by a ``Detector`` backend."""

    model_config = ConfigDict(frozen=True)

    class_name: str
    category: ObjectCategory
    class_id: int | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    bbox: BBox
    track_id: str | None = None
    frame_index: int | None = None
    timestamp: datetime | None = None

    def to_event_dict(self) -> dict:
        """Return a dict compatible with ``DetectionEventCreate`` fields."""
        return {
            "object_class": self.class_name,
            "confidence": self.confidence,
            "bbox": self.bbox.to_dict(),
            "track_id": self.track_id,
            "frame_index": self.frame_index,
            "occurred_at": self.timestamp,
        }

    def to_tracking_dict(self) -> dict[str, Any]:
        """Return a backend-neutral payload for tracking and rule engines."""
        return {
            "bbox": self.bbox.to_dict(),
            "confidence": self.confidence,
            "class_id": self.class_id,
            "class_name": self.class_name,
            "category": self.category.value,
            "track_id": self.track_id,
            "frame_index": self.frame_index,
            "timestamp": self.timestamp,
        }


class DetectionResult(BaseModel):
    """Batch result for a single frame (or image) processed by a detector."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    detections: list[Detection] = Field(default_factory=list)
    frame_index: int | None = None
    timestamp: datetime | None = None
    source_width: int | None = None
    source_height: int | None = None
    inference_ms: float | None = None

    @property
    def count(self) -> int:
        return len(self.detections)

    def by_category(self, category: ObjectCategory) -> list[Detection]:
        return [d for d in self.detections if d.category == category]

    @property
    def vehicles(self) -> list[Detection]:
        return self.by_category(ObjectCategory.VEHICLE)

    @property
    def people(self) -> list[Detection]:
        return self.by_category(ObjectCategory.PERSON)

    @property
    def traffic_lights(self) -> list[Detection]:
        return self.by_category(ObjectCategory.TRAFFIC_LIGHT)

    @property
    def plates(self) -> list[Detection]:
        return self.by_category(ObjectCategory.PLATE)

    def as_numpy_xyxy(self) -> np.ndarray:
        """Return (N, 4) float32 array of bounding boxes for supervision."""
        if not self.detections:
            return np.empty((0, 4), dtype=np.float32)
        return np.array(
            [d.bbox.to_xyxy() for d in self.detections], dtype=np.float32
        )

    def as_numpy_confidence(self) -> np.ndarray:
        """Return (N,) float32 confidence array."""
        if not self.detections:
            return np.empty(0, dtype=np.float32)
        return np.array(
            [d.confidence for d in self.detections], dtype=np.float32
        )

    def as_numpy_class_id(self) -> np.ndarray:
        """Return (N,) int32 class-id array, using ``-1`` for unknown ids."""
        if not self.detections:
            return np.empty(0, dtype=np.int32)
        return np.array(
            [d.class_id if d.class_id is not None else -1 for d in self.detections],
            dtype=np.int32,
        )

    def as_class_names(self) -> list[str]:
        """Return class names in detection order."""
        return [d.class_name for d in self.detections]

    def as_tracking_payload(self) -> list[dict[str, Any]]:
        """Return per-detection payloads suitable for trackers and rules."""
        return [d.to_tracking_dict() for d in self.detections]

    def to_supervision(self) -> Any:
        """Return a ``supervision.Detections`` object with rich metadata."""

        import supervision as sv

        return sv.Detections(
            xyxy=self.as_numpy_xyxy(),
            confidence=self.as_numpy_confidence(),
            class_id=self.as_numpy_class_id(),
            data={
                "class_name": np.array(self.as_class_names(), dtype=object),
                "category": np.array([d.category.value for d in self.detections], dtype=object),
                "track_id": np.array([d.track_id for d in self.detections], dtype=object),
            },
        )
