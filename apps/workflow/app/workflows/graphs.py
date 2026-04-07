"""LangGraph workflow definitions for TrafficMind cold-path orchestration."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from apps.workflow.app.workflows.multimodal_review import build_multimodal_review_grounding
from apps.workflow.app.workflows.providers import WorkflowReasoningProvider
from apps.workflow.app.workflows.repository import WorkflowRepository
from apps.workflow.app.workflows.schemas import (
    HumanReviewDecision,
    HumanReviewPrompt,
    IncidentPriority,
    ReviewDisposition,
    WorkflowTraceEntry,
)
from apps.workflow.app.workflows.operator_assist import plan_operator_assist_request
from apps.workflow.app.workflows.state import (
    DailySummaryState,
    HotspotReportState,
    IncidentTriageState,
    MultimodalReviewState,
    OperatorAssistState,
    ViolationReviewState,
    WeeklySummaryState,
)


def _trace(
    *,
    node: str,
    message: str,
    metadata: dict[str, Any] | None = None,
) -> list[WorkflowTraceEntry]:
    """Return a single-entry trace list.  The Annotated reducer on state['trace'] handles accumulation."""
    return [WorkflowTraceEntry(node=node, message=message, metadata=metadata or {})]


def _append_markdown_note(markdown: str, *, heading: str, note: str) -> str:
    return f"{markdown}\n\n## {heading}\n- {note}" if markdown else f"## {heading}\n- {note}"


def build_incident_triage_graph(provider: WorkflowReasoningProvider):
    graph = StateGraph(IncidentTriageState)

    async def analyze_incident(state: IncidentTriageState) -> dict[str, Any]:
        triage_output = await provider.triage_incident(state["context"])
        return {
            "triage_output": triage_output,
            "trace": _trace(
                node="analyze_incident",
                message="Generated triage recommendation from stored incident context.",
                metadata={"priority": triage_output.priority.value},
            ),
        }

    def human_gate(state: IncidentTriageState) -> dict[str, Any]:
        triage_output = state["triage_output"]
        request = state["request"]
        if not request.require_human_review and not triage_output.requires_human_review:
            return {
                "trace": _trace(
                    node="human_gate",
                    message="Skipped human review because the request and recommendation do not require it.",
                )
            }

        prompt = HumanReviewPrompt(
            review_kind="incident_triage",
            title="Incident triage approval",
            prompt="Confirm whether this triage summary should be accepted or escalated.",
            options=["approve", "reject", "approve_with_note"],
            context_excerpt={
                "summary": triage_output.summary,
                "priority": triage_output.priority.value,
                "recommended_actions": triage_output.recommended_actions,
            },
        )
        decision = HumanReviewDecision.model_validate(interrupt(prompt.model_dump(mode="json")))
        return {
            "human_decision": decision,
            "trace": _trace(
                node="human_gate",
                message="Received human triage review decision.",
                metadata={"approved": decision.approved, "reviewer": decision.reviewer},
            ),
        }

    def finalize(state: IncidentTriageState) -> dict[str, Any]:
        triage_output = state["triage_output"]
        decision = state.get("human_decision")
        final_output = triage_output

        if decision is not None:
            if not decision.approved:
                recommended_actions = [*triage_output.recommended_actions, "escalate_manual_triage"]
                final_output = triage_output.model_copy(
                    update={
                        "summary": f"{triage_output.summary} Human reviewer requested manual follow-up.",
                        "recommended_actions": recommended_actions,
                        "operator_brief": f"Manual intervention requested by {decision.reviewer or 'operator'}.",
                        "priority": IncidentPriority.CRITICAL if triage_output.priority == IncidentPriority.HIGH else triage_output.priority,
                    }
                )
            elif decision.note:
                final_output = triage_output.model_copy(
                    update={
                        "operator_brief": f"{triage_output.operator_brief} Reviewer note: {decision.note}",
                    }
                )

        return {
            "output": final_output,
            "trace": _trace(
                node="finalize",
                message="Finalized incident triage output.",
                metadata={"priority": final_output.priority.value},
            ),
        }

    graph.add_node("analyze_incident", analyze_incident)
    graph.add_node("human_gate", human_gate)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "analyze_incident")
    graph.add_edge("analyze_incident", "human_gate")
    graph.add_edge("human_gate", "finalize")
    graph.add_edge("finalize", END)
    return graph


def build_violation_review_graph(provider: WorkflowReasoningProvider):
    graph = StateGraph(ViolationReviewState)

    async def analyze_review(state: ViolationReviewState) -> dict[str, Any]:
        recommendation = await provider.review_violation(state["context"])
        return {
            "recommendation": recommendation,
            "trace": _trace(
                node="analyze_review",
                message="Generated a violation review recommendation from stored evidence and metadata.",
                metadata={"disposition": recommendation.disposition.value},
            ),
        }

    def approval_gate(state: ViolationReviewState) -> dict[str, Any]:
        request = state["request"]
        recommendation = state["recommendation"]

        if not request.require_human_approval:
            return {
                "trace": _trace(
                    node="approval_gate",
                    message="Skipped human approval because the request does not require it.",
                )
            }

        prompt = HumanReviewPrompt(
            review_kind="violation_review",
            title="Violation review approval",
            prompt="Approve, reject, or override the recommended violation disposition.",
            options=["approve", "reject", "override"],
            context_excerpt={
                "summary": recommendation.summary,
                "disposition": recommendation.disposition.value,
                "confidence": recommendation.confidence,
            },
        )
        decision = HumanReviewDecision.model_validate(interrupt(prompt.model_dump(mode="json")))
        return {
            "human_decision": decision,
            "trace": _trace(
                node="approval_gate",
                message="Captured human review decision for the violation workflow.",
                metadata={"approved": decision.approved, "reviewer": decision.reviewer},
            ),
        }

    def finalize(state: ViolationReviewState) -> dict[str, Any]:
        recommendation = state["recommendation"]
        decision = state.get("human_decision")
        final_output = recommendation

        if decision is not None and not decision.approved:
            override_disposition = decision.overrides.get("disposition")
            disposition = (
                ReviewDisposition(override_disposition)
                if isinstance(override_disposition, str)
                else ReviewDisposition.ESCALATE_SUPERVISOR
            )
            final_output = recommendation.model_copy(
                update={
                    "disposition": disposition,
                    "summary": f"{recommendation.summary} Human reviewer overrode the recommendation.",
                    "suggested_actions": [*recommendation.suggested_actions, "document_override_reason"],
                }
            )
        elif decision is not None and decision.note:
            final_output = recommendation.model_copy(
                update={
                    "summary": f"{recommendation.summary} Reviewer note: {decision.note}",
                }
            )

        return {
            "output": final_output,
            "trace": _trace(
                node="finalize",
                message="Finalized violation review output.",
                metadata={"disposition": final_output.disposition.value},
            ),
        }

    graph.add_node("analyze_review", analyze_review)
    graph.add_node("approval_gate", approval_gate)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "analyze_review")
    graph.add_edge("analyze_review", "approval_gate")
    graph.add_edge("approval_gate", "finalize")
    graph.add_edge("finalize", END)
    return graph


def build_multimodal_review_graph(provider: WorkflowReasoningProvider):
    graph = StateGraph(MultimodalReviewState)

    def prepare_grounding(state: MultimodalReviewState) -> dict[str, Any]:
        grounding = build_multimodal_review_grounding(state["context"])
        return {
            "grounding": grounding,
            "trace": _trace(
                node="prepare_grounding",
                message="Prepared a grounded multimodal review packet from stored metadata, evidence manifests, and attached media references.",
                metadata={
                    "metadata_references": grounding.metadata_reference_count,
                    "image_references": grounding.image_reference_count,
                    "clip_references": grounding.clip_reference_count,
                    "manifest_references": grounding.manifest_reference_count,
                    "prior_review_history": grounding.prior_review_count,
                },
            ),
        }

    async def compose_review(state: MultimodalReviewState) -> dict[str, Any]:
        output = await provider.review_multimodal(
            context=state["context"],
            grounding=state["grounding"],
        )
        return {
            "output": output,
            "trace": _trace(
                node="compose_review",
                message="Generated advisory multimodal review guidance from stored review context.",
                metadata={
                    "image_references": len(output.image_references),
                    "clip_references": len(output.clip_references),
                    "has_escalation_suggestion": output.escalation_suggestion is not None,
                },
            ),
        }

    graph.add_node("prepare_grounding", prepare_grounding)
    graph.add_node("compose_review", compose_review)
    graph.add_edge(START, "prepare_grounding")
    graph.add_edge("prepare_grounding", "compose_review")
    graph.add_edge("compose_review", END)
    return graph


def build_daily_summary_graph(provider: WorkflowReasoningProvider):
    graph = StateGraph(DailySummaryState)

    async def generate_summary(state: DailySummaryState) -> dict[str, Any]:
        summary_output = await provider.summarize_day(state["context"])
        return {
            "summary_output": summary_output,
            "trace": _trace(
                node="generate_summary",
                message="Generated daily report summary from stored counts and review context.",
                metadata={"total_violations": summary_output.total_violations},
            ),
        }

    def approval_gate(state: DailySummaryState) -> dict[str, Any]:
        request = state["request"]
        if not request.require_human_approval:
            return {
                "trace": _trace(
                    node="approval_gate",
                    message="Skipped daily summary approval gate.",
                )
            }

        summary_output = state["summary_output"]
        prompt = HumanReviewPrompt(
            review_kind="daily_summary",
            title="Daily summary publication check",
            prompt="Approve this daily summary for operator circulation.",
            options=["approve", "reject", "approve_with_note"],
            context_excerpt={
                "headline": summary_output.headline,
                "total_violations": summary_output.total_violations,
                "total_open_violations": summary_output.total_open_violations,
            },
        )
        decision = HumanReviewDecision.model_validate(interrupt(prompt.model_dump(mode="json")))
        return {
            "human_decision": decision,
            "trace": _trace(
                node="approval_gate",
                message="Captured human approval for the daily summary.",
                metadata={"approved": decision.approved, "reviewer": decision.reviewer},
            ),
        }

    def finalize(state: DailySummaryState) -> dict[str, Any]:
        summary_output = state["summary_output"]
        decision = state.get("human_decision")
        final_output = summary_output

        if decision is not None and not decision.approved:
            final_output = summary_output.model_copy(
                update={
                    "narrative": f"{summary_output.narrative} Publication held for manual revision.",
                    "markdown": _append_markdown_note(
                        summary_output.markdown,
                        heading="Publication Status",
                        note="Publication held for manual revision.",
                    ),
                    "recommended_follow_ups": [*summary_output.recommended_follow_ups, "revise_daily_summary_before_distribution"],
                }
            )
        elif decision is not None and decision.note:
            final_output = summary_output.model_copy(
                update={
                    "narrative": f"{summary_output.narrative} Reviewer note: {decision.note}",
                    "markdown": _append_markdown_note(
                        summary_output.markdown,
                        heading="Reviewer Note",
                        note=decision.note,
                    ),
                }
            )

        return {
            "output": final_output,
            "trace": _trace(
                node="finalize",
                message="Finalized daily summary output.",
                metadata={"total_violations": final_output.total_violations},
            ),
        }

    graph.add_node("generate_summary", generate_summary)
    graph.add_node("approval_gate", approval_gate)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "generate_summary")
    graph.add_edge("generate_summary", "approval_gate")
    graph.add_edge("approval_gate", "finalize")
    graph.add_edge("finalize", END)
    return graph


def build_operator_assist_graph(
    provider: WorkflowReasoningProvider,
    repository: WorkflowRepository,
):
    """Build the operator-assist graph.

    Boundaries:
    - deterministic query planning first
    - structured repository retrieval second
    - grounded answer synthesis third
    - never used in the live CV frame-processing path
    """

    graph = StateGraph(OperatorAssistState)

    def plan_query(state: OperatorAssistState) -> dict[str, Any]:
        plan = plan_operator_assist_request(state["request"])
        return {
            "plan": plan,
            "trace": _trace(
                node="plan_query",
                message="Mapped the natural-language request to a deterministic retrieval plan.",
                metadata={"intent": plan.intent.value, "rationale": plan.rationale},
            ),
        }

    async def retrieve_grounding(state: OperatorAssistState) -> dict[str, Any]:
        grounding = await repository.build_operator_assist_grounding(state["request"], state["plan"])
        return {
            "grounding": grounding,
            "trace": _trace(
                node="retrieve_grounding",
                message="Loaded structured stored data for operator assist.",
                metadata={
                    "camera_matches": len(grounding.camera_matches),
                    "violation_hits": len(grounding.violation_hits),
                    "incident_summaries": len(grounding.incident_summaries),
                },
            ),
        }

    async def compose_answer(state: OperatorAssistState) -> dict[str, Any]:
        output = await provider.assist_operator(plan=state["plan"], grounding=state["grounding"])
        request = state["request"]
        if request.require_human_review and not output.requires_human_review:
            output = output.model_copy(
                update={
                    "requires_human_review": True,
                    "escalation_reason": output.escalation_reason or "Caller explicitly requested human review.",
                },
            )
        return {
            "output": output,
            "trace": _trace(
                node="compose_answer",
                message="Composed a grounded operator-assist response from structured retrieval results.",
                metadata={
                    "intent": output.intent.value,
                    "grounded": output.grounded,
                    "matched_record_count": output.matched_record_count,
                    "requires_human_review": output.requires_human_review,
                },
            ),
        }

    graph.add_node("plan_query", plan_query)
    graph.add_node("retrieve_grounding", retrieve_grounding)
    graph.add_node("compose_answer", compose_answer)
    graph.add_edge(START, "plan_query")
    graph.add_edge("plan_query", "retrieve_grounding")
    graph.add_edge("retrieve_grounding", "compose_answer")
    graph.add_edge("compose_answer", END)
    return graph


def build_weekly_summary_graph(provider: WorkflowReasoningProvider):
    graph = StateGraph(WeeklySummaryState)

    async def generate_summary(state: WeeklySummaryState) -> dict[str, Any]:
        summary_output = await provider.summarize_week(state["context"])
        return {
            "summary_output": summary_output,
            "trace": _trace(
                node="generate_summary",
                message="Generated weekly summary from stored counts, review backlog, watchlist, and health context.",
                metadata={"total_violations": summary_output.total_violations},
            ),
        }

    def approval_gate(state: WeeklySummaryState) -> dict[str, Any]:
        request = state["request"]
        if not request.require_human_approval:
            return {
                "trace": _trace(
                    node="approval_gate",
                    message="Skipped weekly summary approval gate.",
                )
            }

        summary_output = state["summary_output"]
        prompt = HumanReviewPrompt(
            review_kind="weekly_summary",
            title="Weekly summary publication check",
            prompt="Approve this weekly summary for distribution.",
            options=["approve", "reject", "approve_with_note"],
            context_excerpt={
                "headline": summary_output.headline,
                "total_violations": summary_output.total_violations,
                "total_open_violations": summary_output.total_open_violations,
            },
        )
        decision = HumanReviewDecision.model_validate(interrupt(prompt.model_dump(mode="json")))
        return {
            "human_decision": decision,
            "trace": _trace(
                node="approval_gate",
                message="Captured human approval for the weekly summary.",
                metadata={"approved": decision.approved, "reviewer": decision.reviewer},
            ),
        }

    def finalize(state: WeeklySummaryState) -> dict[str, Any]:
        summary_output = state["summary_output"]
        decision = state.get("human_decision")
        final_output = summary_output

        if decision is not None and not decision.approved:
            final_output = summary_output.model_copy(
                update={
                    "narrative": f"{summary_output.narrative} Publication held for manual revision.",
                    "markdown": _append_markdown_note(
                        summary_output.markdown,
                        heading="Publication Status",
                        note="Publication held for manual revision.",
                    ),
                    "recommended_follow_ups": [*summary_output.recommended_follow_ups, "revise_weekly_summary_before_distribution"],
                }
            )
        elif decision is not None and decision.note:
            final_output = summary_output.model_copy(
                update={
                    "narrative": f"{summary_output.narrative} Reviewer note: {decision.note}",
                    "markdown": _append_markdown_note(
                        summary_output.markdown,
                        heading="Reviewer Note",
                        note=decision.note,
                    ),
                }
            )

        return {
            "output": final_output,
            "trace": _trace(
                node="finalize",
                message="Finalized weekly summary output.",
                metadata={"total_violations": final_output.total_violations},
            ),
        }

    graph.add_node("generate_summary", generate_summary)
    graph.add_node("approval_gate", approval_gate)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "generate_summary")
    graph.add_edge("generate_summary", "approval_gate")
    graph.add_edge("approval_gate", "finalize")
    graph.add_edge("finalize", END)
    return graph


def build_hotspot_report_graph(provider: WorkflowReasoningProvider):
    graph = StateGraph(HotspotReportState)

    async def generate_report(state: HotspotReportState) -> dict[str, Any]:
        report_output = await provider.build_hotspot_report(state["context"])
        return {
            "report_output": report_output,
            "trace": _trace(
                node="generate_report",
                message="Generated hotspot report from stored violation density data.",
                metadata={"hotspot_count": len(report_output.hotspots)},
            ),
        }

    def approval_gate(state: HotspotReportState) -> dict[str, Any]:
        request = state["request"]
        if not request.require_human_approval:
            return {
                "trace": _trace(
                    node="approval_gate",
                    message="Skipped hotspot report approval gate.",
                )
            }

        report_output = state["report_output"]
        prompt = HumanReviewPrompt(
            review_kind="hotspot_report",
            title="Hotspot report publication check",
            prompt="Approve this hotspot report for distribution.",
            options=["approve", "reject", "approve_with_note"],
            context_excerpt={
                "headline": report_output.headline,
                "total_violations_in_window": report_output.total_violations_in_window,
                "hotspot_count": len(report_output.hotspots),
            },
        )
        decision = HumanReviewDecision.model_validate(interrupt(prompt.model_dump(mode="json")))
        return {
            "human_decision": decision,
            "trace": _trace(
                node="approval_gate",
                message="Captured human approval for the hotspot report.",
                metadata={"approved": decision.approved, "reviewer": decision.reviewer},
            ),
        }

    def finalize(state: HotspotReportState) -> dict[str, Any]:
        report_output = state["report_output"]
        decision = state.get("human_decision")
        final_output = report_output

        if decision is not None and not decision.approved:
            final_output = report_output.model_copy(
                update={
                    "narrative": f"{report_output.narrative} Publication held for manual revision.",
                    "markdown": _append_markdown_note(
                        report_output.markdown,
                        heading="Publication Status",
                        note="Publication held for manual revision.",
                    ),
                    "recommended_follow_ups": [*report_output.recommended_follow_ups, "revise_hotspot_report_before_distribution"],
                }
            )
        elif decision is not None and decision.note:
            final_output = report_output.model_copy(
                update={
                    "narrative": f"{report_output.narrative} Reviewer note: {decision.note}",
                    "markdown": _append_markdown_note(
                        report_output.markdown,
                        heading="Reviewer Note",
                        note=decision.note,
                    ),
                }
            )

        return {
            "output": final_output,
            "trace": _trace(
                node="finalize",
                message="Finalized hotspot report output.",
                metadata={"hotspot_count": len(final_output.hotspots)},
            ),
        }

    graph.add_node("generate_report", generate_report)
    graph.add_node("approval_gate", approval_gate)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "generate_report")
    graph.add_edge("generate_report", "approval_gate")
    graph.add_edge("approval_gate", "finalize")
    graph.add_edge("finalize", END)
    return graph
