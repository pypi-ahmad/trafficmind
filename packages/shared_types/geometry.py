"""Geometry and classification primitives shared across all services.

These are the most widely imported types in the codebase — used by vision,
tracking, OCR, rules, signals, streams, flow, motion, evaluation, and dwell.
"""

from __future__ import annotations

from enum import StrEnum

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


class Point2D(BaseModel):
    """2D point in image pixel coordinates."""

    model_config = ConfigDict(frozen=True)

    x: float
    y: float

    def as_tuple(self) -> tuple[float, float]:
        return (self.x, self.y)


# ---------------------------------------------------------------------------
# Composite geometry primitives
# ---------------------------------------------------------------------------


class LineSegment(BaseModel):
    """Two-point line segment for stop-line crossings, counting lines, etc.

    Previously defined independently in ``services.tracking.schemas`` and
    (as ``LineGeometry``) in ``services.rules.schemas``.  The optional
    ``name`` field is preserved so that tracking and flow consumers can
    label geometry without a separate wrapper.
    """

    model_config = ConfigDict(frozen=True)

    start: Point2D
    end: Point2D
    name: str | None = None


class PolygonZone(BaseModel):
    """Closed polygon zone for entry/exit checks, lane geometry, etc.

    Previously defined independently in ``services.tracking.schemas`` and
    (as ``PolygonGeometry``) in ``services.rules.schemas``.
    """

    model_config = ConfigDict(frozen=True)

    name: str | None = None
    points: list[Point2D] = Field(min_length=3)
