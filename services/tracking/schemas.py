"""Typed schemas for the tracking service.

``Point2D`` is canonical in ``packages.shared_types`` and re-exported here
for backward compatibility.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from packages.shared_types.geometry import BBox, ObjectCategory, Point2D

__all__ = [  # re-export shared primitives
    "BBox",
    "ObjectCategory",
    "Point2D",
]


class TrackLifecycleStatus(StrEnum):
    ACTIVE = "active"
    LOST = "lost"
    REMOVED = "removed"


class CardinalDirection(StrEnum):
    STATIONARY = "stationary"
    NORTH = "north"
    NORTH_EAST = "north_east"
    EAST = "east"
    SOUTH_EAST = "south_east"
    SOUTH = "south"
    SOUTH_WEST = "south_west"
    WEST = "west"
    NORTH_WEST = "north_west"


class LineCrossingDirection(StrEnum):
    NEGATIVE_TO_POSITIVE = "negative_to_positive"
    POSITIVE_TO_NEGATIVE = "positive_to_negative"


class ZoneTransitionType(StrEnum):
    ENTERED = "entered"
    EXITED = "exited"
    INSIDE = "inside"
    OUTSIDE = "outside"


# Point2D imported from packages.shared_types — do NOT redefine here.


class TrajectoryPoint(BaseModel):
    """A track point with frame and timestamp context."""

    model_config = ConfigDict(frozen=True)

    point: Point2D
    frame_index: int | None = None
    timestamp: datetime | None = None


class MotionVector(BaseModel):
    """Estimated movement vector from recent trajectory history."""

    model_config = ConfigDict(frozen=True)

    dx: float
    dy: float
    magnitude: float
    bearing_degrees: float | None = None
    direction: CardinalDirection = CardinalDirection.STATIONARY


class LineSegment(BaseModel):
    """Line segment used for rule checks like stop-line crossings."""

    model_config = ConfigDict(frozen=True)

    start: Point2D
    end: Point2D
    name: str | None = None


class PolygonZone(BaseModel):
    """Polygon zone used for entry/exit checks."""

    model_config = ConfigDict(frozen=True)

    name: str | None = None
    points: list[Point2D] = Field(min_length=3)


class LineCrossingCheck(BaseModel):
    """Result of comparing track motion against a line segment."""

    crossed: bool = False
    direction: LineCrossingDirection | None = None


class ZoneTransition(BaseModel):
    """Result of comparing motion against a polygon zone."""

    transition: ZoneTransitionType
    was_inside: bool
    is_inside: bool


class TrackedObject(BaseModel):
    """Persistent tracked object built from detector outputs across frames."""

    track_id: str
    class_name: str
    category: ObjectCategory
    bbox: BBox
    confidence: float = Field(ge=0.0, le=1.0)
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    frame_count: int = Field(default=0, ge=0)
    trajectory: list[TrajectoryPoint] = Field(default_factory=list)
    class_id: int | None = None
    first_seen_frame: int | None = None
    last_seen_frame: int | None = None
    missed_frames: int = Field(default=0, ge=0)
    status: TrackLifecycleStatus = TrackLifecycleStatus.ACTIVE
    direction: MotionVector | None = None

    @property
    def centroid(self) -> Point2D:
        if self.trajectory:
            return self.trajectory[-1].point
        x, y = self.bbox.center
        return Point2D(x=x, y=y)

    @property
    def duration(self) -> timedelta | None:
        """Elapsed time between first and last observation."""
        if self.first_seen_at is not None and self.last_seen_at is not None:
            return self.last_seen_at - self.first_seen_at
        return None

    @property
    def speed_px_per_frame(self) -> float:
        """Estimated speed in pixels per frame from latest motion vector."""
        if self.direction is None or self.frame_count < 2:
            return 0.0
        return self.direction.magnitude

    def to_event_dict(self) -> dict[str, Any]:
        """Flat dict usable by violations and the API persistence layer."""
        c = self.centroid
        return {
            "track_id": self.track_id,
            "class_name": self.class_name,
            "category": self.category.value,
            "class_id": self.class_id,
            "confidence": self.confidence,
            "bbox": self.bbox.to_dict(),
            "centroid": {"x": c.x, "y": c.y},
            "first_seen_at": self.first_seen_at,
            "last_seen_at": self.last_seen_at,
            "first_seen_frame": self.first_seen_frame,
            "last_seen_frame": self.last_seen_frame,
            "frame_count": self.frame_count,
            "status": self.status.value,
            "direction": self.direction.direction.value if self.direction else None,
            "speed_px_per_frame": self.speed_px_per_frame,
            "duration_seconds": self.duration.total_seconds() if self.duration else None,
        }


class TrackingResult(BaseModel):
    """Result of a tracker update for one frame's detections."""

    tracks: list[TrackedObject] = Field(default_factory=list)
    frame_index: int | None = None
    timestamp: datetime | None = None
    new_track_ids: list[str] = Field(default_factory=list)
    lost_track_ids: list[str] = Field(default_factory=list)
    lost_tracks: list[TrackedObject] = Field(default_factory=list)
    removed_track_ids: list[str] = Field(default_factory=list)
    removed_tracks: list[TrackedObject] = Field(default_factory=list)

    @property
    def active_count(self) -> int:
        return len(self.tracks)

    def track_map(self) -> dict[str, TrackedObject]:
        return {track.track_id: track for track in self.tracks}

    def by_category(self, category: ObjectCategory) -> list[TrackedObject]:
        """Return only tracks matching the given category."""
        return [t for t in self.tracks if t.category == category]

    def to_summary_dict(self) -> dict[str, Any]:
        """Analytics-ready summary of this frame's tracking state."""
        category_counts: dict[str, int] = {}
        for track in self.tracks:
            key = track.category.value
            category_counts[key] = category_counts.get(key, 0) + 1
        return {
            "frame_index": self.frame_index,
            "timestamp": self.timestamp,
            "active_count": self.active_count,
            "new_count": len(self.new_track_ids),
            "lost_count": len(self.lost_track_ids),
            "removed_count": len(self.removed_track_ids),
            "category_counts": category_counts,
        }