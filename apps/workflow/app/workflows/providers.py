"""Provider abstraction for workflow reasoning and summarisation."""

from __future__ import annotations

import abc
from collections import Counter
from datetime import datetime, timezone

from apps.workflow.app.workflows.multimodal_review import (
    build_multimodal_review_action,
    build_multimodal_review_audit_notes,
    build_multimodal_review_caveats,
    build_multimodal_review_escalation,
    build_multimodal_review_likely_cause,
    build_multimodal_review_summary,
)
from apps.workflow.app.workflows.schemas import (
    DailySummaryContext,
    DailySummaryOutput,
    HotspotGroupBy,
    HotspotReportContext,
    HotspotReportOutput,
    IncidentPriority,
    IncidentTriageContext,
    IncidentTriageOutput,
    MultimodalReviewContext,
    MultimodalReviewGrounding,
    MultimodalReviewOutput,
    OperatorAssistEventHit,
    OperatorAssistGrounding,
    OperatorAssistIntent,
    OperatorAssistOutput,
    OperatorAssistPlan,
    OperatorAssistPlateHit,
    ReviewDisposition,
    ViolationReviewContext,
    ViolationReviewOutput,
    WeeklySummaryContext,
    WeeklySummaryOutput,
)


def _humanize_label(value: str) -> str:
    return value.replace("_", " ")


