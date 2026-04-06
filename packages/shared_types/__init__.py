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
    ViolationLifecycleStage,
    ViolationSeverity,
    ViolationStatus,
    ViolationType,
    ZoneType,
)
from packages.shared_types.events import (
    Explanation,
    PreViolationRecord,
    RuleEvaluationResult,
    ViolationRecord,
)
from packages.shared_types.geometry import BBox, ObjectCategory, Point2D
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
    "ObjectCategory",
    "Point2D",
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
    "ViolationLifecycleStage",
    "ViolationSeverity",
    "ViolationStatus",
    "ViolationType",
    "ZoneType",
    # event / violation contracts
    "Explanation",
    "PreViolationRecord",
    "RuleEvaluationResult",
    "ViolationRecord",
]
