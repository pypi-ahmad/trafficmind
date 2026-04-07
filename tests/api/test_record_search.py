"""Integration tests for structured record search endpoints."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.db.base import Base
from apps.api.app.db.enums import (
    CameraStatus,
    DetectionEventStatus,
    DetectionEventType,
    PlateReadStatus,
    ViolationSeverity,
    ViolationStatus,
    ViolationType,
    ZoneStatus,
    ZoneType,
)
from apps.api.app.db.models import Camera, DetectionEvent, PlateRead, ViolationEvent, Zone
from apps.api.app.db.session import get_db_session
from apps.api.app.main import create_app
from services.ocr.normalizer import normalize_plate_text


@pytest.fixture
async def client() -> AsyncIterator[tuple[AsyncClient, async_sessionmaker]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app()

    async def override_get_db_session() -> AsyncIterator[object]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as http_client:
        yield http_client, session_factory

    await engine.dispose()


async def _seed_camera(session, code: str, name: str, location: str) -> Camera:
    camera = Camera(
        camera_code=code,
        name=name,
        location_name=location,
        timezone="UTC",
        status=CameraStatus.ACTIVE,
        calibration_config={},
    )
    session.add(camera)
    await session.flush()
    return camera


async def _seed_zone(session, camera: Camera, *, name: str, zone_type: ZoneType) -> Zone:
    zone = Zone(
        camera_id=camera.id,
        name=name,
        zone_type=zone_type,
        status=ZoneStatus.ACTIVE,
        geometry={"points": [{"x": 0, "y": 0}, {"x": 10, "y": 0}, {"x": 10, "y": 10}]},
        rules_config={},
        sort_order=0,
    )
    session.add(zone)
    await session.flush()
    return zone


async def _seed_detection_event(
    session,
    camera: Camera,
    *,
    occurred_at: datetime,
    zone: Zone | None = None,
    object_class: str = "car",
    event_type: DetectionEventType = DetectionEventType.LINE_CROSSING,
    status: DetectionEventStatus = DetectionEventStatus.NEW,
) -> DetectionEvent:
    event = DetectionEvent(
        camera_id=camera.id,
        zone_id=zone.id if zone is not None else None,
        event_type=event_type,
        status=status,
        occurred_at=occurred_at,
        frame_index=101,
        track_id=f"track-{uuid.uuid4().hex[:6]}",
        object_class=object_class,
        confidence=0.96,
        bbox={"x1": 1, "y1": 2, "x2": 20, "y2": 30},
        event_payload={},
        image_uri="s3://events/frame.jpg",
    )
    session.add(event)
    await session.flush()
    return event


async def _seed_plate_read(
    session,
    camera: Camera,
    *,
    plate_text: str,
    occurred_at: datetime,
    status: PlateReadStatus = PlateReadStatus.OBSERVED,
    detection_event: DetectionEvent | None = None,
) -> PlateRead:
    plate_read = PlateRead(
        camera_id=camera.id,
        detection_event_id=detection_event.id if detection_event is not None else None,
        occurred_at=occurred_at,
        status=status,
        plate_text=plate_text,
        normalized_plate_text=normalize_plate_text(plate_text),
        confidence=0.94,
        bbox={"x1": 2, "y1": 3, "x2": 22, "y2": 14},
        crop_image_uri="s3://plates/crop.jpg",
        source_frame_uri="s3://plates/source.jpg",
        ocr_metadata={},
    )
    session.add(plate_read)
    await session.flush()
    return plate_read


async def _seed_violation_event(
    session,
    camera: Camera,
    *,
    occurred_at: datetime,
    violation_type: ViolationType,
    status: ViolationStatus,
    zone: Zone | None = None,
    detection_event: DetectionEvent | None = None,
    plate_read: PlateRead | None = None,
) -> ViolationEvent:
    violation = ViolationEvent(
        camera_id=camera.id,
        zone_id=zone.id if zone is not None else None,
        detection_event_id=detection_event.id if detection_event is not None else None,
        plate_read_id=plate_read.id if plate_read is not None else None,
        violation_type=violation_type,
        severity=ViolationSeverity.HIGH,
        status=status,
        occurred_at=occurred_at,
        summary="Violation",
        evidence_image_uri="s3://violations/image.jpg",
        rule_metadata={},
    )
    session.add(violation)
    await session.flush()
    return violation


@pytest.mark.asyncio
async def test_events_search_filters_by_camera_query_zone_type_object_and_time(
    client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    http_client, session_factory = client
    kept_at = datetime(2026, 4, 4, 23, 30, tzinfo=timezone.utc)

    async with session_factory() as session:
        target_camera = await _seed_camera(session, "CAM-J4-001", "Junction 4 Eastbound", "Junction 4")
        other_camera = await _seed_camera(session, "CAM-OTH-001", "Cargo Gate", "Airport Cargo Gate")
        restricted_zone = await _seed_zone(session, target_camera, name="Restricted Bay", zone_type=ZoneType.RESTRICTED)
        other_zone = await _seed_zone(session, other_camera, name="Other Bay", zone_type=ZoneType.RESTRICTED)
        kept = await _seed_detection_event(
            session,
            target_camera,
            occurred_at=kept_at,
            zone=restricted_zone,
            object_class="truck",
        )
        await _seed_detection_event(
            session,
            target_camera,
            occurred_at=kept_at,
            zone=restricted_zone,
            object_class="car",
        )
        await _seed_detection_event(
            session,
            other_camera,
            occurred_at=kept_at,
            zone=other_zone,
            object_class="truck",
        )
        await session.commit()

    response = await http_client.get(
        "/api/v1/events/",
        params={
            "camera_query": "Junction 4",
            "object_class": "truck",
            "zone_type": "restricted",
            "occurred_after": "2026-04-04T18:00:00Z",
            "occurred_before": "2026-04-05T06:00:00Z",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == str(kept.id)


@pytest.mark.asyncio
async def test_violations_search_filters_by_camera_query_type_status_and_partial_plate(
    client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    http_client, session_factory = client
    occurred_at = datetime(2026, 4, 5, 8, 15, tzinfo=timezone.utc)

    async with session_factory() as session:
        target_camera = await _seed_camera(session, "CAM-J4-002", "Junction 4 Southbound", "Junction 4")
        other_camera = await _seed_camera(session, "CAM-OTH-002", "Tunnel Exit", "Tunnel Exit")
        stop_line = await _seed_zone(session, target_camera, name="Stop Line A", zone_type=ZoneType.STOP_LINE)
        detection = await _seed_detection_event(session, target_camera, occurred_at=occurred_at, zone=stop_line)
        matching_plate = await _seed_plate_read(
            session,
            target_camera,
            plate_text="AB1234",
            occurred_at=occurred_at,
            detection_event=detection,
        )
        dismissed_plate = await _seed_plate_read(
            session,
            target_camera,
            plate_text="AB1299",
            occurred_at=occurred_at,
            detection_event=detection,
        )
        await _seed_violation_event(
            session,
            target_camera,
            occurred_at=occurred_at,
            violation_type=ViolationType.RED_LIGHT,
            status=ViolationStatus.OPEN,
            zone=stop_line,
            detection_event=detection,
            plate_read=matching_plate,
        )
        await _seed_violation_event(
            session,
            target_camera,
            occurred_at=occurred_at,
            violation_type=ViolationType.RED_LIGHT,
            status=ViolationStatus.DISMISSED,
            zone=stop_line,
            detection_event=detection,
            plate_read=dismissed_plate,
        )
        other_detection = await _seed_detection_event(session, other_camera, occurred_at=occurred_at)
        other_plate = await _seed_plate_read(
            session,
            other_camera,
            plate_text="AB1234",
            occurred_at=occurred_at,
            detection_event=other_detection,
        )
        await _seed_violation_event(
            session,
            other_camera,
            occurred_at=occurred_at,
            violation_type=ViolationType.RED_LIGHT,
            status=ViolationStatus.OPEN,
            detection_event=other_detection,
            plate_read=other_plate,
        )
        await session.commit()

    response = await http_client.get(
        "/api/v1/violations/",
        params={
            "camera_query": "Junction 4",
            "violation_type": "red_light",
            "status": "open",
            "plate_text": "AB12",
            "partial_plate": "true",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["status"] == "open"
    assert payload["items"][0]["violation_type"] == "red_light"


@pytest.mark.asyncio
async def test_plate_search_supports_camera_query_filter(
    client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    http_client, session_factory = client
    occurred_at = datetime(2026, 4, 5, 9, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        target_camera = await _seed_camera(session, "CAM-J4-003", "Junction 4 Westbound", "Junction 4")
        other_camera = await _seed_camera(session, "CAM-OTH-003", "Cargo Road", "Cargo Gate")
        target_detection = await _seed_detection_event(session, target_camera, occurred_at=occurred_at)
        other_detection = await _seed_detection_event(session, other_camera, occurred_at=occurred_at)
        kept = await _seed_plate_read(
            session,
            target_camera,
            plate_text="AB1234",
            occurred_at=occurred_at,
            status=PlateReadStatus.MATCHED,
            detection_event=target_detection,
        )
        await _seed_plate_read(
            session,
            other_camera,
            plate_text="AB1299",
            occurred_at=occurred_at,
            status=PlateReadStatus.MATCHED,
            detection_event=other_detection,
        )
        await session.commit()

    response = await http_client.get(
        "/api/v1/plates/",
        params={
            "camera_query": "Junction 4",
            "plate_text": "AB12",
            "partial": "true",
            "status": "matched",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == str(kept.id)
