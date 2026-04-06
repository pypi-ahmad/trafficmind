"""External traffic-signal integration endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from services.rules.schemas import SceneContext, SignalIntegrationMode
from services.signals.integration import (
    ControllerSignalBatch,
    ControllerSignalSnapshot,
    FileSignalFeedIngestRequest,
    MockSignalSimulatorRequest,
    SignalIngestResult,
    SignalIntegrationService,
    SignalPollingRequest,
)

router = APIRouter(prefix="/signals", tags=["signals"])


class SignalResolveRequest(BaseModel):
    """Resolve controller-fed and vision-derived signal state into one scene."""

    model_config = ConfigDict(frozen=True)

    mode: SignalIntegrationMode = SignalIntegrationMode.HYBRID
    camera_id: uuid.UUID | None = None
    junction_id: str | None = None
    timestamp: datetime | None = None
    vision_scene_context: SceneContext | None = None


def _get_signal_integration_service(request: Request) -> SignalIntegrationService:
    service = getattr(request.app.state, "signal_integration_service", None)
    if service is None:
        service = SignalIntegrationService()
        request.app.state.signal_integration_service = service
    return service


@router.post("/controller/events", response_model=SignalIngestResult)
async def ingest_controller_signal_events(
    request: Request,
    body: ControllerSignalBatch,
) -> SignalIngestResult:
    """Ingest a normalized controller signal event batch (webhook or direct push)."""
    return _get_signal_integration_service(request).ingest_events(body)


@router.post("/controller/file-feed", response_model=SignalIngestResult)
async def ingest_controller_signal_file_feed(
    request: Request,
    body: FileSignalFeedIngestRequest,
) -> SignalIngestResult:
    """Parse and ingest a JSON or JSONL file-feed payload."""
    return _get_signal_integration_service(request).ingest_file_feed(body)


@router.post("/controller/poll", response_model=SignalIngestResult)
async def poll_controller_signal_endpoint(
    request: Request,
    body: SignalPollingRequest,
) -> SignalIngestResult:
    """Poll an HTTP endpoint once and ingest the returned signal payload."""
    return await _get_signal_integration_service(request).poll_endpoint(body)


@router.post("/controller/mock/simulate", response_model=ControllerSignalSnapshot)
async def simulate_controller_signals(
    request: Request,
    body: MockSignalSimulatorRequest,
) -> ControllerSignalSnapshot:
    """Build or ingest a mock/local controller snapshot for demo and testing."""
    return _get_signal_integration_service(request).simulate(body)


@router.get("/controller/snapshot", response_model=ControllerSignalSnapshot)
async def get_controller_signal_snapshot(
    request: Request,
    camera_id: uuid.UUID | None = None,
    junction_id: str | None = None,
    timestamp: datetime | None = None,
) -> ControllerSignalSnapshot:
    """Inspect the current normalized controller-fed signal state."""
    return _get_signal_integration_service(request).get_controller_snapshot(
        camera_id=camera_id,
        junction_id=junction_id,
        at_time=timestamp,
    )


@router.post("/resolve", response_model=SceneContext)
async def resolve_signal_scene_context(
    request: Request,
    body: SignalResolveRequest,
) -> SceneContext:
    """Resolve controller-fed and vision-derived signal state into one scene context."""
    return _get_signal_integration_service(request).resolve_scene_context(
        vision_scene=body.vision_scene_context,
        camera_id=body.camera_id,
        junction_id=body.junction_id,
        timestamp=body.timestamp,
        mode=body.mode,
    )
