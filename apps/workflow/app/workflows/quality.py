"""Quality checks for typed report outputs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from apps.workflow.app.workflows.schemas import (
    DailySummaryOutput,
    HotspotReportOutput,
    WeeklySummaryOutput,
)

ReportOutput = DailySummaryOutput | WeeklySummaryOutput | HotspotReportOutput


class WorkflowQualityCheck(BaseModel):
    name: str
    passed: bool
    severity: Literal["warning", "critical"] = "critical"
    detail: str | None = None


class WorkflowQualityReport(BaseModel):
    workflow: str
    passed: bool
    checks: list[WorkflowQualityCheck] = Field(default_factory=list)
    warning_count: int = 0
    critical_count: int = 0


def _has_heading(markdown: str, heading: str) -> bool:
    return f"## {heading}" in markdown


def evaluate_report_output(output: ReportOutput) -> WorkflowQualityReport:
    checks: list[WorkflowQualityCheck] = []

    def add_check(
        name: str,
        passed: bool,
        *,
        severity: Literal["warning", "critical"] = "critical",
        detail: str | None = None,
    ) -> None:
        checks.append(WorkflowQualityCheck(name=name, passed=passed, severity=severity, detail=detail))

    add_check("headline present", bool(output.headline.strip()))
    add_check("narrative present", bool(output.narrative.strip()))
    add_check("markdown present", bool(output.markdown.strip()))
    add_check("recommended follow-ups present", bool(output.recommended_follow_ups), severity="warning")

    required_headings = ["Key Totals", "Recommended Follow-ups"]
    if isinstance(output, (DailySummaryOutput, WeeklySummaryOutput)):
        required_headings.extend(["Top Violation Categories", "Top Cameras and Junctions", "Review Backlog"])
    if isinstance(output, WeeklySummaryOutput):
        required_headings.extend(["Watchlist", "Camera Health", "Scope Notes"])
    if isinstance(output, DailySummaryOutput):
        required_headings.extend(["Watchlist", "Camera Health", "Scope Notes"])
    if isinstance(output, HotspotReportOutput):
        required_headings.append("Top Hotspots")

    for heading in required_headings:
        add_check(
            f"markdown heading: {heading}",
            _has_heading(output.markdown, heading),
            detail=f"Expected '## {heading}' in markdown export.",
        )

    if isinstance(output, (DailySummaryOutput, WeeklySummaryOutput)):
        location_violation_total = sum(item.violation_count for item in output.location_summaries)
        add_check(
            "location totals align with report total",
            location_violation_total == output.total_violations,
            detail=(
                f"Location summaries total {location_violation_total} violations but report total is"
                f" {output.total_violations}."
            ),
        )
        violation_type_total = sum(output.top_violation_types.values())
        add_check(
            "violation type totals align with report total",
            violation_type_total == output.total_violations,
            detail=(
                f"Top violation categories sum to {violation_type_total} but report total is"
                f" {output.total_violations}."
            ),
        )
        add_check(
            "scope notes present",
            bool(output.scope_notes),
            severity="warning",
            detail="Daily and weekly reports should explain current-state snapshot sections.",
        )
        if output.location_summaries:
            top_location = max(output.location_summaries, key=lambda item: item.violation_count).location_name
            add_check(
                "top location surfaced in narrative or markdown",
                top_location in output.narrative or top_location in output.markdown,
                severity="warning",
                detail=f"Expected top location '{top_location}' to appear in the rendered report.",
            )
        if output.total_violations == 0 and not output.location_summaries:
            add_check(
                "empty report explains data gap",
                bool(output.data_gaps),
                severity="warning",
                detail="Zero-activity report should explain why the section is empty.",
            )

    if isinstance(output, HotspotReportOutput):
        hotspot_total = sum(item.violation_count for item in output.hotspots)
        add_check(
            "top hotspot total does not exceed full-window total",
            hotspot_total <= output.total_violations_in_window,
            detail=(
                f"Hotspot entries total {hotspot_total} violations but full-window total is"
                f" {output.total_violations_in_window}."
            ),
        )
        add_check(
            "reported group count covers returned hotspots",
            output.total_groups_with_violations >= len(output.hotspots),
            detail=(
                f"Returned {len(output.hotspots)} hotspot rows but total_groups_with_violations is"
                f" {output.total_groups_with_violations}."
            ),
        )
        if output.hotspots:
            top_hotspot = output.hotspots[0].location_name
            add_check(
                "top hotspot surfaced in narrative or markdown",
                top_hotspot in output.narrative or top_hotspot in output.markdown,
                severity="warning",
                detail=f"Expected top hotspot '{top_hotspot}' to appear in the rendered report.",
            )
        if output.total_violations_in_window == 0 and not output.hotspots:
            add_check(
                "empty hotspot report explains data gap",
                bool(output.data_gaps),
                severity="warning",
                detail="Empty hotspot report should explain why no hotspots were returned.",
            )
        if output.group_by.value == "zone" and output.unassigned_violations > 0:
            add_check(
                "zone report explains unassigned violations",
                any("zone" in item.lower() for item in output.data_gaps) or "zone" in output.narrative.lower(),
                severity="warning",
                detail="Zone-grouped reports should explain excluded violations without zone assignments.",
            )

    critical_count = sum(1 for item in checks if item.severity == "critical" and not item.passed)
    warning_count = sum(1 for item in checks if item.severity == "warning" and not item.passed)
    return WorkflowQualityReport(
        workflow=output.workflow,
        passed=critical_count == 0,
        checks=checks,
        warning_count=warning_count,
        critical_count=critical_count,
    )