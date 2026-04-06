"""Workflow orchestration service built on LangGraph."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

import uuid

from fastapi.encoders import jsonable_encoder
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from apps.api.app.db.enums import ViolationStatus, WorkflowStatus, WorkflowType
from apps.workflow.app.core.config import Settings
from apps.workflow.app.workflows.graphs import (
    build_daily_summary_graph,
    build_hotspot_report_graph,
    build_incident_triage_graph,
    build_multimodal_review_graph,
    build_operator_assist_graph,
    build_violation_review_graph,
    build_weekly_summary_graph,
)
from apps.workflow.app.workflows.providers import WorkflowReasoningProvider, build_reasoning_provider
from apps.workflow.app.workflows.repository import RecordNotFoundError, WorkflowRepository
from apps.workflow.app.workflows.schemas import (
    DailySummaryOutput,
    DailySummaryRequest,
    HotspotReportOutput,
    HotspotReportRequest,
    HumanReviewPrompt,
    IncidentTriageOutput,
    IncidentTriageRequest,
    MultimodalReviewOutput,
    MultimodalReviewRequest,
    OperatorAssistOutput,
    OperatorAssistRequest,
    ReviewDisposition,
    StoredWorkflowRun,
    ViolationReviewOutput,
    ViolationReviewRequest,
    WeeklySummaryOutput,
    WeeklySummaryRequest,
    WorkflowName,
    WorkflowResumeRequest,
    WorkflowRunResponse,
    WorkflowTraceEntry,
    WORKFLOW_OUTPUT_ADAPTER,
)


class WorkflowExecutionError(RuntimeError):
    """Raised when workflow execution or resumption fails."""


class WorkflowService:
    """Owns LangGraph workflow execution for stored TrafficMind records."""

    def __init__(
        self,
        repository: WorkflowRepository,
        settings: Settings,
        provider: WorkflowReasoningProvider | None = None,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._provider = provider or build_reasoning_provider(settings.provider_backend)
        self._checkpointer = InMemorySaver()
        self._graphs = {
            WorkflowName.INCIDENT_TRIAGE: build_incident_triage_graph(self._provider).compile(
                checkpointer=self._checkpointer,
                debug=settings.debug,
            ),
            WorkflowName.VIOLATION_REVIEW: build_violation_review_graph(self._provider).compile(
                checkpointer=self._checkpointer,
                debug=settings.debug,
            ),
            WorkflowName.MULTIMODAL_REVIEW: build_multimodal_review_graph(self._provider).compile(
                checkpointer=self._checkpointer,
                debug=settings.debug,
            ),
            WorkflowName.DAILY_SUMMARY: build_daily_summary_graph(self._provider).compile(
                checkpointer=self._checkpointer,
                debug=settings.debug,
            ),
            WorkflowName.OPERATOR_ASSIST: build_operator_assist_graph(self._provider, self._repository).compile(
                checkpointer=self._checkpointer,
                debug=settings.debug,
            ),
            WorkflowName.WEEKLY_SUMMARY: build_weekly_summary_graph(self._provider).compile(
                checkpointer=self._checkpointer,
                debug=settings.debug,
            ),
            WorkflowName.HOTSPOT_REPORT: build_hotspot_report_graph(self._provider).compile(
                checkpointer=self._checkpointer,
                debug=settings.debug,
            ),
        }

    @property
    def checkpoint_backend(self) -> str:
        return self._settings.checkpoint_backend

    @property
    def durability_note(self) -> str:
        return (
            "Local development uses LangGraph InMemorySaver. Resume works within a running process;"
            " swap in a persistent saver for cross-process durability."
        )

    @property
    def provider_backend(self) -> str:
        return self._settings.provider_backend

    async def start_incident_triage(self, request: IncidentTriageRequest) -> WorkflowRunResponse:
        context = await self._repository.build_incident_triage_context(request)
        run = await self._repository.create_workflow_run(
            workflow_name=WorkflowName.INCIDENT_TRIAGE,
            workflow_type=WorkflowType.TRIAGE,
            requested_by=request.requested_by,
            input_payload=jsonable_encoder(request),
            camera_id=context.camera.id,
            detection_event_id=context.detection_event.id if context.detection_event is not None else None,
            violation_event_id=context.violation_event.id if context.violation_event is not None else None,
            priority=3,
        )
        await self._repository.update_workflow_run(
            run.id,
            status=WorkflowStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
        )
        initial_state = {
            "workflow_run_id": str(run.id),
            "workflow_name": WorkflowName.INCIDENT_TRIAGE,
            "request": request,
            "context": context,
            "trace": [WorkflowTraceEntry(node="bootstrap", message="Loaded incident triage context from stored records.")],
        }
        return await self._run_graph(WorkflowName.INCIDENT_TRIAGE, run.id, initial_state)

    async def start_violation_review(self, request: ViolationReviewRequest) -> WorkflowRunResponse:
        context = await self._repository.build_violation_review_context(request)
        run = await self._repository.create_workflow_run(
            workflow_name=WorkflowName.VIOLATION_REVIEW,
            workflow_type=WorkflowType.REVIEW,
            requested_by=request.requested_by,
            input_payload=jsonable_encoder(request),
            camera_id=context.camera.id,
            detection_event_id=context.detection_event.id if context.detection_event is not None else None,
            violation_event_id=context.violation_event.id,
            priority=2,
        )
        await self._repository.update_workflow_run(
            run.id,
            status=WorkflowStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
        )
        initial_state = {
            "workflow_run_id": str(run.id),
            "workflow_name": WorkflowName.VIOLATION_REVIEW,
            "request": request,
            "context": context,
            "trace": [WorkflowTraceEntry(node="bootstrap", message="Loaded violation review context from stored records.")],
        }
        return await self._run_graph(WorkflowName.VIOLATION_REVIEW, run.id, initial_state)

    async def start_multimodal_review(self, request: MultimodalReviewRequest) -> WorkflowRunResponse:
        context = await self._repository.build_multimodal_review_context(request)
        run = await self._repository.create_workflow_run(
            workflow_name=WorkflowName.MULTIMODAL_REVIEW,
            workflow_type=WorkflowType.ASSIST,
            requested_by=request.requested_by,
            input_payload=jsonable_encoder(request),
            camera_id=context.camera.id,
            detection_event_id=context.detection_event.id if context.detection_event is not None else None,
            violation_event_id=context.violation_event.id,
            priority=3,
        )
        await self._repository.update_workflow_run(
            run.id,
            status=WorkflowStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
        )
        initial_state = {
            "workflow_run_id": str(run.id),
            "workflow_name": WorkflowName.MULTIMODAL_REVIEW,
            "request": request,
            "context": context,
            "trace": [
                WorkflowTraceEntry(
                    node="bootstrap",
                    message="Loaded multimodal review context from stored violation, detection, evidence, and review records.",
                )
            ],
        }
        return await self._run_graph(WorkflowName.MULTIMODAL_REVIEW, run.id, initial_state)

    async def start_daily_summary(self, request: DailySummaryRequest) -> WorkflowRunResponse:
        context = await self._repository.build_daily_summary_context(request)
        run = await self._repository.create_workflow_run(
            workflow_name=WorkflowName.DAILY_SUMMARY,
            workflow_type=WorkflowType.REPORT,
            requested_by=request.requested_by,
            input_payload=jsonable_encoder(request),
            camera_id=request.camera_id,
            priority=4,
        )
        await self._repository.update_workflow_run(
            run.id,
            status=WorkflowStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
        )
        initial_state = {
            "workflow_run_id": str(run.id),
            "workflow_name": WorkflowName.DAILY_SUMMARY,
            "request": request,
            "context": context,
            "trace": [WorkflowTraceEntry(node="bootstrap", message="Loaded daily summary context from stored records.")],
        }
        return await self._run_graph(WorkflowName.DAILY_SUMMARY, run.id, initial_state)

    async def start_operator_assist(self, request: OperatorAssistRequest) -> WorkflowRunResponse:
        run = await self._repository.create_workflow_run(
            workflow_name=WorkflowName.OPERATOR_ASSIST,
            workflow_type=WorkflowType.ASSIST,
            requested_by=request.requested_by,
            input_payload=jsonable_encoder(request),
            camera_id=request.camera_id,
            detection_event_id=request.detection_event_id,
            violation_event_id=request.violation_event_id,
            priority=3,
        )
        await self._repository.update_workflow_run(
            run.id,
            status=WorkflowStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
        )
        initial_state = {
            "workflow_run_id": str(run.id),
            "workflow_name": WorkflowName.OPERATOR_ASSIST,
            "request": request,
            "trace": [
                WorkflowTraceEntry(
                    node="bootstrap",
                    message="Loaded operator-assist request and prepared deterministic planning.",
                )
            ],
        }
        return await self._run_graph(WorkflowName.OPERATOR_ASSIST, run.id, initial_state)

    async def start_weekly_summary(self, request: WeeklySummaryRequest) -> WorkflowRunResponse:
        context = await self._repository.build_weekly_summary_context(request)
        run = await self._repository.create_workflow_run(
            workflow_name=WorkflowName.WEEKLY_SUMMARY,
            workflow_type=WorkflowType.REPORT,
            requested_by=request.requested_by,
            input_payload=jsonable_encoder(request),
            camera_id=request.camera_id,
            priority=4,
        )
        await self._repository.update_workflow_run(
            run.id,
            status=WorkflowStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
        )
        initial_state = {
            "workflow_run_id": str(run.id),
            "workflow_name": WorkflowName.WEEKLY_SUMMARY,
            "request": request,
            "context": context,
            "trace": [WorkflowTraceEntry(node="bootstrap", message="Loaded weekly summary context from stored records.")],
        }
        return await self._run_graph(WorkflowName.WEEKLY_SUMMARY, run.id, initial_state)

    async def start_hotspot_report(self, request: HotspotReportRequest) -> WorkflowRunResponse:
        context = await self._repository.build_hotspot_report_context(request)
        run = await self._repository.create_workflow_run(
            workflow_name=WorkflowName.HOTSPOT_REPORT,
            workflow_type=WorkflowType.REPORT,
            requested_by=request.requested_by,
            input_payload=jsonable_encoder(request),
            priority=4,
        )
        await self._repository.update_workflow_run(
            run.id,
            status=WorkflowStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
        )
        initial_state = {
            "workflow_run_id": str(run.id),
            "workflow_name": WorkflowName.HOTSPOT_REPORT,
            "request": request,
            "context": context,
            "trace": [WorkflowTraceEntry(node="bootstrap", message="Loaded hotspot report context from stored records.")],
        }
        return await self._run_graph(WorkflowName.HOTSPOT_REPORT, run.id, initial_state)

    async def resume_workflow(self, run_id: uuid.UUID, payload: WorkflowResumeRequest) -> WorkflowRunResponse:
        stored_run = await self._repository.get_workflow_run(run_id)
        workflow_name = self._workflow_name_from_run(stored_run)
        graph = self._graphs[workflow_name]
        config = self._graph_config(run_id)
        snapshot = await graph.aget_state(config)
        if not snapshot.next:
            msg = (
                "No resumable checkpoint was found for this workflow run. "
                "If the process restarted, rerun the workflow or configure a persistent checkpointer."
            )
            raise WorkflowExecutionError(msg)

        try:
            result = await graph.ainvoke(Command(resume=jsonable_encoder(payload)), config=config)
        except Exception as exc:
            await self._mark_failed(run_id, exc)
            raise
        return await self._persist_result(workflow_name, stored_run, result)

    async def get_run(self, run_id: uuid.UUID) -> WorkflowRunResponse:
        stored_run = await self._repository.get_workflow_run(run_id)
        return self._to_response(stored_run)

    async def _run_graph(
        self,
        workflow_name: WorkflowName,
        run_id: uuid.UUID,
        initial_state: dict[str, Any],
    ) -> WorkflowRunResponse:
        graph = self._graphs[workflow_name]
        try:
            result = await graph.ainvoke(initial_state, config=self._graph_config(run_id))
        except Exception as exc:
            await self._mark_failed(run_id, exc)
            raise
        stored_run = await self._repository.get_workflow_run(run_id)
        return await self._persist_result(workflow_name, stored_run, result)

    async def _mark_failed(self, run_id: uuid.UUID, error: Exception) -> None:
        await self._repository.update_workflow_run(
            run_id,
            status=WorkflowStatus.FAILED,
            completed_at=datetime.now(timezone.utc),
            error_message=str(error),
            result_payload={
                "interrupted": False,
                "checkpoint_backend": self.checkpoint_backend,
                "durability_note": self.durability_note,
            },
        )

    async def _persist_result(
        self,
        workflow_name: WorkflowName,
        stored_run: StoredWorkflowRun,
        result: dict[str, Any],
    ) -> WorkflowRunResponse:
        graph = self._graphs[workflow_name]
        config = self._graph_config(stored_run.id)
        snapshot = await graph.aget_state(config)
        trace = self._extract_trace(result, snapshot.values)

        interrupt_request = self._extract_interrupt_request(result)
        if interrupt_request is not None:
            updated = await self._repository.update_workflow_run(
                stored_run.id,
                status=WorkflowStatus.RUNNING,
                result_payload={
                    "workflow_name": workflow_name.value,
                    "interrupted": True,
                    "checkpoint_backend": self.checkpoint_backend,
                    "durability_note": self.durability_note,
                    "interrupt_request": jsonable_encoder(interrupt_request),
                    "trace": jsonable_encoder(trace),
                    "next_nodes": list(snapshot.next),
                },
            )
            return self._to_response(updated)

        output = self._extract_output(result, snapshot.values)
        updated = await self._repository.update_workflow_run(
            stored_run.id,
            status=WorkflowStatus.SUCCEEDED,
            completed_at=datetime.now(timezone.utc),
            result_payload={
                "workflow_name": workflow_name.value,
                "interrupted": False,
                "checkpoint_backend": self.checkpoint_backend,
                "durability_note": self.durability_note,
                "output": jsonable_encoder(output),
                "trace": jsonable_encoder(trace),
            },
        )

        if workflow_name == WorkflowName.VIOLATION_REVIEW and isinstance(output, ViolationReviewOutput):
            await self._apply_violation_write_back(stored_run, output)

        return self._to_response(updated)

    _DISPOSITION_STATUS_MAP: dict[ReviewDisposition, ViolationStatus] = {
        ReviewDisposition.CONFIRM_VIOLATION: ViolationStatus.CONFIRMED,
        ReviewDisposition.DISMISS_FALSE_POSITIVE: ViolationStatus.DISMISSED,
        ReviewDisposition.NEED_MORE_EVIDENCE: ViolationStatus.UNDER_REVIEW,
        ReviewDisposition.ESCALATE_SUPERVISOR: ViolationStatus.UNDER_REVIEW,
    }

    async def _apply_violation_write_back(
        self,
        stored_run: StoredWorkflowRun,
        output: ViolationReviewOutput,
    ) -> None:
        violation_id = stored_run.violation_event_id
        if violation_id is None:
            return
        new_status = self._DISPOSITION_STATUS_MAP.get(output.disposition)
        if new_status is None:
            return
        await self._repository.apply_violation_disposition(
            violation_id,
            new_status=new_status,
            reviewed_by=stored_run.requested_by,
            review_note=output.summary,
        )

    def _extract_interrupt_request(self, result: dict[str, Any]) -> HumanReviewPrompt | None:
        interrupts = result.get("__interrupt__")
        if not interrupts:
            return None
        return HumanReviewPrompt.model_validate(interrupts[0].value)

    def _extract_trace(self, result: dict[str, Any], snapshot_values: dict[str, Any]) -> list[WorkflowTraceEntry]:
        trace_data = result.get("trace") or snapshot_values.get("trace") or []
        return [
            item if isinstance(item, WorkflowTraceEntry) else WorkflowTraceEntry.model_validate(item)
            for item in trace_data
        ]

    def _extract_output(self, result: dict[str, Any], snapshot_values: dict[str, Any]) -> IncidentTriageOutput | ViolationReviewOutput | MultimodalReviewOutput | DailySummaryOutput | WeeklySummaryOutput | HotspotReportOutput | OperatorAssistOutput:
        candidate = result.get("output") or snapshot_values.get("output")
        if candidate is None:
            msg = "Workflow graph completed without an output payload."
            raise WorkflowExecutionError(msg)
        return cast(
            IncidentTriageOutput | ViolationReviewOutput | MultimodalReviewOutput | DailySummaryOutput | WeeklySummaryOutput | HotspotReportOutput | OperatorAssistOutput,
            WORKFLOW_OUTPUT_ADAPTER.validate_python(candidate),
        )

    def _workflow_name_from_run(self, stored_run: StoredWorkflowRun) -> WorkflowName:
        workflow_name = stored_run.input_payload.get("workflow_name")
        if not isinstance(workflow_name, str):
            msg = "Stored workflow run is missing workflow_name in input payload."
            raise WorkflowExecutionError(msg)
        return WorkflowName(workflow_name)

    def _to_response(self, stored_run: StoredWorkflowRun) -> WorkflowRunResponse:
        payload = stored_run.result_payload or {}
        workflow_name = self._workflow_name_from_run(stored_run)
        output_payload = payload.get("output")
        trace_payload = payload.get("trace") or []
        interrupt_payload = payload.get("interrupt_request")

        return WorkflowRunResponse(
            run_id=stored_run.id,
            workflow_name=workflow_name,
            workflow_type=stored_run.workflow_type,
            status=stored_run.status,
            interrupted=bool(payload.get("interrupted", False)),
            checkpoint_backend=str(payload.get("checkpoint_backend", self.checkpoint_backend)),
            durability_note=str(payload.get("durability_note", self.durability_note)),
            interrupt_request=(
                HumanReviewPrompt.model_validate(interrupt_payload)
                if interrupt_payload is not None
                else None
            ),
            output=(
                cast(
                    IncidentTriageOutput | ViolationReviewOutput | MultimodalReviewOutput | DailySummaryOutput | WeeklySummaryOutput | HotspotReportOutput | OperatorAssistOutput,
                    WORKFLOW_OUTPUT_ADAPTER.validate_python(output_payload),
                )
                if output_payload is not None
                else None
            ),
            trace=[WorkflowTraceEntry.model_validate(item) for item in trace_payload],
            error_message=stored_run.error_message,
        )

    @staticmethod
    def _graph_config(run_id: uuid.UUID) -> dict[str, Any]:
        return {"configurable": {"thread_id": str(run_id)}}
