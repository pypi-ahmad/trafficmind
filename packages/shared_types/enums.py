"""Domain enums shared across service and application boundaries.

These enums are the single source of truth for event, violation, zone, and
re-identification classification values.  Both the deterministic service
layer (``services/``) and the persistence / API layer (``apps/``) import
from here, eliminating the previous ``services → apps.api.app.db.enums``
coupling.

Downstream modules that previously defined or re-exported these values
(``apps.api.app.db.enums``, ``services.rules.schemas``,
``services.reid.schemas``) now re-export from this module for backward
compatibility.
"""

from __future__ import annotations

from enum import StrEnum

# ---------------------------------------------------------------------------
# Zone classification
# ---------------------------------------------------------------------------


class ZoneType(StrEnum):
    POLYGON = "polygon"
    LINE = "line"
    STOP_LINE = "stop_line"
    CROSSWALK = "crosswalk"
    ROI = "roi"
    LANE = "lane"
    RESTRICTED = "restricted"


# ---------------------------------------------------------------------------
# Detection events
# ---------------------------------------------------------------------------


class DetectionEventType(StrEnum):
    DETECTION = "detection"
    ZONE_ENTRY = "zone_entry"
    ZONE_EXIT = "zone_exit"
    LINE_CROSSING = "line_crossing"
    LIGHT_STATE = "light_state"


class DetectionEventStatus(StrEnum):
    NEW = "new"
    ENRICHED = "enriched"
    SUPPRESSED = "suppressed"


# ---------------------------------------------------------------------------
# Violations
# ---------------------------------------------------------------------------


class ViolationType(StrEnum):
    RED_LIGHT = "red_light"
    STOP_LINE = "stop_line"
    WRONG_WAY = "wrong_way"
    PEDESTRIAN_CONFLICT = "pedestrian_conflict"
    ILLEGAL_TURN = "illegal_turn"
    SPEEDING = "speeding"
    ILLEGAL_PARKING = "illegal_parking"
    NO_STOPPING = "no_stopping"
    BUS_STOP_VIOLATION = "bus_stop_violation"
    STALLED_VEHICLE = "stalled_vehicle"


class ViolationSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ViolationStatus(StrEnum):
    OPEN = "open"
    UNDER_REVIEW = "under_review"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"


class ViolationLifecycleStage(StrEnum):
    PRE_VIOLATION = "pre_violation"
    CONFIRMED = "confirmed"


# ---------------------------------------------------------------------------
# Rule engine
# ---------------------------------------------------------------------------


class RuleType(StrEnum):
    """Every distinct rule the engine can evaluate."""

    LINE_CROSSING = "line_crossing"
    STOP_LINE_CROSSING = "stop_line_crossing"
    ZONE_ENTRY = "zone_entry"
    ZONE_DWELL_TIME = "zone_dwell_time"
    WRONG_DIRECTION = "wrong_direction"
    RED_LIGHT = "red_light"
    PEDESTRIAN_ON_RED = "pedestrian_on_red"
    ILLEGAL_PARKING = "illegal_parking"
    NO_STOPPING = "no_stopping"
    BUS_STOP_OCCUPATION = "bus_stop_occupation"
    STALLED_VEHICLE = "stalled_vehicle"


# ---------------------------------------------------------------------------
# Re-identification
# ---------------------------------------------------------------------------


class ReIdSubjectType(StrEnum):
    """Kind of object eligible for re-identification."""

    VEHICLE = "vehicle"
    PERSON = "person"


class ReIdMatchStatus(StrEnum):
    """Lifecycle of a proposed cross-camera match."""

    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    EXPIRED = "expired"


# ---------------------------------------------------------------------------
# Stream / source classification
# ---------------------------------------------------------------------------


class SourceKind(StrEnum):
    """Type of frame source — used by both the API ORM (``CameraStream``)
    and the stream-processing service (``JobSpec``).

    Previously duplicated as ``SourceType`` in ``apps.api.app.db.enums``
    and ``SourceKind`` in ``services.streams.schemas``.
    """

    RTSP = "rtsp"
    FILE = "file"
    UPLOAD = "upload"
    TEST = "test"


# ---------------------------------------------------------------------------
# Workflow lifecycle
# ---------------------------------------------------------------------------


class WorkflowType(StrEnum):
    """Coarse workflow classification shared between the API and workflow
    service.
    """

    TRIAGE = "triage"
    REVIEW = "review"
    REPORT = "report"
    ASSIST = "assist"


class WorkflowStatus(StrEnum):
    """State machine for workflow run records — shared between the API
    (ORM persistence) and the workflow service (execution engine).
    """

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
