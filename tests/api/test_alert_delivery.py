"""Tests for alert delivery adapters and the dispatch pipeline."""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json
import os
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.db.base import Base
from apps.api.app.db.enums import (
    AlertDeliveryState,
    AlertRoutingChannel,
    CameraStatus,
    OperationalAlertSeverity,
    OperationalAlertSourceKind,
    OperationalAlertStatus,
    PlateReadStatus,
    SourceType,
    StreamKind,
    StreamStatus,
    WatchlistAlertStatus,
    WatchlistEntryStatus,
    WatchlistReason,
)
from apps.api.app.db.models import (
    AlertDeliveryAttempt,
    Camera,
    CameraStream,
    PlateRead,
    WatchlistAlert,
    WatchlistEntry,
)
from apps.api.app.db.session import get_db_session
from apps.api.app.main import create_app
from apps.api.app.services.delivery import (
    AlertDeliveryDispatcher,
    ChannelDeliveryAdapter,
    LogDeliveryAdapter,
    SmtpDeliveryAdapter,
    WebhookDeliveryAdapter,
    build_default_dispatcher,
)


# ---------------------------------------------------------------------------
# Helpers: fake AlertDeliveryAttempt-like objects for unit tests
# ---------------------------------------------------------------------------


class _FakeAttempt:
    """Lightweight stand-in for ``AlertDeliveryAttempt`` ORM objects.

    Adapters only read a handful of attributes; they don't need a real
    SQLAlchemy mapped instance.
    """

    def __init__(
        self,
        *,
        channel: AlertRoutingChannel = AlertRoutingChannel.WEBHOOK,
        destination: str = "https://alerts.example.test/hook",
        delivery_payload: dict[str, Any] | None = None,
        escalation_level: int = 0,
    ) -> None:
        self.id = uuid.uuid4()
        self.alert_id = uuid.uuid4()
        self.channel = channel
        self.destination = destination
        self.delivery_state = AlertDeliveryState.PLANNED
        self.escalation_level = escalation_level
        self.scheduled_for = datetime.now(timezone.utc)
        self.attempted_at: datetime | None = None
        self.error_message: str | None = None
        self.delivery_payload = delivery_payload or {
            "severity": "high",
            "condition_key": "watchlist_match",
            "route_config": {},
            "target_config": {},
        }


def _fake_attempt(**kwargs: Any) -> Any:
    return _FakeAttempt(**kwargs)


# ---------------------------------------------------------------------------
# Unit tests: individual adapters
# ---------------------------------------------------------------------------


