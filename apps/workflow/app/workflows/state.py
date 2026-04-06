"""LangGraph state models for TrafficMind workflows."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from apps.workflow.app.workflows.schemas import (
    DailySummaryContext,
    DailySummaryOutput,
    DailySummaryRequest,
    HotspotReportContext,
    HotspotReportOutput,
    HotspotReportRequest,
    HumanReviewDecision,
    IncidentTriageContext,
    IncidentTriageOutput,
    IncidentTriageRequest,
    MultimodalReviewContext,
    MultimodalReviewGrounding,
    MultimodalReviewOutput,
    MultimodalReviewRequest,
    OperatorAssistGrounding,
    OperatorAssistOutput,
    OperatorAssistPlan,
    OperatorAssistRequest,
    ViolationReviewContext,
    ViolationReviewOutput,
    ViolationReviewRequest,
    WeeklySummaryContext,
    WeeklySummaryOutput,
    WeeklySummaryRequest,
    WorkflowName,
    WorkflowTraceEntry,
)


class BaseWorkflowState(TypedDict, total=False):
    workflow_run_id: str
    workflow_name: WorkflowName
    trace: Annotated[list[WorkflowTraceEntry], operator.add]
    human_decision: HumanReviewDecision | None


class IncidentTriageState(BaseWorkflowState, total=False):
    request: IncidentTriageRequest
    context: IncidentTriageContext
    triage_output: IncidentTriageOutput
    output: IncidentTriageOutput


class ViolationReviewState(BaseWorkflowState, total=False):
    request: ViolationReviewRequest
    context: ViolationReviewContext
    recommendation: ViolationReviewOutput
    output: ViolationReviewOutput


class MultimodalReviewState(BaseWorkflowState, total=False):
    request: MultimodalReviewRequest
    context: MultimodalReviewContext
    grounding: MultimodalReviewGrounding
    output: MultimodalReviewOutput


class DailySummaryState(BaseWorkflowState, total=False):
    request: DailySummaryRequest
    context: DailySummaryContext
    summary_output: DailySummaryOutput
    output: DailySummaryOutput


class OperatorAssistState(BaseWorkflowState, total=False):
    request: OperatorAssistRequest
    plan: OperatorAssistPlan
    grounding: OperatorAssistGrounding
    output: OperatorAssistOutput


class WeeklySummaryState(BaseWorkflowState, total=False):
    request: WeeklySummaryRequest
    context: WeeklySummaryContext
    summary_output: WeeklySummaryOutput
    output: WeeklySummaryOutput


class HotspotReportState(BaseWorkflowState, total=False):
    request: HotspotReportRequest
    context: HotspotReportContext
    report_output: HotspotReportOutput
    output: HotspotReportOutput
