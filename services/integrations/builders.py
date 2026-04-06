"""Builders that map TrafficMind public schemas into adapter payloads."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from apps.api.app.schemas.alerts import AlertDeliveryAttemptRead, OperationalAlertDetailRead
from apps.api.app.schemas.exports import CaseExportDetailRead
from apps.workflow.app.workflows.schemas import StoredWorkflowRun, WorkflowRunResponse
from services.integrations.schemas import (
    CaseSystemRecord,
    IntegrationMetadata,
    IntegrationReference,
    NotificationMessage,
    ObjectStorageWriteRequest,
    ReportingBatch,
)


def build_case_record_from_export(
    export: CaseExportDetailRead,
    *,
    environment: str = "local",
) -> CaseSystemRecord:
    bundle = export.bundle_data or {}
    source_references = bundle.get("source_references") or {}
    incident = bundle.get("incident") or {}
    incident_summary = bundle.get("incident_summary") or {}
    title = (
        incident_summary.get("summary")
        or incident.get("summary")
        or f"TrafficMind export for {export.subject_kind.value} {export.subject_id}"
    )
    references = _references_from_source_references(source_references)
    references.insert(
        0,
        IntegrationReference(
            kind=export.subject_kind.value,
            identifier=str(export.subject_id),
            label=export.filename,
        ),
    )
    return CaseSystemRecord(
        metadata=_metadata(
            environment=environment,
            record_type="case_export",
            tags=[export.subject_kind.value, export.export_format.value, export.status.value],
            attributes={
                "export_id": str(export.id),
                "bundle_version": export.bundle_version,
            },
        ),
        external_key=f"case-export:{export.id}",
        title=title,
        summary=incident_summary.get("summary") or incident.get("summary"),
        status=export.status.value,
        severity=incident.get("severity"),
        assignee=_extract_assignee(bundle),
        opened_at=_first_datetime(bundle, "incident", "occurred_at") or export.created_at,
        updated_at=export.updated_at,
        references=references,
        payload={
            "filename": export.filename,
            "export_format": export.export_format.value,
            "completeness": export.completeness,
            "source_references": source_references,
            "privacy": bundle.get("privacy") or {},
        },
    )


def build_notification_message_from_alert(
    alert: OperationalAlertDetailRead,
    *,
    delivery: AlertDeliveryAttemptRead | None = None,
    environment: str = "local",
) -> NotificationMessage:
    references = _alert_references(alert)
    recipients = [delivery.destination] if delivery is not None else []
    channel_hint = delivery.channel.value if delivery is not None else None
    body = alert.summary or alert.title
    if delivery is not None:
        body = (
            f"{body}\n\n"
            f"Delivery target: {delivery.destination}\n"
            f"Scheduled for: {delivery.scheduled_for.isoformat()}"
        )

    return NotificationMessage(
        metadata=_metadata(
            environment=environment,
            record_type="operational_alert_notification",
            tags=[alert.source_kind.value, alert.severity.value, alert.status.value],
            attributes={
                "alert_id": str(alert.id),
                "delivery_attempt_id": str(delivery.id) if delivery is not None else None,
            },
        ),
        title=alert.title,
        body=body,
        severity=alert.severity.value,
        dedup_key=alert.dedup_key,
        channel_hint=channel_hint,
        recipients=recipients,
        references=references,
        payload={
            "condition_key": alert.condition_key,
            "source_payload": alert.source_payload,
            "alert_metadata": alert.alert_metadata,
            "delivery_payload": delivery.delivery_payload if delivery is not None else {},
        },
    )


def build_case_record_from_workflow_run(
    stored_run: StoredWorkflowRun,
    *,
    response: WorkflowRunResponse | None = None,
    environment: str = "local",
) -> CaseSystemRecord:
    summary = _workflow_summary(response=response, stored_run=stored_run)
    workflow_name = (
        response.workflow_name.value
        if response is not None
        else stored_run.workflow_type.value
    )
    references = [IntegrationReference(kind="workflow_run", identifier=str(stored_run.id))]
    for kind, value in (
        ("camera", stored_run.camera_id),
        ("detection_event", stored_run.detection_event_id),
        ("violation_event", stored_run.violation_event_id),
    ):
        if value is None:
            continue
        references.append(IntegrationReference(kind=kind, identifier=str(value)))

    return CaseSystemRecord(
        metadata=_metadata(
            environment=environment,
            record_type="workflow_run_case_record",
            tags=[stored_run.workflow_type.value, stored_run.status.value],
            attributes={"run_id": str(stored_run.id), "workflow_name": workflow_name},
        ),
        external_key=f"workflow-run:{stored_run.id}",
        title=f"TrafficMind {workflow_name} workflow run {stored_run.id}",
        summary=summary,
        status=stored_run.status.value,
        severity=_workflow_severity(response),
        assignee=stored_run.requested_by,
        opened_at=stored_run.started_at or stored_run.created_at,
        updated_at=stored_run.updated_at,
        references=references,
        payload={
            "input_payload": stored_run.input_payload,
            "result_payload": stored_run.result_payload or {},
            "error_message": stored_run.error_message,
            "interrupted": (
                response.interrupted
                if response is not None
                else _result_payload_flag(stored_run, "interrupted")
            ),
        },
    )


def build_reporting_batch_from_workflow_run(
    stored_run: StoredWorkflowRun,
    *,
    response: WorkflowRunResponse | None = None,
    environment: str = "local",
) -> ReportingBatch:
    interrupted = (
        response.interrupted
        if response is not None
        else _result_payload_flag(stored_run, "interrupted")
    )
    checkpoint_backend = (
        response.checkpoint_backend
        if response is not None
        else _result_payload_value(stored_run, "checkpoint_backend")
    )
    error_message = (
        response.error_message if response is not None else stored_run.error_message
    )
    row = {
        "run_id": str(stored_run.id),
        "workflow_type": stored_run.workflow_type.value,
        "workflow_name": response.workflow_name.value if response is not None else None,
        "status": stored_run.status.value,
        "priority": stored_run.priority,
        "requested_by": stored_run.requested_by,
        "camera_id": str(stored_run.camera_id) if stored_run.camera_id is not None else None,
        "detection_event_id": (
            str(stored_run.detection_event_id)
            if stored_run.detection_event_id is not None
            else None
        ),
        "violation_event_id": (
            str(stored_run.violation_event_id)
            if stored_run.violation_event_id is not None
            else None
        ),
        "started_at": stored_run.started_at.isoformat() if stored_run.started_at else None,
        "completed_at": stored_run.completed_at.isoformat() if stored_run.completed_at else None,
        "created_at": stored_run.created_at.isoformat(),
        "updated_at": stored_run.updated_at.isoformat(),
        "interrupted": interrupted,
        "checkpoint_backend": checkpoint_backend,
        "summary": _workflow_summary(response=response, stored_run=stored_run),
        "error_message": error_message,
    }

    return ReportingBatch(
        metadata=_metadata(
            environment=environment,
            record_type="workflow_run_batch",
            tags=[stored_run.workflow_type.value, stored_run.status.value],
            attributes={"run_id": str(stored_run.id)},
        ),
        dataset="workflow_runs",
        rows=[row],
        row_count=1,
    )


def build_object_storage_write_request_from_export(
    export: CaseExportDetailRead,
    *,
    environment: str = "local",
    object_key: str | None = None,
) -> ObjectStorageWriteRequest:
    payload = export.model_dump(mode="json")
    rendered = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    resolved_object_key = object_key or (
        f"exports/{export.subject_kind.value}/{export.subject_id}/"
        f"{export.id}-{_safe_filename(export.filename)}"
    )
    return ObjectStorageWriteRequest(
        metadata=_metadata(
            environment=environment,
            record_type="case_export_object",
            tags=[export.subject_kind.value, export.export_format.value],
            attributes={"export_id": str(export.id)},
        ),
        object_key=resolved_object_key,
        content_type="application/json",
        body=rendered,
        object_metadata={
            "export_id": str(export.id),
            "subject_kind": export.subject_kind.value,
            "subject_id": str(export.subject_id),
        },
    )


def _metadata(
    *,
    environment: str,
    record_type: str,
    tags: list[str] | None = None,
    attributes: dict[str, Any] | None = None,
) -> IntegrationMetadata:
    return IntegrationMetadata(
        environment=environment,
        record_type=record_type,
        emitted_at=datetime.now(UTC),
        tags=tags or [],
        attributes=attributes or {},
    )


def _references_from_source_references(
    source_references: dict[str, Any],
) -> list[IntegrationReference]:
    references: list[IntegrationReference] = []
    subject = source_references.get("subject") or {}
    if subject.get("id") is not None:
        references.append(
            IntegrationReference(
                kind=str(subject.get("kind") or "subject"),
                identifier=str(subject["id"]),
            )
        )

    for key in (
        "camera_id",
        "stream_id",
        "zone_id",
        "detection_event_id",
        "violation_event_id",
    ):
        value = source_references.get(key)
        if value is None:
            continue
        references.append(
            IntegrationReference(kind=key.removesuffix("_id"), identifier=str(value))
        )

    for key in ("plate_read_ids", "evidence_manifest_ids", "workflow_run_ids"):
        for value in source_references.get(key) or []:
            references.append(
                IntegrationReference(kind=key.removesuffix("_ids"), identifier=str(value))
            )
    return references


def _extract_assignee(bundle: dict[str, Any]) -> str | None:
    review = bundle.get("review") or {}
    if isinstance(review, dict):
        return review.get("assigned_to") or review.get("reviewed_by")
    return None


def _first_datetime(bundle: dict[str, Any], section: str, key: str) -> datetime | None:
    section_data = bundle.get(section) or {}
    if not isinstance(section_data, dict):
        return None
    return _parse_datetime(section_data.get(key))


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            return None
    return None


def _alert_references(alert: OperationalAlertDetailRead) -> list[IntegrationReference]:
    references = [IntegrationReference(kind="operational_alert", identifier=str(alert.id))]
    for kind, value in (
        ("camera", alert.camera_id),
        ("stream", alert.stream_id),
        ("detection_event", alert.detection_event_id),
        ("violation_event", alert.violation_event_id),
        ("watchlist_alert", alert.watchlist_alert_id),
        ("workflow_run", alert.workflow_run_id),
    ):
        if value is None:
            continue
        references.append(IntegrationReference(kind=kind, identifier=str(value)))
    return references


def _workflow_summary(
    *,
    response: WorkflowRunResponse | None,
    stored_run: StoredWorkflowRun,
) -> str | None:
    if response is not None and response.output is not None:
        for attribute in (
            "summary",
            "review_summary",
            "answer",
            "headline",
            "operator_brief",
        ):
            value = getattr(response.output, attribute, None)
            if isinstance(value, str) and value:
                return value
    result_payload = stored_run.result_payload or {}
    output = result_payload.get("output") or {}
    if isinstance(output, dict):
        for key in ("summary", "review_summary", "answer", "headline", "operator_brief"):
            value = output.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _workflow_severity(response: WorkflowRunResponse | None) -> str | None:
    if response is None or response.output is None:
        return None
    priority = getattr(response.output, "priority", None)
    if priority is None:
        return None
    return str(priority)


def _result_payload_flag(stored_run: StoredWorkflowRun, key: str) -> bool:
    return bool(_result_payload_value(stored_run, key))


def _result_payload_value(stored_run: StoredWorkflowRun, key: str) -> Any:
    payload = stored_run.result_payload or {}
    return payload.get(key)


def _safe_filename(value: str) -> str:
    return value.replace("\\", "_").replace("/", "_").replace(" ", "-")
