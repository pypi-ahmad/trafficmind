"""Tests for the event/violation feed summary endpoints and service."""

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
    ViolationSeverity,
    ViolationStatus,
    ViolationType,
)
from apps.api.app.db.models import Camera, DetectionEvent, ViolationEvent
from apps.api.app.db.session import get_db_session
from apps.api.app.main import create_app
from apps.api.app.services.feed_summary import event_counts_by_camera, violation_counts_by_camera


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


async def _seed_detection_event(
    session,
    camera: Camera,
    *,
    occurred_at: datetime,
) -> DetectionEvent:
    event = DetectionEvent(
        camera_id=camera.id,
        event_type=DetectionEventType.DETECTION,
        status=DetectionEventStatus.NEW,
        occurred_at=occurred_at,
        frame_index=0,
        track_id=f"track-{uuid.uuid4().hex[:6]}",
        object_class="car",
        confidence=0.95,
        bbox={"x1": 1, "y1": 2, "x2": 20, "y2": 30},
        event_payload={},
    )
    session.add(event)
    await session.flush()
    return event


async def _seed_violation_event(
    session,
    camera: Camera,
    *,
    occurred_at: datetime,
    severity: ViolationSeverity = ViolationSeverity.MEDIUM,
) -> ViolationEvent:
    violation = ViolationEvent(
        camera_id=camera.id,
        violation_type=ViolationType.RED_LIGHT,
        severity=severity,
        status=ViolationStatus.OPEN,
        occurred_at=occurred_at,
        summary="Test violation",
        rule_metadata={},
    )
    session.add(violation)
    await session.flush()
    return violation


# ---------------------------------------------------------------------------
# Service-level tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_counts_by_camera_returns_grouped_counts(
    client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    _, session_factory = client
    t1 = datetime(2026, 4, 5, 10, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        cam_a = await _seed_camera(session, "CAM-A", "Camera A", "Junction Alpha")
        cam_b = await _seed_camera(session, "CAM-B", "Camera B", "Junction Beta")
        for _ in range(3):
            await _seed_detection_event(session, cam_a, occurred_at=t1)
        await _seed_detection_event(session, cam_b, occurred_at=t1)
        await session.commit()

    async with session_factory() as session:
        rows = await event_counts_by_camera(session)

    assert len(rows) == 2
    # Sorted by count descending
    assert rows[0]["camera_name"] == "Camera A"
    assert rows[0]["event_count"] == 3
    assert rows[1]["camera_name"] == "Camera B"
    assert rows[1]["event_count"] == 1


@pytest.mark.asyncio
async def test_violation_counts_by_camera_includes_severity_breakdown(
    client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    _, session_factory = client
    t1 = datetime(2026, 4, 5, 10, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        cam = await _seed_camera(session, "CAM-C", "Camera C", "Junction Gamma")
        await _seed_violation_event(session, cam, occurred_at=t1, severity=ViolationSeverity.HIGH)
        await _seed_violation_event(session, cam, occurred_at=t1, severity=ViolationSeverity.HIGH)
        await _seed_violation_event(session, cam, occurred_at=t1, severity=ViolationSeverity.LOW)
        await session.commit()

    async with session_factory() as session:
        rows = await violation_counts_by_camera(session)

    assert len(rows) == 1
    assert rows[0]["violation_count"] == 3
    assert rows[0]["severity_counts"]["high"] == 2
    assert rows[0]["severity_counts"]["low"] == 1


@pytest.mark.asyncio
async def test_event_counts_filters_by_time_range(
    client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    _, session_factory = client
    in_range = datetime(2026, 4, 5, 12, 0, tzinfo=timezone.utc)
    out_of_range = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        cam = await _seed_camera(session, "CAM-D", "Camera D", "Junction Delta")
        await _seed_detection_event(session, cam, occurred_at=in_range)
        await _seed_detection_event(session, cam, occurred_at=in_range)
        await _seed_detection_event(session, cam, occurred_at=out_of_range)
        await session.commit()

    async with session_factory() as session:
        rows = await event_counts_by_camera(
            session,
            occurred_after=datetime(2026, 4, 1, tzinfo=timezone.utc),
        )

    assert len(rows) == 1
    assert rows[0]["event_count"] == 2


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_events_summary_by_camera_endpoint(
    client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    http_client, session_factory = client
    t1 = datetime(2026, 4, 5, 10, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        cam = await _seed_camera(session, "CAM-E", "Camera E", "Junction Echo")
        await _seed_detection_event(session, cam, occurred_at=t1)
        await _seed_detection_event(session, cam, occurred_at=t1)
        await session.commit()

    response = await http_client.get("/api/v1/events/summary/by-camera")
    assert response.status_code == 200

    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["camera_name"] == "Camera E"
    assert payload[0]["event_count"] == 2


@pytest.mark.asyncio
async def test_violations_summary_by_camera_endpoint(
    client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    http_client, session_factory = client
    t1 = datetime(2026, 4, 5, 10, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        cam = await _seed_camera(session, "CAM-F", "Camera F", "Junction Foxtrot")
        await _seed_violation_event(session, cam, occurred_at=t1, severity=ViolationSeverity.CRITICAL)
        await session.commit()

    response = await http_client.get("/api/v1/violations/summary/by-camera")
    assert response.status_code == 200

    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["camera_name"] == "Camera F"
    assert payload[0]["violation_count"] == 1
    assert payload[0]["severity_counts"]["critical"] == 1


@pytest.mark.asyncio
async def test_summary_endpoints_return_empty_lists_when_no_data(
    client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    http_client, _ = client

    events_response = await http_client.get("/api/v1/events/summary/by-camera")
    assert events_response.status_code == 200
    assert events_response.json() == []

    violations_response = await http_client.get("/api/v1/violations/summary/by-camera")
    assert violations_response.status_code == 200
    assert violations_response.json() == []


@pytest.mark.asyncio
async def test_summary_endpoints_accept_time_range_params(
    client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    http_client, session_factory = client
    t1 = datetime(2026, 4, 5, 10, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        cam = await _seed_camera(session, "CAM-G", "Camera G", "Junction Golf")
        await _seed_detection_event(session, cam, occurred_at=t1)
        await session.commit()

    # Query outside the time range
    response = await http_client.get(
        "/api/v1/events/summary/by-camera",
        params={
            "occurred_after": "2026-04-06T00:00:00Z",
            "occurred_before": "2026-04-07T00:00:00Z",
        },
    )
    assert response.status_code == 200
    assert response.json() == []

    # Now query the correct range
    response = await http_client.get(
        "/api/v1/events/summary/by-camera",
        params={
            "occurred_after": "2026-04-05T00:00:00Z",
            "occurred_before": "2026-04-06T00:00:00Z",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["event_count"] == 1
