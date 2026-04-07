"""End-to-end persistence test — proves the full worker path saves DB artifacts.

Runs a 5-frame scenario through the golden-path stub backends and verifies
that DetectionEvent, PlateRead, and ViolationEvent rows land in an in-memory
SQLite database with correct foreign-key linkage.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.api.app.db.base import Base
from apps.api.app.db.enums import (
    CameraStatus,
    DetectionEventStatus,
    DetectionEventType,
    PlateReadStatus,
    SourceType,
    StreamKind,
    StreamStatus,
    ViolationStatus,
)
from apps.api.app.db.models import Camera, CameraStream, DetectionEvent, PlateRead, ViolationEvent
from packages.shared_types.geometry import BBox, ObjectCategory, Point2D
from packages.shared_types.scene import (
    SceneContext,
    SceneSignalState,
    SignalPhase,
    TrafficLightState,
)
from services.ocr.interface import OcrEngine
from services.ocr.schemas import OcrResult
from services.rules.schemas import (
    LineCrossingRuleConfig,
    LineGeometry,
    RedLightRuleConfig,
    StopLineCrossingRuleConfig,
    ZoneConfig,
)
from services.streams.persist import PersistenceSummary, persist_frame_result
from services.streams.pipeline import FramePipeline, FrameResult
from services.streams.schemas import PipelineFlags
from services.tracking.interface import Tracker
from services.tracking.schemas import TrackedObject, TrackingResult, TrajectoryPoint
from services.vision.interface import Detector
from services.vision.schemas import Detection, DetectionResult

# ---------------------------------------------------------------------------
# Constants (same scenario as test_golden_path)
# ---------------------------------------------------------------------------

T0 = datetime(2026, 4, 6, 12, 0, 0, tzinfo=UTC)
FRAME_MS = 33
STOP_LINE_Y = 300.0

TRAJECTORY: list[tuple[float, float]] = [
    (200, 260),
    (200, 285),
    (200, 320),
    (200, 350),
    (200, 380),
]

FRAME = np.zeros((480, 640, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# Stub backends (minimal copies from golden-path)
# ---------------------------------------------------------------------------


class _StubDetector(Detector):
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
            inference_ms=4.5,
        )


class _StubTracker(Tracker):
    def __init__(self):
        self._step = 0
        self._first = True

    def update(self, detections):
        fi = detections.frame_index or 0
        pts = TRAJECTORY[: self._step + 1]
        traj = [
            TrajectoryPoint(
                point=Point2D(x=px, y=py),
                frame_index=fi - len(pts) + 1 + i,
                timestamp=T0 + timedelta(milliseconds=(fi - len(pts) + 1 + i) * FRAME_MS),
            )
            for i, (px, py) in enumerate(pts)
        ]
        lx, ly = pts[-1]
        track = TrackedObject(
            track_id="e2e-track-1",
            class_name="car",
            category=ObjectCategory.VEHICLE,
            bbox=BBox(x1=lx - 30, y1=ly - 20, x2=lx + 30, y2=ly + 20),
            confidence=0.92,
            first_seen_at=T0,
            last_seen_at=T0 + timedelta(milliseconds=fi * FRAME_MS),
            first_seen_frame=0,
            last_seen_frame=fi,
            frame_count=len(pts),
            trajectory=traj,
        )
        new_ids = ["e2e-track-1"] if self._first else []
        self._first = False
        self._step = min(self._step + 1, len(TRAJECTORY) - 1)
        return TrackingResult(
            tracks=[track],
            frame_index=fi,
            timestamp=detections.timestamp,
            new_track_ids=new_ids,
        )

    def reset(self):
        self._step = 0
        self._first = True

    def get_active_tracks(self):
        return []

    def snapshot(self, *, include_inactive=False):
        return []


class _StubOcrEngine(OcrEngine):
    def load_model(self):
        pass

    def unload(self):
        pass

    def recognize(self, image, *, context=None):
        return [
            OcrResult(
                recognized_text="RHD 4831",
                confidence=0.94,
                bbox=BBox(x1=0, y1=0, x2=image.shape[1], y2=image.shape[0]),
            )
        ]


# ---------------------------------------------------------------------------
# Zone configuration
# ---------------------------------------------------------------------------


def _stop_line_zone() -> ZoneConfig:
    return ZoneConfig(
        zone_id="e2e-stopline",
        name="E2E Stop Line",
        zone_type="stop_line",
        geometry=LineGeometry(
            start=Point2D(x=50.0, y=STOP_LINE_Y),
            end=Point2D(x=600.0, y=STOP_LINE_Y),
        ),
        rules=[
            LineCrossingRuleConfig(cooldown_seconds=0.0),
            StopLineCrossingRuleConfig(
                cooldown_seconds=0.0,
                requires_red_light=True,
                confirmation_frames=1,
                min_post_crossing_seconds=0.0,
                min_post_crossing_distance_px=0.0,
            ),
            RedLightRuleConfig(
                cooldown_seconds=0.0,
                confirmation_frames=1,
                min_post_crossing_seconds=0.0,
                min_post_crossing_distance_px=0.0,
            ),
        ],
    )


def _red_light_scene(frame_index: int) -> SceneContext:
    return SceneContext(
        frame_index=frame_index,
        timestamp=T0 + timedelta(milliseconds=frame_index * FRAME_MS),
        traffic_light_state=TrafficLightState.RED,
        vehicle_signal_state=TrafficLightState.RED,
        signal_states=[
            SceneSignalState(
                head_id="e2e-head-1",
                phase=SignalPhase.VEHICLE,
                state=TrafficLightState.RED,
                confidence=0.95,
                frame_index=frame_index,
                stop_line_id="e2e-stopline",
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session():
    """In-memory SQLite async session with all tables created."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def camera(db_session: AsyncSession) -> Camera:
    cam = Camera(
        camera_code="CAM-E2E-001",
        name="E2E Test Camera",
        location_name="Test Junction",
        status=CameraStatus.ACTIVE,
        calibration_config={},
    )
    db_session.add(cam)
    await db_session.flush()
    return cam


