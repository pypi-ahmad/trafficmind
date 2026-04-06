"""Tests for the event/violation summary totals endpoints and service functions."""

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
from apps.api.app.services.feed_summary import event_summary_totals, violation_summary_totals


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
    status: DetectionEventStatus = DetectionEventStatus.NEW,
    event_type: DetectionEventType = DetectionEventType.DETECTION,
) -> DetectionEvent:
    event = DetectionEvent(
        camera_id=camera.id,
        event_type=event_type,
        status=status,
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
    violation_type: ViolationType = ViolationType.RED_LIGHT,
    status: ViolationStatus = ViolationStatus.OPEN,
) -> ViolationEvent:
    violation = ViolationEvent(
        camera_id=camera.id,
        violation_type=violation_type,
        severity=severity,
        status=status,
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
async def test_event_summary_totals_empty_db(
    client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    _, session_factory = client
    async with session_factory() as session:
        result = await event_summary_totals(session)
    assert result["total"] == 0
    assert result["by_status"] == {}
    assert result["by_type"] == {}


@pytest.mark.asyncio
async def test_event_summary_totals_returns_breakdowns(
    client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    _, session_factory = client
    t1 = datetime(2026, 4, 5, 10, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        cam = await _seed_camera(session, "CAM-A", "Camera A", "Junction Alpha")
        await _seed_detection_event(session, cam, occurred_at=t1, status=DetectionEventStatus.NEW)
        await _seed_detection_event(session, cam, occurred_at=t1, status=DetectionEventStatus.NEW)
        await _seed_detection_event(session, cam, occurred_at=t1, status=DetectionEventStatus.ENRICHED)
        await session.commit()

    async with session_factory() as session:
        result = await event_summary_totals(session)

    assert result["total"] == 3
    assert result["by_status"]["new"] == 2
    assert result["by_status"]["enriched"] == 1
    assert result["by_type"]["detection"] == 3


@pytest.mark.asyncio
async def test_event_summary_totals_filters_by_time_range(
    client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    _, session_factory = client
    in_range = datetime(2026, 4, 5, 12, 0, tzinfo=timezone.utc)
    out_of_range = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        cam = await _seed_camera(session, "CAM-B", "Camera B", "Junction Beta")
        await _seed_detection_event(session, cam, occurred_at=in_range)
        await _seed_detection_event(session, cam, occurred_at=in_range)
        await _seed_detection_event(session, cam, occurred_at=out_of_range)
        await session.commit()

    async with session_factory() as session:
        result = await event_summary_totals(
            session,
            occurred_after=datetime(2026, 4, 1, tzinfo=timezone.utc),
        )

    assert result["total"] == 2


@pytest.mark.asyncio
async def test_event_summary_totals_filters_by_camera(
    client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    _, session_factory = client
    t1 = datetime(2026, 4, 5, 10, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        cam_a = await _seed_camera(session, "CAM-C", "Camera C", "Junction Gamma")
        cam_b = await _seed_camera(session, "CAM-D", "Camera D", "Junction Delta")
        await _seed_detection_event(session, cam_a, occurred_at=t1)
        await _seed_detection_event(session, cam_a, occurred_at=t1)
        await _seed_detection_event(session, cam_b, occurred_at=t1)
        await session.commit()

    async with session_factory() as session:
        result = await event_summary_totals(session, camera_id=cam_a.id)

    assert result["total"] == 2


@pytest.mark.asyncio
async def test_violation_summary_totals_empty_db(
    client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    _, session_factory = client
    async with session_factory() as session:
        result = await violation_summary_totals(session)
    assert result["total"] == 0
    assert result["by_severity"] == {}
    assert result["by_type"] == {}
    assert result["by_status"] == {}


@pytest.mark.asyncio
async def test_violation_summary_totals_returns_breakdowns(
    client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    _, session_factory = client
    t1 = datetime(2026, 4, 5, 10, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        cam = await _seed_camera(session, "CAM-E", "Camera E", "Junction Echo")
        await _seed_violation_event(session, cam, occurred_at=t1, severity=ViolationSeverity.HIGH, violation_type=ViolationType.RED_LIGHT, status=ViolationStatus.OPEN)
        await _seed_violation_event(session, cam, occurred_at=t1, severity=ViolationSeverity.HIGH, violation_type=ViolationType.SPEEDING, status=ViolationStatus.OPEN)
        await _seed_violation_event(session, cam, occurred_at=t1, severity=ViolationSeverity.LOW, violation_type=ViolationType.RED_LIGHT, status=ViolationStatus.CONFIRMED)
        await session.commit()

    async with session_factory() as session:
        result = await violation_summary_totals(session)

    assert result["total"] == 3
    assert result["by_severity"]["high"] == 2
    assert result["by_severity"]["low"] == 1
    assert result["by_type"]["red_light"] == 2
    assert result["by_type"]["speeding"] == 1
    assert result["by_status"]["open"] == 2
    assert result["by_status"]["confirmed"] == 1


@pytest.mark.asyncio
async def test_violation_summary_totals_filters_by_time_range(
    client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    _, session_factory = client
    in_range = datetime(2026, 4, 5, 12, 0, tzinfo=timezone.utc)
    out_of_range = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        cam = await _seed_camera(session, "CAM-F", "Camera F", "Junction Foxtrot")
        await _seed_violation_event(session, cam, occurred_at=in_range)
        await _seed_violation_event(session, cam, occurred_at=out_of_range)
        await session.commit()

    async with session_factory() as session:
        result = await violation_summary_totals(
            session,
            occurred_after=datetime(2026, 4, 1, tzinfo=timezone.utc),
        )

    assert result["total"] == 1


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_events_summary_totals_endpoint(
    client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    http_client, session_factory = client
    t1 = datetime(2026, 4, 5, 10, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        cam = await _seed_camera(session, "CAM-G", "Camera G", "Junction Golf")
        await _seed_detection_event(session, cam, occurred_at=t1, status=DetectionEventStatus.NEW)
        await _seed_detection_event(session, cam, occurred_at=t1, status=DetectionEventStatus.ENRICHED)
        await session.commit()

    response = await http_client.get("/api/v1/events/summary/totals")
    assert response.status_code == 200

    payload = response.json()
    assert payload["total"] == 2
    assert payload["by_status"]["new"] == 1
    assert payload["by_status"]["enriched"] == 1
    assert "detection" in payload["by_type"]


@pytest.mark.asyncio
async def test_violations_summary_totals_endpoint(
    client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    http_client, session_factory = client
    t1 = datetime(2026, 4, 5, 10, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        cam = await _seed_camera(session, "CAM-H", "Camera H", "Junction Hotel")
        await _seed_violation_event(session, cam, occurred_at=t1, severity=ViolationSeverity.CRITICAL)
        await _seed_violation_event(session, cam, occurred_at=t1, severity=ViolationSeverity.LOW)
        await session.commit()

    response = await http_client.get("/api/v1/violations/summary/totals")
    assert response.status_code == 200

    payload = response.json()
    assert payload["total"] == 2
    assert payload["by_severity"]["critical"] == 1
    assert payload["by_severity"]["low"] == 1
    assert "open" in payload["by_status"]
    assert "red_light" in payload["by_type"]


@pytest.mark.asyncio
async def test_totals_endpoints_return_zeros_when_no_data(
    client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    http_client, _ = client

    events_response = await http_client.get("/api/v1/events/summary/totals")
    assert events_response.status_code == 200
    payload = events_response.json()
    assert payload["total"] == 0
    assert payload["by_status"] == {}
    assert payload["by_type"] == {}

    violations_response = await http_client.get("/api/v1/violations/summary/totals")
    assert violations_response.status_code == 200
    payload = violations_response.json()
    assert payload["total"] == 0
    assert payload["by_severity"] == {}
    assert payload["by_type"] == {}
    assert payload["by_status"] == {}


@pytest.mark.asyncio
async def test_totals_endpoints_accept_time_range_params(
    client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    http_client, session_factory = client
    t1 = datetime(2026, 4, 5, 10, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        cam = await _seed_camera(session, "CAM-I", "Camera I", "Junction India")
        await _seed_detection_event(session, cam, occurred_at=t1)
        await _seed_violation_event(session, cam, occurred_at=t1)
        await session.commit()

    # Query outside the time range
    event_resp = await http_client.get(
        "/api/v1/events/summary/totals",
        params={"occurred_after": "2026-04-06T00:00:00Z"},
    )
    assert event_resp.status_code == 200
    assert event_resp.json()["total"] == 0

    violation_resp = await http_client.get(
        "/api/v1/violations/summary/totals",
        params={"occurred_after": "2026-04-06T00:00:00Z"},
    )
    assert violation_resp.status_code == 200
    assert violation_resp.json()["total"] == 0

    # Query the correct range
    event_resp = await http_client.get(
        "/api/v1/events/summary/totals",
        params={
            "occurred_after": "2026-04-05T00:00:00Z",
            "occurred_before": "2026-04-06T00:00:00Z",
        },
    )
    assert event_resp.status_code == 200
    assert event_resp.json()["total"] == 1

    violation_resp = await http_client.get(
        "/api/v1/violations/summary/totals",
        params={
            "occurred_after": "2026-04-05T00:00:00Z",
            "occurred_before": "2026-04-06T00:00:00Z",
        },
    )
    assert violation_resp.status_code == 200
    assert violation_resp.json()["total"] == 1


@pytest.mark.asyncio
async def test_totals_endpoints_accept_camera_id_param(
    client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    http_client, session_factory = client
    t1 = datetime(2026, 4, 5, 10, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        cam_a = await _seed_camera(session, "CAM-J", "Camera J", "Junction Juliet")
        cam_b = await _seed_camera(session, "CAM-K", "Camera K", "Junction Kilo")
        await _seed_detection_event(session, cam_a, occurred_at=t1)
        await _seed_detection_event(session, cam_a, occurred_at=t1)
        await _seed_detection_event(session, cam_b, occurred_at=t1)
        await _seed_violation_event(session, cam_a, occurred_at=t1)
        await _seed_violation_event(session, cam_b, occurred_at=t1)
        await _seed_violation_event(session, cam_b, occurred_at=t1)
        await session.commit()

    # Filter to camera A
    event_resp = await http_client.get(
        "/api/v1/events/summary/totals",
        params={"camera_id": str(cam_a.id)},
    )
    assert event_resp.status_code == 200
    assert event_resp.json()["total"] == 2

    violation_resp = await http_client.get(
        "/api/v1/violations/summary/totals",
        params={"camera_id": str(cam_a.id)},
    )
    assert violation_resp.status_code == 200
    assert violation_resp.json()["total"] == 1

    # Filter to camera B
    event_resp = await http_client.get(
        "/api/v1/events/summary/totals",
        params={"camera_id": str(cam_b.id)},
    )
    assert event_resp.status_code == 200
    assert event_resp.json()["total"] == 1

    violation_resp = await http_client.get(
        "/api/v1/violations/summary/totals",
        params={"camera_id": str(cam_b.id)},
    )
    assert violation_resp.status_code == 200
    assert violation_resp.json()["total"] == 2
