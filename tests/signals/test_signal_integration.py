from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
import numpy as np
import pytest

from services.rules.schemas import (
    SceneContext,
    SceneSignalState,
    SignalIntegrationMode,
    SignalStateSourceKind,
    TrafficLightState,
)
from services.signals.integration import (
    ControllerSignalBatch,
    ControllerSignalEvent,
    ExternalSignalFeedKind,
    MockSignalCycleStep,
    MockSignalSimulatorRequest,
    MockSignalStateTemplate,
    SignalIntegrationService,
    SignalPollingRequest,
)
from services.signals.schemas import SignalPhase
from services.streams.pipeline import FramePipeline
from services.streams.schemas import PipelineFlags

NOW = datetime(2026, 4, 5, 15, 0, tzinfo=UTC)


def _controller_event(
    *,
    camera_id: uuid.UUID,
    state: TrafficLightState,
    timestamp: datetime = NOW,
    source_type: ExternalSignalFeedKind = ExternalSignalFeedKind.WEBHOOK_EVENT,
) -> ControllerSignalEvent:
    return ControllerSignalEvent(
        camera_id=camera_id,
        junction_id="j-main-1",
        controller_id="controller-a",
        phase_id="veh-main",
        phase=SignalPhase.VEHICLE,
        state=state,
        timestamp=timestamp,
        source_type=source_type,
        confidence=0.98,
        trust_score=0.95,
        stop_line_id="sl-1",
        source_label="integration-test",
    )


def _vision_scene(state: TrafficLightState) -> SceneContext:
    return SceneContext(
        frame_index=42,
        timestamp=NOW,
        traffic_light_state=state,
        vehicle_signal_state=state,
        signal_states=[
            SceneSignalState(
                head_id="vision-head-1",
                phase=SignalPhase.VEHICLE,
                state=state,
                confidence=0.92,
                trust_score=0.92,
                stop_line_id="sl-1",
                source_kind=SignalStateSourceKind.VISION,
                observed_sources=[SignalStateSourceKind.VISION],
            )
        ],
        vision_signal_states=[
            SceneSignalState(
                head_id="vision-head-1",
                phase=SignalPhase.VEHICLE,
                state=state,
                confidence=0.92,
                trust_score=0.92,
                stop_line_id="sl-1",
                source_kind=SignalStateSourceKind.VISION,
                observed_sources=[SignalStateSourceKind.VISION],
            )
        ],
        integration_mode=SignalIntegrationMode.VISION_ONLY,
    )


def test_controller_only_snapshot_strengthens_signal_resolution() -> None:
    camera_id = uuid.uuid4()
    service = SignalIntegrationService()
    result = service.ingest_events(
        ControllerSignalBatch(
            events=[_controller_event(camera_id=camera_id, state=TrafficLightState.RED)]
        )
    )

    assert result.accepted_count == 1

    resolved = service.resolve_scene_context(
        camera_id=camera_id,
        timestamp=NOW,
        mode=SignalIntegrationMode.CONTROLLER_ONLY,
    )

    assert resolved.vehicle_signal_state_for_stop_line("sl-1") == TrafficLightState.RED
    assert resolved.signal_states[0].source_kind == SignalStateSourceKind.CONTROLLER
    assert resolved.controller_signal_states[0].controller_id == "controller-a"
    assert resolved.vision_signal_states == []


def test_hybrid_mode_flags_conflicts_instead_of_hiding_them() -> None:
    camera_id = uuid.uuid4()
    service = SignalIntegrationService()
    service.ingest_events(
        ControllerSignalBatch(
            events=[_controller_event(camera_id=camera_id, state=TrafficLightState.GREEN)]
        )
    )

    resolved = service.resolve_scene_context(
        camera_id=camera_id,
        vision_scene=_vision_scene(TrafficLightState.RED),
        timestamp=NOW,
        mode=SignalIntegrationMode.HYBRID,
    )

    assert resolved.vehicle_signal_state_for_stop_line("sl-1") == TrafficLightState.UNKNOWN
    assert len(resolved.signal_conflicts) == 1
    assert resolved.signal_conflicts[0].vision_state == TrafficLightState.RED
    assert resolved.signal_conflicts[0].controller_state == TrafficLightState.GREEN
    assert resolved.signal_states[0].source_kind == SignalStateSourceKind.RESOLVED
    assert resolved.signal_states[0].conflict_reason is not None


