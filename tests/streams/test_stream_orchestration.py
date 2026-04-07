"""Tests for the stream-processing orchestration layer.

Covers: schemas & state machine, frame sources, pipeline, worker lifecycle,
orchestrator concurrency, and API routes.
"""

from __future__ import annotations

import asyncio
import uuid

import numpy as np
import pytest
from pydantic import ValidationError

from services.streams.config import StreamSettings
from services.streams.frame_source import TestPatternSource, create_frame_source
from services.streams.orchestrator import (
    ConcurrencyLimitError,
    JobNotFoundError,
    StreamOrchestrator,
)
from services.streams.pipeline import FramePipeline, FrameResult
from services.streams.schemas import (
    JobSpec,
    JobState,
    JobStatus,
    PipelineFlags,
    SourceKind,
    StartJobRequest,
    is_terminal,
    is_valid_transition,
    job_state_to_response,
)
from services.streams.startup import build_stream_startup_report
from services.streams.worker import StreamWorker
from services.vision.config import VisionSettings

# ═══════════════════════════════════════════════════════════════════════════
# Schema / state-machine tests
# ═══════════════════════════════════════════════════════════════════════════


class TestJobStatusTransitions:
    """Verify the state machine enforces valid transitions."""

    def test_pending_to_starting(self) -> None:
        assert is_valid_transition(JobStatus.PENDING, JobStatus.STARTING)

    def test_pending_to_stopped(self) -> None:
        assert is_valid_transition(JobStatus.PENDING, JobStatus.STOPPED)

    def test_pending_to_running_invalid(self) -> None:
        assert not is_valid_transition(JobStatus.PENDING, JobStatus.RUNNING)

    def test_running_to_paused(self) -> None:
        assert is_valid_transition(JobStatus.RUNNING, JobStatus.PAUSED)

    def test_running_to_stopping(self) -> None:
        assert is_valid_transition(JobStatus.RUNNING, JobStatus.STOPPING)

    def test_running_to_completed(self) -> None:
        assert is_valid_transition(JobStatus.RUNNING, JobStatus.COMPLETED)

    def test_running_to_failed(self) -> None:
        assert is_valid_transition(JobStatus.RUNNING, JobStatus.FAILED)

    def test_paused_to_running(self) -> None:
        assert is_valid_transition(JobStatus.PAUSED, JobStatus.RUNNING)

    def test_stopped_is_terminal(self) -> None:
        assert is_terminal(JobStatus.STOPPED)

    def test_failed_is_terminal(self) -> None:
        assert is_terminal(JobStatus.FAILED)

    def test_completed_is_terminal(self) -> None:
        assert is_terminal(JobStatus.COMPLETED)

    def test_running_is_not_terminal(self) -> None:
        assert not is_terminal(JobStatus.RUNNING)

    def test_terminal_states_have_no_transitions(self) -> None:
        for status in (JobStatus.STOPPED, JobStatus.FAILED, JobStatus.COMPLETED):
            for target in JobStatus:
                assert not is_valid_transition(status, target)


class TestJobSpec:
    def test_defaults(self) -> None:
        spec = JobSpec(source_kind=SourceKind.TEST, source_uri="test://pattern")
        assert spec.job_id is not None
        assert spec.frame_step == 1
        assert spec.max_frames is None
        assert spec.pipeline.detection is True
        assert spec.pipeline.tracking is True
        assert spec.pipeline.ocr is False

    def test_immutable(self) -> None:
        spec = JobSpec(source_kind=SourceKind.TEST, source_uri="test://pattern")
        with pytest.raises(Exception):
            spec.frame_step = 5  # type: ignore[misc]


