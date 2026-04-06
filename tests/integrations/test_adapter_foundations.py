from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest

from apps.api.app.db.enums import (
    AlertDeliveryState,
    AlertRoutingChannel,
    CaseExportFormat,
    CaseExportStatus,
    CaseSubjectKind,
    OperationalAlertSeverity,
    OperationalAlertSourceKind,
    OperationalAlertStatus,
    WorkflowStatus,
    WorkflowType,
)
from apps.api.app.schemas.alerts import AlertDeliveryAttemptRead, OperationalAlertDetailRead
from apps.api.app.schemas.exports import CaseExportDetailRead
from apps.workflow.app.workflows.schemas import (
    IncidentPriority,
    IncidentTriageOutput,
    StoredWorkflowRun,
    WorkflowName,
    WorkflowRunResponse,
)
from services.integrations import (
    CASE_SYSTEM_ADAPTERS,
    OBJECT_STORAGE_ADAPTERS,
    ExternalSignalAdapter,
    ExternalSignalSyncBridge,
    JsonlIntegrationSinkAdapter,
    build_case_record_from_export,
    build_case_record_from_workflow_run,
    build_notification_message_from_alert,
    build_object_storage_write_request_from_export,
    build_reporting_batch_from_workflow_run,
)
from services.signals.integration import (
    ControllerSignalBatch,
    ControllerSignalEvent,
    ExternalSignalFeedKind,
    SignalIntegrationService,
)
from services.rules.schemas import TrafficLightState
from services.signals.schemas import SignalPhase


def _delivery_attempt(alert_id: uuid.UUID) -> AlertDeliveryAttemptRead:
    now = datetime(2026, 4, 6, 8, 0, tzinfo=UTC)
    return AlertDeliveryAttemptRead(
        id=uuid.uuid4(),
        alert_id=alert_id,
        policy_id=uuid.uuid4(),
        routing_target_id=uuid.uuid4(),
        escalation_level=0,
        delivery_state=AlertDeliveryState.PLANNED,
        channel=AlertRoutingChannel.WEBHOOK,
        destination="https://alerts.example.test/webhook",
        scheduled_for=now,
        attempted_at=None,
        error_message=None,
        delivery_payload={"route_config": {"priority": "high"}},
        created_at=now,
        updated_at=now,
    )


def _operational_alert() -> OperationalAlertDetailRead:
    now = datetime(2026, 4, 6, 8, 0, tzinfo=UTC)
    alert_id = uuid.uuid4()
    return OperationalAlertDetailRead(
        id=alert_id,
        policy_id=uuid.uuid4(),
        camera_id=uuid.uuid4(),
        stream_id=uuid.uuid4(),
        detection_event_id=uuid.uuid4(),
        violation_event_id=uuid.uuid4(),
        watchlist_alert_id=None,
        workflow_run_id=uuid.uuid4(),
        source_kind=OperationalAlertSourceKind.CAMERA_HEALTH,
        condition_key="camera_offline",
        severity=OperationalAlertSeverity.HIGH,
        status=OperationalAlertStatus.NEW,
        dedup_key="camera_health|camera_offline|camera:abc",
        title="Camera offline at King Fahd & Olaya",
        summary="Primary stream heartbeat expired for more than 60 seconds.",
        occurred_at=now,
        first_seen_at=now,
        last_seen_at=now,
        occurrence_count=1,
        escalation_level=0,
        escalation_due_at=None,
        last_routed_at=None,
        cooldown_until=None,
        acknowledged_at=None,
        acknowledged_by=None,
        resolved_at=None,
        resolved_by=None,
        suppressed_at=None,
        suppressed_by=None,
        source_payload={"camera_code": "CAM-001"},
        alert_metadata={"health_state": "offline"},
        created_at=now,
        updated_at=now,
        deliveries=[_delivery_attempt(alert_id)],
        audit_events=[],
    )


def _case_export() -> CaseExportDetailRead:
    now = datetime(2026, 4, 6, 8, 0, tzinfo=UTC)
    subject_id = uuid.uuid4()
    return CaseExportDetailRead(
        id=uuid.uuid4(),
        subject_kind=CaseSubjectKind.VIOLATION_EVENT,
        subject_id=subject_id,
        export_format=CaseExportFormat.JSON,
        status=CaseExportStatus.COMPLETED,
        requested_by="reviewer.jane",
        bundle_version="1.0",
        filename="violation-event-export.json",
        completeness={"missing_or_incomplete": []},
        error_message=None,
        completed_at=now,
        created_at=now,
        updated_at=now,
        bundle_data={
            "incident": {
                "severity": "high",
                "occurred_at": "2026-04-06T07:55:00Z",
            },
            "incident_summary": {
                "summary": "Vehicle crossed the stop line after the signal turned red.",
            },
            "review": {"assigned_to": "reviewer.jane"},
            "source_references": {
                "subject": {"kind": "violation_event", "id": str(subject_id)},
                "camera_id": str(uuid.uuid4()),
                "workflow_run_ids": [str(uuid.uuid4())],
            },
            "privacy": {"asset_view": "original"},
        },
        audit_events=[],
    )


