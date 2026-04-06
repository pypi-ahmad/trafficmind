from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.db.base import Base
from apps.api.app.db.session import get_db_session
from apps.api.app.main import create_app


@pytest.mark.asyncio
async def test_camera_and_ingestion_endpoints_support_frontend_workflows() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app()

    async def override_get_db_session() -> AsyncIterator[object]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        create_camera_response = await client.post(
            "/api/v1/cameras",
            json={
                "camera_code": "CAM-API-001",
                "name": "Elm & 9th",
                "location_name": "Elm St & 9th Ave",
                "status": "active",
                "calibration_config": {"homography": {"status": "pending"}},
            },
        )
        assert create_camera_response.status_code == 201
        camera_id = create_camera_response.json()["id"]

        create_stream_response = await client.post(
            f"/api/v1/cameras/{camera_id}/streams",
            json={
                "name": "primary",
                "stream_kind": "primary",
                "source_type": "rtsp",
                "source_uri": "rtsp://trafficmind.local/live/cam-001",
                "source_config": {"transport": "tcp"},
                "status": "offline",
            },
        )
        assert create_stream_response.status_code == 201
        stream_id = create_stream_response.json()["id"]

        camera_list_response = await client.get(
            "/api/v1/cameras",
            params={"status": "active", "source_type": "rtsp"},
        )
        assert camera_list_response.status_code == 200
        assert camera_list_response.json()["total"] == 1
        assert camera_list_response.json()["items"][0]["stream_count"] == 1

        camera_detail_response = await client.get(f"/api/v1/cameras/{camera_id}")
        assert camera_detail_response.status_code == 200
        assert camera_detail_response.json()["stream_count"] == 1
        assert len(camera_detail_response.json()["streams"]) == 1
        assert camera_detail_response.json()["streams"][0]["source_type"] == "rtsp"

        # Nested streams on nonexistent camera returns 404
        fake_id = "00000000-0000-0000-0000-000000000000"
        not_found_response = await client.get(f"/api/v1/cameras/{fake_id}/streams")
        assert not_found_response.status_code == 404

        register_video_response = await client.post(
            "/api/v1/streams/register-video-source",
            json={
                "camera": {
                    "camera_code": "VID-API-001",
                    "name": "Uploaded Incident Clip",
                    "location_name": "Operator Upload",
                    "status": "provisioning",
                },
                "stream": {
                    "name": "incident-clip",
                    "stream_kind": "auxiliary",
                    "source_type": "upload",
                    "source_uri": "upload://incident-clip-001",
                    "source_config": {"upload_id": "incident-clip-001", "file_name": "clip.mp4"},
                    "status": "offline",
                },
            },
        )
        assert register_video_response.status_code == 201
        assert register_video_response.json()["streams"][0]["source_type"] == "upload"

        update_stream_response = await client.patch(
            f"/api/v1/streams/{stream_id}",
            json={"status": "live", "is_enabled": True},
        )
        assert update_stream_response.status_code == 200
        assert update_stream_response.json()["status"] == "live"

    app.dependency_overrides.clear()
    await engine.dispose()