class TestStreamStartupReport:
    def test_missing_model_path_is_warning_for_non_strict_diagnostics(self, tmp_path) -> None:
        report = build_stream_startup_report(
            StreamSettings(),
            detection_enabled=True,
            tracking_enabled=True,
            ocr_enabled=False,
            require_model_files=False,
            vision_settings=VisionSettings(yolo_model_path=tmp_path / "missing.pt"),
        )

        assert report.status == "ready"
        assert any(check.code == "vision_model_path" and check.severity == "warning" for check in report.checks)

    def test_missing_model_path_blocks_detection_enabled_worker_preflight(self, tmp_path) -> None:
        report = build_stream_startup_report(
            StreamSettings(),
            detection_enabled=True,
            tracking_enabled=True,
            ocr_enabled=False,
            require_model_files=True,
            vision_settings=VisionSettings(yolo_model_path=tmp_path / "missing.pt"),
        )

        assert report.status == "not_ready"
        assert any(check.code == "vision_model_path" and check.severity == "error" for check in report.checks)


class TestJobState:
    def test_is_active_for_pending(self) -> None:
        state = JobState(spec=JobSpec(source_kind=SourceKind.TEST, source_uri="test://x"))
        assert state.is_active

    def test_is_active_false_for_terminal(self) -> None:
        state = JobState(
            spec=JobSpec(source_kind=SourceKind.TEST, source_uri="test://x"),
            status=JobStatus.COMPLETED,
        )
        assert not state.is_active


class TestJobResponseConversion:
    def test_round_trip(self) -> None:
        spec = JobSpec(
            source_kind=SourceKind.FILE,
            source_uri="/tmp/video.mp4",
            pipeline=PipelineFlags(detection=True, tracking=False),
        )
        state = JobState(spec=spec, status=JobStatus.RUNNING)
        resp = job_state_to_response(state)
        assert resp.job_id == spec.job_id
        assert resp.source_kind == SourceKind.FILE
        assert resp.status == JobStatus.RUNNING
        assert resp.pipeline.tracking is False


class TestStartJobRequest:
    def test_requires_direct_source_when_stream_is_missing(self) -> None:
        with pytest.raises(ValidationError):
            StartJobRequest()

    def test_rejects_mixed_stream_and_direct_source(self) -> None:
        with pytest.raises(ValidationError):
            StartJobRequest(
                stream_id=uuid.uuid4(),
                source_kind=SourceKind.TEST,
                source_uri="test://pattern",
            )


# ═══════════════════════════════════════════════════════════════════════════
# Frame-source tests
# ═══════════════════════════════════════════════════════════════════════════


class TestTestPatternSource:
    def test_reads_expected_frames(self) -> None:
        source = TestPatternSource(width=320, height=240, max_frames=5)
        source.open()
        frames = []
        for _ in range(10):
            ok, frame = source.read()
            if not ok:
                break
            frames.append(frame)
        source.release()
        assert len(frames) == 5

    def test_frame_shape(self) -> None:
        source = TestPatternSource(width=160, height=120, max_frames=1)
        source.open()
        ok, frame = source.read()
        source.release()
        assert ok
        assert frame is not None
        assert frame.shape == (120, 160, 3)

    def test_properties(self) -> None:
        source = TestPatternSource(width=640, height=480, fps=30.0)
        assert source.fps_hint == 30.0
        assert source.resolution == (640, 480)
        assert source.is_live is False

    def test_context_manager(self) -> None:
        with TestPatternSource(max_frames=2) as source:
            ok, _ = source.read()
            assert ok


class TestCreateFrameSource:
    def test_test_source(self) -> None:
        source = create_frame_source(SourceKind.TEST, "test://pattern")
        assert isinstance(source, TestPatternSource)

    def test_test_source_with_config(self) -> None:
        source = create_frame_source(
            SourceKind.TEST,
            "test://pattern",
            source_config={"width": 320, "height": 240, "max_frames": 10},
        )
        assert isinstance(source, TestPatternSource)
        assert source.resolution == (320, 240)

    def test_file_uri_is_normalized(self, tmp_path) -> None:
        video_path = tmp_path / "sample.mp4"
        video_path.write_bytes(b"")

        source = create_frame_source(SourceKind.FILE, video_path.as_uri())
        assert source.__class__.__name__ == "OpenCvSource"

    def test_upload_source_requires_local_path_metadata(self) -> None:
        with pytest.raises(ValueError, match="local_path"):
            create_frame_source(SourceKind.UPLOAD, "upload://incident-clip-001")


# ═══════════════════════════════════════════════════════════════════════════
# Pipeline tests (with mocked detector/tracker)
# ═══════════════════════════════════════════════════════════════════════════


