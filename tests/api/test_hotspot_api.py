"""Integration tests for hotspot analytics endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.db.base import Base
from apps.api.app.db.enums import (
    CameraStatus,
    DetectionEventType,
    ViolationSeverity,
    ViolationStatus,
    ViolationType,
    WatchlistAlertStatus,
    WatchlistEntryStatus,
    WatchlistReason,
    ZoneStatus,
    ZoneType,
)
from apps.api.app.db.models import (
    Camera,
    DetectionEvent,
    PlateRead,
    ViolationEvent,
    WatchlistAlert,
    WatchlistEntry,
    Zone,
)
from apps.api.app.db.session import get_db_session
from apps.api.app.main import create_app

T0 = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)
T7 = T0 + timedelta(days=7)
T14 = T7 + timedelta(days=7)


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


async def _seed_camera(session, code: str, name: str, location: str, *, latitude: float, longitude: float) -> Camera:
    camera = Camera(
        camera_code=code,
        name=name,
        location_name=location,
        status=CameraStatus.ACTIVE,
        latitude=latitude,
        longitude=longitude,
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
    event_payload: dict | None = None,
) -> DetectionEvent:
    event = DetectionEvent(
        camera_id=camera.id,
        zone_id=zone.id if zone is not None else None,
        event_type=DetectionEventType.DETECTION,
        occurred_at=occurred_at,
        track_id="track-1",
        object_class="car",
        confidence=0.95,
        bbox={"x1": 1, "y1": 2, "x2": 20, "y2": 30},
        event_payload=event_payload or {},
    )
    session.add(event)
    await session.flush()
    return event


async def _seed_violation_event(
    session,
    camera: Camera,
    *,
    occurred_at: datetime,
    zone: Zone | None = None,
    rule_metadata: dict | None = None,
    violation_type: ViolationType = ViolationType.RED_LIGHT,
) -> ViolationEvent:
    event = ViolationEvent(
        camera_id=camera.id,
        zone_id=zone.id if zone is not None else None,
        violation_type=violation_type,
        severity=ViolationSeverity.HIGH,
        status=ViolationStatus.OPEN,
        occurred_at=occurred_at,
        summary="Violation",
        rule_metadata=rule_metadata or {},
    )
    session.add(event)
    await session.flush()
    return event


async def _seed_plate_read(session, camera: Camera, *, occurred_at: datetime, detection_event: DetectionEvent | None = None) -> PlateRead:
    plate_read = PlateRead(
        camera_id=camera.id,
        detection_event_id=detection_event.id if detection_event is not None else None,
        occurred_at=occurred_at,
        plate_text="ABC1234",
        normalized_plate_text="ABC1234",
        confidence=0.98,
        bbox={"x1": 5, "y1": 5, "x2": 25, "y2": 15},
        ocr_metadata={},
    )
    session.add(plate_read)
    await session.flush()
    return plate_read


async def _seed_watchlist_entry(session) -> WatchlistEntry:
    entry = WatchlistEntry(
        normalized_plate_text="ABC1234",
        plate_text_display="ABC1234",
        reason=WatchlistReason.STOLEN,
        status=WatchlistEntryStatus.ACTIVE,
        alert_enabled=True,
    )
    session.add(entry)
    await session.flush()
    return entry


async def _seed_watchlist_alert(
    session,
    camera: Camera,
    *,
    occurred_at: datetime,
    plate_read: PlateRead,
    entry: WatchlistEntry,
) -> WatchlistAlert:
    alert = WatchlistAlert(
        plate_read_id=plate_read.id,
        watchlist_entry_id=entry.id,
        camera_id=camera.id,
        status=WatchlistAlertStatus.OPEN,
        occurred_at=occurred_at,
        normalized_plate_text="ABC1234",
        plate_text="ABC1234",
        reason=WatchlistReason.STOLEN,
        alert_metadata={},
    )
    session.add(alert)
    await session.flush()
    return alert


@pytest.mark.asyncio
async def test_hotspot_api_returns_frontend_ready_payload(client: tuple[AsyncClient, async_sessionmaker]) -> None:
    http_client, session_factory = client
    async with session_factory() as session:
        camera_a = await _seed_camera(session, "CAM-001", "Camera A", "Main & 1st", latitude=40.1, longitude=-74.1)
        camera_b = await _seed_camera(session, "CAM-002", "Camera B", "Main & 2nd", latitude=40.2, longitude=-74.2)
        lane_zone = await _seed_zone(session, camera_a, name="Lane A1", zone_type=ZoneType.LANE)

        detection = await _seed_detection_event(
            session,
            camera_a,
            occurred_at=T0 + timedelta(days=1),
            zone=lane_zone,
            event_payload={"lane_id": str(lane_zone.id)},
        )
        await _seed_violation_event(
            session,
            camera_a,
            occurred_at=T0 + timedelta(days=2),
            rule_metadata={"lane_id": str(lane_zone.id)},
        )
        plate_read = await _seed_plate_read(
            session,
            camera_b,
            occurred_at=T0 + timedelta(days=3),
            detection_event=detection,
        )
        entry = await _seed_watchlist_entry(session)
        await _seed_watchlist_alert(
            session,
            camera_b,
            occurred_at=T0 + timedelta(days=3),
            plate_read=plate_read,
            entry=entry,
        )
        await session.commit()

    response = await http_client.post(
        "/api/v1/analytics/hotspots",
        json={
            "period_start": T0.isoformat(),
            "period_end": T7.isoformat(),
            "group_by": ["camera"],
            "granularity": "day",
            "compare_previous": False,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_events"] == 3
    assert len(data["ranking"]) == 2
    assert data["ranking_metric"] == "event_count"
    assert data["ranking"][0]["camera_name"] == "Camera A"
    assert len(data["heatmap"]) == 2
    assert data["heatmap"][0]["latitude"] is not None
    assert len(data["time_series"]) == 7
    assert len(data["methodology"]) > 0


@pytest.mark.asyncio
async def test_hotspot_api_supports_lane_grouping_and_trends(client: tuple[AsyncClient, async_sessionmaker]) -> None:
    http_client, session_factory = client
    async with session_factory() as session:
        camera = await _seed_camera(session, "CAM-LANE", "Lane Camera", "Broadway", latitude=40.3, longitude=-74.3)
        lane_zone = await _seed_zone(session, camera, name="Lane 1", zone_type=ZoneType.LANE)

        await _seed_violation_event(
            session,
            camera,
            occurred_at=T0 + timedelta(days=2),
            rule_metadata={"lane_id": str(lane_zone.id)},
            violation_type=ViolationType.STOP_LINE,
        )
        await _seed_violation_event(
            session,
            camera,
            occurred_at=T7 + timedelta(days=1),
            rule_metadata={"lane_id": str(lane_zone.id)},
            violation_type=ViolationType.STOP_LINE,
        )
        await _seed_violation_event(
            session,
            camera,
            occurred_at=T7 + timedelta(days=2),
            rule_metadata={"lane_id": str(lane_zone.id)},
            violation_type=ViolationType.STOP_LINE,
        )
        await session.commit()

    response = await http_client.post(
        "/api/v1/analytics/hotspots",
        json={
            "period_start": T7.isoformat(),
            "period_end": T14.isoformat(),
            "group_by": ["lane", "violation_type"],
            "source_kinds": ["violation_event"],
            "granularity": "week",
            "compare_previous": True,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ranking_metric"] == "event_count"
    assert data["trend"]["delta"]["count_delta"] == 1
    assert data["ranking"][0]["lane_id"] == data["heatmap"][0]["lane_id"]
    assert data["ranking"][0]["violation_type"] == "stop_line"
    assert any("Lane hotspots depend" in warning for warning in data["warnings"])


@pytest.mark.asyncio
async def test_hotspot_api_uses_explicit_lane_id_from_detection_payload(client: tuple[AsyncClient, async_sessionmaker]) -> None:
    http_client, session_factory = client
    async with session_factory() as session:
        camera = await _seed_camera(session, "CAM-DET-LANE", "Detection Lane Camera", "Elm St", latitude=40.5, longitude=-74.5)
        stop_line_zone = await _seed_zone(session, camera, name="Stop Line", zone_type=ZoneType.STOP_LINE)
        lane_zone = await _seed_zone(session, camera, name="Lane 2", zone_type=ZoneType.LANE)

        await _seed_detection_event(
            session,
            camera,
            occurred_at=T0 + timedelta(days=1),
            zone=stop_line_zone,
            event_payload={"lane_id": str(lane_zone.id)},
        )
        await session.commit()

    response = await http_client.post(
        "/api/v1/analytics/hotspots",
        json={
            "period_start": T0.isoformat(),
            "period_end": T7.isoformat(),
            "group_by": ["lane", "event_type"],
            "source_kinds": ["detection_event"],
            "compare_previous": False,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ranking"][0]["lane_id"] == data["heatmap"][0]["lane_id"]
    assert data["ranking"][0]["event_type"] == "detection"


@pytest.mark.asyncio
async def test_hotspot_api_filters_watchlist_only(client: tuple[AsyncClient, async_sessionmaker]) -> None:
    http_client, session_factory = client
    async with session_factory() as session:
        camera = await _seed_camera(session, "CAM-WL", "Watchlist Camera", "Harbor Rd", latitude=40.4, longitude=-74.4)
        detection = await _seed_detection_event(session, camera, occurred_at=T0 + timedelta(days=1))
        await _seed_violation_event(session, camera, occurred_at=T0 + timedelta(days=1))
        plate_read = await _seed_plate_read(session, camera, occurred_at=T0 + timedelta(days=1), detection_event=detection)
        entry = await _seed_watchlist_entry(session)
        await _seed_watchlist_alert(session, camera, occurred_at=T0 + timedelta(days=1), plate_read=plate_read, entry=entry)
        await session.commit()

    response = await http_client.post(
        "/api/v1/analytics/hotspots",
        json={
            "period_start": T0.isoformat(),
            "period_end": T7.isoformat(),
            "group_by": ["event_type"],
            "source_kinds": ["watchlist_alert"],
            "compare_previous": False,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_events"] == 1
    assert data["ranking"][0]["event_type"] == "watchlist_match"


@pytest.mark.asyncio
async def test_hotspot_api_warns_when_congestion_is_requested_without_history(client: tuple[AsyncClient, async_sessionmaker]) -> None:
    http_client, _session_factory = client
    response = await http_client.post(
        "/api/v1/analytics/hotspots",
        json={
            "period_start": T0.isoformat(),
            "period_end": T7.isoformat(),
            "group_by": ["camera"],
            "source_kinds": ["congestion"],
            "compare_previous": False,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_events"] == 0
    assert any("persisted congestion history" in warning for warning in data["warnings"])