def _top_count_lines(values: dict[str, int], *, limit: int = 5) -> list[str]:
    if not values:
        return ["No counts were recorded."]
    return [
        f"{_humanize_label(label)}: {count}"
        for label, count in sorted(values.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def _render_report_markdown(
    *,
    title: str,
    headline: str,
    narrative: str,
    sections: list[tuple[str, list[str]]],
) -> str:
    lines = [f"# {title}", "", f"**Headline:** {headline}", "", narrative]
    for heading, bullets in sections:
        lines.extend(["", f"## {heading}"])
        lines.extend(f"- {bullet}" for bullet in (bullets or ["None recorded for this section."]))
    return "\n".join(lines)


def _current_state_scope_note() -> str:
    return (
        "Open-state sections such as review backlog, open watchlist alerts, and camera health "
        "reflect current system state at report generation time, not a historical point-in-time snapshot."
    )


class WorkflowReasoningProvider(abc.ABC):
    """Abstract reasoning backend for cold-path workflows."""

    @abc.abstractmethod
    async def triage_incident(self, context: IncidentTriageContext) -> IncidentTriageOutput:
        """Return a typed incident triage recommendation."""

    @abc.abstractmethod
    async def review_violation(self, context: ViolationReviewContext) -> ViolationReviewOutput:
        """Return a typed review recommendation for a stored violation."""

    @abc.abstractmethod
    async def review_multimodal(
        self,
        *,
        context: MultimodalReviewContext,
        grounding: MultimodalReviewGrounding,
    ) -> MultimodalReviewOutput:
        """Return grounded operator-copilot guidance for a stored violation review."""

    @abc.abstractmethod
    async def summarize_day(self, context: DailySummaryContext) -> DailySummaryOutput:
        """Return a typed daily operations summary."""

    @abc.abstractmethod
    async def assist_operator(
        self,
        *,
        plan: OperatorAssistPlan,
        grounding: OperatorAssistGrounding,
    ) -> OperatorAssistOutput:
        """Return a typed grounded answer for an operator-assist request."""

    @abc.abstractmethod
    async def summarize_week(self, context: WeeklySummaryContext) -> WeeklySummaryOutput:
        """Return a typed weekly operations summary."""

    @abc.abstractmethod
    async def build_hotspot_report(self, context: HotspotReportContext) -> HotspotReportOutput:
        """Return a typed hotspot report."""


class HeuristicWorkflowProvider(WorkflowReasoningProvider):
    """Deterministic local-development provider.

    This backend intentionally avoids network model calls so the service is
    runnable on a local machine with no credentials. The provider remains
    abstract, so a future LLM-backed implementation can slot in later.
    """

    async def triage_incident(self, context: IncidentTriageContext) -> IncidentTriageOutput:
        violation = context.violation_event
        detection = context.detection_event
        evidence_gaps = [item.label for item in context.evidence if not item.available]

        if violation is not None:
            priority = {
                "critical": IncidentPriority.CRITICAL,
                "high": IncidentPriority.HIGH,
                "medium": IncidentPriority.MEDIUM,
                "low": IncidentPriority.LOW,
            }[violation.severity.value]
            summary = violation.summary or (
                f"{violation.violation_type.value.replace('_', ' ')} event at {context.camera.location_name}."
            )
        else:
            assert detection is not None
            priority = IncidentPriority.HIGH if detection.confidence >= 0.9 else IncidentPriority.MEDIUM
            summary = (
                f"Stored {detection.event_type.value.replace('_', ' ')} event for"
                f" {detection.object_class} at {context.camera.location_name}."
            )

        if detection is not None and detection.confidence < 0.65:
            evidence_gaps.append("low_detection_confidence")

        recommended_actions = ["open_event_feed", "review_evidence_clip"]
        if priority in {IncidentPriority.HIGH, IncidentPriority.CRITICAL}:
            recommended_actions.append("notify_shift_supervisor")
        if context.plate_read is not None:
            recommended_actions.append("check_plate_history")
        if evidence_gaps:
            recommended_actions.append("request_additional_evidence")

        rationale = [
            f"Camera status is {context.camera.status.value}.",
            f"Evidence references available: {sum(1 for item in context.evidence if item.available)} of {len(context.evidence)}.",
        ]
        if violation is not None:
            rationale.append(f"Violation severity recorded as {violation.severity.value}.")
        if detection is not None:
            rationale.append(f"Detection confidence is {detection.confidence:.2f}.")

        requires_human_review = bool(evidence_gaps) or priority in {
            IncidentPriority.HIGH,
            IncidentPriority.CRITICAL,
        }

        operator_brief = (
            f"{summary} Follow-up: {', '.join(recommended_actions[:3])}."
        )

        return IncidentTriageOutput(
            priority=priority,
            summary=summary,
            rationale=rationale,
            recommended_actions=recommended_actions,
            evidence_gaps=evidence_gaps,
            operator_brief=operator_brief,
            requires_human_review=requires_human_review,
            escalation_target="shift_supervisor" if priority in {IncidentPriority.HIGH, IncidentPriority.CRITICAL} else None,
        )

    async def review_violation(self, context: ViolationReviewContext) -> ViolationReviewOutput:
        violation = context.violation_event
        detection = context.detection_event
        available_evidence = sum(1 for item in context.evidence if item.available)

        if available_evidence == 0:
            disposition = ReviewDisposition.NEED_MORE_EVIDENCE
            confidence = 0.35
            rationale = ["No persisted image, clip, or crop evidence is attached to the violation context."]
        elif detection is not None and detection.confidence < 0.6:
            disposition = ReviewDisposition.DISMISS_FALSE_POSITIVE
            confidence = 0.41
            rationale = [f"Detection confidence is only {detection.confidence:.2f}."]
        elif violation.severity.value in {"critical", "high"}:
            disposition = ReviewDisposition.CONFIRM_VIOLATION
            confidence = 0.84
            rationale = [
                f"Stored severity is {violation.severity.value}.",
                f"{available_evidence} persisted evidence reference(s) are available.",
            ]
        else:
            disposition = ReviewDisposition.ESCALATE_SUPERVISOR
            confidence = 0.58
            rationale = ["The stored evidence is mixed and warrants senior operator review."]

        suggested_actions = ["inspect_evidence", "review_rule_metadata"]
        if context.plate_read is not None:
            suggested_actions.append("check_plate_read_consistency")
        if disposition == ReviewDisposition.NEED_MORE_EVIDENCE:
            suggested_actions.append("pull_neighboring_clip_window")
        if disposition == ReviewDisposition.ESCALATE_SUPERVISOR:
            suggested_actions.append("escalate_to_supervisor")

        summary = (
            f"Recommend {disposition.value.replace('_', ' ')} for"
            f" {violation.violation_type.value.replace('_', ' ')} at {context.camera.location_name}."
        )

        return ViolationReviewOutput(
            disposition=disposition,
            summary=summary,
            rationale=rationale,
            suggested_actions=suggested_actions,
            confidence=confidence,
            requires_human_approval=True,
        )

    async def review_multimodal(
        self,
        *,
        context: MultimodalReviewContext,
        grounding: MultimodalReviewGrounding,
    ) -> MultimodalReviewOutput:
        return MultimodalReviewOutput(
            review_summary=build_multimodal_review_summary(context, grounding),
            likely_cause=build_multimodal_review_likely_cause(context),
            confidence_caveats=build_multimodal_review_caveats(context, grounding),
            recommended_operator_action=build_multimodal_review_action(context, grounding),
            escalation_suggestion=build_multimodal_review_escalation(context, grounding),
            metadata_references=context.metadata_references,
            image_references=context.image_references,
            clip_references=context.clip_references,
            manifest_references=context.manifest_references,
            prior_review_history=context.prior_review_history,
            audit_notes=build_multimodal_review_audit_notes(context, grounding),
        )

    async def summarize_day(self, context: DailySummaryContext) -> DailySummaryOutput:
        generated_at = datetime.now(timezone.utc)
        sorted_locations = sorted(
            context.cameras,
            key=lambda item: (item.violation_count, item.open_violation_count, item.detection_count),
            reverse=True,
        )
        busiest = sorted_locations[:3]
        busiest_labels = [f"{item.location_name} ({item.violation_count} violations)" for item in busiest]
        backlog = context.review_backlog

        data_gaps: list[str] = []
        if not context.cameras:
            data_gaps.append("No camera data was available for this reporting window.")
        if not context.watchlist.data_available:
            data_gaps.append("Watchlist data was not available during context retrieval.")
        scope_notes = [_current_state_scope_note()]

        recommended_follow_ups: list[str] = []
        if backlog.open_violations > 0 or backlog.under_review_violations > 0:
            recommended_follow_ups.append(
                f"Clear the review backlog: {backlog.open_violations} open, {backlog.under_review_violations} under review."
            )
        if context.watchlist.open_alerts > 0:
            recommended_follow_ups.append(f"Resolve {context.watchlist.open_alerts} open watchlist alert(s).")
        if context.camera_health_concerns:
            concern_names = ", ".join(item.camera_name for item in context.camera_health_concerns[:3])
            recommended_follow_ups.append(f"Investigate camera health concerns at {concern_names}.")
        if busiest:
            recommended_follow_ups.append(f"Prioritise operator attention on {busiest[0].location_name}.")
        if not recommended_follow_ups:
            recommended_follow_ups.append("No urgent follow-up actions identified for this window.")

        narrative_parts = [
            f"Processed {context.total_detections} detections and {context.total_violations} violations"
            f" for {context.report_date.isoformat()}."
        ]
        if busiest_labels:
            narrative_parts.append(f"Highest activity locations: {', '.join(busiest_labels)}.")
        if backlog.open_violations > 0 or backlog.under_review_violations > 0:
            narrative_parts.append(
                f"Review backlog: {backlog.open_violations} open, {backlog.under_review_violations} under review."
            )
        if context.watchlist.total_alerts > 0:
            narrative_parts.append(
                f"Watchlist: {context.watchlist.total_alerts} alert(s), {context.watchlist.open_alerts} open."
            )
        if context.camera_health_concerns:
            narrative_parts.append(
                f"Camera health concerns: {len(context.camera_health_concerns)} camera(s) flagged."
            )
        narrative = " ".join(narrative_parts)

        headline = (
            f"{context.total_violations} violations across {len(context.cameras)} camera scope"
            f" on {context.report_date.isoformat()}"
        )

        output = DailySummaryOutput(
            report_date=context.report_date,
            generated_at=generated_at,
            headline=headline,
            narrative=narrative,
            total_detections=context.total_detections,
            total_violations=context.total_violations,
            total_open_violations=context.total_open_violations,
            top_violation_types=dict(Counter(context.top_violation_types)),
            location_summaries=context.cameras,
            review_backlog=context.review_backlog,
            watchlist=context.watchlist,
            camera_health_concerns=context.camera_health_concerns,
            recommended_follow_ups=recommended_follow_ups,
            scope_notes=scope_notes,
            data_gaps=data_gaps,
        )
        return output.model_copy(
            update={
                "markdown": _render_report_markdown(
                    title=f"Daily Summary - {output.report_date.isoformat()}",
                    headline=output.headline,
                    narrative=output.narrative,
                    sections=[
                        (
                            "Report Metadata",
                            [
                                f"Generated at: {output.generated_at.isoformat()}",
                                *output.scope_notes,
                            ],
                        ),
                        (
                            "Key Totals",
                            [
                                f"Detections: {output.total_detections}",
                                f"Violations: {output.total_violations}",
                                f"Open violations: {output.total_open_violations}",
                            ],
                        ),
                        ("Top Violation Categories", _top_count_lines(output.top_violation_types)),
                        (
                            "Top Cameras and Junctions",
                            [
                                f"{item.location_name}: {item.violation_count} violations, {item.open_violation_count} open"
                                for item in output.location_summaries[:5]
                            ],
                        ),
                        (
                            "Review Backlog",
                            [
                                f"Open: {output.review_backlog.open_violations}",
                                f"Under review: {output.review_backlog.under_review_violations}",
                                (
                                    f"Average review turnaround: {output.review_backlog.avg_review_hours} hours"
                                    if output.review_backlog.avg_review_hours is not None
                                    else "Average review turnaround: unavailable"
                                ),
                            ],
                        ),
                        (
                            "Watchlist",
                            [
                                f"Total alerts: {output.watchlist.total_alerts}",
                                f"Open alerts: {output.watchlist.open_alerts}",
                                *_top_count_lines(output.watchlist.top_reasons, limit=3),
                            ],
                        ),
                        (
                            "Camera Health",
                            [
                                f"{item.camera_name}: {item.concern}"
                                + (f" {item.detail}" if item.detail else "")
                                for item in output.camera_health_concerns
                            ],
                        ),
                        ("Recommended Follow-ups", output.recommended_follow_ups),
                        ("Scope Notes", output.scope_notes),
                        ("Data Gaps", output.data_gaps),
                    ],
                )
            }
        )

    async def summarize_week(self, context: WeeklySummaryContext) -> WeeklySummaryOutput:
        generated_at = datetime.now(timezone.utc)
        sorted_locations = sorted(
            context.daily_breakdowns,
            key=lambda item: (item.violation_count, item.open_violation_count),
            reverse=True,
        )
        busiest = sorted_locations[:3]
        busiest_labels = [f"{item.location_name} ({item.violation_count} violations)" for item in busiest]

        data_gaps: list[str] = []
        if not context.daily_breakdowns:
            data_gaps.append("No camera data was available for this reporting window.")
        if not context.watchlist.data_available:
            data_gaps.append("Watchlist data was not available during context retrieval.")
        scope_notes = [_current_state_scope_note()]

        recommended: list[str] = []
        backlog = context.review_backlog
        if backlog.open_violations > 0:
            recommended.append(f"Clear the review backlog: {backlog.open_violations} open, {backlog.under_review_violations} under review.")
        if context.camera_health_concerns:
            concern_names = ", ".join(c.camera_name for c in context.camera_health_concerns[:3])
            recommended.append(f"Investigate camera health concerns at {concern_names}.")
        if context.watchlist.open_alerts > 0:
            recommended.append(f"Resolve {context.watchlist.open_alerts} open watchlist alert(s).")
        if busiest:
            recommended.append(f"Prioritise operator attention on {busiest[0].location_name}.")
        if not recommended:
            recommended.append("No urgent follow-up actions identified for this week.")

        headline = (
            f"{context.total_violations} violations across {len(context.daily_breakdowns)} cameras"
            f" for week ending {context.week_ending.isoformat()}"
        )
        narrative_parts = [
            f"Weekly window: {context.week_start.isoformat()} to {context.week_ending.isoformat()}.",
            f"Processed {context.total_detections} detections and {context.total_violations} violations.",
        ]
        if busiest_labels:
            narrative_parts.append(f"Highest activity: {', '.join(busiest_labels)}.")
        if backlog.open_violations > 0:
            narrative_parts.append(
                f"Review backlog: {backlog.open_violations} open, {backlog.under_review_violations} under review."
            )
            if backlog.avg_review_hours is not None:
                narrative_parts.append(f"Average review turnaround: {backlog.avg_review_hours}h.")
        if context.watchlist.total_alerts > 0:
            narrative_parts.append(
                f"Watchlist: {context.watchlist.total_alerts} alert(s), {context.watchlist.open_alerts} open."
            )
        if context.camera_health_concerns:
            narrative_parts.append(
                f"Camera health concerns: {len(context.camera_health_concerns)} camera(s) flagged."
            )

        output = WeeklySummaryOutput(
            week_ending=context.week_ending,
            week_start=context.week_start,
            generated_at=generated_at,
            headline=headline,
            narrative=" ".join(narrative_parts),
            total_detections=context.total_detections,
            total_violations=context.total_violations,
            total_open_violations=context.total_open_violations,
            top_violation_types=dict(Counter(context.top_violation_types)),
            location_summaries=context.daily_breakdowns,
            review_backlog=context.review_backlog,
            watchlist=context.watchlist,
            camera_health_concerns=context.camera_health_concerns,
            recommended_follow_ups=recommended,
            scope_notes=scope_notes,
            data_gaps=data_gaps,
        )
        return output.model_copy(
            update={
                "markdown": _render_report_markdown(
                    title=f"Weekly Summary - Week Ending {output.week_ending.isoformat()}",
                    headline=output.headline,
                    narrative=output.narrative,
                    sections=[
                        (
                            "Report Metadata",
                            [
                                f"Generated at: {output.generated_at.isoformat()}",
                                *output.scope_notes,
                            ],
                        ),
                        (
                            "Key Totals",
                            [
                                f"Detections: {output.total_detections}",
                                f"Violations: {output.total_violations}",
                                f"Open violations: {output.total_open_violations}",
                            ],
                        ),
                        ("Top Violation Categories", _top_count_lines(output.top_violation_types)),
                        (
                            "Top Cameras and Junctions",
                            [
                                f"{item.location_name}: {item.violation_count} violations, {item.open_violation_count} open"
                                for item in output.location_summaries[:5]
                            ],
                        ),
                        (
                            "Review Backlog",
                            [
                                f"Open: {output.review_backlog.open_violations}",
                                f"Under review: {output.review_backlog.under_review_violations}",
                                (
                                    f"Average review turnaround: {output.review_backlog.avg_review_hours} hours"
                                    if output.review_backlog.avg_review_hours is not None
                                    else "Average review turnaround: unavailable"
                                ),
                            ],
                        ),
                        (
                            "Watchlist",
                            [
                                f"Total alerts: {output.watchlist.total_alerts}",
                                f"Open alerts: {output.watchlist.open_alerts}",
                                *_top_count_lines(output.watchlist.top_reasons, limit=3),
                            ],
                        ),
                        (
                            "Camera Health",
                            [
                                f"{item.camera_name}: {item.concern}"
                                + (f" {item.detail}" if item.detail else "")
                                for item in output.camera_health_concerns
                            ],
                        ),
                        ("Recommended Follow-ups", output.recommended_follow_ups),
                        ("Scope Notes", output.scope_notes),
                        ("Data Gaps", output.data_gaps),
                    ],
                )
            }
        )

    async def build_hotspot_report(self, context: HotspotReportContext) -> HotspotReportOutput:
        generated_at = datetime.now(timezone.utc)
        data_gaps: list[str] = []
        if not context.hotspots:
            data_gaps.append("No violation records found in the reporting window.")
        if context.group_by == HotspotGroupBy.ZONE and context.unassigned_violations > 0:
            data_gaps.append(
                f"{context.unassigned_violations} violation(s) in the window were missing zone assignments and were excluded from zone ranking."
            )

        recommended: list[str] = []
        hotspots = context.hotspots
        if hotspots:
            top = hotspots[0]
            recommended.append(
                f"Review {top.location_name}: {top.violation_count} violations, {top.open_count} open."
            )
            high_open = [h for h in hotspots if h.open_count > 0]
            if len(high_open) > 1:
                recommended.append(
                    f"{len(high_open)} hotspot(s) have unresolved open violations. Prioritise review."
                )
        if not recommended:
            recommended.append("No urgent follow-up actions identified for this window.")

        hotspot_lines: list[str] = []
        for idx, h in enumerate(hotspots[:5], 1):
            types_str = ", ".join(f"{k}: {v}" for k, v in sorted(h.top_violation_types.items(), key=lambda x: -x[1])[:3])
            hotspot_lines.append(f"#{idx} {h.location_name}: {h.violation_count} violations ({types_str})")

        scope_label = "zone" if context.group_by == HotspotGroupBy.ZONE else "camera"

        headline = (
            f"Top {len(hotspots)} {scope_label} hotspots over {context.lookback_days} days"
            f" ending {context.report_date.isoformat()}"
        )
        narrative_parts = [
            f"Lookback: {context.lookback_days} day(s) ending {context.report_date.isoformat()}.",
            (
                f"Total violations in window: {context.total_violations_in_window} across"
                f" {context.total_groups_with_violations} {scope_label}(s) and {context.total_cameras_with_violations} camera(s)."
            ),
        ]
        if hotspot_lines:
            narrative_parts.append("Hotspots: " + "; ".join(hotspot_lines) + ".")
        if context.group_by == HotspotGroupBy.ZONE and context.unassigned_violations > 0:
            narrative_parts.append(
                f"{context.unassigned_violations} violation(s) lacked a zone assignment and were excluded from zone ranking."
            )

        output = HotspotReportOutput(
            report_date=context.report_date,
            lookback_days=context.lookback_days,
            group_by=context.group_by,
            generated_at=generated_at,
            headline=headline,
            narrative=" ".join(narrative_parts),
            hotspots=hotspots,
            total_violations_in_window=context.total_violations_in_window,
            total_groups_with_violations=context.total_groups_with_violations,
            total_cameras_with_violations=context.total_cameras_with_violations,
            unassigned_violations=context.unassigned_violations,
            recommended_follow_ups=recommended,
            data_gaps=data_gaps,
        )
        return output.model_copy(
            update={
                "markdown": _render_report_markdown(
                    title=f"Hotspot Report - {output.group_by.value.title()} View - {output.report_date.isoformat()}",
                    headline=output.headline,
                    narrative=output.narrative,
                    sections=[
                        (
                            "Report Metadata",
                            [f"Generated at: {output.generated_at.isoformat()}"],
                        ),
                        (
                            "Key Totals",
                            [
                                f"Violations in window: {output.total_violations_in_window}",
                                f"{scope_label.title()}s with violations: {output.total_groups_with_violations}",
                                f"Cameras with violations: {output.total_cameras_with_violations}",
                                f"Unassigned violations: {output.unassigned_violations}",
                            ],
                        ),
                        (
                            "Top Hotspots",
                            [
                                (
                                    f"{item.location_name}: {item.violation_count} violations, {item.open_count} open"
                                    + (f", top zone: {item.zone_name}" if item.zone_name and output.group_by == HotspotGroupBy.CAMERA else "")
                                    + (f", zone type: {item.zone_type}" if item.zone_type else "")
                                )
                                for item in output.hotspots
                            ],
                        ),
                        ("Recommended Follow-ups", output.recommended_follow_ups),
                        ("Data Gaps", output.data_gaps),
                    ],
                )
            }
        )

    async def assist_operator(
        self,
        *,
        plan: OperatorAssistPlan,
        grounding: OperatorAssistGrounding,
    ) -> OperatorAssistOutput:
        filters = {
            "camera_hint": plan.camera_hint,
            "start_at": plan.start_at,
            "end_at": plan.end_at,
            "event_type": plan.event_type.value if plan.event_type is not None else None,
            "event_status": plan.event_status.value if plan.event_status is not None else None,
            "violation_type": plan.violation_type.value if plan.violation_type is not None else None,
            "violation_types": [item.value for item in plan.violation_types],
            "violation_status": plan.violation_status.value if plan.violation_status is not None else None,
            "plate_status": plan.plate_status.value if plan.plate_status is not None else None,
            "object_class": plan.object_class,
            "zone_type": plan.zone_type.value if plan.zone_type is not None else None,
            "plate_text": plan.plate_text,
            "partial_plate": plan.partial_plate,
            "violation_event_id": str(plan.explicit_violation_event_id) if plan.explicit_violation_event_id else None,
            "resolved_camera_ids": [str(camera.id) for camera in grounding.camera_matches],
            "resolved_camera_labels": [f"{camera.name} ({camera.camera_code})" for camera in grounding.camera_matches],
            "max_results": plan.max_results,
        }

        if plan.intent == OperatorAssistIntent.SEARCH_EVENTS:
            return self._search_events(plan=plan, grounding=grounding, filters=filters)
        if plan.intent == OperatorAssistIntent.SEARCH_PLATES:
            return self._search_plates(plan=plan, grounding=grounding, filters=filters)
        if plan.intent == OperatorAssistIntent.SEARCH_VIOLATIONS:
            return self._search_violations(plan=plan, grounding=grounding, filters=filters)
        if plan.intent == OperatorAssistIntent.EXPLAIN_VIOLATION:
            return self._explain_violation(plan=plan, grounding=grounding, filters=filters)
        if plan.intent == OperatorAssistIntent.SUMMARIZE_REPEATED_INCIDENTS:
            return self._summarize_repeated_incidents(plan=plan, grounding=grounding, filters=filters)

        return OperatorAssistOutput(
            intent=plan.intent,
            answer=(
                "I could not map this request to a supported grounded operator-assist workflow. "
                "Supported flows are stored event search, violation search, plate-read search, stored violation explanation, and repeated-incident summaries."
            ),
            grounded=False,
            filters_applied=filters,
            interpretation_notes=[*plan.rationale, *grounding.grounding_notes],
            references=grounding.references,
            supporting_evidence=grounding.supporting_evidence,
            next_steps=[
                "Rephrase the request as an event search, violation search, plate-read search, explanation, or repeated-incident summary.",
                "Provide a camera_id or violation_event_id from the UI when the request refers to 'this' item.",
            ],
            requires_human_review=True,
            escalation_reason="Unsupported or ungrounded operator-assist request.",
        )

    def _search_events(
        self,
        *,
        plan: OperatorAssistPlan,
        grounding: OperatorAssistGrounding,
        filters: dict[str, object | None],
    ) -> OperatorAssistOutput:
        if grounding.grounding_notes:
            return OperatorAssistOutput(
                intent=plan.intent,
                answer=" ".join(grounding.grounding_notes),
                grounded=False,
                matched_record_count=0,
                filters_applied=filters,
                interpretation_notes=[*plan.rationale, *grounding.grounding_notes],
                references=grounding.references,
                supporting_evidence=grounding.supporting_evidence,
                next_steps=["Narrow the camera scope or provide an exact camera selection from the UI."],
                requires_human_review=True,
                escalation_reason=grounding.grounding_notes[0],
            )

        hits = grounding.event_hits
        if not hits:
            event_label = plan.event_type.value.replace("_", " ") if plan.event_type is not None else "event"
            return OperatorAssistOutput(
                intent=plan.intent,
                answer=f"No stored {event_label} records matched the requested filters.",
                grounded=True,
                matched_record_count=0,
                filters_applied=filters,
                interpretation_notes=self._operator_assist_notes(plan=plan, grounding=grounding),
                references=grounding.references,
                supporting_evidence=grounding.supporting_evidence,
                next_steps=["Expand the time window or remove one filter and retry."],
            )

        labels = [self._event_hit_label(hit) for hit in hits[: min(3, len(hits))]]
        event_label = plan.event_type.value.replace("_", " ") if plan.event_type is not None else "event"
        object_label = f" for {plan.object_class}" if plan.object_class is not None else ""
        total_matches = grounding.total_matches or len(hits)
        preview_note = (
            f" Showing {len(hits)} most recent matches: {'; '.join(labels)}."
            if total_matches > len(hits)
            else f" Most recent matches: {'; '.join(labels)}."
        )
        return OperatorAssistOutput(
            intent=plan.intent,
            answer=(
                f"Found {total_matches} stored {event_label} record(s){object_label}."
                f"{preview_note}"
            ),
            grounded=True,
            matched_record_count=total_matches,
            filters_applied=filters,
            interpretation_notes=self._operator_assist_notes(plan=plan, grounding=grounding),
            references=grounding.references,
            supporting_evidence=grounding.supporting_evidence,
            next_steps=[
                "Open the referenced detection event(s) to inspect persisted metadata and evidence.",
                "Build or fetch the event evidence manifest if more visual context is needed.",
            ],
        )

    def _search_plates(
        self,
        *,
        plan: OperatorAssistPlan,
        grounding: OperatorAssistGrounding,
        filters: dict[str, object | None],
    ) -> OperatorAssistOutput:
        if grounding.grounding_notes:
            return OperatorAssistOutput(
                intent=plan.intent,
                answer=" ".join(grounding.grounding_notes),
                grounded=False,
                matched_record_count=0,
                filters_applied=filters,
                interpretation_notes=[*plan.rationale, *grounding.grounding_notes],
                references=grounding.references,
                supporting_evidence=grounding.supporting_evidence,
                next_steps=["Narrow the camera scope or provide an exact camera selection from the UI."],
                requires_human_review=True,
                escalation_reason=grounding.grounding_notes[0],
            )

        hits = grounding.plate_hits
        if not hits:
            query_label = f" matching {plan.plate_text}" if plan.plate_text is not None else ""
            return OperatorAssistOutput(
                intent=plan.intent,
                answer=f"No stored plate-read records matched the requested filters{query_label}.",
                grounded=True,
                matched_record_count=0,
                filters_applied=filters,
                interpretation_notes=self._operator_assist_notes(plan=plan, grounding=grounding),
                references=grounding.references,
                supporting_evidence=grounding.supporting_evidence,
                next_steps=["Expand the time window or relax the plate-text filter and retry."],
            )

        labels = [self._plate_hit_label(hit) for hit in hits[: min(3, len(hits))]]
        plate_mode = "partial" if plan.partial_plate else "exact"
        plate_text = f" {plate_mode} plate {plan.plate_text}" if plan.plate_text is not None else ""
        total_matches = grounding.total_matches or len(hits)
        preview_note = (
            f" Showing {len(hits)} most recent matches: {'; '.join(labels)}."
            if total_matches > len(hits)
            else f" Most recent matches: {'; '.join(labels)}."
        )
        return OperatorAssistOutput(
            intent=plan.intent,
            answer=(
                f"Found {total_matches} stored plate-read record(s){plate_text}."
                f"{preview_note}"
            ),
            grounded=True,
            matched_record_count=total_matches,
            filters_applied=filters,
            interpretation_notes=self._operator_assist_notes(plan=plan, grounding=grounding),
            references=grounding.references,
            supporting_evidence=grounding.supporting_evidence,
            next_steps=[
                "Open the referenced plate read(s) to inspect OCR confidence and linked source frames.",
                "Refine by camera scope or plate prefix if the result set is still too broad.",
            ],
        )

    def _search_violations(
        self,
        *,
        plan: OperatorAssistPlan,
        grounding: OperatorAssistGrounding,
        filters: dict[str, object | None],
    ) -> OperatorAssistOutput:
        if grounding.grounding_notes:
            return OperatorAssistOutput(
                intent=plan.intent,
                answer=" ".join(grounding.grounding_notes),
                grounded=False,
                matched_record_count=0,
                filters_applied=filters,
                interpretation_notes=[*plan.rationale, *grounding.grounding_notes],
                references=grounding.references,
                supporting_evidence=grounding.supporting_evidence,
                next_steps=["Narrow the camera scope or provide an exact camera selection from the UI."],
                requires_human_review=True,
                escalation_reason=grounding.grounding_notes[0],
            )

        hits = grounding.violation_hits
        if not hits:
            label = self._violation_search_label(plan)
            interpretation = self._violation_inference_note(plan)
            return OperatorAssistOutput(
                intent=plan.intent,
                answer=(
                    f"No stored {label} records matched the requested filters."
                    + (f" {interpretation}" if interpretation else "")
                ),
                grounded=True,
                matched_record_count=0,
                filters_applied=filters,
                interpretation_notes=self._operator_assist_notes(plan=plan, grounding=grounding),
                references=grounding.references,
                supporting_evidence=grounding.supporting_evidence,
                next_steps=["Expand the time window or remove one filter and retry."],
            )

        labels = [
            (
                f"{hit.violation_event.id} at {hit.violation_event.occurred_at.isoformat()} "
                f"({hit.violation_event.status.value}, {hit.camera.name})"
            )
            for hit in hits[: min(3, len(hits))]
        ]
        total_matches = grounding.total_matches or len(hits)
        violation_label = self._violation_search_label(plan)
        interpretation = self._violation_inference_note(plan)
        preview_note = (
            f" Showing {len(hits)} most recent matches: {'; '.join(labels)}."
            if total_matches > len(hits)
            else f" Most recent matches: {'; '.join(labels)}."
        )
        answer = f"Found {total_matches} stored {violation_label} record(s)."
        if interpretation:
            answer += f" {interpretation}"
        answer += preview_note
        return OperatorAssistOutput(
            intent=plan.intent,
            answer=answer,
            grounded=True,
            matched_record_count=total_matches,
            filters_applied=filters,
            interpretation_notes=self._operator_assist_notes(plan=plan, grounding=grounding),
            references=grounding.references,
            supporting_evidence=grounding.supporting_evidence,
            next_steps=[
                "Open the referenced violation event(s) to inspect evidence and rule metadata.",
                "Refine by status or narrower time window if the result set is still too broad.",
            ],
        )

    def _explain_violation(
        self,
        *,
        plan: OperatorAssistPlan,
        grounding: OperatorAssistGrounding,
        filters: dict[str, object | None],
    ) -> OperatorAssistOutput:
        if grounding.grounding_notes:
            return OperatorAssistOutput(
                intent=plan.intent,
                answer=" ".join(grounding.grounding_notes),
                grounded=False,
                matched_record_count=0,
                filters_applied=filters,
                interpretation_notes=[*plan.rationale, *grounding.grounding_notes],
                references=grounding.references,
                supporting_evidence=grounding.supporting_evidence,
                next_steps=["Provide the selected violation_event_id from the UI before asking for a why/explain answer."],
                requires_human_review=True,
                escalation_reason=grounding.grounding_notes[0],
            )

        hit = grounding.violation_hits[0] if grounding.violation_hits else None
        if hit is None:
            return OperatorAssistOutput(
                intent=plan.intent,
                answer="No stored violation record was available to explain why this alert fired.",
                grounded=False,
                matched_record_count=0,
                filters_applied=filters,
                interpretation_notes=[*plan.rationale, *grounding.grounding_notes],
                references=grounding.references,
                supporting_evidence=grounding.supporting_evidence,
                next_steps=["Confirm the alert still exists and pass its violation_event_id into the workflow."],
                requires_human_review=True,
                escalation_reason="Missing stored violation context.",
            )

        violation = hit.violation_event
        detection = hit.detection_event
        rationale_bits = [
            f"Stored violation type: {violation.violation_type.value}.",
            f"Stored severity: {violation.severity.value}.",
        ]
        if violation.summary:
            rationale_bits.append(f"Summary: {violation.summary}")
        if detection is not None:
            rationale_bits.append(
                f"Supporting detection {detection.id} recorded {detection.object_class} with confidence {detection.confidence:.2f}."
            )
        if violation.rule_metadata:
            metadata_preview = ", ".join(
                f"{key}={value}" for key, value in list(violation.rule_metadata.items())[:4]
            )
            rationale_bits.append(f"Rule metadata: {metadata_preview}.")

        evidence_available = [item.label for item in grounding.supporting_evidence if item.available]
        if evidence_available:
            rationale_bits.append(f"Available evidence: {', '.join(evidence_available)}.")

        return OperatorAssistOutput(
            intent=plan.intent,
            answer=" ".join(rationale_bits),
            grounded=True,
            matched_record_count=1,
            filters_applied=filters,
            interpretation_notes=self._operator_assist_notes(plan=plan, grounding=grounding),
            references=grounding.references,
            supporting_evidence=grounding.supporting_evidence,
            next_steps=[
                "Inspect the referenced clip or image to validate the stored rule outcome.",
                "Review the rule metadata and linked detection event if the operator needs a deeper audit trail.",
            ],
            requires_human_review=not bool(violation.rule_metadata or violation.summary),
            escalation_reason=(
                "Stored metadata is too sparse to fully explain the alert."
                if not bool(violation.rule_metadata or violation.summary)
                else None
            ),
        )

    def _summarize_repeated_incidents(
        self,
        *,
        plan: OperatorAssistPlan,
        grounding: OperatorAssistGrounding,
        filters: dict[str, object | None],
    ) -> OperatorAssistOutput:
        if grounding.grounding_notes:
            return OperatorAssistOutput(
                intent=plan.intent,
                answer=" ".join(grounding.grounding_notes),
                grounded=False,
                matched_record_count=0,
                filters_applied=filters,
                interpretation_notes=[*plan.rationale, *grounding.grounding_notes],
                references=grounding.references,
                next_steps=["Provide a single camera/junction scope before requesting a repeated-incident summary."],
                requires_human_review=True,
                escalation_reason=grounding.grounding_notes[0],
            )

        summaries = grounding.incident_summaries
        if not summaries:
            return OperatorAssistOutput(
                intent=plan.intent,
                answer="No repeated stored incidents matched the requested summary scope.",
                grounded=True,
                matched_record_count=0,
                filters_applied=filters,
                interpretation_notes=plan.rationale,
                references=grounding.references,
                next_steps=["Expand the summary window or confirm the correct junction scope."],
            )

        grouped_labels = [
            f"{item.violation_type.value.replace('_', ' ')}: {item.incident_count} total ({item.open_count} open)"
            for item in summaries[:3]
        ]
        camera_label = summaries[0].camera.location_name
        return OperatorAssistOutput(
            intent=plan.intent,
            answer=(
                f"At {camera_label}, repeated stored incidents were led by {'; '.join(grouped_labels)}. "
                f"This summary is grounded in {sum(item.incident_count for item in summaries)} stored violation record(s)."
            ),
            grounded=True,
            matched_record_count=sum(item.incident_count for item in summaries),
            filters_applied=filters,
            interpretation_notes=self._operator_assist_notes(plan=plan, grounding=grounding),
            references=grounding.references,
            next_steps=[
                "Review the top repeated violation type against zone configuration and signal linkage.",
                "Escalate to field operations if the same pattern persists across multiple shifts.",
            ],
        )

    @staticmethod
    def _operator_assist_notes(
        *,
        plan: OperatorAssistPlan,
        grounding: OperatorAssistGrounding,
    ) -> list[str]:
        notes = [*plan.rationale, *grounding.grounding_notes]
        if plan.camera_hint is None or not grounding.camera_matches:
            return notes
        if len(grounding.camera_matches) == 1:
            camera = grounding.camera_matches[0]
            notes.append(
                f"Resolved camera/location hint {plan.camera_hint!r} to stored camera {camera.name} ({camera.camera_code})."
            )
            return notes
        notes.append(
            f"Resolved camera/location hint {plan.camera_hint!r} to {len(grounding.camera_matches)} stored cameras and searched across all matches."
        )
        return notes

    @staticmethod
    def _violation_search_label(plan: OperatorAssistPlan) -> str:
        if plan.violation_type is not None:
            return plan.violation_type.value.replace("_", " ")
        if len(plan.violation_types) > 1:
            return "stop-related violation"
        return "violation"

    @staticmethod
    def _violation_inference_note(plan: OperatorAssistPlan) -> str | None:
        if plan.violation_type is not None or len(plan.violation_types) <= 1:
            return None
        inferred = ", ".join(_humanize_label(item.value) for item in plan.violation_types)
        return f"Interpreted stop-related language as stored {inferred} violations."

    @staticmethod
    def _event_hit_label(hit: OperatorAssistEventHit) -> str:
        zone_bits: list[str] = []
        if hit.zone_name is not None:
            zone_bits.append(hit.zone_name)
        if hit.zone_type is not None:
            zone_bits.append(hit.zone_type)
        zone_label = f", zone: {' / '.join(zone_bits)}" if zone_bits else ""
        event = hit.detection_event
        return (
            f"{event.id} at {event.occurred_at.isoformat()} "
            f"({event.event_type.value}, {event.object_class}, {hit.camera.name}{zone_label})"
        )

    @staticmethod
    def _plate_hit_label(hit: OperatorAssistPlateHit) -> str:
        plate = hit.plate_read
        return (
            f"{plate.id} {plate.normalized_plate_text} at {plate.occurred_at.isoformat()} "
            f"({plate.status.value}, {hit.camera.name})"
        )


def build_reasoning_provider(backend: str) -> WorkflowReasoningProvider:
    """Return the configured reasoning provider.

    The first implementation intentionally supports only the deterministic
    heuristic backend for local development. The service keeps the provider
    interface abstract so a model-backed implementation can be added later
    without changing graph logic.
    """

    normalized = backend.strip().lower()
    if normalized == "heuristic":
        return HeuristicWorkflowProvider()

    msg = f"Unsupported workflow provider backend {backend!r}. Supported backends: heuristic"
    raise ValueError(msg)
