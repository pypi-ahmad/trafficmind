"""TrafficMind tracking service package."""

from services.tracking.config import TrackingSettings
from services.tracking.interface import MatchedDetection, StatefulTracker, Tracker, TrackerRegistry
from services.tracking.schemas import (
	CardinalDirection,
	LineCrossingCheck,
	LineCrossingDirection,
	LineSegment,
	MotionVector,
	Point2D,
	PolygonZone,
	TrackLifecycleStatus,
	TrackedObject,
	TrackingResult,
	TrajectoryPoint,
	ZoneTransition,
	ZoneTransitionType,
)
from services.tracking.utils import (
	check_track_line_crossing,
	check_track_line_crossings,
	check_track_zone_transitions,
)

__all__ = [
	"CardinalDirection",
	"LineCrossingCheck",
	"LineCrossingDirection",
	"LineSegment",
	"MatchedDetection",
	"MotionVector",
	"Point2D",
	"PolygonZone",
	"StatefulTracker",
	"TrackedObject",
	"Tracker",
	"TrackerRegistry",
	"TrackingResult",
	"TrackingSettings",
	"TrackLifecycleStatus",
	"TrajectoryPoint",
	"ZoneTransition",
	"ZoneTransitionType",
	"check_track_line_crossing",
	"check_track_line_crossings",
	"check_track_zone_transitions",
]
