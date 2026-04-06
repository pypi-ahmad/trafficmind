"""TrafficMind shared type contracts.

Canonical definitions for types that cross service boundaries.
Individual services re-export these for backward compatibility.
"""

from packages.shared_types.enums import (
    DetectionEventStatus,
    DetectionEventType,
    ReIdMatchStatus,
    ReIdSubjectType,
    RuleType,
    SourceKind,
    ViolationLifecycleStage,
    ViolationSeverity,
    ViolationStatus,
    ViolationType,
    WorkflowStatus,
    WorkflowType,
    ZoneType,
)
from packages.shared_types.events import (
    Explanation,
    PreViolationRecord,
    RuleEvaluationResult,
    ViolationRecord,
)
from packages.shared_types.geometry import BBox, LineSegment, ObjectCategory, Point2D, PolygonZone
from packages.shared_types.scene import (
    SceneContext,
    SceneSignalState,
    SignalConflict,
    SignalIntegrationMode,
    SignalPhase,
    SignalStateSourceKind,
    TrafficLightState,
)

__all__ = [
    # geometry
    "BBox",
    "LineSegment",
    "ObjectCategory",
    "Point2D",
    "PolygonZone",
    # scene / signals
    "SceneContext",
    "SceneSignalState",
    "SignalConflict",
    "SignalIntegrationMode",
    "SignalPhase",
    "SignalStateSourceKind",
    "TrafficLightState",
    # domain enums
    "DetectionEventStatus",
    "DetectionEventType",
    "ReIdMatchStatus",
    "ReIdSubjectType",
    "RuleType",
    "SourceKind",
    "ViolationLifecycleStage",
    "ViolationSeverity",
    "ViolationStatus",
    "ViolationType",
    "WorkflowStatus",
    "WorkflowType",
    "ZoneType",
    # event / violation contracts
    "Explanation",
    "PreViolationRecord",
    "RuleEvaluationResult",
    "ViolationRecord",
]