class TestWebhookDeliveryAdapter:
    @pytest.mark.asyncio
    async def test_success_returns_none(self) -> None:
        adapter = WebhookDeliveryAdapter()
        attempt = _fake_attempt()

        with patch("apps.api.app.services.delivery.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_response = AsyncMock()
            mock_response.raise_for_status = lambda: None
            mock_client.post.return_value = mock_response

            error = await adapter.deliver(attempt)

        assert error is None
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        body_bytes = call_kwargs.kwargs.get("content") or call_kwargs[1].get("content")
        posted_json = json.loads(body_bytes)
        assert posted_json["alert_id"] == str(attempt.alert_id)
        assert posted_json["severity"] == "high"

    @pytest.mark.asyncio
    async def test_http_error_returns_message(self) -> None:
        import httpx

        adapter = WebhookDeliveryAdapter()
        attempt = _fake_attempt()

        with patch("apps.api.app.services.delivery.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            resp = AsyncMock()
            resp.status_code = 503
            resp.text = "Service Unavailable"
            mock_client.post.side_effect = httpx.HTTPStatusError(
                "503", request=httpx.Request("POST", "https://x"), response=resp,
            )

            error = await adapter.deliver(attempt)

        assert error is not None
        assert "503" in error

    @pytest.mark.asyncio
    async def test_connection_error_returns_message(self) -> None:
        import httpx

        adapter = WebhookDeliveryAdapter()
        attempt = _fake_attempt()

        with patch("apps.api.app.services.delivery.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post.side_effect = httpx.ConnectError("Connection refused")

            error = await adapter.deliver(attempt)

        assert error is not None
        assert "Connection refused" in error

    @pytest.mark.asyncio
    async def test_sends_delivery_id_header(self) -> None:
        adapter = WebhookDeliveryAdapter()
        attempt = _fake_attempt()
        attempt.id = uuid.uuid4()

        with patch("apps.api.app.services.delivery.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_response = AsyncMock()
            mock_response.raise_for_status = lambda: None
            mock_client.post.return_value = mock_response

            error = await adapter.deliver(attempt)

        assert error is None
        call_kwargs = mock_client.post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert headers["X-TrafficMind-Delivery-Id"] == str(attempt.id)

    @pytest.mark.asyncio
    async def test_hmac_signature_when_signing_secret_set(self) -> None:
        secret = "test-signing-secret-42"
        adapter = WebhookDeliveryAdapter()
        attempt = _fake_attempt(delivery_payload={
            "severity": "high",
            "condition_key": "test",
            "route_config": {},
            "target_config": {"signing_secret": secret},
        })

        with patch("apps.api.app.services.delivery.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_response = AsyncMock()
            mock_response.raise_for_status = lambda: None
            mock_client.post.return_value = mock_response

            error = await adapter.deliver(attempt)

        assert error is None
        call_kwargs = mock_client.post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert "X-TrafficMind-Signature" in headers
        sig_header = headers["X-TrafficMind-Signature"]
        assert sig_header.startswith("sha256=")

        body_bytes = call_kwargs.kwargs.get("content") or call_kwargs[1].get("content")
        expected = hmac_mod.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()
        assert sig_header == f"sha256={expected}"


class TestSmtpDeliveryAdapter:
    @pytest.mark.asyncio
    async def test_missing_smtp_host_returns_error(self) -> None:
        adapter = SmtpDeliveryAdapter()
        attempt = _fake_attempt(
            channel=AlertRoutingChannel.EMAIL,
            destination="ops@trafficmind.local",
        )
        error = await adapter.deliver(attempt)
        assert error is not None
        assert "smtp_host" in error

    @pytest.mark.asyncio
    async def test_successful_smtp_delivery(self) -> None:
        adapter = SmtpDeliveryAdapter()
        attempt = _fake_attempt(
            channel=AlertRoutingChannel.EMAIL,
            destination="ops@trafficmind.local",
            delivery_payload={
                "severity": "high",
                "condition_key": "camera_offline",
                "route_config": {},
                "target_config": {
                    "smtp_host": "mail.example.test",
                    "smtp_port": 25,
                    "from_addr": "alerts@trafficmind.local",
                },
            },
        )

        with patch("apps.api.app.services.delivery.smtplib.SMTP") as mock_smtp_cls:
            mock_server = mock_smtp_cls.return_value.__enter__.return_value
            mock_server.ehlo.return_value = None
            mock_server.send_message.return_value = {}

            error = await adapter.deliver(attempt)

        assert error is None
        mock_server.send_message.assert_called_once()
        sent_msg = mock_server.send_message.call_args[0][0]
        assert sent_msg["To"] == "ops@trafficmind.local"
        assert "camera_offline" in sent_msg["Subject"]

    @pytest.mark.asyncio
    async def test_smtp_connection_failure(self) -> None:
        adapter = SmtpDeliveryAdapter()
        attempt = _fake_attempt(
            channel=AlertRoutingChannel.EMAIL,
            destination="ops@trafficmind.local",
            delivery_payload={
                "severity": "high",
                "condition_key": "test",
                "route_config": {},
                "target_config": {"smtp_host": "unreachable.test", "smtp_port": 25},
            },
        )

        with patch("apps.api.app.services.delivery.smtplib.SMTP") as mock_smtp_cls:
            mock_smtp_cls.side_effect = OSError("Connection refused")
            error = await adapter.deliver(attempt)

        assert error is not None
        assert "Connection" in error

    @pytest.mark.asyncio
    async def test_env_fallback_for_smtp_host(self) -> None:
        adapter = SmtpDeliveryAdapter()
        attempt = _fake_attempt(
            channel=AlertRoutingChannel.EMAIL,
            destination="ops@trafficmind.local",
            delivery_payload={
                "severity": "medium",
                "condition_key": "test",
                "route_config": {},
                "target_config": {},
            },
        )

        env_patch = {
            "ALERT_SMTP_HOST": "env-mail.test",
            "ALERT_SMTP_PORT": "25",
            "ALERT_SMTP_FROM": "env-sender@trafficmind.local",
        }
        with patch("apps.api.app.services.delivery.smtplib.SMTP") as mock_smtp_cls, \
             patch.dict(os.environ, env_patch, clear=False):
            mock_server = mock_smtp_cls.return_value.__enter__.return_value
            mock_server.ehlo.return_value = None
            mock_server.send_message.return_value = {}

            error = await adapter.deliver(attempt)

        assert error is None
        mock_smtp_cls.assert_called_once_with("env-mail.test", 25, timeout=15)
        sent_msg = mock_server.send_message.call_args[0][0]
        assert sent_msg["From"] == "env-sender@trafficmind.local"

    @pytest.mark.asyncio
    async def test_target_config_overrides_env(self) -> None:
        adapter = SmtpDeliveryAdapter()
        attempt = _fake_attempt(
            channel=AlertRoutingChannel.EMAIL,
            destination="ops@trafficmind.local",
            delivery_payload={
                "severity": "medium",
                "condition_key": "test",
                "route_config": {},
                "target_config": {
                    "smtp_host": "target-mail.test",
                    "smtp_port": 25,
                },
            },
        )

        env_patch = {"ALERT_SMTP_HOST": "env-mail.test", "ALERT_SMTP_PORT": "587"}
        with patch("apps.api.app.services.delivery.smtplib.SMTP") as mock_smtp_cls, \
             patch.dict(os.environ, env_patch, clear=False):
            mock_server = mock_smtp_cls.return_value.__enter__.return_value
            mock_server.ehlo.return_value = None
            mock_server.send_message.return_value = {}

            error = await adapter.deliver(attempt)

        assert error is None
        mock_smtp_cls.assert_called_once_with("target-mail.test", 25, timeout=15)


class TestLogDeliveryAdapter:
    @pytest.mark.asyncio
    async def test_log_adapter_always_succeeds(self) -> None:
        adapter = LogDeliveryAdapter(channel=AlertRoutingChannel.SMS)
        attempt = _fake_attempt(
            channel=AlertRoutingChannel.SMS,
            destination="+1-555-0100",
        )
        error = await adapter.deliver(attempt)
        assert error is None

    @pytest.mark.asyncio
    async def test_log_adapter_accepts_any_channel(self) -> None:
        for ch in (AlertRoutingChannel.SMS, AlertRoutingChannel.SLACK, AlertRoutingChannel.TEAMS):
            adapter = LogDeliveryAdapter(channel=ch)
            assert adapter.channel == ch
            attempt = _fake_attempt(channel=ch, destination="test-dest")
            error = await adapter.deliver(attempt)
            assert error is None


# ---------------------------------------------------------------------------
# Unit tests: dispatcher
# ---------------------------------------------------------------------------


class TestAlertDeliveryDispatcher:
    @pytest.mark.asyncio
    async def test_dispatch_routes_to_correct_adapter(self) -> None:
        dispatcher = AlertDeliveryDispatcher()

        class _StubAdapter(ChannelDeliveryAdapter):
            channel = AlertRoutingChannel.WEBHOOK
            calls: list[AlertDeliveryAttempt] = []

            async def deliver(self, attempt: AlertDeliveryAttempt) -> str | None:
                self.calls.append(attempt)
                return None

        adapter = _StubAdapter()
        dispatcher.register(adapter)

        attempt = _fake_attempt(channel=AlertRoutingChannel.WEBHOOK)
        result = await dispatcher.dispatch_one(attempt)

        assert result.delivery_state == AlertDeliveryState.SENT
        assert result.attempted_at is not None
        assert result.error_message is None
        assert len(adapter.calls) == 1

    @pytest.mark.asyncio
    async def test_dispatch_marks_failed_on_adapter_error(self) -> None:
        dispatcher = AlertDeliveryDispatcher()

        class _FailAdapter(ChannelDeliveryAdapter):
            channel = AlertRoutingChannel.WEBHOOK

            async def deliver(self, attempt: AlertDeliveryAttempt) -> str | None:
                return "Boom! Something went wrong."

        dispatcher.register(_FailAdapter())
        attempt = _fake_attempt(channel=AlertRoutingChannel.WEBHOOK)
        result = await dispatcher.dispatch_one(attempt)

        assert result.delivery_state == AlertDeliveryState.FAILED
        assert result.error_message == "Boom! Something went wrong."
        assert result.attempted_at is not None

    @pytest.mark.asyncio
    async def test_dispatch_skips_when_no_adapter_registered(self) -> None:
        dispatcher = AlertDeliveryDispatcher()
        attempt = _fake_attempt(channel=AlertRoutingChannel.SLACK)
        result = await dispatcher.dispatch_one(attempt)

        assert result.delivery_state == AlertDeliveryState.SKIPPED
        assert "No adapter registered" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_dispatch_many_isolates_failures(self) -> None:
        dispatcher = AlertDeliveryDispatcher()
        call_count = 0

        class _AlternatingAdapter(ChannelDeliveryAdapter):
            channel = AlertRoutingChannel.WEBHOOK

            async def deliver(self, attempt: AlertDeliveryAttempt) -> str | None:
                nonlocal call_count
                call_count += 1
                return "fail" if call_count % 2 == 0 else None

        dispatcher.register(_AlternatingAdapter())
        attempts = [_fake_attempt() for _ in range(4)]
        results = await dispatcher.dispatch_many(attempts)

        states = [r.delivery_state for r in results]
        assert states == [
            AlertDeliveryState.SENT,
            AlertDeliveryState.FAILED,
            AlertDeliveryState.SENT,
            AlertDeliveryState.FAILED,
        ]


class TestBuildDefaultDispatcher:
    def test_has_all_channels(self) -> None:
        dispatcher = build_default_dispatcher()
        channels = dispatcher.channels
        assert "webhook" in channels
        assert "email" in channels
        assert "sms" in channels
        assert "slack" in channels
        assert "teams" in channels


# ---------------------------------------------------------------------------
# Integration test: full dispatch flow through the alert API
# ---------------------------------------------------------------------------


@pytest.fixture
async def alert_client() -> AsyncIterator[tuple[AsyncClient, async_sessionmaker]]:
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


@pytest.mark.asyncio
async def test_dispatch_delivers_planned_attempts_and_updates_state(
    alert_client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    client, session_factory = alert_client
    occurred_at = datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc)

    # Seed camera + stream + watchlist
    async with session_factory() as session:
        camera = Camera(
            camera_code="CAM-DELIV-001",
            name="Delivery Camera",
            location_name="Main St",
            status=CameraStatus.ACTIVE,
        )
        stream = CameraStream(
            camera=camera,
            name="primary",
            stream_kind=StreamKind.PRIMARY,
            source_type=SourceType.RTSP,
            source_uri="rtsp://trafficmind.local/delivery/cam-001",
            status=StreamStatus.LIVE,
            is_enabled=True,
        )
        plate = PlateRead(
            camera=camera,
            stream=stream,
            status=PlateReadStatus.MATCHED,
            occurred_at=occurred_at,
            plate_text="XYZ9999",
            normalized_plate_text="XYZ9999",
            confidence=0.97,
            bbox={"x1": 10, "y1": 20, "x2": 30, "y2": 40},
        )
        entry = WatchlistEntry(
            normalized_plate_text="XYZ9999",
            plate_text_display="XYZ9999",
            reason=WatchlistReason.WANTED,
            status=WatchlistEntryStatus.ACTIVE,
            description="Test delivery",
            alert_enabled=True,
        )
        alert_record = WatchlistAlert(
            plate_read=plate,
            watchlist_entry=entry,
            camera=camera,
            status=WatchlistAlertStatus.OPEN,
            occurred_at=occurred_at,
            normalized_plate_text="XYZ9999",
            plate_text="XYZ9999",
            reason=WatchlistReason.WANTED,
            description="Test delivery",
            alert_metadata={},
        )
        session.add_all([camera, stream, plate, entry, alert_record])
        await session.commit()
        await session.refresh(camera)
        await session.refresh(stream)
        await session.refresh(alert_record)
        camera_id = str(camera.id)
        stream_id = str(stream.id)
        watchlist_alert_id = str(alert_record.id)

    # Create an SMS target (will use LogDeliveryAdapter → always succeeds)
    target_resp = await client.post(
        "/api/v1/alerts/targets",
        params={"access_role": "evidence_admin"},
        json={
            "name": "Ops SMS",
            "channel": "sms",
            "destination": "+1-555-0100",
            "config": {},
        },
    )
    assert target_resp.status_code == 201
    target_id = target_resp.json()["id"]

    # Create policy
    policy_resp = await client.post(
        "/api/v1/alerts/policies",
        params={"access_role": "evidence_admin"},
        json={
            "name": "Delivery Test Policy",
            "source_kind": "watchlist_alert",
            "condition_key": "watchlist_match",
            "min_severity": "high",
            "cooldown_seconds": 300,
            "dedup_window_seconds": 900,
            "routes": [
                {
                    "routing_target_id": target_id,
                    "escalation_level": 0,
                    "delay_seconds": 0,
                },
            ],
        },
    )
    assert policy_resp.status_code == 201

    # Ingest signal → creates PLANNED delivery
    signal_resp = await client.post(
        "/api/v1/alerts/signals",
        json={
            "source_kind": "watchlist_alert",
            "condition_key": "watchlist_match",
            "severity": "high",
            "title": "XYZ9999 matched",
            "summary": "Wanted vehicle detected.",
            "occurred_at": occurred_at.isoformat(),
            "camera_id": camera_id,
            "stream_id": stream_id,
            "watchlist_alert_id": watchlist_alert_id,
            "dedup_key": f"watchlist:{watchlist_alert_id}",
            "source_payload": {"plate_text": "XYZ9999"},
        },
    )
    assert signal_resp.status_code == 200
    alert_id = signal_resp.json()["alerts"][0]["id"]

    # Verify delivery starts as PLANNED
    pre_detail = (await client.get(f"/api/v1/alerts/{alert_id}")).json()
    assert len(pre_detail["deliveries"]) == 1
    assert pre_detail["deliveries"][0]["delivery_state"] == "planned"

    # Dispatch
    dispatch_resp = await client.post(
        "/api/v1/alerts/deliveries/dispatch",
        json={"alert_id": alert_id},
    )
    assert dispatch_resp.status_code == 200
    dispatch_result = dispatch_resp.json()
    assert dispatch_result["dispatched_count"] == 1
    assert dispatch_result["sent_count"] == 1
    assert dispatch_result["failed_count"] == 0
    assert dispatch_result["skipped_count"] == 0

    # Verify delivery is now SENT
    post_detail = (await client.get(f"/api/v1/alerts/{alert_id}")).json()
    assert post_detail["deliveries"][0]["delivery_state"] == "sent"
    assert post_detail["deliveries"][0]["attempted_at"] is not None

    # Re-dispatch should find nothing PLANNED
    redispatch = await client.post(
        "/api/v1/alerts/deliveries/dispatch",
        json={"alert_id": alert_id},
    )
    assert redispatch.json()["dispatched_count"] == 0


@pytest.mark.asyncio
async def test_retry_failed_delivery_via_include_failed(
    alert_client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    """FAILED attempts are retried when include_failed=true."""
    client, session_factory = alert_client
    occurred_at = datetime(2026, 4, 6, 14, 0, tzinfo=timezone.utc)

    # Seed camera + stream + watchlist
    async with session_factory() as session:
        camera = Camera(
            camera_code="CAM-RETRY-001",
            name="Retry Camera",
            location_name="Retry St",
            status=CameraStatus.ACTIVE,
        )
        stream = CameraStream(
            camera=camera,
            name="primary",
            stream_kind=StreamKind.PRIMARY,
            source_type=SourceType.RTSP,
            source_uri="rtsp://trafficmind.local/retry/cam-001",
            status=StreamStatus.LIVE,
            is_enabled=True,
        )
        plate = PlateRead(
            camera=camera,
            stream=stream,
            status=PlateReadStatus.MATCHED,
            occurred_at=occurred_at,
            plate_text="RETRY111",
            normalized_plate_text="RETRY111",
            confidence=0.95,
            bbox={"x1": 10, "y1": 20, "x2": 30, "y2": 40},
        )
        entry = WatchlistEntry(
            normalized_plate_text="RETRY111",
            plate_text_display="RETRY111",
            reason=WatchlistReason.BOLO,
            status=WatchlistEntryStatus.ACTIVE,
            description="Retry test",
            alert_enabled=True,
        )
        alert_record = WatchlistAlert(
            plate_read=plate,
            watchlist_entry=entry,
            camera=camera,
            status=WatchlistAlertStatus.OPEN,
            occurred_at=occurred_at,
            normalized_plate_text="RETRY111",
            plate_text="RETRY111",
            reason=WatchlistReason.BOLO,
            description="Retry test",
            alert_metadata={},
        )
        session.add_all([camera, stream, plate, entry, alert_record])
        await session.commit()
        await session.refresh(camera)
        await session.refresh(stream)
        await session.refresh(alert_record)
        camera_id = str(camera.id)
        stream_id = str(stream.id)
        watchlist_alert_id = str(alert_record.id)

    # Create a webhook target (will fail because no real server)
    target_resp = await client.post(
        "/api/v1/alerts/targets",
        params={"access_role": "evidence_admin"},
        json={
            "name": "Retry Webhook",
            "channel": "webhook",
            "destination": "https://unreachable.test/hook",
            "config": {},
        },
    )
    assert target_resp.status_code == 201
    target_id = target_resp.json()["id"]

    # Create policy
    policy_resp = await client.post(
        "/api/v1/alerts/policies",
        params={"access_role": "evidence_admin"},
        json={
            "name": "Retry Test Policy",
            "source_kind": "watchlist_alert",
            "condition_key": "watchlist_retry_match",
            "min_severity": "high",
            "cooldown_seconds": 300,
            "dedup_window_seconds": 900,
            "routes": [
                {
                    "routing_target_id": target_id,
                    "escalation_level": 0,
                    "delay_seconds": 0,
                },
            ],
        },
    )
    assert policy_resp.status_code == 201

    # Ingest signal → creates PLANNED delivery
    signal_resp = await client.post(
        "/api/v1/alerts/signals",
        json={
            "source_kind": "watchlist_alert",
            "condition_key": "watchlist_retry_match",
            "severity": "high",
            "title": "RETRY111 matched",
            "summary": "BOLO vehicle detected.",
            "occurred_at": occurred_at.isoformat(),
            "camera_id": camera_id,
            "stream_id": stream_id,
            "watchlist_alert_id": watchlist_alert_id,
            "dedup_key": f"watchlist_retry:{watchlist_alert_id}",
            "source_payload": {"plate_text": "RETRY111"},
        },
    )
    assert signal_resp.status_code == 200
    alert_id = signal_resp.json()["alerts"][0]["id"]

    # First dispatch → webhook will FAIL (connection error to unreachable host)
    # Mock the httpx call to simulate failure
    with patch("apps.api.app.services.delivery.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        import httpx
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")

        dispatch1 = await client.post(
            "/api/v1/alerts/deliveries/dispatch",
            json={"alert_id": alert_id},
        )
    assert dispatch1.status_code == 200
    assert dispatch1.json()["failed_count"] == 1
    assert dispatch1.json()["sent_count"] == 0

    # Verify delivery is FAILED
    detail = (await client.get(f"/api/v1/alerts/{alert_id}")).json()
    assert detail["deliveries"][0]["delivery_state"] == "failed"
    assert detail["deliveries"][0]["retry_count"] == 0

    # Normal re-dispatch (no include_failed) should find nothing
    dispatch2 = await client.post(
        "/api/v1/alerts/deliveries/dispatch",
        json={"alert_id": alert_id},
    )
    assert dispatch2.json()["dispatched_count"] == 0

    # Retry with include_failed=true → the LogDeliveryAdapter won't be used
    # for webhook, so let's mock success this time
    with patch("apps.api.app.services.delivery.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_response = AsyncMock()
        mock_response.raise_for_status = lambda: None
        mock_client.post.return_value = mock_response

        dispatch3 = await client.post(
            "/api/v1/alerts/deliveries/dispatch",
            json={"alert_id": alert_id, "include_failed": True, "max_retries": 3},
        )
    assert dispatch3.status_code == 200
    assert dispatch3.json()["dispatched_count"] == 1
    assert dispatch3.json()["sent_count"] == 1
    assert dispatch3.json()["retried_count"] == 1

    # Verify delivery is now SENT with retry_count=1
    final_detail = (await client.get(f"/api/v1/alerts/{alert_id}")).json()
    assert final_detail["deliveries"][0]["delivery_state"] == "sent"
    assert final_detail["deliveries"][0]["retry_count"] == 1
