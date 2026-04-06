"""Camera health and observability endpoints.

These endpoints aggregate data from **CameraStream** (database) and
**StreamOrchestrator** (in-memory job state) to produce derived health
signals.  Every metric exposed here traces to a real data source.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Request, status

from apps.api.app.api.dependencies import DbSession
from apps.api.app.db.enums import CameraStatus
from apps.api.app.services import CameraService
from apps.api.app.services.errors import NotFoundError
from services.health.assessor import HealthAssessor
from services.health.schemas import (
    CameraHealthReport,
    HealthDashboard,
    StreamHealthReport,
)
from services.streams.orchestrator import StreamOrchestrator
from services.streams.schemas import JobState

router = APIRouter(prefix="/observability", tags=["observability"])

_camera_service = CameraService()
_assessor = HealthAssessor()


def _get_orchestrator(request: Request) -> StreamOrchestrator | None:
    return getattr(request.app.state, "orchestrator", None)


def _find_job_for_stream(
    orchestrator: StreamOrchestrator | None,
    stream_id: uuid.UUID,
) -> JobState | None:
    """Find the latest observable job for a stream, preferring active jobs."""
    if orchestrator is None:
        return None
    candidates = [
        job_state
        for job_state in orchestrator.list_jobs(include_finished=True)
        if job_state.spec.stream_id == stream_id
    ]
    if not candidates:
        return None

    def sort_key(job_state: JobState) -> tuple[int, object]:
        timestamp = (
            job_state.last_heartbeat_at
            or job_state.stopped_at
            or job_state.started_at
            or job_state.spec.created_at
        )
        return (1 if job_state.is_active else 0, timestamp)

    return max(candidates, key=sort_key)


# ── Dashboard ───────────────────────────────────────────────────────────────


@router.get("/dashboard", response_model=HealthDashboard)
async def health_dashboard(
    request: Request,
    db_session: DbSession,
    camera_status: CameraStatus | None = Query(default=None, alias="status"),
) -> HealthDashboard:
    """Aggregate health summary for all cameras — designed for dashboards."""
    orchestrator = _get_orchestrator(request)

    cameras, _total = await _camera_service.list_cameras(
        db_session,
        status=camera_status,
        source_type=None,
        search=None,
        skip=0,
        limit=None,
    )

    camera_reports: list[CameraHealthReport] = []
    for camera in cameras:
        stream_reports = _assess_streams(camera.streams, orchestrator)
        report = _assessor.assess_camera(
            camera_id=camera.id,
            camera_code=camera.camera_code,
            camera_name=camera.name,
            camera_status=camera.status.value,
            stream_reports=stream_reports,
        )
        camera_reports.append(report)

    active_jobs = orchestrator.active_count if orchestrator else 0
    return _assessor.assess_dashboard(camera_reports, active_jobs=active_jobs)


# ── Per-camera health ──────────────────────────────────────────────────────


@router.get("/cameras/{camera_id}/health", response_model=CameraHealthReport)
async def camera_health(
    camera_id: uuid.UUID,
    request: Request,
    db_session: DbSession,
) -> CameraHealthReport:
    """Health assessment for a single camera and all its streams."""
    try:
        camera = await _camera_service.get_camera_detail(db_session, camera_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    orchestrator = _get_orchestrator(request)
    stream_reports = _assess_streams(camera.streams, orchestrator)

    return _assessor.assess_camera(
        camera_id=camera.id,
        camera_code=camera.camera_code,
        camera_name=camera.name,
        camera_status=camera.status.value,
        stream_reports=stream_reports,
    )


# ── Per-stream health ─────────────────────────────────────────────────────


@router.get("/streams/{stream_id}/health", response_model=StreamHealthReport)
async def stream_health(
    stream_id: uuid.UUID,
    request: Request,
    db_session: DbSession,
) -> StreamHealthReport:
    """Health assessment for a single stream."""
    try:
        stream = await _camera_service.get_stream(db_session, stream_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    orchestrator = _get_orchestrator(request)
    job_state = _find_job_for_stream(orchestrator, stream.id)

    return _assessor.assess_stream(
        stream_id=stream.id,
        stream_name=stream.name,
        camera_id=stream.camera_id,
        source_type=stream.source_type.value,
        db_status=stream.status.value,
        is_enabled=stream.is_enabled,
        last_heartbeat_at=stream.last_heartbeat_at,
        last_error=stream.last_error,
        fps_hint=stream.fps_hint,
        job_state=job_state,
    )


# ── Internal helpers ────────────────────────────────────────────────────────


def _assess_streams(
    streams: list,
    orchestrator: StreamOrchestrator | None,
) -> list[StreamHealthReport]:
    reports: list[StreamHealthReport] = []
    for stream in streams:
        job_state = _find_job_for_stream(orchestrator, stream.id)
        report = _assessor.assess_stream(
            stream_id=stream.id,
            stream_name=stream.name,
            camera_id=stream.camera_id,
            source_type=stream.source_type.value,
            db_status=stream.status.value,
            is_enabled=stream.is_enabled,
            last_heartbeat_at=stream.last_heartbeat_at,
            last_error=stream.last_error,
            fps_hint=stream.fps_hint,
            job_state=job_state,
        )
        reports.append(report)
    return reports
