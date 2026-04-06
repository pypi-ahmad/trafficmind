"""Workflow execution endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from apps.workflow.app.api.dependencies import WorkflowServiceDep
from apps.workflow.app.workflows.repository import RecordNotFoundError
from apps.workflow.app.workflows.schemas import (
    DailySummaryRequest,
    HotspotReportRequest,
    IncidentTriageRequest,
    MultimodalReviewRequest,
    OperatorAssistRequest,
    ViolationReviewRequest,
    WeeklySummaryRequest,
    WorkflowResumeRequest,
    WorkflowRunResponse,
)
from apps.workflow.app.workflows.service import WorkflowExecutionError

router = APIRouter(prefix="/workflows", tags=["workflows"])


def _raise_http_error(error: Exception) -> None:
    if isinstance(error, RecordNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    if isinstance(error, WorkflowExecutionError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    raise error


@router.post("/incident-triage", response_model=WorkflowRunResponse, status_code=status.HTTP_201_CREATED)
async def start_incident_triage(
    payload: IncidentTriageRequest,
    workflow_service: WorkflowServiceDep,
) -> WorkflowRunResponse:
    try:
        return await workflow_service.start_incident_triage(payload)
    except (RecordNotFoundError, WorkflowExecutionError) as error:
        _raise_http_error(error)


@router.post("/violation-review", response_model=WorkflowRunResponse, status_code=status.HTTP_201_CREATED)
async def start_violation_review(
    payload: ViolationReviewRequest,
    workflow_service: WorkflowServiceDep,
) -> WorkflowRunResponse:
    try:
        return await workflow_service.start_violation_review(payload)
    except (RecordNotFoundError, WorkflowExecutionError) as error:
        _raise_http_error(error)


@router.post("/multimodal-review", response_model=WorkflowRunResponse, status_code=status.HTTP_201_CREATED)
async def start_multimodal_review(
    payload: MultimodalReviewRequest,
    workflow_service: WorkflowServiceDep,
) -> WorkflowRunResponse:
    try:
        return await workflow_service.start_multimodal_review(payload)
    except (RecordNotFoundError, WorkflowExecutionError) as error:
        _raise_http_error(error)


@router.post("/daily-summary", response_model=WorkflowRunResponse, status_code=status.HTTP_201_CREATED)
async def start_daily_summary(
    payload: DailySummaryRequest,
    workflow_service: WorkflowServiceDep,
) -> WorkflowRunResponse:
    try:
        return await workflow_service.start_daily_summary(payload)
    except (RecordNotFoundError, WorkflowExecutionError) as error:
        _raise_http_error(error)


@router.post("/operator-assist", response_model=WorkflowRunResponse, status_code=status.HTTP_201_CREATED)
async def start_operator_assist(
    payload: OperatorAssistRequest,
    workflow_service: WorkflowServiceDep,
) -> WorkflowRunResponse:
    try:
        return await workflow_service.start_operator_assist(payload)
    except (RecordNotFoundError, WorkflowExecutionError) as error:
        _raise_http_error(error)


@router.post("/weekly-summary", response_model=WorkflowRunResponse, status_code=status.HTTP_201_CREATED)
async def start_weekly_summary(
    payload: WeeklySummaryRequest,
    workflow_service: WorkflowServiceDep,
) -> WorkflowRunResponse:
    try:
        return await workflow_service.start_weekly_summary(payload)
    except (RecordNotFoundError, WorkflowExecutionError) as error:
        _raise_http_error(error)


@router.post("/hotspot-report", response_model=WorkflowRunResponse, status_code=status.HTTP_201_CREATED)
async def start_hotspot_report(
    payload: HotspotReportRequest,
    workflow_service: WorkflowServiceDep,
) -> WorkflowRunResponse:
    try:
        return await workflow_service.start_hotspot_report(payload)
    except (RecordNotFoundError, WorkflowExecutionError) as error:
        _raise_http_error(error)


@router.post("/runs/{run_id}/resume", response_model=WorkflowRunResponse)
async def resume_run(
    run_id: uuid.UUID,
    payload: WorkflowResumeRequest,
    workflow_service: WorkflowServiceDep,
) -> WorkflowRunResponse:
    try:
        return await workflow_service.resume_workflow(run_id, payload)
    except (RecordNotFoundError, WorkflowExecutionError) as error:
        _raise_http_error(error)


@router.get("/runs/{run_id}", response_model=WorkflowRunResponse)
async def get_run(
    run_id: uuid.UUID,
    workflow_service: WorkflowServiceDep,
) -> WorkflowRunResponse:
    try:
        return await workflow_service.get_run(run_id)
    except (RecordNotFoundError, WorkflowExecutionError) as error:
        _raise_http_error(error)