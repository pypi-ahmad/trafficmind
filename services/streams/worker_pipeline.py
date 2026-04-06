"""Integrated worker pipeline — frame source → detect → track → OCR → rules → persist.

This module wires the full deterministic processing path:

    video/test source
        → FramePipeline (detection → tracking → optional OCR → rules)
        → persist_frame_result (DetectionEvent, PlateRead, ViolationEvent → DB)

It does NOT use LangGraph, queues, or any cold-path orchestration.
It is a single-process, single-job worker that proves the core product works
as an integrated system.

Usage (programmatic)::

    summary = await run_worker_pipeline(
        source_kind=SourceKind.FILE,
        source_uri="video.mp4",
        database_url="sqlite+aiosqlite:///trafficmind.db",
        zone_configs=[...],
    )

Usage (CLI)::

    python -m services.streams.worker_pipeline --source-uri video.mp4
    python -m services.streams.worker_pipeline --source-kind test --max-frames 30
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.api.app.db.base import Base
from apps.api.app.db.enums import CameraStatus, SourceType, StreamKind, StreamStatus
from apps.api.app.db.models import Camera, CameraStream
from services.ocr.interface import OcrEngine
from services.rules.schemas import ZoneConfig
from services.signals.schemas import SignalHeadConfig
from services.streams.frame_source import FrameSource, create_frame_source
from services.streams.persist import PersistenceSummary, persist_frame_result
from services.streams.pipeline import FramePipeline, FrameResult
from services.streams.schemas import PipelineFlags, SourceKind
from services.tracking.interface import Tracker
from services.vision.interface import Detector

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result summary
# ---------------------------------------------------------------------------


@dataclass
class WorkerPipelineSummary:
    """Aggregate statistics from a completed pipeline run."""

    frames_read: int = 0
    frames_processed: int = 0
    frames_failed: int = 0
    total_detections: int = 0
    total_tracks_started: int = 0
    total_plate_reads: int = 0
    total_violations: int = 0
    total_events_emitted: int = 0
    persistence: PersistenceSummary = field(default_factory=PersistenceSummary)
    elapsed_seconds: float = 0.0
    camera_id: uuid.UUID | None = None
    stream_id: uuid.UUID | None = None

    @property
    def avg_fps(self) -> float:
        if self.elapsed_seconds <= 0:
            return 0.0
        return self.frames_processed / self.elapsed_seconds

    def log_summary(self) -> None:
        logger.info(
            "Worker pipeline complete: frames_processed=%d elapsed=%.2fs avg_fps=%.1f "
            "detections=%d tracks_started=%d plate_reads=%d violations=%d "
            "db_rows(det=%d plate=%d viol=%d)",
            self.frames_processed,
            self.elapsed_seconds,
            self.avg_fps,
            self.total_detections,
            self.total_tracks_started,
            self.total_plate_reads,
            self.total_violations,
            self.persistence.detection_events,
            self.persistence.plate_reads,
            self.persistence.violation_events,
        )


# ---------------------------------------------------------------------------
# Database bootstrap
# ---------------------------------------------------------------------------


async def _ensure_schema(engine) -> None:
    """Create tables if they don't exist (for local dev / SQLite)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _ensure_camera_and_stream(
    session: AsyncSession,
    *,
    source_kind: SourceKind,
    source_uri: str,
    camera_code: str = "WORKER-001",
) -> tuple[Camera, CameraStream]:
    """Create or reuse a camera + stream row for the worker run.

    For local dev / smoke tests this ensures FK targets exist.
    """
    from sqlalchemy import select

    row = (
        await session.execute(select(Camera).where(Camera.camera_code == camera_code))
    ).scalar_one_or_none()

    if row is None:
        row = Camera(
            camera_code=camera_code,
            name=f"Worker Pipeline ({camera_code})",
            location_name="Local Worker",
            status=CameraStatus.ACTIVE,
            calibration_config={},
        )
        session.add(row)
        await session.flush()

    stream_source_type = (
        SourceType.RTSP if source_kind == SourceKind.RTSP else SourceType.FILE
    )
    stream = CameraStream(
        camera=row,
        name="worker-primary",
        stream_kind=StreamKind.PRIMARY,
        source_type=stream_source_type,
        source_uri=source_uri,
        source_config={},
        status=StreamStatus.LIVE,
        fps_hint=30.0,
    )
    session.add(stream)
    await session.flush()
    return row, stream