def test_unscoped_hybrid_resolution_does_not_pull_unrelated_controller_state() -> None:
    camera_id = uuid.uuid4()
    service = SignalIntegrationService()
    service.ingest_events(
        ControllerSignalBatch(
            events=[_controller_event(camera_id=camera_id, state=TrafficLightState.GREEN)]
        )
    )

    resolved = service.resolve_scene_context(
        vision_scene=_vision_scene(TrafficLightState.RED),
        timestamp=NOW,
        mode=SignalIntegrationMode.HYBRID,
    )

    assert resolved.vehicle_signal_state == TrafficLightState.RED
    assert resolved.controller_signal_states == []
    assert resolved.signal_conflicts == []


@pytest.mark.asyncio
async def test_polling_endpoint_ingests_normalized_signal_payload() -> None:
    camera_id = uuid.uuid4()
    service = SignalIntegrationService()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://signals.trafficmind.local/feed")
        return httpx.Response(
            200,
            json={
                "events": [
                    {
                        "camera_id": str(camera_id),
                        "junction_id": "j-main-1",
                        "controller_id": "controller-a",
                        "phase_id": "veh-main",
                        "phase": "vehicle",
                        "state": "red",
                        "timestamp": NOW.isoformat(),
                        "confidence": 0.96,
                        "trust_score": 0.94,
                        "stop_line_id": "sl-1",
                    }
                ]
            },
        )

    result = await service.poll_endpoint(
        SignalPollingRequest(
            url="https://signals.trafficmind.local/feed", source_label="poller-a"
        ),
        transport=httpx.MockTransport(handler),
    )

    assert result.accepted_count == 1
    snapshot = service.get_controller_snapshot(camera_id=camera_id, at_time=NOW)
    assert snapshot.usable_signal_count == 1
    assert snapshot.signal_states[0].state == TrafficLightState.RED
    assert snapshot.signal_states[0].source_id == "poller-a"


def test_mock_simulator_emits_current_cycle_step() -> None:
    camera_id = uuid.uuid4()
    service = SignalIntegrationService()
    request = MockSignalSimulatorRequest(
        camera_id=camera_id,
        junction_id="j-main-1",
        controller_id="controller-a",
        cycle_started_at=NOW,
        at_time=NOW.replace(second=25),
        steps=[
            MockSignalCycleStep(
                duration_seconds=20.0,
                states=[
                    MockSignalStateTemplate(
                        phase_id="veh-main",
                        phase=SignalPhase.VEHICLE,
                        state=TrafficLightState.GREEN,
                        stop_line_id="sl-1",
                    )
                ],
            ),
            MockSignalCycleStep(
                duration_seconds=20.0,
                states=[
                    MockSignalStateTemplate(
                        phase_id="veh-main",
                        phase=SignalPhase.VEHICLE,
                        state=TrafficLightState.RED,
                        stop_line_id="sl-1",
                    )
                ],
            ),
        ],
    )

    snapshot = service.simulate(request)

    assert snapshot.signal_states[0].state == TrafficLightState.RED
    assert snapshot.signal_states[0].source_kind == SignalStateSourceKind.CONTROLLER


def test_frame_pipeline_supports_controller_only_mode() -> None:
    camera_id = uuid.uuid4()
    service = SignalIntegrationService()
    service.ingest_events(
        ControllerSignalBatch(
            events=[_controller_event(camera_id=camera_id, state=TrafficLightState.RED)]
        )
    )

    pipeline = FramePipeline(
        PipelineFlags(detection=False, tracking=False, signals=False, ocr=False, rules=False),
        signal_integration_service=service,
        signal_integration_mode=SignalIntegrationMode.CONTROLLER_ONLY,
    )

    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    with pipeline:
        result = pipeline.process_frame(
            frame,
            frame_index=0,
            source_id="controller-only-demo",
            camera_id=camera_id,
            timestamp=NOW,
        )

    assert result.signal_snapshot is None
    assert result.controller_signal_snapshot is not None
    assert result.scene_context is not None
    assert result.scene_context.vehicle_signal_state_for_stop_line("sl-1") == TrafficLightState.RED
