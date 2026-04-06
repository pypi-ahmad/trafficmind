"""Typed schemas for the traffic-light signal perception module.

These schemas are the contract between the signal classifier, the temporal
state tracker, and all downstream consumers (rules engine via SceneContext,
perception event batches, persistence layer).

``SignalPhase`` is canonical in ``packages.shared_types`` and re-exported
here for backward compatibility.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

import uuid

from pydantic import BaseModel, ConfigDict, Field

from packages.shared_types.geometry import BBox
from packages.shared_types.scene import SignalPhase

__all__ = ["SignalPhase"]  # re-export shared primitive


# ---------------------------------------------------------------------------
# Core enums
# ---------------------------------------------------------------------------


class SignalColor(StrEnum):
    """Colour of a single signal indication.

    This enum intentionally mirrors ``rules.schemas.TrafficLightState`` but
    lives in the *perception* layer to avoid a circular dependency.  The
    state tracker produces this; downstream code maps it to
    ``TrafficLightState`` via :func:`to_traffic_light_state`.
    """

    RED = "red"
    YELLOW = "yellow"
    GREEN = "green"
    UNKNOWN = "unknown"


# SignalPhase imported from packages.shared_types — do NOT redefine here.


# ---------------------------------------------------------------------------
# Per-frame classifier output
# ---------------------------------------------------------------------------


class SignalClassification(BaseModel):
    """Raw output from a single classifier invocation on one crop."""

    model_config = ConfigDict(frozen=True)

    color: SignalColor
    confidence: float = Field(ge=0.0, le=1.0)
    color_scores: dict[str, float] = Field(
        default_factory=dict,
        description="Per-colour confidence scores, e.g. {'red': 0.7, 'yellow': 0.1, 'green': 0.2}.",
    )


# ---------------------------------------------------------------------------
# Signal head observation (one detection + classification on one frame)
# ---------------------------------------------------------------------------


class SignalHeadObservation(BaseModel):
    """One traffic-light detection with its classified signal state on one frame."""

    model_config = ConfigDict(frozen=True)

    head_id: str = Field(
        description="Stable identifier for this signal head.  Populated by the "
        "state tracker after spatial matching; classifier outputs use a "
        "placeholder until tracking assigns a persistent id.",
    )
    phase: SignalPhase = SignalPhase.UNKNOWN
    bbox: BBox
    classification: SignalClassification
    frame_index: int
    timestamp: datetime
    source_id: str | None = None
    stream_id: uuid.UUID | None = None
    camera_id: uuid.UUID | None = None

    # ── optional spatial linkage (populated by configuration, not CV) ───
    lane_id: str | None = Field(default=None, description="Linked lane zone id.")
    stop_line_id: str | None = Field(default=None, description="Linked stop-line zone id.")
    crosswalk_id: str | None = Field(default=None, description="Linked crosswalk zone id.")

    def to_event_dict(self) -> dict[str, Any]:
        return {
            "head_id": self.head_id,
            "phase": self.phase.value,
            "color": self.classification.color.value,
            "confidence": self.classification.confidence,
            "color_scores": self.classification.color_scores,
            "bbox": self.bbox.to_dict(),
            "frame_index": self.frame_index,
            "timestamp": self.timestamp,
            "source_id": self.source_id,
            "stream_id": self.stream_id,
            "camera_id": self.camera_id,
            "lane_id": self.lane_id,
            "stop_line_id": self.stop_line_id,
            "crosswalk_id": self.crosswalk_id,
        }


# ---------------------------------------------------------------------------
# Smoothed signal head state (output of the temporal tracker)
# ---------------------------------------------------------------------------


class SignalHeadState(BaseModel):
    """Temporally-smoothed state for one signal head across frames.

    Downstream consumers should use ``confirmed_color`` (the smoothed
    value) rather than ``raw_color`` (the latest single-frame vote).
    """

    head_id: str
    phase: SignalPhase = SignalPhase.UNKNOWN
    raw_color: SignalColor = SignalColor.UNKNOWN
    confirmed_color: SignalColor = SignalColor.UNKNOWN
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    last_seen_frame: int = 0
    last_seen_at: datetime | None = None
    frames_since_seen: int = 0
    is_stale: bool = False
    bbox: BBox | None = None
    source_id: str | None = None
    stream_id: uuid.UUID | None = None
    camera_id: uuid.UUID | None = None

    # spatial links
    lane_id: str | None = None
    stop_line_id: str | None = None
    crosswalk_id: str | None = None


# ---------------------------------------------------------------------------
# Signal head configuration (operator / calibration input)
# ---------------------------------------------------------------------------


class SignalHeadConfig(BaseModel):
    """Pre-configured signal head that maps a bounding-box region to lanes/zones.

    Operators define these at calibration time.  The state tracker uses
    ``anchor_bbox`` for spatial matching when no multi-object tracker is
    running on traffic lights.
    """

    model_config = ConfigDict(frozen=True)

    head_id: str
    phase: SignalPhase = SignalPhase.VEHICLE
    anchor_bbox: BBox | None = Field(
        default=None,
        description="Expected bounding-box region in pixel coordinates.  Used for spatial matching.",
    )
    lane_id: str | None = None
    stop_line_id: str | None = None
    crosswalk_id: str | None = None


# ---------------------------------------------------------------------------
# Frame-level aggregate
# ---------------------------------------------------------------------------


class SignalSceneSnapshot(BaseModel):
    """All signal-head observations and smoothed states for one processed frame."""

    model_config = ConfigDict(frozen=True)

    frame_index: int
    timestamp: datetime
    source_id: str | None = None
    stream_id: uuid.UUID | None = None
    camera_id: uuid.UUID | None = None
    observations: list[SignalHeadObservation] = Field(default_factory=list)
    head_states: list[SignalHeadState] = Field(default_factory=list)

    @property
    def observation_count(self) -> int:
        return len(self.observations)

    def primary_vehicle_signal(self) -> SignalHeadState | None:
        """Return the first explicit vehicle-phase head state, or None."""
        for hs in self.head_states:
            if hs.phase == SignalPhase.VEHICLE:
                return hs
        return None

    def by_head_id(self, head_id: str) -> SignalHeadState | None:
        for hs in self.head_states:
            if hs.head_id == head_id:
                return hs
        return None

    def to_event_dicts(self) -> list[dict[str, Any]]:
        return [obs.to_event_dict() for obs in self.observations]
