"""Stream-processing job management endpoints."""

from __future__ import annotations

import uuid
from typing import NoReturn

from fastapi import APIRouter, HTTPException, Query, Request, status

from apps.api.app.api.dependencies import DbSession
from apps.api.app.db.enums import StreamStatus
from apps.api.app.services import CameraService
from apps.api.app.services.errors import NotFoundError, ServiceValidationError
from services.streams.orchestrator import (
    ConcurrencyLimitError,
    JobNotFoundError,
    StreamOrchestrator,
)
from services.streams.schemas import (
    JobListResponse,
    JobResponse,
    StartJobRequest,
    job_state_to_response,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])
camera_service = CameraService()


def _get_orchestrator(request: Request) -> StreamOrchestrator:
    """Retrieve the orchestrator from app state."""
    orch: StreamOrchestrator | None = getattr(request.app.state, "orchestrator", None)
    if orch is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stream orchestrator not available",
        )
    return orch


def _raise_job_http_error(error: Exception) -> NoReturn:
    if isinstance(error, JobNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    if isinstance(error, NotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    if isinstance(error, ServiceValidationError):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    if isinstance(error, ConcurrencyLimitError):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(error)) from error
    raise error


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def start_job(body: StartJobRequest, request: Request, db_session: DbSession) -> JobResponse:
    """Start a new stream-processing job."""
    orch = _get_orchestrator(request)
    try:
        if body.stream_id is not None:
            stream = await camera_service.get_stream(db_session, body.stream_id)
            if not stream.is_enabled or stream.status == StreamStatus.DISABLED:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Cannot start a job for a disabled stream.",
                )

            state = await orch.start_job_for_stream(
                stream_id=stream.id,
                camera_id=stream.camera_id,
                source_kind=stream.source_type,
                source_uri=stream.source_uri,
                source_config=stream.source_config,
                frame_step=body.frame_step,
                max_processing_fps=body.max_processing_fps,
                max_frames=body.max_frames,
                pipeline=body.pipeline,
                requested_by=body.requested_by,
            )
        else:
            state = await orch.start_job(body)
    except (ConcurrencyLimitError, JobNotFoundError, NotFoundError, ServiceValidationError) as exc:
        _raise_job_http_error(exc)
    return job_state_to_response(state)


@router.get("", response_model=JobListResponse)
async def list_jobs(
    request: Request,
    include_finished: bool = Query(True, description="Include completed/failed/stopped jobs."),
) -> JobListResponse:
    """List all stream-processing jobs."""
    orch = _get_orchestrator(request)
    return orch.list_response(include_finished=include_finished)


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(request: Request, job_id: uuid.UUID) -> JobResponse:
    """Get details of a specific job."""
    orch = _get_orchestrator(request)
    try:
        return orch.get_response(job_id)
    except JobNotFoundError as exc:
        _raise_job_http_error(exc)


@router.delete("/{job_id}", response_model=JobResponse)
async def stop_job(request: Request, job_id: uuid.UUID) -> JobResponse:
    """Stop a running job."""
    orch = _get_orchestrator(request)
    try:
        state = await orch.stop_job(job_id)
    except JobNotFoundError as exc:
        _raise_job_http_error(exc)
    return job_state_to_response(state)


@router.post("/{job_id}/restart", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def restart_job(request: Request, job_id: uuid.UUID) -> JobResponse:
    """Restart a job — stops the existing one and starts a new job with the same spec."""
    orch = _get_orchestrator(request)
    try:
        state = await orch.restart_job(job_id)
    except (JobNotFoundError, ConcurrencyLimitError) as exc:
        _raise_job_http_error(exc)
    return job_state_to_response(state)


@router.post("/stop-all", response_model=JobListResponse)
async def stop_all_jobs(request: Request) -> JobListResponse:
    """Stop all active jobs.  Used for maintenance or shutdown preparation."""
    orch = _get_orchestrator(request)
    await orch.stop_all()
    return orch.list_response(include_finished=True)