# ---------------------------------------------------------------------------
# Core pipeline runner
# ---------------------------------------------------------------------------


async def run_worker_pipeline(
    *,
    source_kind: SourceKind = SourceKind.TEST,
    source_uri: str = "test://pattern",
    source_config: dict[str, Any] | None = None,
    database_url: str = "sqlite+aiosqlite:///trafficmind.db",
    camera_code: str = "WORKER-001",
    max_frames: int | None = None,
    frame_step: int = 1,
    flags: PipelineFlags | None = None,
    zone_configs: list[ZoneConfig] | None = None,
    signal_head_configs: list[SignalHeadConfig] | None = None,
    detector_factory=None,
    tracker_factory=None,
    ocr_engine_factory=None,
    log_every: int = 10,
    create_schema: bool = True,
) -> WorkerPipelineSummary:
    """Run the full integrated worker pipeline: source → detect → track → rules → persist.

    Parameters
    ----------
    source_kind
        Type of frame source (file, test, rtsp).
    source_uri
        Path or URI for the source.
    database_url
        SQLAlchemy async database URL.
    camera_code
        Camera code for the worker run.  A Camera + CameraStream row will
        be created if it doesn't exist.
    max_frames
        Stop after this many frames.  ``None`` runs until the source ends.
    frame_step
        Process every Nth frame.  1 = every frame.
    flags
        Pipeline stage flags.  Defaults to detection + tracking + rules (no OCR).
    zone_configs
        Zone configurations for the rules engine.  Empty means no rules fire.
    detector_factory, tracker_factory, ocr_engine_factory
        Optional factories for test stubs.  ``None`` = use real backends.
    log_every
        Log a status line every N frames.  0 disables.
    create_schema
        Whether to create DB tables on startup (for local dev / SQLite).

    Returns
    -------
    WorkerPipelineSummary
        Aggregate statistics from the run.
    """

    pipeline_flags = flags or PipelineFlags(
        detection=True,
        tracking=True,
        signals=False,
        ocr=False,
        rules=True,
    )

    engine = create_async_engine(database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    if create_schema:
        await _ensure_schema(engine)

    # Ensure a camera + stream row for FK targets
    async with session_factory() as setup_session:
        camera, stream = await _ensure_camera_and_stream(
            setup_session,
            source_kind=source_kind,
            source_uri=source_uri,
            camera_code=camera_code,
        )
        await setup_session.commit()
        camera_id = camera.id
        stream_id = stream.id

    # Build the frame source
    source = create_frame_source(
        source_kind,
        source_uri,
        source_config=source_config or {},
    )

    # Build the pipeline
    pipeline = FramePipeline(
        pipeline_flags,
        detector_factory=detector_factory,
        tracker_factory=tracker_factory,
        ocr_engine_factory=ocr_engine_factory,
        zone_configs=zone_configs or [],
        signal_head_configs=signal_head_configs or [],
    )

    summary = WorkerPipelineSummary(camera_id=camera_id, stream_id=stream_id)
    t_start = time.monotonic()

    try:
        source.open()
        pipeline.start()
        logger.info(
            "Worker pipeline started: source=%s:%s camera=%s flags=%s",
            source_kind.value,
            source_uri,
            camera_code,
            pipeline_flags.model_dump(),
        )

        frame_index = 0

        while True:
            if max_frames is not None and summary.frames_processed >= max_frames:
                break

            ok, frame = source.read()
            if not ok:
                break
            summary.frames_read += 1

            if frame_index % frame_step != 0:
                frame_index += 1
                continue

            ts = datetime.now(UTC)

            try:
                result = pipeline.process_frame(
                    frame,
                    frame_index=frame_index,
                    source_id=source_uri,
                    camera_id=camera_id,
                    stream_id=stream_id,
                    timestamp=ts,
                )

                # Persist to database
                async with session_factory() as session:
                    ps = await persist_frame_result(
                        session,
                        result,
                        camera_id=camera_id,
                        stream_id=stream_id,
                    )
                    await session.commit()

                # Accumulate metrics
                summary.frames_processed += 1
                summary.total_detections += result.detection_count
                summary.total_plate_reads += len(result.plate_reads)
                summary.total_violations += len(result.violations)
                summary.total_events_emitted += result.event_count
                summary.persistence.detection_events += ps.detection_events
                summary.persistence.plate_reads += ps.plate_reads
                summary.persistence.violation_events += ps.violation_events

                if result.tracking_result is not None:
                    summary.total_tracks_started += len(result.tracking_result.new_track_ids)

                if log_every > 0 and (summary.frames_processed % log_every == 0 or result.violations):
                    logger.info(
                        "frame=%d detections=%d tracks=%d plates=%d "
                        "violations=%d latency_ms=%.1f db(det=%d plate=%d viol=%d)",
                        frame_index,
                        result.detection_count,
                        result.active_tracks,
                        len(result.plate_reads),
                        len(result.violations),
                        result.elapsed_ms,
                        ps.detection_events,
                        ps.plate_reads,
                        ps.violation_events,
                    )

            except Exception:
                summary.frames_failed += 1
                logger.exception("Frame %d processing/persist failed", frame_index)

            frame_index += 1

    finally:
        pipeline.stop()
        source.release()
        await engine.dispose()

    summary.elapsed_seconds = time.monotonic() - t_start
    summary.log_summary()
    return summary


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_parser():
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m services.streams.worker_pipeline",
        description=(
            "Run the integrated worker pipeline: "
            "video source → detect → track → OCR → rules → persist to DB."
        ),
    )
    parser.add_argument(
        "--source-kind",
        choices=[k.value for k in SourceKind],
        default=SourceKind.TEST.value,
        help="Frame source type (default: test pattern).",
    )
    parser.add_argument(
        "--source-uri",
        default="test://pattern",
        help="Path or URI of the frame source.",
    )
    parser.add_argument(
        "--database-url",
        default="sqlite+aiosqlite:///trafficmind.db",
        help="Async SQLAlchemy database URL.",
    )
    parser.add_argument(
        "--camera-code",
        default="WORKER-001",
        help="Camera code for the worker run.",
    )
    parser.add_argument("--max-frames", type=int, default=30)
    parser.add_argument("--frame-step", type=int, default=1)
    parser.add_argument("--log-every", type=int, default=10)
    parser.add_argument(
        "--disable-detection",
        action="store_true",
        help="Disable the detection stage.",
    )
    parser.add_argument(
        "--disable-tracking",
        action="store_true",
        help="Disable the tracking stage.",
    )
    parser.add_argument(
        "--enable-ocr",
        action="store_true",
        help="Enable OCR on detected plates (requires PaddleOCR weights).",
    )
    return parser


async def _cli_main() -> int:
    import asyncio

    parser = _build_parser()
    args = parser.parse_args()

    flags = PipelineFlags(
        detection=not args.disable_detection,
        tracking=not args.disable_tracking,
        signals=False,
        ocr=args.enable_ocr,
        rules=not args.disable_tracking,  # rules need tracking
    )

    try:
        summary = await run_worker_pipeline(
            source_kind=SourceKind(args.source_kind),
            source_uri=args.source_uri,
            database_url=args.database_url,
            camera_code=args.camera_code,
            max_frames=args.max_frames,
            frame_step=args.frame_step,
            flags=flags,
            log_every=args.log_every,
        )
    except Exception:
        logger.exception("Worker pipeline failed")
        return 1

    return 0 if summary.frames_failed == 0 else 1


def main() -> int:
    import asyncio

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    return asyncio.run(_cli_main())


if __name__ == "__main__":
    raise SystemExit(main())

