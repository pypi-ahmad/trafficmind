from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.app.main import create_app

NOW = datetime(2026, 4, 5, 16, 0, tzinfo=UTC)


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


@pytest.mark.asyncio
async def test_signal_controller_event_ingest_and_snapshot(client: AsyncClient) -> None:
    camera_id = uuid.uuid4()
    ingest = await client.post(
        "/api/v1/signals/controller/events",
        json={
            "events": [
                {
                    "camera_id": str(camera_id),
                    "junction_id": "j-main-1",
                    "controller_id": "controller-a",
                    "phase_id": "veh-main",
                    "phase": "vehicle",
                    "state": "red",
                    "timestamp": NOW.isoformat(),
                    "source_type": "webhook_event",
                    "confidence": 0.99,
                    "trust_score": 0.95,
                    "stop_line_id": "sl-1",
                }
            ]
        },
    )
    assert ingest.status_code == 200
    assert ingest.json()["accepted_count"] == 1

    snapshot = await client.get(
        "/api/v1/signals/controller/snapshot",
        params={"camera_id": str(camera_id), "timestamp": NOW.isoformat()},
    )
    assert snapshot.status_code == 200
    payload = snapshot.json()
    assert payload["usable_signal_count"] == 1
    assert payload["signal_states"][0]["state"] == "red"
    assert payload["signal_states"][0]["source_kind"] == "controller"


@pytest.mark.asyncio
async def test_signal_resolve_endpoint_reports_conflict(client: AsyncClient) -> None:
    camera_id = uuid.uuid4()
    await client.post(
        "/api/v1/signals/controller/events",
        json={
            "events": [
                {
                    "camera_id": str(camera_id),
                    "junction_id": "j-main-1",
                    "controller_id": "controller-a",
                    "phase_id": "veh-main",
                    "phase": "vehicle",
                    "state": "green",
                    "timestamp": NOW.isoformat(),
                    "source_type": "webhook_event",
                    "confidence": 0.99,
                    "trust_score": 0.95,
                    "stop_line_id": "sl-1",
                }
            ]
        },
    )

    resolve = await client.post(
        "/api/v1/signals/resolve",
        json={
            "mode": "hybrid",
            "camera_id": str(camera_id),
            "timestamp": NOW.isoformat(),
            "vision_scene_context": {
                "frame_index": 12,
                "timestamp": NOW.isoformat(),
                "traffic_light_state": "red",
                "vehicle_signal_state": "red",
                "pedestrian_signal_state": "unknown",
                "signal_states": [
                    {
                        "head_id": "vision-head-1",
                        "phase": "vehicle",
                        "state": "red",
                        "confidence": 0.9,
                        "trust_score": 0.9,
                        "stop_line_id": "sl-1",
                        "source_kind": "vision",
                        "observed_sources": ["vision"],
                    }
                ],
                "vision_signal_states": [
                    {
                        "head_id": "vision-head-1",
                        "phase": "vehicle",
                        "state": "red",
                        "confidence": 0.9,
                        "trust_score": 0.9,
                        "stop_line_id": "sl-1",
                        "source_kind": "vision",
                        "observed_sources": ["vision"],
                    }
                ],
            },
        },
    )

    assert resolve.status_code == 200
    payload = resolve.json()
    assert payload["vehicle_signal_state"] == "unknown"
    assert payload["integration_mode"] == "hybrid"
    assert len(payload["signal_conflicts"]) == 1
    assert payload["signal_conflicts"][0]["vision_state"] == "red"
    assert payload["signal_conflicts"][0]["controller_state"] == "green"


@pytest.mark.asyncio
async def test_signal_file_feed_and_mock_simulator_endpoints(client: AsyncClient) -> None:
    camera_id = uuid.uuid4()
    file_feed = await client.post(
        "/api/v1/signals/controller/file-feed",
        json={
            "payload_format": "json",
            "source_label": "file-feed-a",
            "payload": (
                f'[{{"camera_id": "{camera_id}", "junction_id": "j-main-1", '
                f'"controller_id": "controller-a", "phase_id": "veh-main", '
                f'"phase": "vehicle", "state": "red", '
                f'"timestamp": "{NOW.isoformat()}", "confidence": 0.97, '
                f'"trust_score": 0.94, "stop_line_id": "sl-1"}}]'
            ),
        },
    )
    assert file_feed.status_code == 200
    assert file_feed.json()["accepted_count"] == 1

    simulator = await client.post(
        "/api/v1/signals/controller/mock/simulate",
        json={
            "camera_id": str(camera_id),
            "junction_id": "j-main-1",
            "controller_id": "controller-a",
            "cycle_started_at": NOW.isoformat(),
            "at_time": NOW.replace(second=25).isoformat(),
            "steps": [
                {
                    "duration_seconds": 20,
                    "states": [
                        {
                            "phase_id": "veh-main",
                            "phase": "vehicle",
                            "state": "green",
                            "stop_line_id": "sl-1",
                        }
                    ],
                },
                {
                    "duration_seconds": 20,
                    "states": [
                        {
                            "phase_id": "veh-main",
                            "phase": "vehicle",
                            "state": "red",
                            "stop_line_id": "sl-1",
                        }
                    ],
                },
            ],
        },
    )

    assert simulator.status_code == 200
    payload = simulator.json()
    assert payload["signal_states"][0]["state"] == "red"
    assert payload["signal_states"][0]["source_kind"] == "controller"
