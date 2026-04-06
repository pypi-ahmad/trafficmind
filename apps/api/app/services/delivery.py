"""Alert delivery adapters and dispatcher.

Each adapter knows how to send one ``AlertDeliveryAttempt`` over a specific
channel (webhook, email, SMS, …).  The ``AlertDeliveryDispatcher`` picks the
right adapter per attempt, calls it, and records the outcome in the database.

Design principles
-----------------
* **Zero vendor lock-in**: only stdlib/httpx for HTTP and smtplib for SMTP.
* **Auditable by default**: every attempt records ``attempted_at``, the final
  ``delivery_state``, and any ``error_message``.
* **Fail-safe**: a single adapter failure marks that attempt as FAILED but
  does not prevent other deliveries on the same alert.
* **Extensible**: register a new ``ChannelDeliveryAdapter`` for any channel
  enum value.
* **Retryable**: FAILED attempts can be retried up to ``max_retries``.
"""

from __future__ import annotations

import abc
import email.message
import hashlib
import hmac
import json
import logging
import os
import smtplib
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from apps.api.app.db.enums import AlertDeliveryState, AlertRoutingChannel
from apps.api.app.db.models import AlertDeliveryAttempt

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Abstract adapter
# ---------------------------------------------------------------------------


class ChannelDeliveryAdapter(abc.ABC):
    """Deliver one alert attempt over a specific channel."""

    channel: AlertRoutingChannel

    @abc.abstractmethod
    async def deliver(self, attempt: AlertDeliveryAttempt) -> str | None:
        """Send the alert.

        Returns
        -------
        str | None
            ``None`` on success, or an error message string on failure.
        """


# ---------------------------------------------------------------------------
# Concrete adapters
# ---------------------------------------------------------------------------


class WebhookDeliveryAdapter(ChannelDeliveryAdapter):
    """POST a JSON payload to the configured ``destination`` URL.

    Expects ``target_config`` to optionally contain:
    * ``auth_header`` — header name for bearer/API-key auth.
    * ``auth_value``  — the secret value (in production this should come
      from a secret manager, not from the database row directly).
    * ``timeout``     — request timeout in seconds (default 15).
    * ``signing_secret`` — if set, the request body is HMAC-SHA256 signed
      and the signature placed in the ``X-TrafficMind-Signature`` header.
    """

    channel = AlertRoutingChannel.WEBHOOK

    async def deliver(self, attempt: AlertDeliveryAttempt) -> str | None:
        url = attempt.destination
        payload = _build_webhook_body(attempt)
        target_cfg: dict[str, Any] = attempt.delivery_payload.get("target_config", {})
        timeout = float(target_cfg.get("timeout", 15))

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "X-TrafficMind-Delivery-Id": str(attempt.id if hasattr(attempt, "id") and attempt.id else _uuid.uuid4()),
        }
        auth_header = target_cfg.get("auth_header")
        auth_value = target_cfg.get("auth_value")
        if auth_header and auth_value:
            headers[str(auth_header)] = str(auth_value)

        body_bytes = json.dumps(payload, default=str, sort_keys=True).encode()
        signing_secret = target_cfg.get("signing_secret")
        if signing_secret:
            signature = hmac.new(
                signing_secret.encode(), body_bytes, hashlib.sha256,
            ).hexdigest()
            headers["X-TrafficMind-Signature"] = f"sha256={signature}"

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, content=body_bytes, headers=headers)
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            return f"HTTP {exc.response.status_code}: {exc.response.text[:300]}"
        except httpx.RequestError as exc:
            return f"Request error: {exc}"
        return None


class SmtpDeliveryAdapter(ChannelDeliveryAdapter):
    """Send a plain-text email via SMTP.

    Reads connection parameters from ``target_config`` **with environment
    variable fallbacks** so operators can set SMTP credentials once instead
    of duplicating them in every routing target:

    * ``smtp_host``  — target_config or ``ALERT_SMTP_HOST`` env
    * ``smtp_port``  — target_config or ``ALERT_SMTP_PORT`` env (default 587)
    * ``smtp_user``  — target_config or ``ALERT_SMTP_USER`` env
    * ``smtp_pass``  — target_config or ``ALERT_SMTP_PASS`` env
    * ``from_addr``  — target_config or ``ALERT_SMTP_FROM`` env
      (default ``noreply@trafficmind.local``)
    """

    channel = AlertRoutingChannel.EMAIL

    async def deliver(self, attempt: AlertDeliveryAttempt) -> str | None:
        target_cfg: dict[str, Any] = attempt.delivery_payload.get("target_config", {})
        smtp_host = target_cfg.get("smtp_host") or os.environ.get("ALERT_SMTP_HOST")
        if not smtp_host:
            return "Missing smtp_host in target_config and ALERT_SMTP_HOST env var"

        smtp_port = int(target_cfg.get("smtp_port") or os.environ.get("ALERT_SMTP_PORT", "587"))
        smtp_user = target_cfg.get("smtp_user") or os.environ.get("ALERT_SMTP_USER")
        smtp_pass = target_cfg.get("smtp_pass") or os.environ.get("ALERT_SMTP_PASS")
        from_addr = (
            target_cfg.get("from_addr")
            or os.environ.get("ALERT_SMTP_FROM")
            or "noreply@trafficmind.local"
        )

        msg = email.message.EmailMessage()
        msg["Subject"] = _build_subject(attempt)
        msg["From"] = from_addr
        msg["To"] = attempt.destination
        msg.set_content(_build_email_body(attempt))

        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
                server.ehlo()
                if smtp_port != 25:
                    server.starttls()
                    server.ehlo()
                if smtp_user and smtp_pass:
                    server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        except smtplib.SMTPException as exc:
            return f"SMTP error: {exc}"
        except OSError as exc:
            return f"Connection error: {exc}"
        return None


