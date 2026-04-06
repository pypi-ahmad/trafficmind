"""Operational alert routing, escalation, and audit endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status

from apps.api.app.api.access import enforce_route_permissions
from apps.api.app.api.dependencies import DbSession
from apps.api.app.db.enums import (
    AlertRoutingChannel,
    OperationalAlertSeverity,
    OperationalAlertSourceKind,
    OperationalAlertStatus,
)
from apps.api.app.schemas.alerts import (
    AlertActionRequest,
    AlertDeliveryDispatchRequest,
    AlertDeliveryDispatchResult,
    AlertEscalationProcessRequest,
    AlertEscalationProcessResult,
    AlertPolicyCreate,
    AlertPolicyListResult,
    AlertPolicyRead,
    AlertRoutingTargetCreate,
    AlertRoutingTargetListResult,
    AlertRoutingTargetRead,
    AlertSignalCreate,
    AlertSignalEvaluationResult,
    OperationalAlertDetailRead,
    OperationalAlertListResult,
    OperationalAlertSummaryRead,
)
from apps.api.app.services.alerts import AlertingService
from apps.api.app.services.errors import ConflictError, NotFoundError, ServiceValidationError
from services.access_control.policy import AccessPermission
from services.evidence.schemas import EvidenceAccessRole

router = APIRouter(prefix="/alerts", tags=["alerts"])

_service = AlertingService()


def _raise_service_error(exc: Exception) -> None:
    if isinstance(exc, NotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, ConflictError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if isinstance(exc, ServiceValidationError):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    raise exc


@router.post("/targets", response_model=AlertRoutingTargetRead, status_code=status.HTTP_201_CREATED)
async def create_routing_target(
    db: DbSession,
    body: AlertRoutingTargetCreate,
    access_role: EvidenceAccessRole = Query(
        EvidenceAccessRole.OPERATOR,
        description="Caller role for alert policy management authorization",
    ),
) -> AlertRoutingTargetRead:
    enforce_route_permissions(
        role=access_role,
        required_permissions=[AccessPermission.MANAGE_POLICY_SETTINGS],
        resource="alert_policy",
        action="create routing target",
    )
    try:
        target = await _service.create_routing_target(db, body)
        await db.commit()
    except (ConflictError, ServiceValidationError) as exc:
        await db.rollback()
        _raise_service_error(exc)
    return AlertRoutingTargetRead.model_validate(target)


@router.get("/targets", response_model=AlertRoutingTargetListResult)
async def list_routing_targets(
    db: DbSession,
    channel: AlertRoutingChannel | None = Query(default=None),
    is_enabled: bool | None = Query(default=None),
    access_role: EvidenceAccessRole = Query(
        EvidenceAccessRole.OPERATOR,
        description="Caller role for alert policy management authorization",
    ),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> AlertRoutingTargetListResult:
    enforce_route_permissions(
        role=access_role,
        required_permissions=[AccessPermission.MANAGE_POLICY_SETTINGS],
        resource="alert_policy",
        action="list routing targets",
    )
    items, total = await _service.list_routing_targets(
        db,
        channel=channel,
        is_enabled=is_enabled,
        limit=limit,
        offset=offset,
    )
    return AlertRoutingTargetListResult(
        items=[AlertRoutingTargetRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/policies", response_model=AlertPolicyRead, status_code=status.HTTP_201_CREATED)
async def create_policy(
    db: DbSession,
    body: AlertPolicyCreate,
    access_role: EvidenceAccessRole = Query(
        EvidenceAccessRole.OPERATOR,
        description="Caller role for alert policy management authorization",
    ),
) -> AlertPolicyRead:
    enforce_route_permissions(
        role=access_role,
        required_permissions=[AccessPermission.MANAGE_POLICY_SETTINGS],
        resource="alert_policy",
        action="create alert policy",
    )
    try:
        policy = await _service.create_policy(db, body)
        await db.commit()
    except (ConflictError, ServiceValidationError, NotFoundError) as exc:
        await db.rollback()
        _raise_service_error(exc)
    return AlertPolicyRead.model_validate(policy)


@router.get("/policies", response_model=AlertPolicyListResult)
async def list_policies(
    db: DbSession,
    source_kind: OperationalAlertSourceKind | None = Query(default=None),
    is_enabled: bool | None = Query(default=None),
    access_role: EvidenceAccessRole = Query(
        EvidenceAccessRole.OPERATOR,
        description="Caller role for alert policy management authorization",
    ),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> AlertPolicyListResult:
    enforce_route_permissions(
        role=access_role,
        required_permissions=[AccessPermission.MANAGE_POLICY_SETTINGS],
        resource="alert_policy",
        action="list alert policies",
    )
    items, total = await _service.list_policies(
        db,
        source_kind=source_kind,
        is_enabled=is_enabled,
        limit=limit,
        offset=offset,
    )
    return AlertPolicyListResult(
        items=[AlertPolicyRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/signals", response_model=AlertSignalEvaluationResult)
async def ingest_signal(db: DbSession, body: AlertSignalCreate) -> AlertSignalEvaluationResult:
    try:
        result = await _service.ingest_signal(db, body)
        await db.commit()
    except (ConflictError, ServiceValidationError, NotFoundError) as exc:
        await db.rollback()
        _raise_service_error(exc)
    return AlertSignalEvaluationResult(
        matched_policy_count=result.matched_policy_count,
        created_count=result.created_count,
        deduplicated_count=result.deduplicated_count,
        alerts=[OperationalAlertSummaryRead.model_validate(alert) for alert in result.alerts],
    )


@router.post("/escalations/process", response_model=AlertEscalationProcessResult)
async def process_due_escalations(
    db: DbSession,
    body: AlertEscalationProcessRequest,
) -> AlertEscalationProcessResult:
    try:
        alerts = await _service.process_due_escalations(db, as_of=body.as_of)
        await db.commit()
    except (ConflictError, ServiceValidationError, NotFoundError) as exc:
        await db.rollback()
        _raise_service_error(exc)
    return AlertEscalationProcessResult(
        processed_count=len(alerts),
        alert_ids=[alert.id for alert in alerts],
    )


@router.get("/", response_model=OperationalAlertListResult)
async def list_alerts(
    db: DbSession,
    alert_status: OperationalAlertStatus | None = Query(default=None, alias="status"),
    severity: OperationalAlertSeverity | None = Query(default=None),
    source_kind: OperationalAlertSourceKind | None = Query(default=None),
    camera_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> OperationalAlertListResult:
    items, total = await _service.list_alerts(
        db,
        status=alert_status,
        severity=severity,
        source_kind=source_kind,
        camera_id=camera_id,
        limit=limit,
        offset=offset,
    )
    return OperationalAlertListResult(
        items=[OperationalAlertSummaryRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{alert_id}", response_model=OperationalAlertDetailRead)
async def get_alert(db: DbSession, alert_id: uuid.UUID) -> OperationalAlertDetailRead:
    try:
        alert = await _service.get_alert(db, alert_id)
    except NotFoundError as exc:
        _raise_service_error(exc)
    return OperationalAlertDetailRead.model_validate(alert)


@router.post("/{alert_id}/acknowledge", response_model=OperationalAlertDetailRead)
async def acknowledge_alert(
    db: DbSession,
    alert_id: uuid.UUID,
    body: AlertActionRequest,
) -> OperationalAlertDetailRead:
    try:
        alert = await _service.acknowledge_alert(db, alert_id, actor=body.actor, note=body.note)
        await db.commit()
    except (ConflictError, ServiceValidationError, NotFoundError) as exc:
        await db.rollback()
        _raise_service_error(exc)
    return OperationalAlertDetailRead.model_validate(alert)


@router.post("/{alert_id}/resolve", response_model=OperationalAlertDetailRead)
async def resolve_alert(
    db: DbSession,
    alert_id: uuid.UUID,
    body: AlertActionRequest,
) -> OperationalAlertDetailRead:
    try:
        alert = await _service.resolve_alert(db, alert_id, actor=body.actor, note=body.note)
        await db.commit()
    except (ConflictError, ServiceValidationError, NotFoundError) as exc:
        await db.rollback()
        _raise_service_error(exc)
    return OperationalAlertDetailRead.model_validate(alert)


@router.post("/{alert_id}/suppress", response_model=OperationalAlertDetailRead)
async def suppress_alert(
    db: DbSession,
    alert_id: uuid.UUID,
    body: AlertActionRequest,
) -> OperationalAlertDetailRead:
    try:
        alert = await _service.suppress_alert(db, alert_id, actor=body.actor, note=body.note)
        await db.commit()
    except (ConflictError, ServiceValidationError, NotFoundError) as exc:
        await db.rollback()
        _raise_service_error(exc)
    return OperationalAlertDetailRead.model_validate(alert)


@router.post("/{alert_id}/escalate", response_model=OperationalAlertDetailRead)
async def escalate_alert(
    db: DbSession,
    alert_id: uuid.UUID,
    body: AlertActionRequest,
) -> OperationalAlertDetailRead:
    try:
        alert = await _service.escalate_alert(db, alert_id, actor=body.actor, note=body.note)
        await db.commit()
    except (ConflictError, ServiceValidationError, NotFoundError) as exc:
        await db.rollback()
        _raise_service_error(exc)
    return OperationalAlertDetailRead.model_validate(alert)


@router.post("/deliveries/dispatch", response_model=AlertDeliveryDispatchResult)
async def dispatch_deliveries(
    db: DbSession,
    body: AlertDeliveryDispatchRequest,
) -> AlertDeliveryDispatchResult:
    """Send all PLANNED delivery attempts via their configured channel adapters."""
    from apps.api.app.db.enums import AlertDeliveryState

    attempts = await _service.dispatch_planned_deliveries(
        db,
        alert_id=body.alert_id,
        include_failed=body.include_failed,
        max_retries=body.max_retries,
        limit=body.limit,
    )
    await db.commit()
    sent = sum(1 for a in attempts if a.delivery_state == AlertDeliveryState.SENT)
    failed = sum(1 for a in attempts if a.delivery_state == AlertDeliveryState.FAILED)
    skipped = sum(1 for a in attempts if a.delivery_state == AlertDeliveryState.SKIPPED)
    retried = sum(1 for a in attempts if (a.retry_count or 0) > 0)
    return AlertDeliveryDispatchResult(
        dispatched_count=len(attempts),
        sent_count=sent,
        failed_count=failed,
        skipped_count=skipped,
        retried_count=retried,
    )