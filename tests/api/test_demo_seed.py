from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from apps.api.app.demo.seed import seed_demo_scenario
from apps.api.app.db.models import (
    Camera,
    CameraStream,
    DetectionEvent,
    EvidenceManifest,
    PlateRead,
    ViolationEvent,
    WorkflowRun,
    Zone,
)
from apps.api.app.db.session import get_db_session
from apps.api.app.main import create_app
from tests.fixtures.sample_data import load_json_fixture, make_sqlite_session_factory

FIXED_NOW = datetime(2026, 4, 5, 18, 0, tzinfo=timezone.utc)


async def _count_rows(session, model) -> int:
    total = await session.scalar(select(func.count()).select_from(model))
    return int(total or 0)


@pytest.fixture
async def demo_client() -> AsyncIterator[tuple[AsyncClient, object]]:
    session_factory, engine = await make_sqlite_session_factory()
    # Use real wall-clock so heartbeats are fresh when the API route evaluates
    # health (the route calls datetime.now(utc), not the seed's fixed clock).
    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        await seed_demo_scenario(session, now=now)
        await session.commit()

    app = create_app()

    async def override_get_db_session() -> AsyncIterator[object]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        yield client, session_factory

    await engine.dispose()


@pytest.mark.asyncio
async def test_demo_seed_populates_consistent_dataset() -> None:
    expectations = load_json_fixture("demo/seed_expectations.json")
    session_factory, engine = await make_sqlite_session_factory()

    async with session_factory() as session:
        report = (await seed_demo_scenario(session, now=FIXED_NOW)).to_dict()
        await session.commit()

        counts = {
            "cameras": await _count_rows(session, Camera),
            "streams": await _count_rows(session, CameraStream),
            "zones": await _count_rows(session, Zone),
            "events": await _count_rows(session, DetectionEvent),
            "violations": await _count_rows(session, ViolationEvent),
            "plate_reads": await _count_rows(session, PlateRead),
            "review_cases": await _count_rows(session, ViolationEvent),
            "evidence_manifests": await _count_rows(session, EvidenceManifest),
            "workflows": await _count_rows(session, WorkflowRun),
        }
        assert counts == expectations["counts"]

        cameras = list((await session.execute(select(Camera).order_by(Camera.camera_code))).scalars().all())
        assert [camera.camera_code for camera in cameras] == expectations["camera_codes"]
        assert all(camera.camera_code.startswith("DEMO-") for camera in cameras)
        assert all(camera.notes and len(camera.notes) > 10 for camera in cameras)
        assert all(camera.calibration_config["trafficmind_record_origin"]["mode"] == "demo_seed" for camera in cameras)

        streams = list((await session.execute(select(CameraStream).order_by(CameraStream.name))).scalars().all())
        assert all(stream.source_type.value == "test" for stream in streams)
        assert all(stream.source_uri.startswith("demo://") for stream in streams)

        events = list((await session.execute(select(DetectionEvent).order_by(DetectionEvent.occurred_at))).scalars().all())
        assert all(event.event_payload["trafficmind_record_origin"]["mode"] == "demo_seed" for event in events)

        violations = list((await session.execute(select(ViolationEvent).order_by(ViolationEvent.occurred_at))).scalars().all())
        assert any(violation.status.value == "confirmed" for violation in violations)
        assert any(violation.status.value == "under_review" for violation in violations)
        assert any(violation.status.value == "dismissed" for violation in violations)

        assert report["scenario_name"] == expectations["scenario_name"]
        assert report["synthetic"] is True
        assert report["counts"] == expectations["counts"]
        assert report["health_dashboard_preview"]["cameras_online"] == expectations["health_dashboard_preview"]["cameras_online"]
        assert report["health_dashboard_preview"]["cameras_degraded"] == expectations["health_dashboard_preview"]["cameras_degraded"]
        assert report["health_dashboard_preview"]["cameras_offline"] == expectations["health_dashboard_preview"]["cameras_offline"]
        assert report["walkthrough"]["api_hints"] == ["/api/v1/cameras", "/api/v1/observability/dashboard", "/api/v1/exports"]

    await engine.dispose()


@pytest.mark.asyncio
async def test_demo_seed_is_repeatable_without_duplicates() -> None:
    expectations = load_json_fixture("demo/seed_expectations.json")
    session_factory, engine = await make_sqlite_session_factory()

    async with session_factory() as session:
        await seed_demo_scenario(session, now=FIXED_NOW)
        await session.commit()

    async with session_factory() as session:
        await seed_demo_scenario(session, now=FIXED_NOW)
        await session.commit()

        assert await _count_rows(session, Camera) == expectations["counts"]["cameras"]
        assert await _count_rows(session, CameraStream) == expectations["counts"]["streams"]
        assert await _count_rows(session, DetectionEvent) == expectations["counts"]["events"]
        assert await _count_rows(session, ViolationEvent) == expectations["counts"]["violations"]

    await engine.dispose()


@pytest.mark.asyncio
async def test_demo_seed_surfaces_in_camera_and_observability_apis(demo_client: tuple[AsyncClient, object]) -> None:
    client, _session_factory = demo_client

    cameras_resp = await client.get("/api/v1/cameras", params={"limit": 100})
    assert cameras_resp.status_code == 200
    cameras_payload = cameras_resp.json()
    assert cameras_payload["total"] == 3
    assert any(item["camera_code"] == "DEMO-CAM-001" for item in cameras_payload["items"])

    dashboard_resp = await client.get("/api/v1/observability/dashboard")
    assert dashboard_resp.status_code == 200
    dashboard = dashboard_resp.json()
    assert dashboard["total_cameras"] == 3
    assert dashboard["cameras_online"] == 1
    assert dashboard["cameras_degraded"] == 1
    assert dashboard["cameras_offline"] == 1
    assert dashboard["total_streams"] == 4
    assert {camera["camera_code"] for camera in dashboard["cameras"]} == {"DEMO-CAM-001", "DEMO-CAM-002", "DEMO-CAM-003"}