@pytest_asyncio.fixture
async def stream(db_session: AsyncSession, camera: Camera) -> CameraStream:
    s = CameraStream(
        camera=camera,
        name="primary",
        stream_kind=StreamKind.PRIMARY,
        source_type=SourceType.FILE,
        source_uri="file:///test.mp4",
        source_config={},
        status=StreamStatus.LIVE,
        fps_hint=30.0,
    )
    db_session.add(s)
    await db_session.flush()
    return s


@pytest.fixture
def pipeline() -> FramePipeline:
    return FramePipeline(
        PipelineFlags(detection=True, tracking=True, signals=False, ocr=True, rules=True),
        detector_factory=_StubDetector,
        tracker_factory=_StubTracker,
        ocr_engine_factory=_StubOcrEngine,
        zone_configs=[_stop_line_zone()],
    )


@pytest.fixture
def frame_results(pipeline: FramePipeline) -> list[FrameResult]:
    """Run 5 frames through the pipeline, injecting red-light on frames 3-4."""
    results: list[FrameResult] = []
    with pipeline:
        for fi in range(5):
            ts = T0 + timedelta(milliseconds=fi * FRAME_MS)
            result = pipeline.process_frame(
                FRAME,
                frame_index=fi,
                source_id="e2e-test",
                camera_id=uuid.UUID("aaaa0000-0000-4000-8000-000000000001"),
                stream_id=uuid.UUID("bbbb0000-0000-4000-8000-000000000001"),
                timestamp=ts,
            )
            results.append(result)
            if fi >= 2 and hasattr(pipeline, "_rules_engine") and pipeline._rules_engine:
                pipeline._scene_context = _red_light_scene(fi)
    return results


