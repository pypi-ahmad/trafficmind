"""CLI demo for the real-time perception pipeline."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from services.runtime import RuntimeReadinessState, log_readiness_report
from services.streams.config import StreamSettings
from services.streams.orchestrator import JobNotFoundError, StreamOrchestrator
from services.streams.pipeline import FrameResult
from services.streams.schemas import (
    JobStatus,
    PipelineFlags,
    SourceKind,
    StartJobRequest,
    is_terminal,
)
from services.streams.startup import build_stream_startup_report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the realtime perception pipeline on a local file or test stream."
    )
    parser.add_argument(
        "--source-kind",
        choices=[kind.value for kind in SourceKind],
        default=SourceKind.TEST.value,
    )
    parser.add_argument("--source-uri", default="test://pattern")
    parser.add_argument("--max-frames", type=int, default=120)
    parser.add_argument("--frame-step", type=int, default=1)
    parser.add_argument("--max-processing-fps", type=float, default=None)
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Loop file sources instead of stopping at EOF.",
    )
    parser.add_argument("--disable-detection", action="store_true")
    parser.add_argument("--disable-tracking", action="store_true")
    parser.add_argument(
        "--check-config-only",
        action="store_true",
        help="Run startup sanity checks and exit without starting a worker.",
    )
    parser.add_argument("--log-every", type=int, default=10)
    parser.add_argument(
        "--events-jsonl",
        default=None,
        help="Optional path to append emitted event batches as JSONL.",
    )
    return parser


def _frame_callback_factory(*, log_every: int, events_jsonl: str | None):
    logger = logging.getLogger("services.streams.demo")
    output_path = Path(events_jsonl).resolve() if events_jsonl else None
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)

    def on_frame(_spec, result: FrameResult) -> None:
        if output_path is not None and result.event_batch is not None:
            with output_path.open("a", encoding="utf-8") as handle:
                handle.write(result.event_batch.model_dump_json())
                handle.write("\n")

        if log_every > 0 and (result.frame_index % log_every == 0 or result.event_count > 0):
            checkpoint_count = (
                result.event_batch.checkpoint_event_count if result.event_batch is not None else 0
            )
            logger.info(
                "frame=%d source=%s detections=%d active_tracks=%d "
                "events=%d checkpoints=%d latency_ms=%.2f",
                result.frame_index,
                result.metadata.get("source_id", "unknown"),
                result.detection_count,
                result.active_tracks,
                result.event_count,
                checkpoint_count,
                result.elapsed_ms,
            )

    return on_frame


async def _wait_for_job(orchestrator: StreamOrchestrator, job_id) -> object:
    while True:
        try:
            state = orchestrator.get_job(job_id)
        except JobNotFoundError:
            await asyncio.sleep(0.05)
            continue
        if is_terminal(state.status):
            return state
        await asyncio.sleep(0.1)


async def _run_demo(args: argparse.Namespace) -> int:
    settings = StreamSettings(file_loop=args.loop)
    pipeline = PipelineFlags(
        detection=not args.disable_detection,
        tracking=not args.disable_tracking,
    )
    startup_report = build_stream_startup_report(
        settings,
        detection_enabled=pipeline.detection,
        tracking_enabled=pipeline.tracking,
        ocr_enabled=pipeline.ocr,
        require_model_files=not args.check_config_only,
    )
    logger = logging.getLogger("services.streams.demo")
    log_readiness_report(logger, startup_report)
    if startup_report.status == RuntimeReadinessState.NOT_READY:
        return 1
    if args.check_config_only:
        logger.info("stream worker startup checks passed")
        return 0

    request = StartJobRequest(
        source_kind=SourceKind(args.source_kind),
        source_uri=args.source_uri,
        frame_step=args.frame_step,
        max_processing_fps=args.max_processing_fps,
        max_frames=args.max_frames,
        pipeline=pipeline,
    )

    orchestrator = StreamOrchestrator(
        settings,
        on_frame=_frame_callback_factory(
            log_every=args.log_every,
            events_jsonl=args.events_jsonl,
        ),
    )

    state = await orchestrator.start_job(request)
    final_state = await _wait_for_job(orchestrator, state.job_id)
    metrics = final_state.metrics
    logging.getLogger("services.streams.demo").info(
        "completed status=%s frames_read=%d processed=%d skipped=%d "
        "cadence_skips=%d backpressure_drops=%d events=%d",
        final_state.status.value,
        metrics.frames_read,
        metrics.frames_processed,
        metrics.frames_skipped,
        metrics.frames_skipped_cadence,
        metrics.frames_dropped_backpressure,
        metrics.events_emitted,
    )
    await orchestrator.stop_all()
    return 0 if final_state.status != JobStatus.FAILED else 1


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    return asyncio.run(_run_demo(args))


if __name__ == "__main__":
    raise SystemExit(main())
