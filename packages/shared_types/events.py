"""Event and violation result contracts shared across the pipeline.

These types are produced by the rules engine and consumed by the persistence
layer, stream pipeline, model-registry runtime, and the review UI.  Moving
them to ``packages.shared_types`` removes the previous tight coupling
between ``services.rules`` and its downstream consumers.

Downstream modules (``services.rules.schemas``) re-export these for
backward compatibility.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from packages.shared_types.enums import (
    RuleType,
    ViolationLifecycleStage,
    ViolationSeverity,
    ViolationType,
)


class Explanation(BaseModel):
    """Structured evidence for why a violation fired.

    Every field is serialisable so the value can be stored in JSON and
    rendered by the review UI.
    """

    rule_type: RuleType
    rule_config: dict[str, Any] = Field(default_factory=dict)
    reason: str
    frame_index: int | None = None
    conditions_satisfied: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
    track_snapshot: dict[str, Any] = Field(default_factory=dict)
    zone_info: dict[str, Any] = Field(default_factory=dict)


class PreViolationRecord(BaseModel):
    """One candidate/pre-violation state emitted before confirmation."""

    stage: ViolationLifecycleStage = ViolationLifecycleStage.PRE_VIOLATION
    rule_type: RuleType
    violation_type: ViolationType
    zone_id: str
    zone_name: str
    track_id: str
    observed_at: datetime
    candidate_started_at: datetime
    frame_index: int | None = None
    certainty: float = Field(default=0.5, ge=0.0, le=1.0)
    explanation: Explanation

    def to_event_dict(self) -> dict[str, Any]:
        """Serialisable dict for persistence or downstream consumers."""
        return {
            "stage": self.stage.value,
            "rule_type": self.rule_type.value,
            "violation_type": self.violation_type.value,
            "zone_id": self.zone_id,
            "zone_name": self.zone_name,
            "track_id": self.track_id,
            "observed_at": self.observed_at,
            "candidate_started_at": self.candidate_started_at,
            "frame_index": self.frame_index,
            "certainty": self.certainty,
            "explanation": self.explanation.model_dump(mode="json"),
        }


class ViolationRecord(BaseModel):
    """One emitted violation from the rules engine."""

    rule_type: RuleType
    violation_type: ViolationType
    severity: ViolationSeverity
    zone_id: str
    zone_name: str
    track_id: str
    occurred_at: datetime
    frame_index: int | None = None
    certainty: float = Field(default=1.0, ge=0.0, le=1.0)
    explanation: Explanation

    def to_orm_kwargs(self) -> dict[str, Any]:
        """Dict suitable for creating a ViolationEvent ORM instance."""
        return {
            "violation_type": self.violation_type,
            "severity": self.severity,
            "occurred_at": self.occurred_at,
            "summary": self.explanation.reason,
            "rule_metadata": {
                "rule_type": self.rule_type.value,
                "frame_index": self.frame_index,
                "track_id": self.track_id,
                "certainty": self.certainty,
                "explanation": self.explanation.model_dump(mode="json"),
            },
        }


class RuleEvaluationResult(BaseModel):
    """Full per-frame rules evaluation output, including pre-violations."""

    pre_violations: list[PreViolationRecord] = Field(default_factory=list)
    violations: list[ViolationRecord] = Field(default_factory=list)
