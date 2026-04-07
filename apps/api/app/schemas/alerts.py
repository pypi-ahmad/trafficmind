"""Pydantic schemas for operational alert routing and escalation."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import AliasChoices, Field, model_validator

from apps.api.app.db.enums import (
    AlertAuditEventType,
    AlertDeliveryState,
    AlertRoutingChannel,
    OperationalAlertSeverity,
    OperationalAlertSourceKind,
    OperationalAlertStatus,
)
from apps.api.app.schemas.domain import ORMSchema


class AlertRoutingTargetBase(ORMSchema):
    name: str = Field(min_length=1, max_length=120)
    channel: AlertRoutingChannel
    destination: str = Field(min_length=1)
    is_enabled: bool = True
    target_config: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("target_config", "config"),
        serialization_alias="config",
    )


class AlertRoutingTargetCreate(AlertRoutingTargetBase):
    pass


class AlertRoutingTargetRead(AlertRoutingTargetBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class AlertRoutingTargetListResult(ORMSchema):
    items: list[AlertRoutingTargetRead] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0


class AlertPolicyRouteBase(ORMSchema):
    routing_target_id: uuid.UUID
    escalation_level: int = Field(default=0, ge=0)
    delay_seconds: int = Field(default=0, ge=0)
    route_config: dict[str, Any] = Field(default_factory=dict)


class AlertPolicyRouteCreate(AlertPolicyRouteBase):
    pass


class AlertPolicyRouteRead(AlertPolicyRouteBase):
    id: uuid.UUID
    policy_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class AlertPolicyBase(ORMSchema):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    source_kind: OperationalAlertSourceKind
    condition_key: str = Field(min_length=1, max_length=80)
    min_severity: OperationalAlertSeverity = OperationalAlertSeverity.MEDIUM
    cooldown_seconds: int = Field(default=300, ge=0)
    dedup_window_seconds: int = Field(default=900, ge=0)
    is_enabled: bool = True
    policy_metadata: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("policy_metadata", "metadata"),
        serialization_alias="metadata",
    )


class AlertPolicyCreate(AlertPolicyBase):
    routes: list[AlertPolicyRouteCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_routes(self) -> "AlertPolicyCreate":
        if not self.routes:
            raise ValueError("At least one routing route is required.")

        if not any(route.escalation_level == 0 for route in self.routes):
            raise ValueError("At least one escalation_level=0 route is required.")

        delays_by_level: dict[int, int] = {}
        for route in self.routes:
            configured = delays_by_level.setdefault(route.escalation_level, route.delay_seconds)
            if configured != route.delay_seconds:
                raise ValueError("All routes within the same escalation level must share one delay_seconds value.")

        if delays_by_level.get(0, 0) != 0:
            raise ValueError("Escalation level 0 routes must use delay_seconds=0.")

        last_delay = -1
        for level in sorted(delays_by_level):
            delay = delays_by_level[level]
            if delay < last_delay:
                raise ValueError("Escalation delays must be non-decreasing across levels.")
            last_delay = delay

        return self


class AlertPolicyRead(AlertPolicyBase):
    id: uuid.UUID
    routes: list[AlertPolicyRouteRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class AlertPolicyListResult(ORMSchema):
    items: list[AlertPolicyRead] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0


class AlertSignalCreate(ORMSchema):
    source_kind: OperationalAlertSourceKind
    condition_key: str = Field(min_length=1, max_length=80)
    severity: OperationalAlertSeverity
    title: str = Field(min_length=1, max_length=200)
    summary: str | None = None
    occurred_at: datetime
    dedup_key: str | None = Field(default=None, max_length=240)
    camera_id: uuid.UUID | None = None
    stream_id: uuid.UUID | None = None
    detection_event_id: uuid.UUID | None = None
    violation_event_id: uuid.UUID | None = None
    watchlist_alert_id: uuid.UUID | None = None
    workflow_run_id: uuid.UUID | None = None
    source_payload: dict[str, Any] = Field(default_factory=dict)
    alert_metadata: dict[str, Any] = Field(default_factory=dict)


class AlertDeliveryAttemptRead(ORMSchema):
    id: uuid.UUID
    alert_id: uuid.UUID
    policy_id: uuid.UUID | None = None
    routing_target_id: uuid.UUID | None = None
    escalation_level: int
    delivery_state: AlertDeliveryState
    channel: AlertRoutingChannel
    destination: str
    scheduled_for: datetime
    attempted_at: datetime | None = None
    error_message: str | None = None
    retry_count: int = 0
    delivery_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class AlertAuditEventRead(ORMSchema):
    id: uuid.UUID
    alert_id: uuid.UUID
    policy_id: uuid.UUID | None = None
    event_type: AlertAuditEventType
    status_after: OperationalAlertStatus | None = None
    actor: str | None = None
    note: str | None = None
    event_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class OperationalAlertSummaryRead(ORMSchema):
    id: uuid.UUID
    policy_id: uuid.UUID | None = None
    camera_id: uuid.UUID | None = None
    stream_id: uuid.UUID | None = None
    detection_event_id: uuid.UUID | None = None
    violation_event_id: uuid.UUID | None = None
    watchlist_alert_id: uuid.UUID | None = None
    workflow_run_id: uuid.UUID | None = None
    source_kind: OperationalAlertSourceKind
    condition_key: str
    severity: OperationalAlertSeverity
    status: OperationalAlertStatus
    dedup_key: str
    title: str
    summary: str | None = None
    occurred_at: datetime
    first_seen_at: datetime
    last_seen_at: datetime
    occurrence_count: int
    escalation_level: int
    escalation_due_at: datetime | None = None
    last_routed_at: datetime | None = None
    cooldown_until: datetime | None = None
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    suppressed_at: datetime | None = None
    suppressed_by: str | None = None
    source_payload: dict[str, Any] = Field(default_factory=dict)
    alert_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class OperationalAlertDetailRead(OperationalAlertSummaryRead):
    deliveries: list[AlertDeliveryAttemptRead] = Field(default_factory=list)
    audit_events: list[AlertAuditEventRead] = Field(default_factory=list)


class OperationalAlertListResult(ORMSchema):
    items: list[OperationalAlertSummaryRead] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0


class AlertSignalEvaluationResult(ORMSchema):
    matched_policy_count: int = 0
    created_count: int = 0
    deduplicated_count: int = 0
    alerts: list[OperationalAlertSummaryRead] = Field(default_factory=list)


class AlertActionRequest(ORMSchema):
    actor: str | None = Field(default=None, max_length=120)
    note: str | None = None


class AlertEscalationProcessRequest(ORMSchema):
    as_of: datetime | None = None


class AlertEscalationProcessResult(ORMSchema):
    processed_count: int = 0
    alert_ids: list[uuid.UUID] = Field(default_factory=list)


class AlertDeliveryDispatchRequest(ORMSchema):
    alert_id: uuid.UUID | None = Field(
        default=None,
        description="Optional alert to scope delivery. Omit to dispatch all pending.",
    )
    include_failed: bool = Field(
        default=False,
        description="Also retry previously FAILED attempts (up to max_retries).",
    )
    max_retries: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum retry count for FAILED attempts.",
    )
    limit: int = Field(default=100, ge=1, le=1000)


class AlertDeliveryDispatchResult(ORMSchema):
    dispatched_count: int = 0
    sent_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    retried_count: int = 0
