from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select
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
    WorkflowStatus,
    WorkflowType,
    ZoneStatus,
    ZoneType,
)
from apps.api.app.db.models import (
    Camera,
    CameraStream,
    DetectionEvent,
    PlateRead,
    ViolationEvent,
    WorkflowRun,
    Zone,
)


@pytest.mark.asyncio
async def test_database_foundation_persists_core_entities() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    occurred_at = datetime.now(timezone.utc)

    async with session_factory() as session:
        camera = Camera(
            camera_code="CAM-001",
            name="Main St Northbound",
            location_name="Main St & 3rd Ave",
            approach="northbound",
            timezone="UTC",
            status=CameraStatus.ACTIVE,
            calibration_config={"homography": {"status": "pending"}},
        )
        stream = CameraStream(
            camera=camera,
            name="primary",
            stream_kind=StreamKind.PRIMARY,
            source_type=SourceType.RTSP,
            source_uri="rtsp://trafficmind.local/cam-001",
            source_config={"transport": "tcp"},
            status=StreamStatus.LIVE,
        )
        zone = Zone(
            camera=camera,
            name="stop-line-a",
            zone_type=ZoneType.STOP_LINE,
            status=ZoneStatus.ACTIVE,
            geometry={"points": [[0.1, 0.7], [0.8, 0.7]]},
            rules_config={"light_phase_required": "red"},
        )
        detection = DetectionEvent(
            camera=camera,
            stream=stream,
            zone=zone,
            event_type=DetectionEventType.LINE_CROSSING,
            occurred_at=occurred_at,
            object_class="car",
            confidence=0.97,
            bbox={"x1": 120, "y1": 240, "x2": 420, "y2": 510},
            event_payload={"direction": "northbound"},
        )
        plate_read = PlateRead(
            camera=camera,
            stream=stream,
            detection_event=detection,
            status=PlateReadStatus.OBSERVED,
            occurred_at=occurred_at,
            plate_text="ABC1234",
            normalized_plate_text="ABC1234",
            confidence=0.88,
            bbox={"x1": 200, "y1": 320, "x2": 300, "y2": 360},
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
        )
        workflow_run = WorkflowRun(
            camera=camera,
            detection_event=detection,
            violation_event=violation,
            workflow_type=WorkflowType.TRIAGE,
            status=WorkflowStatus.QUEUED,
            input_payload={"trigger": "violation"},
        )

        session.add_all([camera, stream, zone, detection, plate_read, violation, workflow_run])
        await session.commit()

        stored_violation = await session.scalar(
            select(ViolationEvent).where(ViolationEvent.violation_type == ViolationType.RED_LIGHT)
        )
        stored_workflow = await session.scalar(
            select(WorkflowRun).where(WorkflowRun.violation_event_id == violation.id)
        )

        assert stored_violation is not None
        assert stored_violation.plate_read_id == plate_read.id
        assert stored_workflow is not None
        assert stored_workflow.camera_id == camera.id
        assert camera.calibration_config["homography"]["status"] == "pending"

    await engine.dispose()