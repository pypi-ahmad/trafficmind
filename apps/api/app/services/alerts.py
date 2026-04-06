"""Service layer for operational alert routing and escalation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.app.db.enums import (
    AlertAuditEventType,
    AlertDeliveryState,
    AlertRoutingChannel,
    OperationalAlertSeverity,
    OperationalAlertSourceKind,
    OperationalAlertStatus,
)
from apps.api.app.db.models import (
    AlertAuditEvent,
    AlertDeliveryAttempt,
    AlertPolicy,
    AlertPolicyRoute,
    AlertRoutingTarget,
    OperationalAlert,
)
from apps.api.app.schemas.alerts import AlertPolicyCreate, AlertRoutingTargetCreate, AlertSignalCreate
from apps.api.app.services.errors import ConflictError, NotFoundError, ServiceValidationError


@dataclass(slots=True)
class SignalEvaluationResult:
    matched_policy_count: int
    created_count: int
    deduplicated_count: int
    alerts: list[OperationalAlert]


_ACTIVE_ALERT_STATUSES = (
    OperationalAlertStatus.NEW,
    OperationalAlertStatus.ACKNOWLEDGED,
    OperationalAlertStatus.ESCALATED,
)

_SEVERITY_RANK = {
    OperationalAlertSeverity.INFO: 0,
    OperationalAlertSeverity.LOW: 1,
    OperationalAlertSeverity.MEDIUM: 2,
    OperationalAlertSeverity.HIGH: 3,
    OperationalAlertSeverity.CRITICAL: 4,
}


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class AlertingService:
    """Persist and route operational alerts from normalized source signals."""

    async def create_routing_target(
        self,
        session: AsyncSession,
        body: AlertRoutingTargetCreate,
    ) -> AlertRoutingTarget:
        existing = await session.scalar(select(AlertRoutingTarget).where(AlertRoutingTarget.name == body.name))
        if existing is not None:
            raise ConflictError("Alert routing target already exists.")

        target = AlertRoutingTarget(
            name=body.name,
            channel=body.channel,
            destination=body.destination,
            is_enabled=body.is_enabled,
            target_config=dict(body.target_config),
        )
        session.add(target)
        await session.flush()
        await session.refresh(target)
        return target

    async def list_routing_targets(
        self,
        session: AsyncSession,
        *,
        channel: AlertRoutingChannel | None,
        is_enabled: bool | None,
        limit: int,
        offset: int,
    ) -> tuple[list[AlertRoutingTarget], int]:
        statement = select(AlertRoutingTarget)
        if channel is not None:
            statement = statement.where(AlertRoutingTarget.channel == channel)
        if is_enabled is not None:
            statement = statement.where(AlertRoutingTarget.is_enabled.is_(is_enabled))

        total = await self._count(session, statement)
        items = list(
            (
                await session.execute(
                    statement.order_by(AlertRoutingTarget.name).offset(offset).limit(limit)
                )
            ).scalars().all()
        )
        return items, total

    async def create_policy(
        self,
        session: AsyncSession,
        body: AlertPolicyCreate,
    ) -> AlertPolicy:
        existing = await session.scalar(select(AlertPolicy).where(AlertPolicy.name == body.name))
        if existing is not None:
            raise ConflictError("Alert policy already exists.")

        target_ids = [route.routing_target_id for route in body.routes]
        target_rows = list(
            (
                await session.execute(
                    select(AlertRoutingTarget).where(AlertRoutingTarget.id.in_(target_ids))
                )
            ).scalars().all()
        )
        targets_by_id = {target.id: target for target in target_rows}
        missing_target_ids = [str(target_id) for target_id in target_ids if target_id not in targets_by_id]
        if missing_target_ids:
            raise ServiceValidationError(
                f"Unknown routing target id(s): {', '.join(sorted(missing_target_ids))}"
            )

        policy = AlertPolicy(
            name=body.name,
            description=body.description,
            source_kind=body.source_kind,
            condition_key=body.condition_key,
            min_severity=body.min_severity,
            cooldown_seconds=body.cooldown_seconds,
            dedup_window_seconds=body.dedup_window_seconds,
            is_enabled=body.is_enabled,
            policy_metadata=dict(body.policy_metadata),
        )
        session.add(policy)
        await session.flush()

        sorted_routes = sorted(
            body.routes,
            key=lambda route: (route.escalation_level, route.delay_seconds, str(route.routing_target_id)),
        )
        for route in sorted_routes:
            session.add(
                AlertPolicyRoute(
                    policy_id=policy.id,
                    routing_target_id=route.routing_target_id,
                    escalation_level=route.escalation_level,
                    delay_seconds=route.delay_seconds,
                    route_config=dict(route.route_config),
                )
            )

        await session.flush()
        return await self.get_policy(session, policy.id)

    async def get_policy(self, session: AsyncSession, policy_id: uuid.UUID) -> AlertPolicy:
        statement = (
            select(AlertPolicy)
            .options(selectinload(AlertPolicy.routes))
            .where(AlertPolicy.id == policy_id)
        )
        policy = await session.scalar(statement)
        if policy is None:
            raise NotFoundError("Alert policy not found.")
        policy.routes.sort(key=lambda route: (route.escalation_level, route.delay_seconds, route.created_at))
        return policy

    async def list_policies(
        self,
        session: AsyncSession,
        *,
        source_kind: OperationalAlertSourceKind | None,
        is_enabled: bool | None,
        limit: int,
        offset: int,
    ) -> tuple[list[AlertPolicy], int]:
        statement = select(AlertPolicy).options(selectinload(AlertPolicy.routes))
        if source_kind is not None:
            statement = statement.where(AlertPolicy.source_kind == source_kind)
        if is_enabled is not None:
            statement = statement.where(AlertPolicy.is_enabled.is_(is_enabled))

        total = await self._count(session, statement)
        items = list(
            (
                await session.execute(
                    statement.order_by(AlertPolicy.name).offset(offset).limit(limit)
                )
            ).scalars().all()
        )
        for policy in items:
            policy.routes.sort(key=lambda route: (route.escalation_level, route.delay_seconds, route.created_at))
        return items, total

    async def ingest_signal(
        self,
        session: AsyncSession,
        body: AlertSignalCreate,
    ) -> SignalEvaluationResult:
        occurred_at = _ensure_utc(body.occurred_at)
        policies = await self._matching_policies(session, body.source_kind, body.condition_key, body.severity)

        created_count = 0
        deduplicated_count = 0
        alerts: list[OperationalAlert] = []

        for policy in policies:
            dedup_key = body.dedup_key or self._build_default_dedup_key(body)
            alert = await self._find_active_alert(
                session,
                policy_id=policy.id,
                dedup_key=dedup_key,
                occurred_at=occurred_at,
                dedup_window_seconds=policy.dedup_window_seconds,
            )
            if alert is None:
                alert = OperationalAlert(
                    policy_id=policy.id,
                    camera_id=body.camera_id,
                    stream_id=body.stream_id,
                    detection_event_id=body.detection_event_id,
                    violation_event_id=body.violation_event_id,
                    watchlist_alert_id=body.watchlist_alert_id,
                    workflow_run_id=body.workflow_run_id,
                    source_kind=body.source_kind,
                    condition_key=body.condition_key,
                    severity=body.severity,
                    status=OperationalAlertStatus.NEW,
                    dedup_key=dedup_key,
                    title=body.title,
                    summary=body.summary,
                    occurred_at=occurred_at,
                    first_seen_at=occurred_at,
                    last_seen_at=occurred_at,
                    occurrence_count=1,
                    source_payload=dict(body.source_payload),
                    alert_metadata=dict(body.alert_metadata),
                )
                session.add(alert)
                await session.flush()

                self._record_audit_event(
                    session,
                    alert,
                    policy_id=policy.id,
                    event_type=AlertAuditEventType.CREATED,
                    status_after=OperationalAlertStatus.NEW,
                    note="Alert created from a matched routing policy.",
                    event_payload={"policy_name": policy.name},
                )

                planned = self._plan_deliveries(
                    session,
                    alert,
                    policy,
                    levels=[0],
                    scheduled_for=occurred_at,
                )
                if planned > 0:
                    alert.last_routed_at = occurred_at
                    alert.cooldown_until = occurred_at + timedelta(seconds=policy.cooldown_seconds)
                    self._record_audit_event(
                        session,
                        alert,
                        policy_id=policy.id,
                        event_type=AlertAuditEventType.ROUTED,
                        status_after=alert.status,
                        note="Initial delivery plan created.",
                        event_payload={"delivery_count": planned, "escalation_level": 0},
                    )

                alert.escalation_due_at = self._next_escalation_due_at(alert.first_seen_at, policy, alert.escalation_level)
                created_count += 1
            else:
                existing_last_seen = _ensure_utc(alert.last_seen_at)
                alert.last_seen_at = max(existing_last_seen, occurred_at)
                alert.occurrence_count += 1
                if body.summary:
                    alert.summary = body.summary
                alert.title = body.title
                if body.alert_metadata:
                    alert.alert_metadata = {**dict(alert.alert_metadata), **dict(body.alert_metadata)}

                self._record_audit_event(
                    session,
                    alert,
                    policy_id=policy.id,
                    event_type=AlertAuditEventType.DEDUPLICATED,
                    status_after=alert.status,
                    note="Signal merged into an existing active alert within the dedup window.",
                    event_payload={"occurrence_count": alert.occurrence_count},
                )

                cooldown_until = _ensure_utc(alert.cooldown_until) if alert.cooldown_until is not None else None
                should_reroute = (
                    alert.status not in {OperationalAlertStatus.ACKNOWLEDGED, OperationalAlertStatus.RESOLVED, OperationalAlertStatus.SUPPRESSED}
                    and (cooldown_until is None or occurred_at >= cooldown_until)
                )
                if should_reroute:
                    planned = self._plan_deliveries(
                        session,
                        alert,
                        policy,
                        levels=[alert.escalation_level],
                        scheduled_for=occurred_at,
                    )
                    if planned > 0:
                        alert.last_routed_at = occurred_at
                        alert.cooldown_until = occurred_at + timedelta(seconds=policy.cooldown_seconds)
                        self._record_audit_event(
                            session,
                            alert,
                            policy_id=policy.id,
                            event_type=AlertAuditEventType.ROUTED,
                            status_after=alert.status,
                            note="Signal repeated after cooldown; route plan refreshed.",
                            event_payload={"delivery_count": planned, "escalation_level": alert.escalation_level},
                        )

                alert.escalation_due_at = self._next_escalation_due_at(alert.first_seen_at, policy, alert.escalation_level)
                deduplicated_count += 1

            alerts.append(alert)

        await session.flush()
        alert_ids = [alert.id for alert in alerts]
        hydrated_alerts = await self.get_alerts_by_ids(session, alert_ids)
        return SignalEvaluationResult(
            matched_policy_count=len(policies),
            created_count=created_count,
            deduplicated_count=deduplicated_count,
            alerts=hydrated_alerts,
        )

    async def list_alerts(
        self,
        session: AsyncSession,
        *,
        status: OperationalAlertStatus | None,
        severity: OperationalAlertSeverity | None,
        source_kind: OperationalAlertSourceKind | None,
        camera_id: uuid.UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[list[OperationalAlert], int]:
        statement = select(OperationalAlert)
        if status is not None:
            statement = statement.where(OperationalAlert.status == status)
        if severity is not None:
            statement = statement.where(OperationalAlert.severity == severity)
        if source_kind is not None:
            statement = statement.where(OperationalAlert.source_kind == source_kind)
        if camera_id is not None:
            statement = statement.where(OperationalAlert.camera_id == camera_id)

        total = await self._count(session, statement)
        items = list(
            (
                await session.execute(
                    statement.order_by(OperationalAlert.occurred_at.desc()).offset(offset).limit(limit)
                )
            ).scalars().all()
        )
        return items, total

    async def get_alert(self, session: AsyncSession, alert_id: uuid.UUID) -> OperationalAlert:
        statement = self._alert_detail_statement().where(OperationalAlert.id == alert_id)
        alert = await session.scalar(statement)
        if alert is None:
            raise NotFoundError("Operational alert not found.")
        self._sort_alert_detail(alert)
        return alert

    async def get_alerts_by_ids(
        self,
        session: AsyncSession,
        alert_ids: list[uuid.UUID],
    ) -> list[OperationalAlert]:
        if not alert_ids:
            return []
        statement = select(OperationalAlert).where(OperationalAlert.id.in_(alert_ids))
        items = list((await session.execute(statement)).scalars().all())
        items_by_id = {item.id: item for item in items}
        return [items_by_id[alert_id] for alert_id in alert_ids if alert_id in items_by_id]

    async def process_due_escalations(
        self,
        session: AsyncSession,
        *,
        as_of: datetime | None = None,
    ) -> list[OperationalAlert]:
        resolved_as_of = _ensure_utc(as_of or datetime.now(timezone.utc))
        statement = self._alert_detail_statement().where(
            OperationalAlert.status.in_(_ACTIVE_ALERT_STATUSES),
            OperationalAlert.escalation_due_at.is_not(None),
            OperationalAlert.escalation_due_at <= resolved_as_of,
        )
        alerts = list((await session.execute(statement)).scalars().all())
        processed: list[OperationalAlert] = []

        for alert in alerts:
            if alert.policy is None or not alert.policy.is_enabled:
                continue

            due_levels = self._due_levels(alert.policy, alert, resolved_as_of)
            if not due_levels:
                alert.escalation_due_at = self._next_escalation_due_at(
                    alert.first_seen_at,
                    alert.policy,
                    alert.escalation_level,
                )
                continue

            planned = self._plan_deliveries(
                session,
                alert,
                alert.policy,
                levels=due_levels,
                scheduled_for=resolved_as_of,
            )
            alert.status = OperationalAlertStatus.ESCALATED
            alert.escalation_level = max(due_levels)
            alert.last_routed_at = resolved_as_of if planned > 0 else alert.last_routed_at
            alert.cooldown_until = (
                resolved_as_of + timedelta(seconds=alert.policy.cooldown_seconds)
                if planned > 0 else alert.cooldown_until
            )
            alert.escalation_due_at = self._next_escalation_due_at(
                alert.first_seen_at,
                alert.policy,
                alert.escalation_level,
            )
            self._record_audit_event(
                session,
                alert,
                policy_id=alert.policy_id,
                event_type=AlertAuditEventType.ESCALATED,
                status_after=OperationalAlertStatus.ESCALATED,
                note="Escalation level advanced by the scheduler.",
                event_payload={"levels": due_levels, "delivery_count": planned},
            )
            self._sort_alert_detail(alert)
            processed.append(alert)

        await session.flush()
        return processed

    async def acknowledge_alert(
        self,
        session: AsyncSession,
        alert_id: uuid.UUID,
        *,
        actor: str | None,
        note: str | None,
    ) -> OperationalAlert:
        alert = await self.get_alert(session, alert_id)
        if alert.status in {OperationalAlertStatus.RESOLVED, OperationalAlertStatus.SUPPRESSED}:
            raise ConflictError("Resolved or suppressed alerts cannot be acknowledged.")

        now = datetime.now(timezone.utc)
        alert.status = OperationalAlertStatus.ACKNOWLEDGED
        alert.acknowledged_at = now
        alert.acknowledged_by = actor
        alert.escalation_due_at = None
        self._record_audit_event(
            session,
            alert,
            policy_id=alert.policy_id,
            event_type=AlertAuditEventType.ACKNOWLEDGED,
            status_after=OperationalAlertStatus.ACKNOWLEDGED,
            actor=actor,
            note=note,
        )
        await session.flush()
        return await self.get_alert(session, alert.id)

    async def resolve_alert(
        self,
        session: AsyncSession,
        alert_id: uuid.UUID,
        *,
        actor: str | None,
        note: str | None,
    ) -> OperationalAlert:
        alert = await self.get_alert(session, alert_id)
        if alert.status == OperationalAlertStatus.SUPPRESSED:
            raise ConflictError("Suppressed alerts cannot be resolved.")
        if alert.status == OperationalAlertStatus.RESOLVED:
            raise ConflictError("Alert is already resolved.")

        now = datetime.now(timezone.utc)
        alert.status = OperationalAlertStatus.RESOLVED
        alert.resolved_at = now
        alert.resolved_by = actor
        alert.escalation_due_at = None
        alert.cooldown_until = None
        self._record_audit_event(
            session,
            alert,
            policy_id=alert.policy_id,
            event_type=AlertAuditEventType.RESOLVED,
            status_after=OperationalAlertStatus.RESOLVED,
            actor=actor,
            note=note,
        )
        await session.flush()
        return await self.get_alert(session, alert.id)

    async def suppress_alert(
        self,
        session: AsyncSession,
        alert_id: uuid.UUID,
        *,
        actor: str | None,
        note: str | None,
    ) -> OperationalAlert:
        alert = await self.get_alert(session, alert_id)
        if alert.status == OperationalAlertStatus.RESOLVED:
            raise ConflictError("Resolved alerts cannot be suppressed.")
        if alert.status == OperationalAlertStatus.SUPPRESSED:
            raise ConflictError("Alert is already suppressed.")

        now = datetime.now(timezone.utc)
        alert.status = OperationalAlertStatus.SUPPRESSED
        alert.suppressed_at = now
        alert.suppressed_by = actor
        alert.escalation_due_at = None
        alert.cooldown_until = None
        self._record_audit_event(
            session,
            alert,
            policy_id=alert.policy_id,
            event_type=AlertAuditEventType.SUPPRESSED,
            status_after=OperationalAlertStatus.SUPPRESSED,
            actor=actor,
            note=note,
        )
        await session.flush()
        return await self.get_alert(session, alert.id)

    async def escalate_alert(
        self,
        session: AsyncSession,
        alert_id: uuid.UUID,
        *,
        actor: str | None,
        note: str | None,
    ) -> OperationalAlert:
        alert = await self.get_alert(session, alert_id)
        if alert.policy is None:
            raise ServiceValidationError("Alert is not bound to an escalation policy.")
        if alert.status in {OperationalAlertStatus.RESOLVED, OperationalAlertStatus.SUPPRESSED}:
            raise ConflictError("Resolved or suppressed alerts cannot be escalated.")

        next_levels = sorted(
            {
                route.escalation_level
                for route in alert.policy.routes
                if route.escalation_level > alert.escalation_level
            }
        )
        if not next_levels:
            raise ConflictError("Alert is already at the highest configured escalation level.")

        next_level = next_levels[0]
        now = datetime.now(timezone.utc)
        planned = self._plan_deliveries(session, alert, alert.policy, levels=[next_level], scheduled_for=now)
        alert.status = OperationalAlertStatus.ESCALATED
        alert.escalation_level = next_level
        alert.last_routed_at = now if planned > 0 else alert.last_routed_at
        alert.cooldown_until = now + timedelta(seconds=alert.policy.cooldown_seconds) if planned > 0 else alert.cooldown_until
        alert.escalation_due_at = self._next_escalation_due_at(alert.first_seen_at, alert.policy, alert.escalation_level)
        self._record_audit_event(
            session,
            alert,
            policy_id=alert.policy_id,
            event_type=AlertAuditEventType.ESCALATED,
            status_after=OperationalAlertStatus.ESCALATED,
            actor=actor,
            note=note,
            event_payload={"levels": [next_level], "delivery_count": planned},
        )
        await session.flush()
        return await self.get_alert(session, alert.id)

    async def _matching_policies(
        self,
        session: AsyncSession,
        source_kind: OperationalAlertSourceKind,
        condition_key: str,
        severity: OperationalAlertSeverity,
    ) -> list[AlertPolicy]:
        statement = (
            select(AlertPolicy)
            .options(selectinload(AlertPolicy.routes).selectinload(AlertPolicyRoute.routing_target))
            .where(
                AlertPolicy.is_enabled.is_(True),
                AlertPolicy.source_kind == source_kind,
                AlertPolicy.condition_key == condition_key,
            )
        )
        policies = list((await session.execute(statement)).scalars().all())
        matching = [
            policy
            for policy in policies
            if _SEVERITY_RANK[policy.min_severity] <= _SEVERITY_RANK[severity]
        ]
        for policy in matching:
            policy.routes.sort(key=lambda route: (route.escalation_level, route.delay_seconds, route.created_at))
        return matching

    async def _find_active_alert(
        self,
        session: AsyncSession,
        *,
        policy_id: uuid.UUID,
        dedup_key: str,
        occurred_at: datetime,
        dedup_window_seconds: int,
    ) -> OperationalAlert | None:
        window_start = occurred_at - timedelta(seconds=dedup_window_seconds)
        statement = (
            select(OperationalAlert)
            .where(
                OperationalAlert.policy_id == policy_id,
                OperationalAlert.dedup_key == dedup_key,
                OperationalAlert.status.in_(_ACTIVE_ALERT_STATUSES),
                OperationalAlert.last_seen_at >= window_start,
            )
            .order_by(OperationalAlert.last_seen_at.desc())
            .limit(1)
        )
        return await session.scalar(statement)

    @staticmethod
    def _build_default_dedup_key(body: AlertSignalCreate) -> str:
        parts = [body.source_kind.value, body.condition_key]
        for label, value in (
            ("camera", body.camera_id),
            ("stream", body.stream_id),
            ("detection", body.detection_event_id),
            ("violation", body.violation_event_id),
            ("watchlist", body.watchlist_alert_id),
            ("workflow", body.workflow_run_id),
        ):
            if value is not None:
                parts.append(f"{label}:{value}")
        return "|".join(parts)

    @staticmethod
    def _plan_deliveries(
        session: AsyncSession,
        alert: OperationalAlert,
        policy: AlertPolicy,
        *,
        levels: list[int],
        scheduled_for: datetime,
    ) -> int:
        planned = 0
        selected_levels = set(levels)
        for route in sorted(policy.routes, key=lambda item: (item.escalation_level, item.delay_seconds, item.created_at)):
            if route.escalation_level not in selected_levels:
                continue
            target = route.routing_target
            if target is None or not target.is_enabled:
                continue
            session.add(
                AlertDeliveryAttempt(
                    alert_id=alert.id,
                    policy_id=policy.id,
                    routing_target_id=target.id,
                    escalation_level=route.escalation_level,
                    delivery_state=AlertDeliveryState.PLANNED,
                    channel=target.channel,
                    destination=target.destination,
                    scheduled_for=scheduled_for,
                    delivery_payload={
                        "condition_key": alert.condition_key,
                        "severity": alert.severity.value,
                        "route_config": dict(route.route_config),
                        "target_config": dict(target.target_config),
                    },
                )
            )
            planned += 1
        return planned

    def _record_audit_event(
        self,
        session: AsyncSession,
        alert: OperationalAlert,
        *,
        policy_id: uuid.UUID | None,
        event_type: AlertAuditEventType,
        status_after: OperationalAlertStatus | None,
        actor: str | None = None,
        note: str | None = None,
        event_payload: dict[str, Any] | None = None,
    ) -> None:
        session.add(
            AlertAuditEvent(
                alert_id=alert.id,
                policy_id=policy_id,
                event_type=event_type,
                status_after=status_after,
                actor=actor,
                note=note,
                event_payload=event_payload or {},
            )
        )

    @staticmethod
    def _next_escalation_due_at(
        first_seen_at: datetime,
        policy: AlertPolicy,
        current_level: int,
    ) -> datetime | None:
        normalized_first_seen = _ensure_utc(first_seen_at)
        future_delays = sorted(
            {
                route.delay_seconds
                for route in policy.routes
                if route.escalation_level > current_level
            }
        )
        if not future_delays:
            return None
        return normalized_first_seen + timedelta(seconds=future_delays[0])

    @staticmethod
    def _due_levels(policy: AlertPolicy, alert: OperationalAlert, as_of: datetime) -> list[int]:
        first_seen_at = _ensure_utc(alert.first_seen_at)
        elapsed_seconds = max(0, int((as_of - first_seen_at).total_seconds()))
        return sorted(
            {
                route.escalation_level
                for route in policy.routes
                if route.escalation_level > alert.escalation_level and route.delay_seconds <= elapsed_seconds
            }
        )

    @staticmethod
    def _alert_detail_statement():
        return select(OperationalAlert).options(
            selectinload(OperationalAlert.policy).selectinload(AlertPolicy.routes).selectinload(AlertPolicyRoute.routing_target),
            selectinload(OperationalAlert.deliveries),
            selectinload(OperationalAlert.audit_events),
        )

    async def dispatch_planned_deliveries(
        self,
        session: AsyncSession,
        *,
        alert_id: uuid.UUID | None = None,
        include_failed: bool = False,
        max_retries: int = 3,
        limit: int = 100,
    ) -> list[AlertDeliveryAttempt]:
        """Send all PLANNED delivery attempts through the channel dispatcher.

        Optionally scoped to a single alert.  When ``include_failed`` is
        True, FAILED attempts with ``retry_count < max_retries`` are also
        dispatched.  Returns the mutated attempts with updated
        ``delivery_state`` and ``attempted_at``.
        """
        from apps.api.app.services.delivery import build_default_dispatcher

        states = [AlertDeliveryState.PLANNED]
        if include_failed:
            states.append(AlertDeliveryState.FAILED)

        statement = (
            select(AlertDeliveryAttempt)
            .where(AlertDeliveryAttempt.delivery_state.in_(states))
            .order_by(AlertDeliveryAttempt.scheduled_for.asc())
            .limit(limit)
        )
        if alert_id is not None:
            statement = statement.where(AlertDeliveryAttempt.alert_id == alert_id)
        if include_failed:
            statement = statement.where(AlertDeliveryAttempt.retry_count < max_retries)

        attempts = list((await session.execute(statement)).scalars().all())
        if not attempts:
            return []

        # Bump retry_count for FAILED attempts being retried
        for attempt in attempts:
            if attempt.delivery_state == AlertDeliveryState.FAILED:
                attempt.retry_count = (attempt.retry_count or 0) + 1

        dispatcher = build_default_dispatcher()
        results = await dispatcher.dispatch_many(attempts)
        await session.flush()
        return results

    @staticmethod
    def _sort_alert_detail(alert: OperationalAlert) -> None:
        if alert.policy is not None:
            alert.policy.routes.sort(key=lambda route: (route.escalation_level, route.delay_seconds, route.created_at))
        alert.deliveries.sort(key=lambda item: (item.escalation_level, item.created_at))
        alert.audit_events.sort(key=lambda item: item.created_at)

    @staticmethod
    async def _count(session: AsyncSession, statement) -> int:
        count_statement = select(func.count()).select_from(statement.order_by(None).subquery())
        total = await session.scalar(count_statement)
        return int(total or 0)