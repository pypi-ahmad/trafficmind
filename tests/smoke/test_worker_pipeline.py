"""Integrated worker-pipeline test — proves the full e2e path works as one unit.

Runs a 5-frame synthetic scenario through the worker pipeline with stub
backends and an in-memory SQLite database, then verifies:

1. All frames were processed and persisted
2. DetectionEvent, PlateRead, and ViolationEvent rows exist in DB
3. Violations are FK-linked to their detection events
4. The summary statistics are internally consistent
5. Timestamps and track IDs are coherent end-to-end

This is the smoke test that proves the core product works as a system.

Run standalone::

    python -m pytest tests/smoke/test_worker_pipeline.py -v
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.db.base import Base
from apps.api.app.db.enums import (
    DetectionEventStatus,
    PlateReadStatus,
    ViolationStatus,
)
from apps.api.app.db.models import Camera, CameraStream, DetectionEvent, PlateRead, ViolationEvent
from packages.shared_types.geometry import BBox, ObjectCategory, Point2D
from services.ocr.interface import OcrEngine
from services.ocr.schemas import OcrResult
from services.rules.schemas import (
    LineCrossingRuleConfig,
    LineGeometry,
    StopLineCrossingRuleConfig,
    ZoneConfig,
)
from services.streams.schemas import PipelineFlags, SourceKind
from services.streams.worker_pipeline import run_worker_pipeline
from services.tracking.interface import Tracker
from services.tracking.schemas import TrackedObject, TrackingResult, TrajectoryPoint
from services.vision.interface import Detector
from services.vision.schemas import Detection, DetectionResult

# ---------------------------------------------------------------------------
# Constants — same 5-frame scenario as the golden-path smoke tests
# ---------------------------------------------------------------------------

T0 = datetime(2026, 4, 6, 12, 0, 0, tzinfo=UTC)
FRAME_MS = 33
STOP_LINE_Y = 300.0

TRAJECTORY: list[tuple[float, float]] = [
    (200, 260),  # frame 0 — above stop-line
    (200, 285),  # frame 1 — approaching
    (200, 320),  # frame 2 — crossed → line-crossing fires
    (200, 350),  # frame 3 — past line
    (200, 380),  # frame 4 — continues
]

FRAME = np.zeros((480, 640, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# Stub backends — deterministic, no GPU, no model files
# ---------------------------------------------------------------------------


class _PipelineDetector(Detector):
    """Returns one vehicle + one plate per frame along the canned trajectory."""

    def load_model(self) -> None:
        pass

    def unload(self) -> None:
        pass

    def detect(self, image, *, frame_index=None, timestamp=None, confidence=None):
        fi = frame_index or 0
        x, y = TRAJECTORY[min(fi, len(TRAJECTORY) - 1)]
        ts = timestamp or T0
        return DetectionResult(
            detections=[
                Detection(
                    class_name="car",
                    category=ObjectCategory.VEHICLE,
                    class_id=2,
                    confidence=0.92,
                    bbox=BBox(x1=x - 30, y1=y - 20, x2=x + 30, y2=y + 20),
                    frame_index=fi,
                    timestamp=ts,
                ),
                Detection(
                    class_name="license_plate",
                    category=ObjectCategory.PLATE,
                    class_id=0,
                    confidence=0.87,
                    bbox=BBox(x1=x - 15, y1=y + 10, x2=x + 15, y2=y + 20),
                    frame_index=fi,
                    timestamp=ts,
                ),
            ],
            frame_index=fi,
            timestamp=ts,
            source_width=640,
            source_height=480,
            inference_ms=3.0,
        )


class _PipelineTracker(Tracker):
    """Single-track tracker following the canned trajectory."""

    def __init__(self):
        self._step = 0
        self._first = True
        self._first_ts: datetime | None = None

    def update(self, detections):
        fi = detections.frame_index or 0
        ts = detections.timestamp or T0

        # Anchor timestamps to the first detection we actually receive so
        # trajectory / first_seen / last_seen are consistent with the
        # real clock timestamps produced by the worker pipeline.
        if self._first_ts is None:
            self._first_ts = ts

        pts = TRAJECTORY[: self._step + 1]
        traj = [
            TrajectoryPoint(
                point=Point2D(x=px, y=py),
                frame_index=fi - len(pts) + 1 + i,
                timestamp=self._first_ts + timedelta(milliseconds=(fi - len(pts) + 1 + i) * FRAME_MS),
            )
            for i, (px, py) in enumerate(pts)
        ]
        lx, ly = pts[-1]
        track = TrackedObject(
            track_id="wp-track-1",
            class_name="car",
            category=ObjectCategory.VEHICLE,
            bbox=BBox(x1=lx - 30, y1=ly - 20, x2=lx + 30, y2=ly + 20),
            confidence=0.92,
            first_seen_at=self._first_ts,
            last_seen_at=self._first_ts + timedelta(milliseconds=fi * FRAME_MS),
            first_seen_frame=0,
            last_seen_frame=fi,
            frame_count=len(pts),
            trajectory=traj,
        )
        new_ids = ["wp-track-1"] if self._first else []
        self._first = False
        self._step = min(self._step + 1, len(TRAJECTORY) - 1)
        return TrackingResult(
            tracks=[track],
            frame_index=fi,
            timestamp=ts,
            new_track_ids=new_ids,
        )

    def reset(self):
        self._step = 0
        self._first = True
        self._first_ts = None

    def get_active_tracks(self):
        return []

    def snapshot(self, *, include_inactive=False):
        return []


class _PipelineOcrEngine(OcrEngine):
    """Returns a fixed plate string for every crop."""

    def load_model(self):
        pass

    def unload(self):
        pass

    def recognize(self, image, *, context=None):
        return [
            OcrResult(
                recognized_text="WP 1234",
                confidence=0.93,
                bbox=BBox(x1=0, y1=0, x2=image.shape[1], y2=image.shape[0]),
            ),
        ]


# ---------------------------------------------------------------------------
# Zone configuration — horizontal stop-line at y=300
# ---------------------------------------------------------------------------


def _stop_line_zone() -> ZoneConfig:
    return ZoneConfig(
        zone_id="wp-stopline",
        name="Worker Pipeline Stop Line",
        zone_type="stop_line",
        geometry=LineGeometry(
            start=Point2D(x=50.0, y=STOP_LINE_Y),
            end=Point2D(x=600.0, y=STOP_LINE_Y),
        ),
        rules=[
            LineCrossingRuleConfig(cooldown_seconds=0.0),
            StopLineCrossingRuleConfig(
                cooldown_seconds=0.0,
                requires_red_light=False,
                confirmation_frames=1,
                min_post_crossing_seconds=0.0,
                min_post_crossing_distance_px=0.0,
            ),
        ],
    )


# ═══════════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.smoke
class TestWorkerPipeline:
    """Full source → detect → track → OCR → rules → persist integration."""

    @pytest.mark.asyncio
    async def test_full_pipeline_processes_and_persists(self) -> None:
        """Run the integrated worker pipeline and verify DB artifacts."""
        summary = await run_worker_pipeline(
            source_kind=SourceKind.TEST,
            source_uri="test://worker-pipeline",
            database_url="sqlite+aiosqlite:///:memory:",
            camera_code="WP-TEST-001",
            max_frames=5,
            flags=PipelineFlags(
                detection=True,
                tracking=True,
                signals=False,
                ocr=True,
                rules=True,
            ),
            zone_configs=[_stop_line_zone()],
            detector_factory=_PipelineDetector,
            tracker_factory=_PipelineTracker,
            ocr_engine_factory=_PipelineOcrEngine,
            log_every=0,
        )

        # All 5 frames processed, none failed
        assert summary.frames_processed == 5
        assert summary.frames_failed == 0
        assert summary.frames_read >= 5

        # Detections emitted (2 detections/frame × 5 frames = 10)
        assert summary.total_detections == 10

        # One track started
        assert summary.total_tracks_started == 1

        # One plate per frame (5 total)
        assert summary.total_plate_reads == 5

        # At least one violation (line-crossing on frame 2)
        assert summary.total_violations >= 1

        # DB persistence counters should be positive
        assert summary.persistence.detection_events >= 1
        assert summary.persistence.plate_reads == 5
        assert summary.persistence.violation_events >= 1

        # Camera and stream IDs were assigned
        assert summary.camera_id is not None
        assert summary.stream_id is not None

        # Timing recorded
        assert summary.elapsed_seconds > 0
        assert summary.avg_fps > 0

    @pytest.mark.asyncio
    async def test_pipeline_db_rows_are_correct(self) -> None:
        """Verify the actual DB rows match expected field values."""
        # Use an explicit engine so we can query after the pipeline finishes
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Run pipeline — we need to pass the same DB URL, but since it's
        # :memory: we must use the same engine.  Easiest approach: use
        # a temp file DB.
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "wp_test.db"
            db_url = f"sqlite+aiosqlite:///{db_path}"

            summary = await run_worker_pipeline(
                source_kind=SourceKind.TEST,
                source_uri="test://worker-pipeline-db",
                database_url=db_url,
                camera_code="WP-DB-001",
                max_frames=5,
                flags=PipelineFlags(
                    detection=True, tracking=True, signals=False, ocr=True, rules=True,
                ),
                zone_configs=[_stop_line_zone()],
                detector_factory=_PipelineDetector,
                tracker_factory=_PipelineTracker,
                ocr_engine_factory=_PipelineOcrEngine,
                log_every=0,
            )

            # Re-open the file DB to inspect rows
            verify_engine = create_async_engine(db_url)
            verify_factory = async_sessionmaker(verify_engine, expire_on_commit=False)

            async with verify_factory() as session:
                # Camera row exists
                cam_count = (await session.execute(select(func.count(Camera.id)))).scalar()
                assert cam_count == 1

                # Stream row exists
                stream_count = (await session.execute(select(func.count(CameraStream.id)))).scalar()
                assert stream_count == 1

                # Detection events persisted
                det_count = (await session.execute(select(func.count(DetectionEvent.id)))).scalar()
                assert det_count >= 1
                assert det_count == summary.persistence.detection_events

                # Plate reads persisted
                pr_count = (await session.execute(select(func.count(PlateRead.id)))).scalar()
                assert pr_count == 5
                assert pr_count == summary.persistence.plate_reads

                # Check plate text
                plates = (await session.execute(select(PlateRead))).scalars().all()
                for plate in plates:
                    assert plate.plate_text == "WP 1234"
                    assert plate.normalized_plate_text == "WP1234"
                    assert plate.status == PlateReadStatus.OBSERVED
                    assert plate.confidence >= 0.60
                    assert plate.occurred_at is not None

                # Violation events persisted
                ve_count = (await session.execute(select(func.count(ViolationEvent.id)))).scalar()
                assert ve_count >= 1
                assert ve_count == summary.persistence.violation_events

                # Violations have correct fields
                violations = (await session.execute(select(ViolationEvent))).scalars().all()
                for v in violations:
                    assert v.status == ViolationStatus.OPEN
                    assert v.violation_type is not None
                    assert v.severity is not None
                    assert v.occurred_at is not None
                    assert v.rule_metadata is not None

                # At least one violation is FK-linked to a detection
                linked = [v for v in violations if v.detection_event_id is not None]
                assert len(linked) >= 1

                # Detection events have valid fields
                dets = (await session.execute(select(DetectionEvent))).scalars().all()
                det_track_ids = set()
                det_timestamps = []
                for d in dets:
                    assert d.camera_id == summary.camera_id
                    assert d.stream_id == summary.stream_id
                    assert d.track_id is not None
                    assert d.occurred_at is not None
                    assert d.status == DetectionEventStatus.NEW
                    det_track_ids.add(d.track_id)
                    det_timestamps.append(d.occurred_at)

                # All detection events reference the same track (single-track scenario)
                assert det_track_ids == {"wp-track-1"}

                # Detection timestamps are monotonically non-decreasing
                assert det_timestamps == sorted(det_timestamps)

                # Violation track_ids must be a subset of detection track_ids
                violation_track_ids = set()
                for v in violations:
                    assert v.rule_metadata is not None
                    tid = v.rule_metadata.get("track_id")
                    assert tid is not None
                    violation_track_ids.add(tid)
                assert violation_track_ids <= det_track_ids

            await verify_engine.dispose()

    @pytest.mark.asyncio
    async def test_pipeline_without_zones_produces_no_violations(self) -> None:
        """Without zone configs, rules engine has nothing to evaluate."""
        summary = await run_worker_pipeline(
            source_kind=SourceKind.TEST,
            source_uri="test://no-zones",
            database_url="sqlite+aiosqlite:///:memory:",
            camera_code="WP-NOZONE-001",
            max_frames=5,
            flags=PipelineFlags(
                detection=True, tracking=True, signals=False, ocr=False, rules=True,
            ),
            zone_configs=[],
            detector_factory=_PipelineDetector,
            tracker_factory=_PipelineTracker,
            log_every=0,
        )

        assert summary.frames_processed == 5
        assert summary.total_violations == 0
        assert summary.total_plate_reads == 0
        assert summary.persistence.violation_events == 0

    @pytest.mark.asyncio
    async def test_pipeline_summary_consistency(self) -> None:
        """Summary metrics should be internally consistent."""
        summary = await run_worker_pipeline(
            source_kind=SourceKind.TEST,
            source_uri="test://consistency",
            database_url="sqlite+aiosqlite:///:memory:",
            camera_code="WP-CON-001",
            max_frames=3,
            flags=PipelineFlags(
                detection=True, tracking=True, signals=False, ocr=True, rules=True,
            ),
            zone_configs=[_stop_line_zone()],
            detector_factory=_PipelineDetector,
            tracker_factory=_PipelineTracker,
            ocr_engine_factory=_PipelineOcrEngine,
            log_every=0,
        )

        assert summary.frames_processed == 3
        assert summary.frames_failed == 0
        # DB plate reads must equal pipeline plate reads
        assert summary.persistence.plate_reads == summary.total_plate_reads
        # DB violation events must equal pipeline violations
        assert summary.persistence.violation_events == summary.total_violations
        # Must have a camera and stream
        assert summary.camera_id is not None
        assert summary.stream_id is not None