def _stored_workflow_run() -> StoredWorkflowRun:
    now = datetime(2026, 4, 6, 8, 0, tzinfo=UTC)
    return StoredWorkflowRun(
        id=uuid.uuid4(),
        workflow_type=WorkflowType.TRIAGE,
        status=WorkflowStatus.SUCCEEDED,
        priority=3,
        requested_by="analyst.a",
        camera_id=uuid.uuid4(),
        detection_event_id=uuid.uuid4(),
        violation_event_id=uuid.uuid4(),
        started_at=now,
        completed_at=now,
        input_payload={"violation_event_id": "abc"},
        result_payload={"interrupted": False, "checkpoint_backend": "memory"},
        error_message=None,
        created_at=now,
        updated_at=now,
    )


def _workflow_response(run_id: uuid.UUID) -> WorkflowRunResponse:
    return WorkflowRunResponse(
        run_id=run_id,
        workflow_name=WorkflowName.INCIDENT_TRIAGE,
        workflow_type=WorkflowType.TRIAGE,
        status=WorkflowStatus.SUCCEEDED,
        interrupted=False,
        checkpoint_backend="memory",
        durability_note="In-memory checkpointing only.",
        output=IncidentTriageOutput(
            priority=IncidentPriority.HIGH,
            summary="Recommend supervisor review for the red-light incident.",
            rationale=["Severity is high."],
            recommended_actions=["review_evidence_clip"],
            evidence_gaps=[],
            operator_brief="Review the evidence clip and notify the shift supervisor.",
            requires_human_review=True,
            escalation_target="shift_supervisor",
        ),
        trace=[],
        error_message=None,
    )


@pytest.mark.asyncio
async def test_jsonl_sink_records_case_notification_and_reporting(tmp_path) -> None:
    export = _case_export()
    alert = _operational_alert()
    run = _stored_workflow_run()
    response = _workflow_response(run.id)

    adapter = JsonlIntegrationSinkAdapter(tmp_path)
    case_receipt = await adapter.upsert_case(build_case_record_from_export(export))
    notification_receipt = await adapter.send_notification(
        build_notification_message_from_alert(alert, delivery=alert.deliveries[0])
    )
    report_receipt = await adapter.publish_batch(
        build_reporting_batch_from_workflow_run(run, response=response)
    )

    assert case_receipt.status == "stored"
    assert notification_receipt.status == "stored"
    assert report_receipt.status == "stored"
    assert (tmp_path / "cases.jsonl").exists()
    assert (tmp_path / "notifications.jsonl").exists()
    assert (tmp_path / "reports-workflow_runs.jsonl").exists()


@pytest.mark.asyncio
async def test_local_object_storage_adapter_writes_export_payload(tmp_path) -> None:
    export = _case_export()
    request = build_object_storage_write_request_from_export(export)

    adapter = OBJECT_STORAGE_ADAPTERS.create("local_fs", root_dir=tmp_path)
    result = await adapter.put_object(request)

    stored_path = tmp_path / request.object_key
    assert stored_path.exists()
    assert result.size_bytes == len(request.body)
    stored_payload = json.loads(stored_path.read_text(encoding="utf-8"))
    assert stored_payload["id"] == str(export.id)


def test_case_and_workflow_builders_produce_normalized_records() -> None:
    export = _case_export()
    run = _stored_workflow_run()
    response = _workflow_response(run.id)

    export_record = build_case_record_from_export(export, environment="dev")
    workflow_record = build_case_record_from_workflow_run(
        run,
        response=response,
        environment="dev",
    )

    assert export_record.metadata.environment == "dev"
    assert export_record.summary == (
        "Vehicle crossed the stop line after the signal turned red."
    )
    assert workflow_record.severity == "high"
    assert workflow_record.summary == (
        "Recommend supervisor review for the red-light incident."
    )


def test_alert_builder_uses_delivery_target() -> None:
    alert = _operational_alert()
    message = build_notification_message_from_alert(
        alert,
        delivery=alert.deliveries[0],
        environment="staging",
    )

    assert message.metadata.environment == "staging"
    assert message.channel_hint == "webhook"
    assert message.recipients == ["https://alerts.example.test/webhook"]
    assert message.references[0].kind == "operational_alert"


@pytest.mark.asyncio
async def test_external_signal_bridge_ingests_adapter_events() -> None:
    camera_id = uuid.uuid4()

    class StaticSignalAdapter(ExternalSignalAdapter):
        adapter_name = "static-signal"

        async def fetch_controller_events(self) -> ControllerSignalBatch:
            return ControllerSignalBatch(
                events=[
                    ControllerSignalEvent(
                        camera_id=camera_id,
                        controller_id="ctrl-001",
                        phase_id="veh-main",
                        phase=SignalPhase.VEHICLE,
                        state=TrafficLightState.RED,
                        timestamp=datetime(2026, 4, 6, 8, 0, tzinfo=UTC),
                        source_type=ExternalSignalFeedKind.MOCK_SIMULATOR,
                    )
                ]
            )

    bridge = ExternalSignalSyncBridge(SignalIntegrationService())
    receipt = await bridge.sync_once(StaticSignalAdapter())

    assert receipt.adapter_name == "static-signal"
    assert receipt.accepted_count == 1
    assert receipt.fetched_event_count == 1


def test_jsonl_case_adapter_is_registered() -> None:
    assert "jsonl_sink" in CASE_SYSTEM_ADAPTERS.available()