# ═══════════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.smoke
class TestE2EPersistence:
    """Verify pipeline results persist to DB with correct rows and FK linkage."""

    @pytest.mark.asyncio
    async def test_persist_all_frames(
        self,
        db_session: AsyncSession,
        camera: Camera,
        stream: CameraStream,
        frame_results: list[FrameResult],
    ) -> None:
        """Persist 5 frames and verify aggregate row counts."""
        totals = PersistenceSummary()
        for result in frame_results:
            s = await persist_frame_result(
                db_session,
                result,
                camera_id=camera.id,
                stream_id=stream.id,
            )
            totals.detection_events += s.detection_events
            totals.plate_reads += s.plate_reads
            totals.violation_events += s.violation_events

        await db_session.commit()

        # At least one detection event (TRACK_STARTED on frame 0)
        det_count = (await db_session.execute(select(func.count(DetectionEvent.id)))).scalar()
        assert det_count >= 1, f"Expected ≥1 detection events, got {det_count}"
        assert det_count == totals.detection_events

        # One plate read per frame (5 total)
        pr_count = (await db_session.execute(select(func.count(PlateRead.id)))).scalar()
        assert pr_count == 5, f"Expected 5 plate reads, got {pr_count}"
        assert pr_count == totals.plate_reads

        # At least one violation (line-crossing on frame 2)
        ve_count = (await db_session.execute(select(func.count(ViolationEvent.id)))).scalar()
        assert ve_count >= 1, f"Expected ≥1 violation events, got {ve_count}"
        assert ve_count == totals.violation_events

    @pytest.mark.asyncio
    async def test_detection_events_have_correct_fields(
        self,
        db_session: AsyncSession,
        camera: Camera,
        stream: CameraStream,
        frame_results: list[FrameResult],
    ) -> None:
        """Verify DetectionEvent rows have expected column values."""
        for result in frame_results:
            await persist_frame_result(
                db_session, result, camera_id=camera.id, stream_id=stream.id,
            )
        await db_session.commit()

        rows = (await db_session.execute(select(DetectionEvent))).scalars().all()
        assert len(rows) >= 1

        for row in rows:
            assert row.camera_id == camera.id
            assert row.stream_id == stream.id
            assert row.event_type in (
                DetectionEventType.DETECTION,
                DetectionEventType.LINE_CROSSING,
            )
            assert row.status == DetectionEventStatus.NEW
            assert row.track_id is not None
            assert row.confidence > 0
            assert row.occurred_at is not None

    @pytest.mark.asyncio
    async def test_plate_reads_have_correct_fields(
        self,
        db_session: AsyncSession,
        camera: Camera,
        stream: CameraStream,
        frame_results: list[FrameResult],
    ) -> None:
        """Verify PlateRead rows have expected OCR data."""
        for result in frame_results:
            await persist_frame_result(
                db_session, result, camera_id=camera.id, stream_id=stream.id,
            )
        await db_session.commit()

        rows = (await db_session.execute(select(PlateRead))).scalars().all()
        assert len(rows) == 5

        for row in rows:
            assert row.camera_id == camera.id
            assert row.stream_id == stream.id
            assert row.status == PlateReadStatus.OBSERVED
            assert row.plate_text == "RHD 4831"
            assert row.normalized_plate_text == "RHD4831"
            assert row.confidence >= 0.60
            assert row.occurred_at is not None

    @pytest.mark.asyncio
    async def test_violation_events_have_correct_fields(
        self,
        db_session: AsyncSession,
        camera: Camera,
        stream: CameraStream,
        frame_results: list[FrameResult],
    ) -> None:
        """Verify ViolationEvent rows have expected rule data."""
        for result in frame_results:
            await persist_frame_result(
                db_session, result, camera_id=camera.id, stream_id=stream.id,
            )
        await db_session.commit()

        rows = (await db_session.execute(select(ViolationEvent))).scalars().all()
        assert len(rows) >= 1

        for row in rows:
            assert row.camera_id == camera.id
            assert row.stream_id == stream.id
            assert row.status == ViolationStatus.OPEN
            assert row.violation_type is not None
            assert row.severity is not None
            assert row.occurred_at is not None
            assert row.rule_metadata is not None
            assert "rule_type" in row.rule_metadata

    @pytest.mark.asyncio
    async def test_violation_linked_to_detection_event(
        self,
        db_session: AsyncSession,
        camera: Camera,
        stream: CameraStream,
        frame_results: list[FrameResult],
    ) -> None:
        """Violations should be FK-linked to the detection event for the same track."""
        for result in frame_results:
            await persist_frame_result(
                db_session, result, camera_id=camera.id, stream_id=stream.id,
            )
        await db_session.commit()

        violations = (await db_session.execute(select(ViolationEvent))).scalars().all()
        linked = [v for v in violations if v.detection_event_id is not None]
        assert len(linked) >= 1, "Expected at least one violation linked to a detection event"

        # Verify the linked detection event exists and shares the same camera
        for v in linked:
            det = (
                await db_session.execute(
                    select(DetectionEvent).where(DetectionEvent.id == v.detection_event_id)
                )
            ).scalar_one()
            assert det.camera_id == v.camera_id

    @pytest.mark.asyncio
    async def test_persist_summary_matches_db_counts(
        self,
        db_session: AsyncSession,
        camera: Camera,
        stream: CameraStream,
        frame_results: list[FrameResult],
    ) -> None:
        """PersistenceSummary counters must match actual DB row counts."""
        totals = PersistenceSummary()
        for result in frame_results:
            s = await persist_frame_result(
                db_session, result, camera_id=camera.id, stream_id=stream.id,
            )
            totals.detection_events += s.detection_events
            totals.plate_reads += s.plate_reads
            totals.violation_events += s.violation_events

        await db_session.commit()

        det_count = (await db_session.execute(select(func.count(DetectionEvent.id)))).scalar()
        pr_count = (await db_session.execute(select(func.count(PlateRead.id)))).scalar()
        ve_count = (await db_session.execute(select(func.count(ViolationEvent.id)))).scalar()

        assert totals.detection_events == det_count
        assert totals.plate_reads == pr_count
        assert totals.violation_events == ve_count
