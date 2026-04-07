"""Stream orchestrator — manages stream-processing workers.

The orchestrator is the single entry point for starting, stopping, and
querying jobs.  It enforces the concurrency limit and maintains the
in-memory job registry.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import uuid

from services.streams.config import StreamSettings, get_stream_settings
from services.streams.schemas import (
    JobListResponse,
    JobResponse,
    JobSpec,
    JobState,
    PipelineFlags,
    SourceKind,
    StartJobRequest,
    is_terminal,
    job_state_to_response,
)
from services.streams.worker import FrameCallback, StreamWorker

logger = logging.getLogger(__name__)


class OrchestratorError(RuntimeError):
    """Base exception for orchestrator failures."""


class JobNotFoundError(OrchestratorError):
    """Raised when a job ID is not in the registry."""


class ConcurrencyLimitError(OrchestratorError):
    """Raised when the concurrency cap is reached."""


class InvalidJobStateError(OrchestratorError):
    """Raised when an operation cannot be applied to the job's current state."""


class StreamOrchestrator:
    """Manages stream-processing workers within a single process.

    Thread-safe for reads; mutations must happen on the event loop that
    owns the orchestrator.
    """

    def __init__(
        self,
        settings: StreamSettings | None = None,
        *,
        on_frame: FrameCallback | None = None,
    ) -> None:
        self._settings = settings or get_stream_settings()
        self._on_frame = on_frame
        self._workers: dict[uuid.UUID, StreamWorker] = {}
        self._tasks: dict[uuid.UUID, asyncio.Task] = {}
        self._history: dict[uuid.UUID, JobState] = {}

    @property
    def settings(self) -> StreamSettings:
        return self._settings

    @property
    def active_count(self) -> int:
        return sum(1 for w in self._workers.values() if w.state.is_active)

    def get_job(self, job_id: uuid.UUID) -> JobState:
        if job_id in self._workers:
            return self._workers[job_id].state
        if job_id in self._history:
            return self._history[job_id]
        raise JobNotFoundError(f"Job {job_id} not found")

    def list_jobs(self, *, include_finished: bool = True) -> list[JobState]:
        active = [w.state for w in self._workers.values()]
        if not include_finished:
            return active
        finished = list(self._history.values())
        return active + finished

    def _ensure_capacity(self) -> None:
        if self.active_count >= self._settings.max_concurrent_jobs:
            raise ConcurrencyLimitError(
                f"Concurrency limit reached ({self._settings.max_concurrent_jobs}). "
                "Stop a running job before starting a new one."
            )

    def _launch_worker(self, spec: JobSpec) -> JobState:
        worker = StreamWorker(spec, self._settings, on_frame=self._on_frame)
        self._workers[spec.job_id] = worker

        task = asyncio.create_task(self._run_worker(worker), name=f"job-{spec.job_id}")
        self._tasks[spec.job_id] = task

        logger.info(
            "Started job %s  source=%s:%s  pipeline=%s",
            spec.job_id,
            spec.source_kind.value,
            spec.source_uri,
            spec.pipeline.model_dump(),
        )
        return worker.state

    async def start_job(self, request: StartJobRequest) -> JobState:
        """Create and start a new stream-processing job."""

        self._ensure_capacity()
        if request.source_kind is None or request.source_uri is None:
            msg = "Direct job starts require both source_kind and source_uri."
            raise ValueError(msg)

        spec = JobSpec(
            stream_id=request.stream_id,
            source_kind=request.source_kind,
            source_uri=request.source_uri,
            source_config=request.source_config,
            frame_step=request.frame_step or self._settings.default_frame_step,
            max_processing_fps=request.max_processing_fps or self._settings.default_max_processing_fps,
            max_frames=request.max_frames,
            pipeline=request.pipeline,
            requested_by=request.requested_by,
        )

        return self._launch_worker(spec)

    async def start_job_for_stream(
        self,
        *,
        stream_id: uuid.UUID,
        camera_id: uuid.UUID | None,
        source_kind: SourceKind,
        source_uri: str,
        source_config: dict[str, Any] | None = None,
        frame_step: int | None = None,
        max_processing_fps: float | None = None,
        max_frames: int | None = None,
        pipeline: PipelineFlags | None = None,
        requested_by: str | None = None,
    ) -> JobState:
        """Start a job directly from a CameraStream record.

        This is the path used by the API when a caller provides a ``stream_id``.
        """
        self._ensure_capacity()

        spec = JobSpec(
            stream_id=stream_id,
            camera_id=camera_id,
            source_kind=source_kind,
            source_uri=source_uri,
            source_config=source_config or {},
            frame_step=frame_step or self._settings.default_frame_step,
            max_processing_fps=max_processing_fps or self._settings.default_max_processing_fps,
            max_frames=max_frames,
            pipeline=pipeline or PipelineFlags(),
            requested_by=requested_by,
        )

        return self._launch_worker(spec)

    async def stop_job(self, job_id: uuid.UUID) -> JobState:
        """Gracefully stop a running job."""
        if job_id not in self._workers:
            if job_id in self._history:
                return self._history[job_id]
            raise JobNotFoundError(f"Job {job_id} not found")

        worker = self._workers[job_id]
        if is_terminal(worker.state.status):
            return worker.state

        worker.request_stop()

        task = self._tasks.get(job_id)
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=10.0)
            except asyncio.TimeoutError:
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=1.0)
                except asyncio.TimeoutError:
                    logger.warning("Job %s cancellation still pending after forced stop", job_id)
                except asyncio.CancelledError:
                    pass
                logger.warning("Job %s did not stop gracefully; cancelled", job_id)

        return worker.state

    async def restart_job(self, job_id: uuid.UUID) -> JobState:
        """Stop a running job and start a new one with the same spec."""
        old_state = await self.stop_job(job_id)
        old_spec = old_state.spec

        self._ensure_capacity()
        new_spec = old_spec.model_copy(
            update={
                "job_id": uuid.uuid4(),
                "created_at": datetime.now(timezone.utc),
            }
        )
        return self._launch_worker(new_spec)

    async def stop_all(self) -> list[JobState]:
        """Stop all active jobs.  Used during shutdown."""
        results = []
        job_ids = list(self._workers.keys())
        for job_id in job_ids:
            try:
                state = await self.stop_job(job_id)
                results.append(state)
            except Exception:
                logger.exception("Error stopping job %s during shutdown", job_id)
        return results

    def get_response(self, job_id: uuid.UUID) -> JobResponse:
        return job_state_to_response(self.get_job(job_id))

    def list_response(self, *, include_finished: bool = True) -> JobListResponse:
        jobs = self.list_jobs(include_finished=include_finished)
        return JobListResponse(
            items=[job_state_to_response(j) for j in jobs],
            total=len(jobs),
            active=sum(1 for j in jobs if j.is_active),
        )

    async def _run_worker(self, worker: StreamWorker) -> None:
        """Wrapper that moves finished workers to history."""
        try:
            await worker.run()
        finally:
            job_id = worker.job_id
            self._history[job_id] = worker.state
            self._workers.pop(job_id, None)
            self._tasks.pop(job_id, None)
            logger.info("Job %s moved to history (status=%s)", job_id, worker.state.status.value)
