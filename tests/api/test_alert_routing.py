"""Integration tests for the alert routing and escalation foundation."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.db.base import Base
from apps.api.app.db.enums import (
    CameraStatus,
    PlateReadStatus,
    SourceType,
    StreamKind,
    StreamStatus,
    WatchlistAlertStatus,
    WatchlistEntryStatus,
    WatchlistReason,
)
from apps.api.app.db.models import Camera, CameraStream, PlateRead, WatchlistAlert, WatchlistEntry
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
async def seeded_watchlist_signal(
    client: tuple[AsyncClient, async_sessionmaker],
) -> tuple[AsyncClient, async_sessionmaker, dict[str, str]]:
    client, session_factory = client
    occurred_at = datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        camera = Camera(
            camera_code="CAM-ALERT-001",
            name="Alert Camera",
            location_name="Main St & 2nd Ave",
            status=CameraStatus.ACTIVE,
        )
        stream = CameraStream(
            camera=camera,
            name="primary",
            stream_kind=StreamKind.PRIMARY,
            source_type=SourceType.RTSP,
            source_uri="rtsp://trafficmind.local/alerts/cam-001",
            status=StreamStatus.LIVE,
            is_enabled=True,
        )
        plate_read = PlateRead(
            camera=camera,
            stream=stream,
            status=PlateReadStatus.MATCHED,
            occurred_at=occurred_at,
            plate_text="ABC1234",
            normalized_plate_text="ABC1234",
            confidence=0.98,
            bbox={"x1": 100, "y1": 120, "x2": 220, "y2": 180},
        )
        entry = WatchlistEntry(
            normalized_plate_text="ABC1234",
            plate_text_display="ABC1234",
            reason=WatchlistReason.WANTED,
            status=WatchlistEntryStatus.ACTIVE,
            description="Known wanted vehicle",
            alert_enabled=True,
        )
        alert = WatchlistAlert(
            plate_read=plate_read,
            watchlist_entry=entry,
            camera=camera,
            status=WatchlistAlertStatus.OPEN,
            occurred_at=occurred_at,
            normalized_plate_text="ABC1234",
            plate_text="ABC1234",
            reason=WatchlistReason.WANTED,
            description="Known wanted vehicle",
            alert_metadata={"source": "integration-test"},
        )

        session.add_all([camera, stream, plate_read, entry, alert])
        await session.commit()
        await session.refresh(camera)
        await session.refresh(stream)
        await session.refresh(alert)

        return client, session_factory, {
            "camera_id": str(camera.id),
            "stream_id": str(stream.id),
            "watchlist_alert_id": str(alert.id),
            "occurred_at": occurred_at.isoformat(),
        }


async def _create_policy_stack(client: AsyncClient) -> dict[str, str]:
    ops_target = await client.post(
        "/api/v1/alerts/targets",
        params={"access_role": "evidence_admin"},
        json={
            "name": "Ops Email",
            "channel": "email",
            "destination": "ops@trafficmind.local",
            "config": {"template": "watchlist-primary"},
        },
    )
    assert ops_target.status_code == 201

    escalation_target = await client.post(
        "/api/v1/alerts/targets",
        params={"access_role": "evidence_admin"},
        json={
            "name": "Escalation Webhook",
            "channel": "webhook",
            "destination": "https://alerts.trafficmind.local/escalate",
            "config": {"auth_scheme": "placeholder"},
        },
    )
    assert escalation_target.status_code == 201

    policy_resp = await client.post(
        "/api/v1/alerts/policies",
        params={"access_role": "evidence_admin"},
        json={
            "name": "Wanted Watchlist Match",
            "description": "Immediately notify operations and escalate after ten minutes.",
            "source_kind": "watchlist_alert",
            "condition_key": "watchlist_match",
            "min_severity": "high",
            "cooldown_seconds": 300,
            "dedup_window_seconds": 900,
            "routes": [
                {
                    "routing_target_id": ops_target.json()["id"],
                    "escalation_level": 0,
                    "delay_seconds": 0,
                },
                {
                    "routing_target_id": escalation_target.json()["id"],
                    "escalation_level": 1,
                    "delay_seconds": 600,
                },
            ],
        },
    )
    assert policy_resp.status_code == 201

    return {
        "ops_target_id": ops_target.json()["id"],
        "escalation_target_id": escalation_target.json()["id"],
        "policy_id": policy_resp.json()["id"],
    }


@pytest.mark.asyncio
async def test_alert_policy_routes_require_manage_policy_permission(
    client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    client, _session_factory = client

    resp = await client.post(
        "/api/v1/alerts/targets",
        json={
            "name": "Ops Email",
            "channel": "email",
            "destination": "ops@trafficmind.local",
            "config": {"template": "watchlist-primary"},
        },
    )
    assert resp.status_code == 403
    assert "manage_policy_settings" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_signal_creates_routed_alert_with_audit_trail(seeded_watchlist_signal: tuple) -> None:
    client, _session_factory, seeded = seeded_watchlist_signal
    policy_stack = await _create_policy_stack(client)

    signal_resp = await client.post(
        "/api/v1/alerts/signals",
        json={
            "source_kind": "watchlist_alert",
            "condition_key": "watchlist_match",
            "severity": "high",
            "title": "Wanted plate matched",
            "summary": "ABC1234 matched a wanted watchlist entry.",
            "occurred_at": seeded["occurred_at"],
            "camera_id": seeded["camera_id"],
            "stream_id": seeded["stream_id"],
            "watchlist_alert_id": seeded["watchlist_alert_id"],
            "dedup_key": f"watchlist:{seeded['watchlist_alert_id']}",
            "source_payload": {"reason": "wanted", "plate_text": "ABC1234"},
        },
    )

    assert signal_resp.status_code == 200
    payload = signal_resp.json()
    assert payload["matched_policy_count"] == 1
    assert payload["created_count"] == 1
    assert payload["deduplicated_count"] == 0
    assert len(payload["alerts"]) == 1

    alert_id = payload["alerts"][0]["id"]
    assert payload["alerts"][0]["policy_id"] == policy_stack["policy_id"]
    assert payload["alerts"][0]["status"] == "new"
    assert payload["alerts"][0]["occurrence_count"] == 1

    detail_resp = await client.get(f"/api/v1/alerts/{alert_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["watchlist_alert_id"] == seeded["watchlist_alert_id"]
    assert len(detail["deliveries"]) == 1
    assert detail["deliveries"][0]["routing_target_id"] == policy_stack["ops_target_id"]
    assert detail["deliveries"][0]["delivery_state"] == "planned"
    assert [event["event_type"] for event in detail["audit_events"]] == ["created", "routed"]


@pytest.mark.asyncio
async def test_signal_deduplicates_within_window_without_replanning_routes(seeded_watchlist_signal: tuple) -> None:
    client, _session_factory, seeded = seeded_watchlist_signal
    await _create_policy_stack(client)

    signal_body = {
        "source_kind": "watchlist_alert",
        "condition_key": "watchlist_match",
        "severity": "high",
        "title": "Wanted plate matched",
        "summary": "ABC1234 matched a wanted watchlist entry.",
        "occurred_at": seeded["occurred_at"],
        "camera_id": seeded["camera_id"],
        "stream_id": seeded["stream_id"],
        "watchlist_alert_id": seeded["watchlist_alert_id"],
        "dedup_key": f"watchlist:{seeded['watchlist_alert_id']}",
        "source_payload": {"reason": "wanted", "plate_text": "ABC1234"},
    }

    first = await client.post("/api/v1/alerts/signals", json=signal_body)
    assert first.status_code == 200
    alert_id = first.json()["alerts"][0]["id"]

    second = await client.post("/api/v1/alerts/signals", json=signal_body)
    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["matched_policy_count"] == 1
    assert second_payload["created_count"] == 0
    assert second_payload["deduplicated_count"] == 1
    assert second_payload["alerts"][0]["id"] == alert_id
    assert second_payload["alerts"][0]["occurrence_count"] == 2

    detail_resp = await client.get(f"/api/v1/alerts/{alert_id}")
    detail = detail_resp.json()
    assert len(detail["deliveries"]) == 1
    assert [event["event_type"] for event in detail["audit_events"]] == ["created", "routed", "deduplicated"]


@pytest.mark.asyncio
async def test_due_escalations_are_processed_and_alert_can_be_resolved(seeded_watchlist_signal: tuple) -> None:
    client, _session_factory, seeded = seeded_watchlist_signal
    await _create_policy_stack(client)

    signal_resp = await client.post(
        "/api/v1/alerts/signals",
        json={
            "source_kind": "watchlist_alert",
            "condition_key": "watchlist_match",
            "severity": "high",
            "title": "Wanted plate matched",
            "summary": "ABC1234 matched a wanted watchlist entry.",
            "occurred_at": seeded["occurred_at"],
            "camera_id": seeded["camera_id"],
            "stream_id": seeded["stream_id"],
            "watchlist_alert_id": seeded["watchlist_alert_id"],
            "dedup_key": f"watchlist:{seeded['watchlist_alert_id']}",
            "source_payload": {"reason": "wanted", "plate_text": "ABC1234"},
        },
    )
    assert signal_resp.status_code == 200
    alert_id = signal_resp.json()["alerts"][0]["id"]

    escalations_resp = await client.post(
        "/api/v1/alerts/escalations/process",
        json={
            "as_of": (datetime.fromisoformat(seeded["occurred_at"]) + timedelta(minutes=11)).isoformat(),
        },
    )
    assert escalations_resp.status_code == 200
    escalation_payload = escalations_resp.json()
    assert escalation_payload["processed_count"] == 1
    assert escalation_payload["alert_ids"] == [alert_id]

    detail_resp = await client.get(f"/api/v1/alerts/{alert_id}")
    detail = detail_resp.json()
    assert detail["status"] == "escalated"
    assert detail["escalation_level"] == 1
    assert len(detail["deliveries"]) == 2
    assert detail["deliveries"][1]["delivery_state"] == "planned"
    assert [event["event_type"] for event in detail["audit_events"]] == ["created", "routed", "escalated"]

    acknowledge_resp = await client.post(
        f"/api/v1/alerts/{alert_id}/acknowledge",
        json={"actor": "ops.user", "note": "Investigating the wanted vehicle alert."},
    )
    assert acknowledge_resp.status_code == 200
    ack_detail = acknowledge_resp.json()
    assert ack_detail["status"] == "acknowledged"
    assert ack_detail["escalation_due_at"] is None, "Acknowledging must clear escalation_due_at"

    # A second escalation sweep AFTER acknowledge must NOT re-escalate
    late_esc_resp = await client.post(
        "/api/v1/alerts/escalations/process",
        json={
            "as_of": (datetime.fromisoformat(seeded["occurred_at"]) + timedelta(minutes=30)).isoformat(),
        },
    )
    assert late_esc_resp.status_code == 200
    assert late_esc_resp.json()["processed_count"] == 0, "Acknowledged alerts must not be re-escalated"

    resolve_resp = await client.post(
        f"/api/v1/alerts/{alert_id}/resolve",
        json={"actor": "ops.user", "note": "Vehicle stop confirmed and alert closed."},
    )
    assert resolve_resp.status_code == 200
    assert resolve_resp.json()["status"] == "resolved"


@pytest.mark.asyncio
async def test_dedup_after_acknowledge_skips_rerouting(seeded_watchlist_signal: tuple) -> None:
    """Once a human acknowledges, repeat signals must dedup but NOT plan new deliveries."""
    client, _session_factory, seeded = seeded_watchlist_signal
    await _create_policy_stack(client)

    signal_body = {
        "source_kind": "watchlist_alert",
        "condition_key": "watchlist_match",
        "severity": "high",
        "title": "Wanted plate matched",
        "summary": "ABC1234 matched a wanted watchlist entry.",
        "occurred_at": seeded["occurred_at"],
        "camera_id": seeded["camera_id"],
        "stream_id": seeded["stream_id"],
        "watchlist_alert_id": seeded["watchlist_alert_id"],
        "dedup_key": f"watchlist:{seeded['watchlist_alert_id']}",
        "source_payload": {"reason": "wanted", "plate_text": "ABC1234"},
    }

    first = await client.post("/api/v1/alerts/signals", json=signal_body)
    assert first.status_code == 200
    alert_id = first.json()["alerts"][0]["id"]

    ack = await client.post(
        f"/api/v1/alerts/{alert_id}/acknowledge",
        json={"actor": "ops.user", "note": "Working on it."},
    )
    assert ack.status_code == 200

    # Send a duplicate signal well past the cooldown window (5 min)
    late_signal = dict(signal_body)
    late_time = datetime.fromisoformat(seeded["occurred_at"]) + timedelta(minutes=10)
    late_signal["occurred_at"] = late_time.isoformat()
    dedup_resp = await client.post("/api/v1/alerts/signals", json=late_signal)
    assert dedup_resp.status_code == 200
    assert dedup_resp.json()["deduplicated_count"] == 1

    detail = (await client.get(f"/api/v1/alerts/{alert_id}")).json()
    assert len(detail["deliveries"]) == 1, "No new deliveries after acknowledge"
    assert detail["status"] == "acknowledged", "Status must stay acknowledged"
    # Original source_payload preserved, not overwritten
    assert detail["source_payload"]["reason"] == "wanted"