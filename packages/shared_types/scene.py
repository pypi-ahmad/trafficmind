"""Scene context and signal-state contracts shared across services.

These types mediate the bidirectional coupling between signals, rules,
and streams.  By living in shared_types, no service owns them and
the circular import between rules↔signals is eliminated.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from packages.shared_types.geometry import Point2D  # noqa: F401 — re-exported for convenience


class SignalPhase(StrEnum):
    """Which traffic participant the signal head controls."""

    VEHICLE = "vehicle"
    PEDESTRIAN = "pedestrian"
    UNKNOWN = "unknown"


class TrafficLightState(StrEnum):
    """Possible traffic signal states."""

    RED = "red"
    YELLOW = "yellow"
    GREEN = "green"
    UNKNOWN = "unknown"


class SignalStateSourceKind(StrEnum):
    """Where a rules-facing signal state came from."""

    VISION = "vision"
    CONTROLLER = "controller"
    RESOLVED = "resolved"


class SignalIntegrationMode(StrEnum):
    """How controller-fed and vision-derived signal states are combined."""

    VISION_ONLY = "vision_only"
    CONTROLLER_ONLY = "controller_only"
    HYBRID = "hybrid"


class SceneSignalState(BaseModel):
    """Rules-facing signal state for one linked signal head on one frame."""

    model_config = ConfigDict(frozen=True)

    head_id: str
    phase: SignalPhase = SignalPhase.UNKNOWN
    state: TrafficLightState = TrafficLightState.UNKNOWN
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    frame_index: int | None = None
    last_seen_at: datetime | None = None
    frames_since_seen: int = 0
    is_stale: bool = False
    source_id: str | None = None
    stream_id: uuid.UUID | None = None
    camera_id: uuid.UUID | None = None
    lane_id: str | None = None
    stop_line_id: str | None = None
    crosswalk_id: str | None = None
    source_kind: SignalStateSourceKind = SignalStateSourceKind.RESOLVED
    observed_sources: list[SignalStateSourceKind] = Field(default_factory=list)
    trust_score: float | None = Field(default=None, ge=0.0, le=1.0)
    junction_id: str | None = None
    controller_id: str | None = None
    phase_id: str | None = None
    conflict_reason: str | None = None


class SignalConflict(BaseModel):
    """Explicit conflict between controller-fed and vision-derived signal state."""

    model_config = ConfigDict(frozen=True)

    phase: SignalPhase = SignalPhase.UNKNOWN
    reason: str
    head_id: str | None = None
    lane_id: str | None = None
    stop_line_id: str | None = None
    crosswalk_id: str | None = None
    phase_id: str | None = None
    junction_id: str | None = None
    controller_id: str | None = None
    vision_state: TrafficLightState = TrafficLightState.UNKNOWN
    controller_state: TrafficLightState = TrafficLightState.UNKNOWN
    vision_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    controller_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class SceneContext(BaseModel):
    """External signals for the current frame (traffic-light state, etc.)."""

    model_config = ConfigDict(frozen=True)

    frame_index: int | None = None
    timestamp: datetime | None = None
    traffic_light_state: TrafficLightState = TrafficLightState.UNKNOWN
    traffic_light_zone_name: str | None = None
    vehicle_signal_state: TrafficLightState = TrafficLightState.UNKNOWN
    pedestrian_signal_state: TrafficLightState = TrafficLightState.UNKNOWN
    signal_states: list[SceneSignalState] = Field(default_factory=list)
    vision_signal_states: list[SceneSignalState] = Field(default_factory=list)
    controller_signal_states: list[SceneSignalState] = Field(default_factory=list)
    signal_conflicts: list[SignalConflict] = Field(default_factory=list)
    integration_mode: SignalIntegrationMode = SignalIntegrationMode.VISION_ONLY

    def _phase_signals(self, *, phase: SignalPhase) -> list[SceneSignalState]:
        return [signal for signal in self.signal_states if signal.phase == phase]

    def primary_signal(self, *, phase: SignalPhase) -> SceneSignalState | None:
        phase_signals = self._phase_signals(phase=phase)
        if len(phase_signals) != 1:
            return None
        return phase_signals[0]

    def signal_for_stop_line(
        self,
        stop_line_id: str | None,
        *,
        phase: SignalPhase = SignalPhase.VEHICLE,
    ) -> SceneSignalState | None:
        phase_signals = self._phase_signals(phase=phase)
        if stop_line_id is not None:
            linked_signals = [
                signal for signal in phase_signals if signal.stop_line_id is not None
            ]
            for signal in linked_signals:
                if signal.stop_line_id == stop_line_id:
                    return signal
            if linked_signals:
                return None
        return self.primary_signal(phase=phase)

    def signal_for_crosswalk(
        self,
        crosswalk_id: str | None,
        *,
        phase: SignalPhase = SignalPhase.PEDESTRIAN,
    ) -> SceneSignalState | None:
        phase_signals = self._phase_signals(phase=phase)
        if crosswalk_id is not None:
            linked_signals = [
                signal for signal in phase_signals if signal.crosswalk_id is not None
            ]
            for signal in linked_signals:
                if signal.crosswalk_id == crosswalk_id:
                    return signal
            if linked_signals:
                return None
        return self.primary_signal(phase=phase)

    def vehicle_signal_state_for_stop_line(
        self,
        stop_line_id: str | None,
        *,
        min_confidence: float = 0.0,
    ) -> TrafficLightState:
        signal = self.signal_for_stop_line(stop_line_id, phase=SignalPhase.VEHICLE)
        if signal is not None:
            if signal.is_stale or signal.confidence < min_confidence:
                return TrafficLightState.UNKNOWN
            return signal.state
        if self.vehicle_signal_state != TrafficLightState.UNKNOWN:
            return self.vehicle_signal_state
        return self.traffic_light_state

    def pedestrian_signal_state_for_crosswalk(
        self,
        crosswalk_id: str | None,
        *,
        min_confidence: float = 0.0,
    ) -> TrafficLightState:
        signal = self.signal_for_crosswalk(crosswalk_id, phase=SignalPhase.PEDESTRIAN)
        if signal is not None:
            if signal.is_stale or signal.confidence < min_confidence:
                return TrafficLightState.UNKNOWN
            return signal.state
        return self.pedestrian_signal_state