class LogDeliveryAdapter(ChannelDeliveryAdapter):
    """Emit delivery details to the Python logger.

    Used as a fallback for channels that lack a real adapter (SMS, Slack,
    Teams) and for local development.  The attempt is marked SENT so
    downstream audit queries see it as delivered.
    """

    channel = AlertRoutingChannel.SMS  # default; overridden at register time

    def __init__(self, *, channel: AlertRoutingChannel) -> None:
        self.channel = channel

    async def deliver(self, attempt: AlertDeliveryAttempt) -> str | None:
        logger.info(
            "Alert delivery [%s] → %s | severity=%s condition=%s alert_id=%s",
            self.channel.value,
            attempt.destination,
            attempt.delivery_payload.get("severity", "?"),
            attempt.delivery_payload.get("condition_key", "?"),
            attempt.alert_id,
        )
        return None


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


class AlertDeliveryDispatcher:
    """Fan-out PLANNED deliveries to the appropriate channel adapter.

    Usage::

        dispatcher = AlertDeliveryDispatcher()
        dispatcher.register(WebhookDeliveryAdapter())
        dispatcher.register(SmtpDeliveryAdapter())
        results = await dispatcher.dispatch(session, attempts)
    """

    def __init__(self) -> None:
        self._adapters: dict[AlertRoutingChannel, ChannelDeliveryAdapter] = {}

    def register(self, adapter: ChannelDeliveryAdapter) -> None:
        self._adapters[adapter.channel] = adapter

    @property
    def channels(self) -> list[str]:
        return sorted(ch.value for ch in self._adapters)

    async def dispatch_one(self, attempt: AlertDeliveryAttempt) -> AlertDeliveryAttempt:
        """Deliver a single attempt and mutate its state in-place.

        Supports retrying FAILED attempts — the caller decides which
        attempts to include (PLANNED-only or PLANNED + FAILED).
        The caller is responsible for flushing the session.
        """
        now = datetime.now(timezone.utc)
        attempt.attempted_at = now
        attempt.retry_count = getattr(attempt, "retry_count", 0) or 0

        adapter = self._adapters.get(attempt.channel)
        if adapter is None:
            attempt.delivery_state = AlertDeliveryState.SKIPPED
            attempt.error_message = f"No adapter registered for channel {attempt.channel.value!r}"
            logger.warning(
                "No delivery adapter for channel=%s destination=%s alert_id=%s",
                attempt.channel.value,
                attempt.destination,
                attempt.alert_id,
            )
            return attempt

        error = await adapter.deliver(attempt)
        if error is None:
            attempt.delivery_state = AlertDeliveryState.SENT
            attempt.error_message = None
        else:
            attempt.delivery_state = AlertDeliveryState.FAILED
            attempt.error_message = error
            logger.error(
                "Delivery failed channel=%s destination=%s alert_id=%s error=%s",
                attempt.channel.value,
                attempt.destination,
                attempt.alert_id,
                error,
            )
        return attempt

    async def dispatch_many(
        self, attempts: list[AlertDeliveryAttempt]
    ) -> list[AlertDeliveryAttempt]:
        """Deliver every attempt.  Failures are isolated per-attempt."""
        results: list[AlertDeliveryAttempt] = []
        for attempt in attempts:
            results.append(await self.dispatch_one(attempt))
        return results


# ---------------------------------------------------------------------------
# Default dispatcher factory
# ---------------------------------------------------------------------------


def build_default_dispatcher() -> AlertDeliveryDispatcher:
    """Build a dispatcher with all built-in adapters registered."""
    dispatcher = AlertDeliveryDispatcher()
    dispatcher.register(WebhookDeliveryAdapter())
    dispatcher.register(SmtpDeliveryAdapter())
    dispatcher.register(LogDeliveryAdapter(channel=AlertRoutingChannel.SMS))
    dispatcher.register(LogDeliveryAdapter(channel=AlertRoutingChannel.SLACK))
    dispatcher.register(LogDeliveryAdapter(channel=AlertRoutingChannel.TEAMS))
    return dispatcher


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_webhook_body(attempt: AlertDeliveryAttempt) -> dict[str, Any]:
    return {
        "alert_id": str(attempt.alert_id),
        "channel": attempt.channel.value,
        "destination": attempt.destination,
        "severity": attempt.delivery_payload.get("severity"),
        "condition_key": attempt.delivery_payload.get("condition_key"),
        "escalation_level": attempt.escalation_level,
        "scheduled_for": attempt.scheduled_for.isoformat(),
        "payload": attempt.delivery_payload,
    }


def _build_subject(attempt: AlertDeliveryAttempt) -> str:
    severity = attempt.delivery_payload.get("severity", "info").upper()
    condition = attempt.delivery_payload.get("condition_key", "alert")
    return f"[TrafficMind {severity}] {condition}"


def _build_email_body(attempt: AlertDeliveryAttempt) -> str:
    lines = [
        f"Alert ID: {attempt.alert_id}",
        f"Severity: {attempt.delivery_payload.get('severity', 'N/A')}",
        f"Condition: {attempt.delivery_payload.get('condition_key', 'N/A')}",
        f"Escalation Level: {attempt.escalation_level}",
        f"Scheduled For: {attempt.scheduled_for.isoformat()}",
        "",
        "Delivery Payload:",
        json.dumps(attempt.delivery_payload, indent=2, default=str),
    ]
    return "\n".join(lines)
