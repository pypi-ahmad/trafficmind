"""Integration tests for camera health observability endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.db.base import Base
from apps.api.app.db.models import CameraStream
from apps.api.app.db.session import get_db_session
from apps.api.app.main import create_app


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

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c, session_factory

    await engine.dispose()


@pytest.fixture
async def seeded_client(client: tuple[AsyncClient, async_sessionmaker]) -> tuple[AsyncClient, async_sessionmaker, str, str]:
    """Create a camera + stream and return (client, camera_id, stream_id)."""
    client, session_factory = client
    cam_resp = await client.post(
        "/api/v1/cameras",
        json={
            "camera_code": "CAM-HEALTH-001",
            "name": "Health Test Camera",
            "location_name": "Main St & 1st Ave",
            "status": "active",
        },
    )
    assert cam_resp.status_code == 201
    camera_id = cam_resp.json()["id"]

    stream_resp = await client.post(
        f"/api/v1/cameras/{camera_id}/streams",
        json={
            "name": "primary",
            "source_type": "rtsp",
            "source_uri": "rtsp://trafficmind.local/live/cam-001",
            "status": "live",
            "is_enabled": True,
            "fps_hint": 25.0,
        },
    )
    assert stream_resp.status_code == 201
    stream_id = stream_resp.json()["id"]

    return client, session_factory, camera_id, stream_id


# ── Dashboard ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dashboard_empty(client: tuple[AsyncClient, async_sessionmaker]) -> None:
    client, _session_factory = client
    resp = await client.get("/api/v1/observability/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_cameras"] == 0
    assert data["cameras_online"] == 0
    assert data["cameras_offline"] == 0
    assert data["cameras_degraded"] == 0
    assert "assessed_at" in data


@pytest.mark.asyncio
async def test_dashboard_with_camera(seeded_client: tuple) -> None:
    client, session_factory, camera_id, stream_id = seeded_client

    async with session_factory() as session:
        await session.execute(
            update(CameraStream)
            .where(CameraStream.id == uuid.UUID(stream_id))
            .values(last_heartbeat_at=datetime.now(timezone.utc))
        )
        await session.commit()

    resp = await client.get("/api/v1/observability/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_cameras"] == 1
    assert data["total_streams"] == 1
    assert data["streams_online"] == 1
    assert len(data["cameras"]) == 1

    cam = data["cameras"][0]
    assert cam["camera_code"] == "CAM-HEALTH-001"
    assert cam["overall_health"] in {"online", "degraded", "offline"}
    assert len(cam["streams"]) == 1

    stream = cam["streams"][0]
    assert stream["stream_id"] == stream_id
    assert stream["is_online"] is True
    assert stream["state_basis"] == "recent_heartbeat"
    assert stream["db_status"] == "live"


@pytest.mark.asyncio
async def test_dashboard_filter_by_status(seeded_client: tuple) -> None:
    client, _session_factory, camera_id, stream_id = seeded_client
    resp = await client.get("/api/v1/observability/dashboard", params={"status": "provisioning"})
    assert resp.status_code == 200
    assert resp.json()["total_cameras"] == 0


# ── Per-camera health ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_camera_health(seeded_client: tuple) -> None:
    client, session_factory, camera_id, stream_id = seeded_client

    async with session_factory() as session:
        await session.execute(
            update(CameraStream)
            .where(CameraStream.id == uuid.UUID(stream_id))
            .values(last_heartbeat_at=datetime.now(timezone.utc))
        )
        await session.commit()

    resp = await client.get(f"/api/v1/observability/cameras/{camera_id}/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["camera_id"] == camera_id
    assert data["camera_code"] == "CAM-HEALTH-001"
    assert data["overall_health"] in {"online", "degraded", "offline"}
    assert len(data["streams"]) == 1


@pytest.mark.asyncio
async def test_camera_health_404(client: tuple[AsyncClient, async_sessionmaker]) -> None:
    client, _session_factory = client
    resp = await client.get("/api/v1/observability/cameras/00000000-0000-0000-0000-000000000000/health")
    assert resp.status_code == 404


# ── Per-stream health ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_health(seeded_client: tuple) -> None:
    client, _session_factory, camera_id, stream_id = seeded_client
    resp = await client.get(f"/api/v1/observability/streams/{stream_id}/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["stream_id"] == stream_id
    assert data["is_online"] is False
    assert data["state_basis"] == "no_runtime_signal"
    assert data["source_type"] == "rtsp"
    assert data["db_status"] == "live"
    # No active job in test setup
    assert data["active_job_id"] is None
    assert data["latest_job_id"] is None
    assert data["metrics"] is None


@pytest.mark.asyncio
async def test_stream_health_404(client: tuple[AsyncClient, async_sessionmaker]) -> None:
    client, _session_factory = client
    resp = await client.get("/api/v1/observability/streams/00000000-0000-0000-0000-000000000000/health")
    assert resp.status_code == 404


# ── Offline stream ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_offline_stream_reports_offline(client: tuple[AsyncClient, async_sessionmaker]) -> None:
    client, _session_factory = client
    cam_resp = await client.post(
        "/api/v1/cameras",
        json={
            "camera_code": "CAM-OFF-001",
            "name": "Offline Camera",
            "location_name": "Nowhere",
            "status": "active",
        },
    )
    camera_id = cam_resp.json()["id"]

    stream_resp = await client.post(
        f"/api/v1/cameras/{camera_id}/streams",
        json={
            "name": "offline-stream",
            "source_type": "rtsp",
            "source_uri": "rtsp://dead.local/stream",
            "status": "offline",
            "is_enabled": True,
        },
    )
    stream_id = stream_resp.json()["id"]

    resp = await client.get(f"/api/v1/observability/streams/{stream_id}/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_online"] is False


# ── Error stream ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_error_stream_produces_alert(client: tuple[AsyncClient, async_sessionmaker]) -> None:
    client, _session_factory = client
    cam_resp = await client.post(
        "/api/v1/cameras",
        json={
            "camera_code": "CAM-ERR-001",
            "name": "Error Camera",
            "location_name": "Errorville",
            "status": "active",
        },
    )
    camera_id = cam_resp.json()["id"]

    stream_resp = await client.post(
        f"/api/v1/cameras/{camera_id}/streams",
        json={
            "name": "error-stream",
            "source_type": "rtsp",
            "source_uri": "rtsp://broken.local/stream",
            "status": "error",
            "is_enabled": True,
        },
    )
    stream_id = stream_resp.json()["id"]

    resp = await client.get(f"/api/v1/observability/streams/{stream_id}/health")
    data = resp.json()
    assert any(a["signal"] == "stream_error" for a in data["alerts"])
    assert any(a["severity"] == "critical" for a in data["alerts"])


# ── Dashboard structure validation ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_dashboard_structure_keys(seeded_client: tuple) -> None:
    client, _session_factory, _, _ = seeded_client
    resp = await client.get("/api/v1/observability/dashboard")
    data = resp.json()
    expected_keys = {
        "assessed_at", "total_cameras", "cameras_online", "cameras_offline",
        "cameras_degraded", "total_streams", "streams_online", "active_jobs",
        "critical_alerts", "warning_alerts", "cameras",
    }
    assert expected_keys <= set(data.keys())


@pytest.mark.asyncio
async def test_stream_health_with_recent_heartbeat_reports_online(seeded_client: tuple) -> None:
    client, session_factory, _camera_id, stream_id = seeded_client

    async with session_factory() as session:
        await session.execute(
            update(CameraStream)
            .where(CameraStream.id == uuid.UUID(stream_id))
            .values(last_heartbeat_at=datetime.now(timezone.utc))
        )
        await session.commit()

    resp = await client.get(f"/api/v1/observability/streams/{stream_id}/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_online"] is True
    assert data["state_basis"] == "recent_heartbeat"
