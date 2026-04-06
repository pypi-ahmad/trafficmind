from __future__ import annotations

import json
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.db.base import Base
from apps.api.app.db.enums import (
    CameraStatus,
    DetectionEventType,
    PlateReadStatus,
    SourceType,
    StreamKind,
    StreamStatus,
    ViolationSeverity,
    ViolationStatus,
    ViolationType,
    ZoneStatus,
    ZoneType,
)
from apps.api.app.db.models import Camera, CameraStream, DetectionEvent, PlateRead, ViolationEvent, Zone
from services.ocr.normalizer import normalize_plate_text

FIXTURES_ROOT = Path(__file__).resolve().parent


def load_json_fixture(relative_path: str) -> dict:
    return json.loads((FIXTURES_ROOT / relative_path).read_text(encoding="utf-8"))


async def make_sqlite_session_factory() -> tuple[async_sessionmaker, object]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False), engine


async def seed_camera(session, *, camera_code: str | None = None) -> Camera:
    camera = Camera(
        camera_code=camera_code or f"CAM-{uuid.uuid4().hex[:6]}",
        name="Sample Camera",
        location_name="Sample Junction",
        status=CameraStatus.ACTIVE,
        calibration_config={},
    )
    session.add(camera)
    await session.flush()
    return camera


async def seed_detection_event(
    session,
    camera: Camera,
    *,
    track_id: str | None = None,
    occurred_at,
) -> DetectionEvent:
    event = DetectionEvent(
        camera_id=camera.id,
        event_type=DetectionEventType.DETECTION,
        occurred_at=occurred_at,
        track_id=track_id,
        object_class="car",
        confidence=0.97,
        bbox={"x1": 10, "y1": 20, "x2": 100, "y2": 80},
        event_payload={},
    )
    session.add(event)
    await session.flush()
    return event


async def seed_plate_read(
    session,
    camera: Camera,
    plate_text: str,
    *,
    occurred_at,
    confidence: float = 0.92,
    country_code: str | None = None,
    region_code: str | None = None,
    status: PlateReadStatus = PlateReadStatus.OBSERVED,
    detection_event_id: uuid.UUID | None = None,
    crop_image_uri: str | None = None,
    source_frame_uri: str | None = None,
) -> PlateRead:
    plate_read = PlateRead(
        camera_id=camera.id,
        status=status,
        occurred_at=occurred_at,
        plate_text=plate_text,
        normalized_plate_text=normalize_plate_text(plate_text, country_code=country_code),
        confidence=confidence,
        country_code=country_code,
        region_code=region_code,
        detection_event_id=detection_event_id,
        bbox={"x1": 0, "y1": 0, "x2": 100, "y2": 50},
        crop_image_uri=crop_image_uri,
        source_frame_uri=source_frame_uri,
        ocr_metadata={},
    )
    session.add(plate_read)
    await session.flush()
    return plate_read


async def seed_evidence_incident(session, *, occurred_at) -> tuple[uuid.UUID, uuid.UUID]:
    camera = Camera(
        camera_code="CAM-EVAL-001",
        name="Signalized Approach",
        location_name="King Fahd & Tahlia",
        status=CameraStatus.ACTIVE,
        calibration_config={},
    )
    stream = CameraStream(
        camera=camera,
        name="primary",
        stream_kind=StreamKind.PRIMARY,
        source_type=SourceType.RTSP,
        source_uri="rtsp://trafficmind.local/evidence",
        source_config={},
        status=StreamStatus.LIVE,
        fps_hint=10.0,
    )
    zone = Zone(
        camera=camera,
        name="stop-line-a",
        zone_type=ZoneType.STOP_LINE,
        status=ZoneStatus.ACTIVE,
        geometry={"points": [[0.1, 0.8], [0.9, 0.8]]},
        rules_config={"rules": [{"rule_type": "red_light"}]},
    )
    detection = DetectionEvent(
        camera=camera,
        stream=stream,
        zone=zone,
        event_type=DetectionEventType.LINE_CROSSING,
        occurred_at=occurred_at,
        frame_index=42,
        track_id="T-123",
        object_class="car",
        confidence=0.98,
        bbox={"x1": 120, "y1": 200, "x2": 360, "y2": 420},
        event_payload={
            "direction": "northbound",
            "track_path": [{"x": 150, "y": 210}, {"x": 195, "y": 260}, {"x": 240, "y": 310}],
        },
        image_uri="s3://trafficmind/evidence/violation-frame.jpg",
        video_uri=None,
    )
    plate_read = PlateRead(
        camera=camera,
        stream=stream,
        detection_event=detection,
        status=PlateReadStatus.OBSERVED,
        occurred_at=occurred_at,
        plate_text="ABC1234",
        normalized_plate_text="ABC1234",
        confidence=0.92,
        country_code="SA",
        region_code="RUH",
        bbox={"x1": 180, "y1": 300, "x2": 250, "y2": 340},
        crop_image_uri="s3://trafficmind/evidence/plate-crop.jpg",
        source_frame_uri="s3://trafficmind/evidence/source-frame.jpg",
        ocr_metadata={},
    )
    violation = ViolationEvent(
        camera=camera,
        stream=stream,
        zone=zone,
        detection_event=detection,
        plate_read=plate_read,
        violation_type=ViolationType.RED_LIGHT,
        severity=ViolationSeverity.HIGH,
        status=ViolationStatus.OPEN,
        occurred_at=occurred_at,
        summary="Vehicle crossed the stop line on red.",
        evidence_image_uri="s3://trafficmind/evidence/review-keyframe.jpg",
        evidence_video_uri=None,
        rule_metadata={
            "rule_type": "red_light",
            "frame_index": 42,
            "track_id": "T-123",
            "certainty": 1.0,
            "explanation": {
                "rule_type": "red_light",
                "reason": "Vehicle crossed the stop line during red.",
                "frame_index": 42,
                "conditions_satisfied": ["signal_red_at_detection", "stop_line_crossed"],
                "details": {
                    "signal_state_at_decision": "red",
                    "signal_phase": "vehicle",
                    "signal_head_id": "veh-head-1",
                    "signal_confidence": 0.99,
                },
                "track_snapshot": {
                    "track_id": "T-123",
                    "bbox": {"x1": 120, "y1": 200, "x2": 360, "y2": 420},
                },
                "zone_info": {
                    "zone_id": "stop-line-a",
                    "zone_name": "Stop Line A",
                    "zone_type": "stop_line",
                    "geometry": {"points": [[0.1, 0.8], [0.9, 0.8]]},
                },
            },
        },
    )

    session.add_all([camera, stream, zone, detection, plate_read, violation])
    await session.flush()
    return violation.id, detection.id