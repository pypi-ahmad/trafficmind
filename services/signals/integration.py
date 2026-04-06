"""External signal-controller ingestion and conservative arbitration.

This module keeps controller-fed signal state separate from vision-derived
signal state while exposing a resolved ``SceneContext`` that the rules engine
can use without any vendor-specific protocol assumptions.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from services.rules.schemas import (
    SceneContext,
    SceneSignalState,
    SignalConflict,
    SignalIntegrationMode,
    SignalStateSourceKind,
    TrafficLightState,
)
from services.signals.schemas import SignalPhase


class ExternalSignalFeedKind(StrEnum):
    """Supported external controller integration patterns."""

    FILE_FEED = "file_feed"
    POLLING_ENDPOINT = "polling_endpoint"
    WEBHOOK_EVENT = "webhook_event"
    MOCK_SIMULATOR = "mock_simulator"


class ControllerSignalEvent(BaseModel):
    """Normalized controller-fed signal state observation."""

    model_config = ConfigDict(frozen=True)

    camera_id: uuid.UUID | None = None
    junction_id: str | None = None
    controller_id: str
    phase_id: str
    phase: SignalPhase = SignalPhase.UNKNOWN
    state: TrafficLightState = TrafficLightState.UNKNOWN
    timestamp: datetime
    source_type: ExternalSignalFeedKind
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    trust_score: float = Field(default=1.0, ge=0.0, le=1.0)
    source_label: str | None = None
    source_event_id: str | None = None
    head_id: str | None = None
    lane_id: str | None = None
    stop_line_id: str | None = None
    crosswalk_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ControllerSignalBatch(BaseModel):
    """Batch of normalized controller-fed signal observations."""

    model_config = ConfigDict(frozen=True)

    events: list[ControllerSignalEvent] = Field(default_factory=list)


class SignalIngestResult(BaseModel):
    """Summary of an ingest operation against the controller-state store."""

    model_config = ConfigDict(frozen=True)

    accepted_count: int = 0
    ignored_older_count: int = 0
    tracked_signal_count: int = 0
    ingested_keys: list[str] = Field(default_factory=list)


class ControllerSignalSnapshot(BaseModel):
    """Current rules-facing view of controller-fed signal state."""

    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    camera_id: uuid.UUID | None = None
    junction_id: str | None = None
    signal_states: list[SceneSignalState] = Field(default_factory=list)
    stale_signal_count: int = 0
    usable_signal_count: int = 0


class FileSignalFeedIngestRequest(BaseModel):
    """Ingest external signal state from a JSON or JSONL file payload."""

    model_config = ConfigDict(frozen=True)

    payload: str
    payload_format: str = Field(default="json", pattern="^(json|jsonl)$")
    source_label: str | None = None


class SignalPollingRequest(BaseModel):
    """Fetch a polling endpoint once and ingest the returned signal payload."""

    model_config = ConfigDict(frozen=True)

    url: str
    method: str = Field(default="GET", pattern="^(GET|POST)$")
    headers: dict[str, str] = Field(default_factory=dict)
    json_body: dict[str, Any] | list[dict[str, Any]] | None = None
    timeout_seconds: float = Field(default=5.0, gt=0.0)
    source_label: str | None = None


class MockSignalStateTemplate(BaseModel):
    """One signal state emitted during one mock controller cycle step."""

    model_config = ConfigDict(frozen=True)

    phase_id: str
    phase: SignalPhase
    state: TrafficLightState
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    trust_score: float = Field(default=1.0, ge=0.0, le=1.0)
    head_id: str | None = None
    lane_id: str | None = None
    stop_line_id: str | None = None
    crosswalk_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class MockSignalCycleStep(BaseModel):
    """One step in a mock signal controller cycle."""

    model_config = ConfigDict(frozen=True)

    duration_seconds: float = Field(gt=0.0)
    states: list[MockSignalStateTemplate] = Field(default_factory=list)


class MockSignalSimulatorRequest(BaseModel):
    """Build or ingest a mock/local controller snapshot for a target time."""

    model_config = ConfigDict(frozen=True)

    camera_id: uuid.UUID | None = None
    junction_id: str | None = None
    controller_id: str
    cycle_started_at: datetime
    at_time: datetime
    steps: list[MockSignalCycleStep] = Field(default_factory=list)
    source_label: str | None = "mock-simulator"
    ingest: bool = True


class SignalIntegrationService:
    """In-memory external signal store and conservative arbitration service."""

    def __init__(
        self,
        *,
        default_mode: SignalIntegrationMode = SignalIntegrationMode.HYBRID,
        vision_min_confidence: float = 0.35,
        controller_min_confidence: float = 0.7,
        controller_stale_after_seconds: float = 5.0,
    ) -> None:
        self._default_mode = default_mode
        self._vision_min_confidence = vision_min_confidence
        self._controller_min_confidence = controller_min_confidence
        self._controller_stale_after = timedelta(seconds=controller_stale_after_seconds)
        self._controller_events: dict[str, ControllerSignalEvent] = {}

    def ingest_events(self, batch: ControllerSignalBatch) -> SignalIngestResult:
        accepted = 0
        ignored_older = 0
        ingested_keys: list[str] = []

        for event in batch.events:
            key = self._controller_event_key(event)
            existing = self._controller_events.get(key)
            if existing is not None and existing.timestamp > event.timestamp:
                ignored_older += 1
                continue
            self._controller_events[key] = event
            accepted += 1
            ingested_keys.append(key)

        return SignalIngestResult(
            accepted_count=accepted,
            ignored_older_count=ignored_older,
            tracked_signal_count=len(self._controller_events),
            ingested_keys=ingested_keys,
        )

    def ingest_file_feed(self, request: FileSignalFeedIngestRequest) -> SignalIngestResult:
        events = self._parse_file_payload(
            request.payload,
            payload_format=request.payload_format,
            source_type=ExternalSignalFeedKind.FILE_FEED,
            source_label=request.source_label,
        )
        return self.ingest_events(ControllerSignalBatch(events=events))

    async def poll_endpoint(
        self,
        request: SignalPollingRequest,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> SignalIngestResult:
        async with httpx.AsyncClient(
            transport=transport, timeout=request.timeout_seconds
        ) as client:
            response = await client.request(
                request.method,
                request.url,
                headers=request.headers,
                json=request.json_body,
            )
            response.raise_for_status()
            payload = response.json()

        events = self._parse_event_payload(
            payload,
            source_type=ExternalSignalFeedKind.POLLING_ENDPOINT,
            source_label=request.source_label or request.url,
        )
        return self.ingest_events(ControllerSignalBatch(events=events))

    def simulate(self, request: MockSignalSimulatorRequest) -> ControllerSignalSnapshot:
        events = self._build_mock_events(request)
        if request.ingest:
            self.ingest_events(ControllerSignalBatch(events=events))
            return self.get_controller_snapshot(
                camera_id=request.camera_id,
                junction_id=request.junction_id,
                at_time=request.at_time,
            )
        return self._controller_snapshot_from_events(
            events,
            camera_id=request.camera_id,
            junction_id=request.junction_id,
            at_time=request.at_time,
        )

    def get_controller_snapshot(
        self,
        *,
        camera_id: uuid.UUID | None = None,
        junction_id: str | None = None,
        at_time: datetime | None = None,
    ) -> ControllerSignalSnapshot:
        now = at_time or datetime.now(UTC)
        events = [
            event
            for event in self._controller_events.values()
            if (camera_id is None or event.camera_id == camera_id)
            and (junction_id is None or event.junction_id == junction_id)
        ]
        return self._controller_snapshot_from_events(
            events,
            camera_id=camera_id,
            junction_id=junction_id,
            at_time=now,
        )

    def resolve_scene_context(
        self,
        *,
        vision_scene: SceneContext | None = None,
        controller_snapshot: ControllerSignalSnapshot | None = None,
        camera_id: uuid.UUID | None = None,
        junction_id: str | None = None,
        timestamp: datetime | None = None,
        mode: SignalIntegrationMode | None = None,
    ) -> SceneContext:
        now = (
            timestamp
            or (vision_scene.timestamp if vision_scene is not None else None)
            or datetime.now(UTC)
        )
        chosen_mode = mode or self._default_mode
        if controller_snapshot is not None:
            snapshot = controller_snapshot
        elif camera_id is not None or junction_id is not None:
            snapshot = self.get_controller_snapshot(
                camera_id=camera_id,
                junction_id=junction_id,
                at_time=now,
            )
        else:
            snapshot = ControllerSignalSnapshot(generated_at=now)

        vision_states = self._resolve_vision_states(vision_scene)
        controller_states = list(snapshot.signal_states)
        resolved_states, conflicts = self._resolve_states(
            vision_states=vision_states,
            controller_states=controller_states,
            mode=chosen_mode,
        )

        primary_vehicle = self._unique_phase_state(
            resolved_states,
            phase=SignalPhase.VEHICLE,
        )
        primary_pedestrian = self._unique_phase_state(
            resolved_states,
            phase=SignalPhase.PEDESTRIAN,
        )

        return SceneContext(
            frame_index=vision_scene.frame_index if vision_scene is not None else None,
            timestamp=now,
            traffic_light_state=(
                primary_vehicle.state if primary_vehicle is not None else TrafficLightState.UNKNOWN
            ),
            traffic_light_zone_name=(
                primary_vehicle.stop_line_id if primary_vehicle is not None else None
            ),
            vehicle_signal_state=(
                primary_vehicle.state if primary_vehicle is not None else TrafficLightState.UNKNOWN
            ),
            pedestrian_signal_state=(
                primary_pedestrian.state
                if primary_pedestrian is not None
                else TrafficLightState.UNKNOWN
            ),
            signal_states=resolved_states,
            vision_signal_states=vision_states,
            controller_signal_states=controller_states,
            signal_conflicts=conflicts,
            integration_mode=chosen_mode,
        )

    def _parse_file_payload(
        self,
        payload: str,
        *,
        payload_format: str,
        source_type: ExternalSignalFeedKind,
        source_label: str | None,
    ) -> list[ControllerSignalEvent]:
        if payload_format == "jsonl":
            items = [json.loads(line) for line in payload.splitlines() if line.strip()]
        else:
            items = json.loads(payload)
        return self._parse_event_payload(items, source_type=source_type, source_label=source_label)

    def _parse_event_payload(
        self,
        payload: Any,
        *,
        source_type: ExternalSignalFeedKind,
        source_label: str | None,
    ) -> list[ControllerSignalEvent]:
        if isinstance(payload, dict):
            if isinstance(payload.get("events"), list):
                items = payload["events"]
            elif isinstance(payload.get("signal_states"), list):
                items = payload["signal_states"]
            else:
                items = [payload]
        elif isinstance(payload, list):
            items = payload
        else:
            msg = "External signal payload must be a JSON object or array."
            raise ValueError(msg)

        events: list[ControllerSignalEvent] = []
        for item in items:
            if not isinstance(item, dict):
                msg = "Each external signal event must be a JSON object."
                raise ValueError(msg)
            normalized = dict(item)
            normalized.setdefault("source_type", source_type)
            if source_label is not None:
                normalized.setdefault("source_label", source_label)
            events.append(ControllerSignalEvent.model_validate(normalized))
        return events

    def _build_mock_events(
        self, request: MockSignalSimulatorRequest
    ) -> list[ControllerSignalEvent]:
        if not request.steps:
            return []

        cycle_seconds = sum(step.duration_seconds for step in request.steps)
        if cycle_seconds <= 0:
            return []

        elapsed = max(0.0, (request.at_time - request.cycle_started_at).total_seconds())
        cycle_position = elapsed % cycle_seconds
        selected_step = request.steps[-1]
        consumed = 0.0
        for step in request.steps:
            consumed += step.duration_seconds
            if cycle_position < consumed:
                selected_step = step
                break

        return [
            ControllerSignalEvent(
                camera_id=request.camera_id,
                junction_id=request.junction_id,
                controller_id=request.controller_id,
                phase_id=state.phase_id,
                phase=state.phase,
                state=state.state,
                timestamp=request.at_time,
                source_type=ExternalSignalFeedKind.MOCK_SIMULATOR,
                confidence=state.confidence,
                trust_score=state.trust_score,
                source_label=request.source_label,
                head_id=state.head_id,
                lane_id=state.lane_id,
                stop_line_id=state.stop_line_id,
                crosswalk_id=state.crosswalk_id,
                details=state.details,
            )
            for state in selected_step.states
        ]

    def _controller_snapshot_from_events(
        self,
        events: list[ControllerSignalEvent],
        *,
        camera_id: uuid.UUID | None,
        junction_id: str | None,
        at_time: datetime,
    ) -> ControllerSignalSnapshot:
        signal_states = [
            self._controller_event_to_scene_signal_state(event, now=at_time) for event in events
        ]
        stale_count = sum(1 for state in signal_states if state.is_stale)
        usable_count = sum(
            1
            for state in signal_states
            if self._is_usable_state(state, min_confidence=self._controller_min_confidence)
        )
        return ControllerSignalSnapshot(
            generated_at=at_time,
            camera_id=camera_id,
            junction_id=junction_id,
            signal_states=sorted(signal_states, key=self._scene_signal_sort_key),
            stale_signal_count=stale_count,
            usable_signal_count=usable_count,
        )

    def _resolve_vision_states(self, vision_scene: SceneContext | None) -> list[SceneSignalState]:
        if vision_scene is None:
            return []

        if vision_scene.vision_signal_states:
            return list(vision_scene.vision_signal_states)

        if vision_scene.signal_states:
            return [
                state.model_copy(
                    update={
                        "source_kind": (
                            state.source_kind
                            if state.source_kind != SignalStateSourceKind.RESOLVED
                            else SignalStateSourceKind.VISION
                        ),
                        "observed_sources": state.observed_sources
                        or [SignalStateSourceKind.VISION],
                    }
                )
                for state in vision_scene.signal_states
            ]

        fallback: list[SceneSignalState] = []
        vehicle_state = vision_scene.vehicle_signal_state
        if vehicle_state == TrafficLightState.UNKNOWN:
            vehicle_state = vision_scene.traffic_light_state
        if vehicle_state != TrafficLightState.UNKNOWN:
            fallback.append(
                SceneSignalState(
                    head_id="vision-primary-vehicle",
                    phase=SignalPhase.VEHICLE,
                    state=vehicle_state,
                    confidence=1.0,
                    frame_index=vision_scene.frame_index,
                    last_seen_at=vision_scene.timestamp,
                    source_kind=SignalStateSourceKind.VISION,
                    observed_sources=[SignalStateSourceKind.VISION],
                    stop_line_id=vision_scene.traffic_light_zone_name,
                    source_id="vision-primary",
                )
            )
        if vision_scene.pedestrian_signal_state != TrafficLightState.UNKNOWN:
            fallback.append(
                SceneSignalState(
                    head_id="vision-primary-pedestrian",
                    phase=SignalPhase.PEDESTRIAN,
                    state=vision_scene.pedestrian_signal_state,
                    confidence=1.0,
                    frame_index=vision_scene.frame_index,
                    last_seen_at=vision_scene.timestamp,
                    source_kind=SignalStateSourceKind.VISION,
                    observed_sources=[SignalStateSourceKind.VISION],
                    source_id="vision-primary",
                )
            )
        return fallback

    @staticmethod
    def _unique_phase_state(
        states: list[SceneSignalState],
        *,
        phase: SignalPhase,
    ) -> SceneSignalState | None:
        phase_states = [state for state in states if state.phase == phase]
        if len(phase_states) != 1:
            return None
        return phase_states[0]

    def _resolve_states(
        self,
        *,
        vision_states: list[SceneSignalState],
        controller_states: list[SceneSignalState],
        mode: SignalIntegrationMode,
    ) -> tuple[list[SceneSignalState], list[SignalConflict]]:
        vision_by_key = {self._scene_signal_key(state): state for state in vision_states}
        controller_by_key = {self._scene_signal_key(state): state for state in controller_states}
        resolved: list[SceneSignalState] = []
        conflicts: list[SignalConflict] = []

        for key in sorted(set(vision_by_key) | set(controller_by_key)):
            vision = vision_by_key.get(key)
            controller = controller_by_key.get(key)
            chosen, conflict = self._resolve_signal_pair(
                vision_state=vision,
                controller_state=controller,
                mode=mode,
            )
            if chosen is not None:
                resolved.append(chosen)
            if conflict is not None:
                conflicts.append(conflict)

        return resolved, conflicts

    def _resolve_signal_pair(
        self,
        *,
        vision_state: SceneSignalState | None,
        controller_state: SceneSignalState | None,
        mode: SignalIntegrationMode,
    ) -> tuple[SceneSignalState | None, SignalConflict | None]:
        if mode == SignalIntegrationMode.VISION_ONLY:
            return self._choose_single_source(
                chosen=vision_state,
                other=controller_state,
                min_confidence=self._vision_min_confidence,
            ), None

        if mode == SignalIntegrationMode.CONTROLLER_ONLY:
            return self._choose_single_source(
                chosen=controller_state,
                other=vision_state,
                min_confidence=self._controller_min_confidence,
            ), None

        vision_usable = self._is_usable_state(
            vision_state, min_confidence=self._vision_min_confidence
        )
        controller_usable = self._is_usable_state(
            controller_state, min_confidence=self._controller_min_confidence
        )

        if vision_usable and controller_usable:
            assert vision_state is not None
            assert controller_state is not None
            if vision_state.state == controller_state.state:
                return self._build_agreed_state(vision_state, controller_state), None
            conflict = self._build_conflict(vision_state, controller_state)
            return self._build_conflicted_unknown_state(
                vision_state, controller_state, conflict.reason
            ), conflict

        if controller_usable:
            assert controller_state is not None
            return self._annotate_observed_sources(controller_state, other=vision_state), None

        if vision_usable:
            assert vision_state is not None
            return self._annotate_observed_sources(vision_state, other=controller_state), None

        return None, None

    def _choose_single_source(
        self,
        *,
        chosen: SceneSignalState | None,
        other: SceneSignalState | None,
        min_confidence: float,
    ) -> SceneSignalState | None:
        if not self._is_usable_state(chosen, min_confidence=min_confidence):
            return None
        assert chosen is not None
        return self._annotate_observed_sources(chosen, other=other)

    @staticmethod
    def _annotate_observed_sources(
        chosen: SceneSignalState,
        *,
        other: SceneSignalState | None,
    ) -> SceneSignalState:
        observed = list(chosen.observed_sources or [chosen.source_kind])
        if other is not None:
            for source_kind in other.observed_sources or [other.source_kind]:
                if source_kind not in observed:
                    observed.append(source_kind)
        return chosen.model_copy(update={"observed_sources": observed})

    def _build_agreed_state(
        self,
        vision_state: SceneSignalState,
        controller_state: SceneSignalState,
    ) -> SceneSignalState:
        effective_confidence = min(
            self._effective_confidence(vision_state),
            self._effective_confidence(controller_state),
        )
        trust_score = min(
            vision_state.trust_score
            if vision_state.trust_score is not None
            else vision_state.confidence,
            controller_state.trust_score
            if controller_state.trust_score is not None
            else controller_state.confidence,
        )
        return vision_state.model_copy(
            update={
                "source_kind": SignalStateSourceKind.RESOLVED,
                "observed_sources": [
                    SignalStateSourceKind.VISION,
                    SignalStateSourceKind.CONTROLLER,
                ],
                "confidence": effective_confidence,
                "trust_score": trust_score,
                "junction_id": controller_state.junction_id,
                "controller_id": controller_state.controller_id,
                "phase_id": controller_state.phase_id,
                "source_id": "hybrid-agreement",
            }
        )

    def _build_conflicted_unknown_state(
        self,
        vision_state: SceneSignalState,
        controller_state: SceneSignalState,
        reason: str,
    ) -> SceneSignalState:
        return vision_state.model_copy(
            update={
                "state": TrafficLightState.UNKNOWN,
                "confidence": min(
                    self._effective_confidence(vision_state),
                    self._effective_confidence(controller_state),
                ),
                "trust_score": min(
                    vision_state.trust_score
                    if vision_state.trust_score is not None
                    else vision_state.confidence,
                    controller_state.trust_score
                    if controller_state.trust_score is not None
                    else controller_state.confidence,
                ),
                "source_kind": SignalStateSourceKind.RESOLVED,
                "observed_sources": [
                    SignalStateSourceKind.VISION,
                    SignalStateSourceKind.CONTROLLER,
                ],
                "junction_id": controller_state.junction_id,
                "controller_id": controller_state.controller_id,
                "phase_id": controller_state.phase_id,
                "conflict_reason": reason,
                "source_id": "hybrid-conflict",
            }
        )

    def _build_conflict(
        self,
        vision_state: SceneSignalState,
        controller_state: SceneSignalState,
    ) -> SignalConflict:
        return SignalConflict(
            phase=vision_state.phase,
            reason=(
                "Vision-derived and controller-fed signal states conflict; "
                "hybrid resolution returned UNKNOWN."
            ),
            head_id=vision_state.head_id or controller_state.head_id,
            lane_id=vision_state.lane_id or controller_state.lane_id,
            stop_line_id=vision_state.stop_line_id or controller_state.stop_line_id,
            crosswalk_id=vision_state.crosswalk_id or controller_state.crosswalk_id,
            phase_id=controller_state.phase_id,
            junction_id=controller_state.junction_id,
            controller_id=controller_state.controller_id,
            vision_state=vision_state.state,
            controller_state=controller_state.state,
            vision_confidence=self._effective_confidence(vision_state),
            controller_confidence=self._effective_confidence(controller_state),
        )

    def _controller_event_to_scene_signal_state(
        self,
        event: ControllerSignalEvent,
        *,
        now: datetime,
    ) -> SceneSignalState:
        effective_confidence = min(event.confidence, event.trust_score)
        is_stale = (
            (now - event.timestamp) > self._controller_stale_after
            if now >= event.timestamp
            else False
        )
        return SceneSignalState(
            head_id=event.head_id or f"controller:{event.controller_id}:{event.phase_id}",
            phase=event.phase,
            state=event.state,
            confidence=effective_confidence,
            trust_score=event.trust_score,
            last_seen_at=event.timestamp,
            is_stale=is_stale,
            source_id=event.source_label or event.source_type.value,
            camera_id=event.camera_id,
            lane_id=event.lane_id,
            stop_line_id=event.stop_line_id,
            crosswalk_id=event.crosswalk_id,
            source_kind=SignalStateSourceKind.CONTROLLER,
            observed_sources=[SignalStateSourceKind.CONTROLLER],
            junction_id=event.junction_id,
            controller_id=event.controller_id,
            phase_id=event.phase_id,
        )

    @staticmethod
    def _effective_confidence(state: SceneSignalState) -> float:
        trust_score = state.trust_score if state.trust_score is not None else state.confidence
        return min(state.confidence, trust_score)

    @staticmethod
    def _is_usable_state(
        state: SceneSignalState | None,
        *,
        min_confidence: float,
    ) -> bool:
        if state is None:
            return False
        if state.is_stale or state.state == TrafficLightState.UNKNOWN:
            return False
        return SignalIntegrationService._effective_confidence(state) >= min_confidence

    @staticmethod
    def _scene_signal_sort_key(state: SceneSignalState) -> tuple[str, str, str, str, str]:
        return (
            state.phase.value,
            state.stop_line_id or "",
            state.crosswalk_id or "",
            state.lane_id or "",
            state.head_id,
        )

    @staticmethod
    def _scene_signal_key(state: SceneSignalState) -> tuple[str, str]:
        if state.stop_line_id is not None:
            link_key = f"stop_line:{state.stop_line_id}"
        elif state.crosswalk_id is not None:
            link_key = f"crosswalk:{state.crosswalk_id}"
        elif state.lane_id is not None:
            link_key = f"lane:{state.lane_id}"
        elif state.phase_id is not None:
            link_key = f"phase_id:{state.phase_id}"
        else:
            link_key = f"head:{state.head_id}"
        return (state.phase.value, link_key)

    @staticmethod
    def _controller_event_key(event: ControllerSignalEvent) -> str:
        if event.stop_line_id is not None:
            link_key = f"stop_line:{event.stop_line_id}"
        elif event.crosswalk_id is not None:
            link_key = f"crosswalk:{event.crosswalk_id}"
        elif event.lane_id is not None:
            link_key = f"lane:{event.lane_id}"
        elif event.head_id is not None:
            link_key = f"head:{event.head_id}"
        else:
            link_key = f"phase_id:{event.phase_id}"
        camera_key = str(event.camera_id) if event.camera_id is not None else ""
        junction_key = event.junction_id or ""
        return "|".join(
            (camera_key, junction_key, event.controller_id, event.phase.value, link_key)
        )
