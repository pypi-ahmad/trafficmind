"""Integration tests for junction CRUD API."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.db.base import Base
from apps.api.app.db.session import get_db_session
from apps.api.app.main import create_app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app()

    async def override_get_db_session() -> AsyncIterator[object]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        yield ac


@pytest.mark.asyncio
async def test_junction_crud_lifecycle(client: AsyncClient) -> None:
    # Create junction
    create_resp = await client.post(
        "/api/v1/junctions",
        json={"name": "Elm St & 9th Ave", "latitude": 40.7, "longitude": -74.0},
    )
    assert create_resp.status_code == 201
    junction = create_resp.json()
    junction_id = junction["id"]
    assert junction["name"] == "Elm St & 9th Ave"
    assert junction["latitude"] == 40.7

    # List junctions
    list_resp = await client.get("/api/v1/junctions")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    # Get junction detail
    detail_resp = await client.get(f"/api/v1/junctions/{junction_id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["name"] == "Elm St & 9th Ave"
    assert detail_resp.json()["cameras"] == []

    # Update junction
    update_resp = await client.patch(
        f"/api/v1/junctions/{junction_id}",
        json={"name": "Elm St & 9th Ave (Updated)", "description": "Main intersection"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "Elm St & 9th Ave (Updated)"
    assert update_resp.json()["description"] == "Main intersection"

    # Delete junction
    delete_resp = await client.delete(f"/api/v1/junctions/{junction_id}")
    assert delete_resp.status_code == 204

    # Verify gone
    gone_resp = await client.get(f"/api/v1/junctions/{junction_id}")
    assert gone_resp.status_code == 404


@pytest.mark.asyncio
async def test_junction_name_uniqueness(client: AsyncClient) -> None:
    resp1 = await client.post(
        "/api/v1/junctions",
        json={"name": "Unique Junction"},
    )
    assert resp1.status_code == 201

    resp2 = await client.post(
        "/api/v1/junctions",
        json={"name": "Unique Junction"},
    )
    assert resp2.status_code == 409


@pytest.mark.asyncio
async def test_junction_search(client: AsyncClient) -> None:
    await client.post("/api/v1/junctions", json={"name": "Oak & 3rd"})
    await client.post("/api/v1/junctions", json={"name": "Pine & 5th"})

    # Search should filter
    search_resp = await client.get("/api/v1/junctions", params={"search": "Oak"})
    assert search_resp.status_code == 200
    assert len(search_resp.json()) == 1
    assert search_resp.json()[0]["name"] == "Oak & 3rd"


@pytest.mark.asyncio
async def test_junction_404(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/junctions/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_camera_junction_assignment(client: AsyncClient) -> None:
    # Create junction
    junction_resp = await client.post(
        "/api/v1/junctions",
        json={"name": "Test Junction"},
    )
    assert junction_resp.status_code == 201
    junction_id = junction_resp.json()["id"]

    # Create camera with junction_id
    camera_resp = await client.post(
        "/api/v1/cameras",
        json={
            "camera_code": "CAM-J-001",
            "name": "Junction Camera",
            "location_name": "Test Junction",
            "status": "active",
            "junction_id": junction_id,
        },
    )
    assert camera_resp.status_code == 201
    assert camera_resp.json()["junction_id"] == junction_id

    # Junction detail should list the camera
    detail_resp = await client.get(f"/api/v1/junctions/{junction_id}")
    assert detail_resp.status_code == 200
    assert len(detail_resp.json()["cameras"]) == 1
    assert detail_resp.json()["cameras"][0]["camera_code"] == "CAM-J-001"

    # Camera without junction should have null junction_id
    camera2_resp = await client.post(
        "/api/v1/cameras",
        json={
            "camera_code": "CAM-J-002",
            "name": "Unassigned Camera",
            "location_name": "Somewhere",
            "status": "active",
        },
    )
    assert camera2_resp.status_code == 201
    assert camera2_resp.json()["junction_id"] is None


@pytest.mark.asyncio
async def test_junction_deletion_nullifies_camera_fk(client: AsyncClient) -> None:
    # Create junction
    junction_resp = await client.post(
        "/api/v1/junctions",
        json={"name": "Deletable Junction"},
    )
    junction_id = junction_resp.json()["id"]

    # Create camera linked to junction
    camera_resp = await client.post(
        "/api/v1/cameras",
        json={
            "camera_code": "CAM-DEL-001",
            "name": "Camera",
            "location_name": "Somewhere",
            "junction_id": junction_id,
        },
    )
    camera_id = camera_resp.json()["id"]

    # Delete junction
    await client.delete(f"/api/v1/junctions/{junction_id}")

    # Camera should still exist with junction_id = null
    camera_detail = await client.get(f"/api/v1/cameras/{camera_id}")
    assert camera_detail.status_code == 200
    assert camera_detail.json()["junction_id"] is None
