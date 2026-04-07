from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.core.config import Settings
from apps.api.app.db.base import Base
from apps.api.app.db.session import get_db_session
from apps.api.app.main import create_app


def test_health_info_and_public_config_endpoints() -> None:
    client = TestClient(create_app())

    health_response = client.get("/api/v1/health")
    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok"}

    info_response = client.get("/api/v1/info")
    assert info_response.status_code == 200
    assert info_response.json()["docs_url"] == "/api/v1/docs"

    config_response = client.get("/api/v1/config/public")
    assert config_response.status_code == 200
    assert config_response.json()["api_prefix"] == "/api/v1"

    readiness_response = client.get("/api/v1/health/ready")
    assert readiness_response.status_code == 200
    readiness_payload = readiness_response.json()
    assert readiness_payload["service"] == "api"
    assert readiness_payload["status"] == "ready"
    assert any(item["code"] == "database_connectivity" for item in readiness_payload["checks"])


def test_strict_startup_checks_fail_for_prod_like_sqlite_api() -> None:
    settings = Settings(
        environment="prod",
        strict_startup_checks=True,
        database_url="sqlite+aiosqlite:///./trafficmind.db",
        allowed_origins=["https://trafficmind.example.com"],
        enable_vision=False,
    )

    with (
        pytest.raises(RuntimeError, match="API startup readiness checks failed"),
        TestClient(create_app(settings=settings)),
    ):
        pass


def test_strict_startup_checks_fail_when_database_probe_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_probe_database_connectivity(_: str) -> tuple[bool, str]:
        return False, "Database connectivity probe failed: unavailable"

    monkeypatch.setattr(
        "apps.api.app.main.probe_database_connectivity",
        fake_probe_database_connectivity,
    )
    settings = Settings(
        environment="dev",
        strict_startup_checks=True,
        database_url="postgresql+asyncpg://trafficmind:change-me@db-host:5432/trafficmind",
        allowed_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        enable_vision=False,
    )

    with (
        pytest.raises(RuntimeError, match="API startup readiness checks failed"),
        TestClient(create_app(settings=settings)),
    ):
        pass


def test_record_search_routes_are_registered() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def prepare_database() -> async_sessionmaker:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, expire_on_commit=False)

    session_factory = asyncio.run(prepare_database())
    app = create_app()

    async def override_get_db_session() -> AsyncIterator[object]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db_session
    client = TestClient(app)

    for resource in ("events", "violations", "plates"):
        response = client.get(f"/api/v1/{resource}/")
        assert response.status_code == 200
        assert response.json()["items"] == []
        assert response.json()["total"] == 0

    asyncio.run(engine.dispose())