class TestFramePipeline:
    def test_no_stages_enabled(self) -> None:
        flags = PipelineFlags(detection=False, tracking=False, ocr=False, rules=False)
        pipeline = FramePipeline(flags)
        pipeline.start()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        result = pipeline.process_frame(frame, frame_index=0)
        assert result.detection_result is None
        assert result.tracking_result is None
        assert result.elapsed_ms >= 0
        pipeline.stop()

    def test_context_manager(self) -> None:
        flags = PipelineFlags(detection=False, tracking=False)
        with FramePipeline(flags) as p:
            assert p.is_started
        assert not p.is_started

    def test_process_frame_returns_typed_result(self) -> None:
        flags = PipelineFlags(detection=False, tracking=False)
        with FramePipeline(flags) as p:
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            result = p.process_frame(frame, frame_index=42)
            assert isinstance(result, FrameResult)
            assert result.frame_index == 42
            assert result.detection_count == 0
            assert result.active_tracks == 0


# ═══════════════════════════════════════════════════════════════════════════
# Worker tests
# ═══════════════════════════════════════════════════════════════════════════


class TestStreamWorker:
    @staticmethod
    def _make_settings(**overrides: object) -> StreamSettings:
        defaults = {
            "max_concurrent_jobs": 2,
            "default_frame_step": 1,
            "metrics_window_size": 10,
            "max_reconnect_attempts": 1,
            "file_loop": False,
        }
        defaults.update(overrides)
        return StreamSettings(**defaults)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_worker_completes_test_pattern(self) -> None:
        """Worker processes a test-pattern source to completion."""
        spec = JobSpec(
            source_kind=SourceKind.TEST,
            source_uri="test://pattern",
            source_config={"max_frames": 5},
            pipeline=PipelineFlags(detection=False, tracking=False),
        )
        settings = self._make_settings()
        worker = StreamWorker(spec, settings)
        state = await worker.run()
        assert state.status == JobStatus.COMPLETED
        assert state.metrics.frames_read == 5
        assert state.metrics.frames_processed == 5
        assert state.started_at is not None
        assert state.stopped_at is not None

    @pytest.mark.asyncio
    async def test_worker_stop_request(self) -> None:
        """Worker stops gracefully when stop is requested."""
        spec = JobSpec(
            source_kind=SourceKind.TEST,
            source_uri="test://pattern",
            source_config={"max_frames": 10000},
            pipeline=PipelineFlags(detection=False, tracking=False),
        )
        settings = self._make_settings()
        worker = StreamWorker(spec, settings)

        async def stop_after_delay() -> None:
            await asyncio.sleep(0.05)
            worker.request_stop()

        asyncio.create_task(stop_after_delay())
        state = await worker.run()
        assert state.status == JobStatus.STOPPED

    @pytest.mark.asyncio
    async def test_worker_max_frames(self) -> None:
        """Worker completes after processing max_frames."""
        spec = JobSpec(
            source_kind=SourceKind.TEST,
            source_uri="test://pattern",
            source_config={"max_frames": 100},
            max_frames=3,
            pipeline=PipelineFlags(detection=False, tracking=False),
        )
        settings = self._make_settings()
        worker = StreamWorker(spec, settings)
        state = await worker.run()
        assert state.status == JobStatus.COMPLETED
        assert state.metrics.frames_processed == 3

    @pytest.mark.asyncio
    async def test_worker_frame_step(self) -> None:
        """Worker skips frames according to frame_step."""
        spec = JobSpec(
            source_kind=SourceKind.TEST,
            source_uri="test://pattern",
            source_config={"max_frames": 10},
            frame_step=3,
            pipeline=PipelineFlags(detection=False, tracking=False),
        )
        settings = self._make_settings()
        worker = StreamWorker(spec, settings)
        state = await worker.run()
        assert state.status == JobStatus.COMPLETED
        assert state.metrics.frames_read == 10
        # frames at indices 0,3,6,9 are processed
        assert state.metrics.frames_processed == 4
        assert state.metrics.frames_skipped == 6

    @pytest.mark.asyncio
    async def test_worker_callback_invoked(self) -> None:
        """on_frame callback fires for each processed frame."""
        received: list[FrameResult] = []

        def on_frame(spec: JobSpec, result: FrameResult) -> None:
            received.append(result)

        spec = JobSpec(
            source_kind=SourceKind.TEST,
            source_uri="test://pattern",
            source_config={"max_frames": 3},
            pipeline=PipelineFlags(detection=False, tracking=False),
        )
        settings = self._make_settings()
        worker = StreamWorker(spec, settings, on_frame=on_frame)
        await worker.run()
        assert len(received) == 3

    @pytest.mark.asyncio
    async def test_worker_metrics_populated(self) -> None:
        """Worker populates average inference and FPS metrics."""
        spec = JobSpec(
            source_kind=SourceKind.TEST,
            source_uri="test://pattern",
            source_config={"max_frames": 5},
            pipeline=PipelineFlags(detection=False, tracking=False),
        )
        settings = self._make_settings()
        worker = StreamWorker(spec, settings)
        state = await worker.run()
        assert state.metrics.avg_inference_ms >= 0
        assert state.metrics.avg_fps >= 0
        assert state.metrics.last_successful_inference_at is not None

    @pytest.mark.asyncio
    async def test_worker_counts_live_stream_read_failures(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Live-source read failures are counted separately from pipeline failures."""

        class FlakyLiveSource:
            def __init__(self) -> None:
                self._reads = 0

            def open(self) -> None:
                return None

            def read(self):
                self._reads += 1
                if self._reads <= 2:
                    return False, None
                return True, np.zeros((8, 8, 3), dtype=np.uint8)

            def release(self) -> None:
                return None

            @property
            def fps_hint(self) -> float:
                return 25.0

            @property
            def resolution(self) -> tuple[int, int]:
                return (8, 8)

            @property
            def is_live(self) -> bool:
                return True

        monkeypatch.setattr("services.streams.worker.create_frame_source", lambda *args, **kwargs: FlakyLiveSource())

        spec = JobSpec(
            source_kind=SourceKind.RTSP,
            source_uri="rtsp://flaky/live",
            max_frames=1,
            pipeline=PipelineFlags(detection=False, tracking=False),
        )
        settings = self._make_settings(max_reconnect_attempts=5, reconnect_delay_seconds=0.0)
        worker = StreamWorker(spec, settings)
        state = await worker.run()

        assert state.status == JobStatus.COMPLETED
        assert state.metrics.stream_read_failures == 2
        assert state.metrics.reconnect_count == 2
        assert state.metrics.frames_failed == 0

    @pytest.mark.asyncio
    async def test_worker_cancel_sets_terminal_state(self) -> None:
        """Task cancellation should not leave the worker in RUNNING."""
        spec = JobSpec(
            source_kind=SourceKind.TEST,
            source_uri="test://pattern",
            source_config={"max_frames": 10000},
            pipeline=PipelineFlags(detection=False, tracking=False),
        )
        settings = self._make_settings()
        worker = StreamWorker(spec, settings)
        task = asyncio.create_task(worker.run())

        await asyncio.sleep(0.05)
        task.cancel()
        state = await task

        assert state.status == JobStatus.STOPPED
        assert state.error_message == "Task cancelled"


# ═══════════════════════════════════════════════════════════════════════════
# Orchestrator tests
# ═══════════════════════════════════════════════════════════════════════════


class TestStreamOrchestrator:
    @staticmethod
    def _make_settings(**overrides: object) -> StreamSettings:
        defaults = {
            "max_concurrent_jobs": 2,
            "default_frame_step": 1,
            "metrics_window_size": 10,
            "max_reconnect_attempts": 1,
            "file_loop": False,
        }
        defaults.update(overrides)
        return StreamSettings(**defaults)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_start_and_complete_job(self) -> None:
        settings = self._make_settings()
        orch = StreamOrchestrator(settings)
        req = StartJobRequest(
            source_kind=SourceKind.TEST,
            source_uri="test://pattern",
            source_config={"max_frames": 3},
            pipeline=PipelineFlags(detection=False, tracking=False),
        )
        state = await orch.start_job(req)
        assert state.status in {JobStatus.PENDING, JobStatus.STARTING, JobStatus.RUNNING}

        # Wait for the job to complete
        for _ in range(50):
            await asyncio.sleep(0.05)
            try:
                current = orch.get_job(state.job_id)
            except JobNotFoundError:
                # moved to history — fetch from list
                jobs = orch.list_jobs(include_finished=True)
                found = [j for j in jobs if j.job_id == state.job_id]
                assert found, "Job vanished from history"
                current = found[0]
            if is_terminal(current.status):
                break
        assert current.status == JobStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_concurrency_limit(self) -> None:
        settings = self._make_settings(max_concurrent_jobs=1)
        orch = StreamOrchestrator(settings)
        req1 = StartJobRequest(
            source_kind=SourceKind.TEST,
            source_uri="test://pattern",
            source_config={"max_frames": 10000},
            pipeline=PipelineFlags(detection=False, tracking=False),
        )
        await orch.start_job(req1)

        req2 = StartJobRequest(
            source_kind=SourceKind.TEST,
            source_uri="test://pattern",
            source_config={"max_frames": 5},
            pipeline=PipelineFlags(detection=False, tracking=False),
        )
        with pytest.raises(ConcurrencyLimitError):
            await orch.start_job(req2)

        await orch.stop_all()

    @pytest.mark.asyncio
    async def test_stop_job(self) -> None:
        settings = self._make_settings()
        orch = StreamOrchestrator(settings)
        req = StartJobRequest(
            source_kind=SourceKind.TEST,
            source_uri="test://pattern",
            source_config={"max_frames": 10000},
            pipeline=PipelineFlags(detection=False, tracking=False),
        )
        state = await orch.start_job(req)
        # Give the task a moment to start
        await asyncio.sleep(0.05)

        stopped = await orch.stop_job(state.job_id)
        assert is_terminal(stopped.status)
        await orch.stop_all()

    @pytest.mark.asyncio
    async def test_stop_nonexistent_job_raises(self) -> None:
        settings = self._make_settings()
        orch = StreamOrchestrator(settings)
        with pytest.raises(JobNotFoundError):
            await orch.stop_job(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_list_jobs(self) -> None:
        settings = self._make_settings()
        orch = StreamOrchestrator(settings)
        req = StartJobRequest(
            source_kind=SourceKind.TEST,
            source_uri="test://pattern",
            source_config={"max_frames": 3},
            pipeline=PipelineFlags(detection=False, tracking=False),
        )
        await orch.start_job(req)
        jobs = orch.list_jobs(include_finished=False)
        assert len(jobs) >= 1
        await orch.stop_all()

    @pytest.mark.asyncio
    async def test_list_response(self) -> None:
        settings = self._make_settings()
        orch = StreamOrchestrator(settings)
        resp = orch.list_response()
        assert resp.total == 0
        assert resp.active == 0

    @pytest.mark.asyncio
    async def test_stop_all(self) -> None:
        settings = self._make_settings()
        orch = StreamOrchestrator(settings)
        for _ in range(2):
            await orch.start_job(
                StartJobRequest(
                    source_kind=SourceKind.TEST,
                    source_uri="test://pattern",
                    source_config={"max_frames": 10000},
                    pipeline=PipelineFlags(detection=False, tracking=False),
                )
            )
        assert orch.active_count == 2
        results = await orch.stop_all()
        assert len(results) == 2
        assert all(is_terminal(r.status) for r in results)

    @pytest.mark.asyncio
    async def test_restart_job(self) -> None:
        settings = self._make_settings()
        orch = StreamOrchestrator(settings)
        req = StartJobRequest(
            source_kind=SourceKind.TEST,
            source_uri="test://pattern",
            source_config={"max_frames": 10000},
            pipeline=PipelineFlags(detection=False, tracking=False),
        )
        state = await orch.start_job(req)
        await asyncio.sleep(0.05)

        new_state = await orch.restart_job(state.job_id)
        assert new_state.job_id != state.job_id  # new job
        assert new_state.status in {JobStatus.PENDING, JobStatus.STARTING, JobStatus.RUNNING}
        await orch.stop_all()

    @pytest.mark.asyncio
    async def test_stream_backed_job_preserves_camera_metadata_for_callbacks(self) -> None:
        settings = self._make_settings()
        seen_camera_ids: list[uuid.UUID | None] = []

        def on_frame(spec: JobSpec, result: FrameResult) -> None:
            seen_camera_ids.append(spec.camera_id)

        orch = StreamOrchestrator(settings, on_frame=on_frame)
        stream_id = uuid.uuid4()
        camera_id = uuid.uuid4()

        state = await orch.start_job_for_stream(
            stream_id=stream_id,
            camera_id=camera_id,
            source_kind=SourceKind.TEST,
            source_uri="test://pattern",
            source_config={"max_frames": 1},
            frame_step=1,
            max_frames=1,
            pipeline=PipelineFlags(detection=False, tracking=False),
        )

        for _ in range(20):
            await asyncio.sleep(0.05)
            current = orch.get_job(state.job_id)
            if is_terminal(current.status):
                break

        final_state = orch.get_job(state.job_id)
        assert final_state.spec.stream_id == stream_id
        assert final_state.spec.camera_id == camera_id
        assert seen_camera_ids == [camera_id]


# ═══════════════════════════════════════════════════════════════════════════
# API route tests
# ═══════════════════════════════════════════════════════════════════════════


class TestJobsAPI:
    """Integration tests for the /api/v1/jobs endpoints."""

    @staticmethod
    async def _create_test_app():
        """Build a test app with an in-memory DB and orchestrator."""
        from collections.abc import AsyncIterator

        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from apps.api.app.db.base import Base
        from apps.api.app.db.session import get_db_session
        from apps.api.app.main import create_app

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        app = create_app()
        settings = StreamSettings(
            max_concurrent_jobs=2,
            metrics_window_size=10,
            max_reconnect_attempts=1,
            file_loop=False,
        )
        app.state.orchestrator = StreamOrchestrator(settings)

        async def override_get_db_session() -> AsyncIterator[object]:
            async with session_factory() as session:
                yield session

        app.dependency_overrides[get_db_session] = override_get_db_session
        return app, engine

    @pytest.mark.asyncio
    async def test_start_job_endpoint(self) -> None:
        from httpx import ASGITransport, AsyncClient

        app, engine = await self._create_test_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            resp = await client.post(
                "/api/v1/jobs",
                json={
                    "source_kind": "test",
                    "source_uri": "test://pattern",
                    "source_config": {"max_frames": 3},
                    "pipeline": {"detection": False, "tracking": False},
                },
            )
            assert resp.status_code == 201
            data = resp.json()
            assert "job_id" in data
            assert data["source_kind"] == "test"
            assert data["status"] in ("pending", "starting", "running")

        await app.state.orchestrator.stop_all()
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_list_jobs_endpoint(self) -> None:
        from httpx import ASGITransport, AsyncClient

        app, engine = await self._create_test_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            resp = await client.get("/api/v1/jobs")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 0
            assert data["items"] == []

        await app.state.orchestrator.stop_all()
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_get_job_endpoint(self) -> None:
        from httpx import ASGITransport, AsyncClient

        app, engine = await self._create_test_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            start_resp = await client.post(
                "/api/v1/jobs",
                json={
                    "source_kind": "test",
                    "source_uri": "test://pattern",
                    "source_config": {"max_frames": 3},
                    "pipeline": {"detection": False, "tracking": False},
                },
            )
            job_id = start_resp.json()["job_id"]

            resp = await client.get(f"/api/v1/jobs/{job_id}")
            assert resp.status_code == 200
            assert resp.json()["job_id"] == job_id

        await app.state.orchestrator.stop_all()
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_get_nonexistent_job_returns_404(self) -> None:
        from httpx import ASGITransport, AsyncClient

        app, engine = await self._create_test_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            resp = await client.get(f"/api/v1/jobs/{uuid.uuid4()}")
            assert resp.status_code == 404

        await app.state.orchestrator.stop_all()
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_stop_job_endpoint(self) -> None:
        from httpx import ASGITransport, AsyncClient

        app, engine = await self._create_test_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            start_resp = await client.post(
                "/api/v1/jobs",
                json={
                    "source_kind": "test",
                    "source_uri": "test://pattern",
                    "source_config": {"max_frames": 10000},
                    "pipeline": {"detection": False, "tracking": False},
                },
            )
            job_id = start_resp.json()["job_id"]
            await asyncio.sleep(0.05)

            resp = await client.delete(f"/api/v1/jobs/{job_id}")
            assert resp.status_code == 200
            assert resp.json()["status"] in ("stopped", "stopping", "completed")

        await app.state.orchestrator.stop_all()
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_stop_all_endpoint(self) -> None:
        from httpx import ASGITransport, AsyncClient

        app, engine = await self._create_test_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            resp = await client.post("/api/v1/jobs/stop-all")
            assert resp.status_code == 200
            data = resp.json()
            assert data["active"] == 0

        await app.state.orchestrator.stop_all()
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_concurrency_limit_returns_429(self) -> None:
        from httpx import ASGITransport, AsyncClient

        settings = StreamSettings(
            max_concurrent_jobs=1,
            metrics_window_size=10,
            max_reconnect_attempts=1,
            file_loop=False,
        )
        app, engine = await self._create_test_app()
        app.state.orchestrator = StreamOrchestrator(settings)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            await client.post(
                "/api/v1/jobs",
                json={
                    "source_kind": "test",
                    "source_uri": "test://pattern",
                    "source_config": {"max_frames": 10000},
                    "pipeline": {"detection": False, "tracking": False},
                },
            )
            resp = await client.post(
                "/api/v1/jobs",
                json={
                    "source_kind": "test",
                    "source_uri": "test://pattern",
                    "source_config": {"max_frames": 5},
                    "pipeline": {"detection": False, "tracking": False},
                },
            )
            assert resp.status_code == 429

        await app.state.orchestrator.stop_all()
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_start_job_from_registered_stream(self) -> None:
        from httpx import ASGITransport, AsyncClient

        app, engine = await self._create_test_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            camera_resp = await client.post(
                "/api/v1/cameras",
                json={
                    "camera_code": "CAM-STREAM-001",
                    "name": "Worker Test Camera",
                    "location_name": "Test Bench",
                    "status": "active",
                    "calibration_config": {},
                },
            )
            assert camera_resp.status_code == 201
            camera_id = camera_resp.json()["id"]

            stream_resp = await client.post(
                f"/api/v1/cameras/{camera_id}/streams",
                json={
                    "name": "primary",
                    "stream_kind": "primary",
                    "source_type": "test",
                    "source_uri": "test://pattern",
                    "source_config": {"max_frames": 3},
                    "status": "offline",
                },
            )
            assert stream_resp.status_code == 201
            stream_id = stream_resp.json()["id"]

            job_resp = await client.post(
                "/api/v1/jobs",
                json={
                    "stream_id": stream_id,
                    "max_frames": 2,
                    "pipeline": {"detection": False, "tracking": False},
                },
            )
            assert job_resp.status_code == 201
            data = job_resp.json()
            assert data["stream_id"] == stream_id
            assert data["camera_id"] == camera_id
            assert data["source_kind"] == "test"
            assert data["source_uri"] == "test://pattern"

        await app.state.orchestrator.stop_all()
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_missing_source_selector_returns_422(self) -> None:
        from httpx import ASGITransport, AsyncClient

        app, engine = await self._create_test_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            resp = await client.post(
                "/api/v1/jobs",
                json={"pipeline": {"detection": False, "tracking": False}},
            )
            assert resp.status_code == 422

        await app.state.orchestrator.stop_all()
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_mixed_stream_and_direct_source_returns_422(self) -> None:
        from httpx import ASGITransport, AsyncClient

        app, engine = await self._create_test_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            resp = await client.post(
                "/api/v1/jobs",
                json={
                    "stream_id": str(uuid.uuid4()),
                    "source_kind": "test",
                    "source_uri": "test://pattern",
                },
            )
            assert resp.status_code == 422

        await app.state.orchestrator.stop_all()
        await engine.dispose()
