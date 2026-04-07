"""Stream worker — owns the frame-read + pipeline loop for a single job.

Each worker runs in its own ``asyncio.Task``.  Heavy CV work (frame reads
and inference) is delegated to a thread executor so the event loop stays
responsive.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from services.signals.schemas import SignalHeadConfig
from services.streams.config import StreamSettings
from services.streams.frame_source import FrameSource, create_frame_source
from services.streams.pipeline import FramePipeline, FrameResult
from services.streams.schemas import (
    JobSpec,
    JobState,
    JobStatus,
    is_terminal,
    is_valid_transition,
)

logger = logging.getLogger(__name__)

FrameCallback = Callable[[JobSpec, FrameResult], Any]


def _resolve_signal_head_configs(source_config: dict[str, Any]) -> list[SignalHeadConfig]:
    raw_configs = source_config.get("signal_heads") or []
    return [
        cfg if isinstance(cfg, SignalHeadConfig) else SignalHeadConfig.model_validate(cfg)
        for cfg in raw_configs
    ]


class StreamWorker:
    """Manages the lifecycle of a single stream-processing job.

    Usage::

        worker = StreamWorker(spec, settings)
        task = asyncio.create_task(worker.run())
        # ... later ...
        worker.request_stop()
        await task
    """

    def __init__(
        self,
        spec: JobSpec,
        settings: StreamSettings,
        *,
        on_frame: FrameCallback | None = None,
    ) -> None:
        self._spec = spec
        self._settings = settings
        self._on_frame = on_frame
        self._state = JobState(spec=spec)
        self._stop_requested = asyncio.Event()
        self._pause_requested = asyncio.Event()
        self._frame_times: deque[float] = deque(maxlen=settings.metrics_window_size)
        self._last_metrics_log_at = 0.0
        self._touch_heartbeat(force=True)

    @property
    def state(self) -> JobState:
        return self._state

    @property
    def job_id(self):
        return self._spec.job_id

    def request_stop(self) -> None:
        """Signal the worker to stop gracefully after the current frame."""
        self._stop_requested.set()
        self._touch_heartbeat(force=True)
        if self._state.status in {JobStatus.RUNNING, JobStatus.PAUSED}:
            self._transition(JobStatus.STOPPING)

    def request_pause(self) -> None:
        self._pause_requested.set()

    def request_resume(self) -> None:
        self._pause_requested.clear()

    def _touch_heartbeat(self, *, force: bool = False) -> None:
        now = datetime.now(timezone.utc)
        last = self._state.last_heartbeat_at
        if force or last is None:
            self._state.last_heartbeat_at = now
            return
        elapsed = (now - last).total_seconds()
        if elapsed >= self._settings.heartbeat_interval_seconds:
            self._state.last_heartbeat_at = now

    def _transition(self, target: JobStatus, *, error: str | None = None) -> None:
        current = self._state.status
        if not is_valid_transition(current, target):
            logger.warning("Invalid transition %s → %s for job %s", current, target, self.job_id)
            return
        self._state.status = target
        now = datetime.now(timezone.utc)
        self._state.last_heartbeat_at = now
        if target == JobStatus.RUNNING and self._state.started_at is None:
            self._state.started_at = now
        if is_terminal(target):
            self._state.stopped_at = now
        if error is not None:
            self._state.error_message = error
        logger.info("Job %s: %s → %s", self.job_id, current.value, target.value)

    def _transition_to_stopped(self, *, error: str | None = None) -> None:
        if is_terminal(self._state.status):
            if error is not None and self._state.error_message is None:
                self._state.error_message = error
            self._touch_heartbeat(force=True)
            return

        current = self._state.status
        if current != JobStatus.STOPPING and is_valid_transition(current, JobStatus.STOPPING):
            self._transition(JobStatus.STOPPING)

        if is_valid_transition(self._state.status, JobStatus.STOPPED):
            self._transition(JobStatus.STOPPED, error=error)
        elif error is not None and self._state.error_message is None:
            self._state.error_message = error

        self._touch_heartbeat(force=True)

    async def run(self) -> JobState:
        """Execute the full worker lifecycle.  Returns the final JobState."""

        self._transition(JobStatus.STARTING)
        loop = asyncio.get_running_loop()

        source: FrameSource | None = None
        pipeline: FramePipeline | None = None

        try:
            source = create_frame_source(
                self._spec.source_kind,
                self._spec.source_uri,
                source_config=self._spec.source_config,
                loop=self._settings.file_loop,
            )
            pipeline = FramePipeline(
                self._spec.pipeline,
                signal_head_configs=_resolve_signal_head_configs(self._spec.source_config),
            )

            await loop.run_in_executor(None, source.open)
            await loop.run_in_executor(None, pipeline.start)

            self._transition(JobStatus.RUNNING)
            await self._frame_loop(source, pipeline, loop)

        except asyncio.CancelledError:
            self._transition_to_stopped(error="Task cancelled")
        except Exception as exc:
            self._transition(JobStatus.FAILED, error=str(exc))
            logger.exception("Job %s failed: %s", self.job_id, exc)
        finally:
            if pipeline is not None:
                try:
                    await loop.run_in_executor(None, pipeline.stop)
                except Exception as exc:
                    logger.exception("Job %s pipeline cleanup failed: %s", self.job_id, exc)
            if source is not None:
                try:
                    await loop.run_in_executor(None, source.release)
                except Exception as exc:
                    logger.exception("Job %s source cleanup failed: %s", self.job_id, exc)
            self._touch_heartbeat(force=True)

        return self._state

    async def _frame_loop(
        self,
        source: FrameSource,
        pipeline: FramePipeline,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        frame_index = 0
        processed = 0
        cadence_interval_frames = self._resolve_cadence_interval_frames(source.fps_hint)
        next_due_frame = 0.0
        desired_interval_frames = max(float(self._spec.frame_step), cadence_interval_frames)
        source_width, source_height = source.resolution

        while not self._stop_requested.is_set():
            if self._pause_requested.is_set():
                if self._state.status != JobStatus.PAUSED:
                    self._transition(JobStatus.PAUSED)
                self._touch_heartbeat()
                await asyncio.sleep(0.1)
                continue

            if self._state.status == JobStatus.PAUSED:
                self._transition(JobStatus.RUNNING)

            ok, frame = await loop.run_in_executor(None, source.read)
            if not ok:
                if source.is_live:
                    self._state.metrics.stream_read_failures += 1
                    self._state.metrics.reconnect_count += 1
                    self._touch_heartbeat(force=True)
                    if (
                        self._settings.max_reconnect_attempts > 0
                        and self._state.metrics.reconnect_count > self._settings.max_reconnect_attempts
                    ):
                        self._transition(JobStatus.FAILED, error="Max reconnect attempts exceeded")
                        return
                    await asyncio.sleep(self._settings.reconnect_delay_seconds)
                    continue
                else:
                    self._transition(JobStatus.COMPLETED)
                    return

            self._state.metrics.frames_read += 1
            self._touch_heartbeat()

            cadence_blocked = frame_index % self._spec.frame_step != 0 or frame_index + 1e-9 < next_due_frame
            if cadence_blocked:
                self._state.metrics.frames_skipped += 1
                self._state.metrics.frames_skipped_cadence += 1
                frame_index += 1
                continue

            try:
                result = await loop.run_in_executor(
                    None,
                    lambda: pipeline.process_frame(
                        frame,
                        frame_index=frame_index,
                        source_id=self._spec.source_id,
                        stream_id=self._spec.stream_id,
                        camera_id=self._spec.camera_id,
                        source_width=source_width or None,
                        source_height=source_height or None,
                    ),
                )
                self._record_metrics(result)
                next_due_frame = max(next_due_frame + cadence_interval_frames, float(frame_index) + 1.0)

                dropped_backpressure = await self._drop_backpressure_frames(
                    source=source,
                    loop=loop,
                    result=result,
                    desired_interval_frames=desired_interval_frames,
                )

                if self._on_frame is not None:
                    cb_result = self._on_frame(self._spec, result)
                    if asyncio.iscoroutine(cb_result):
                        await cb_result

                self._maybe_log_metrics(result)

            except Exception:
                self._state.metrics.frames_failed += 1
                logger.exception("Job %s: frame %d processing failed", self.job_id, frame_index)
                dropped_backpressure = 0

            frame_index += 1 + dropped_backpressure
            processed += 1

            if self._spec.max_frames is not None and processed >= self._spec.max_frames:
                self._transition(JobStatus.COMPLETED)
                return

            # Yield to event loop periodically
            if processed % 10 == 0:
                await asyncio.sleep(0)

        self._transition_to_stopped()

    def _record_metrics(self, result: FrameResult) -> None:
        m = self._state.metrics
        m.frames_processed += 1
        m.detections_total += result.detection_count
        m.tracks_active = result.active_tracks
        m.violations_total += len(result.violations)
        m.events_emitted += result.event_count
        m.last_processing_latency_ms = round(result.elapsed_ms, 2)
        m.last_frame_at = datetime.now(timezone.utc)
        m.last_successful_inference_at = m.last_frame_at
        self._state.last_heartbeat_at = m.last_frame_at

        self._frame_times.append(result.elapsed_ms)
        if self._frame_times:
            avg_ms = sum(self._frame_times) / len(self._frame_times)
            m.avg_inference_ms = round(avg_ms, 2)
            m.avg_fps = round(1000.0 / avg_ms, 2) if avg_ms > 0 else 0.0

    def _resolve_cadence_interval_frames(self, source_fps: float) -> float:
        if self._spec.max_processing_fps is None:
            return 1.0
        if source_fps <= 0:
            return 1.0
        return max(1.0, source_fps / self._spec.max_processing_fps)

    async def _drop_backpressure_frames(
        self,
        *,
        source: FrameSource,
        loop: asyncio.AbstractEventLoop,
        result: FrameResult,
        desired_interval_frames: float,
    ) -> int:
        if not source.is_live or not self._settings.drop_frames_when_behind:
            return 0
        if self._settings.max_backpressure_frame_drops <= 0 or source.fps_hint <= 0:
            return 0

        elapsed_source_frames = (result.elapsed_ms / 1000.0) * source.fps_hint
        behind_frames = math.floor(elapsed_source_frames - desired_interval_frames)
        if behind_frames <= 0:
            return 0

        drop_count = min(self._settings.max_backpressure_frame_drops, behind_frames)
        dropped = 0
        while dropped < drop_count and not self._stop_requested.is_set():
            ok, _frame = await loop.run_in_executor(None, source.read)
            if not ok:
                break
            dropped += 1
            self._state.metrics.frames_read += 1
            self._state.metrics.frames_skipped += 1
            self._state.metrics.frames_dropped_backpressure += 1

        return dropped

    def _maybe_log_metrics(self, result: FrameResult) -> None:
        now = time.perf_counter()
        if self._last_metrics_log_at and now - self._last_metrics_log_at < self._settings.metrics_log_interval_seconds:
            return

        self._last_metrics_log_at = now
        metrics = self._state.metrics
        logger.info(
            "Job %s metrics frame=%d source=%s read=%d processed=%d skipped=%d backpressure=%d detections=%d active_tracks=%d events=%d latency_ms=%.2f avg_fps=%.2f",
            self.job_id,
            result.frame_index,
            self._spec.source_id,
            metrics.frames_read,
            metrics.frames_processed,
            metrics.frames_skipped,
            metrics.frames_dropped_backpressure,
            result.detection_count,
            result.active_tracks,
            metrics.events_emitted,
            result.elapsed_ms,
            metrics.avg_fps,
        )
