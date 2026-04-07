from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest

from apps.workflow.app.workflows.providers import HeuristicWorkflowProvider
from apps.workflow.app.workflows.quality import evaluate_report_output
from apps.workflow.app.workflows.schemas import (
    CameraDailySummary,
    DailySummaryContext,
    DailySummaryOutput,
    HotspotEntry,
    HotspotGroupBy,
    HotspotReportContext,
    HotspotReportOutput,
    ReviewBacklog,
    WatchlistSection,
    WeeklySummaryContext,
)

NOW = datetime(2026, 4, 5, 12, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_daily_summary_quality_checks_pass_for_provider_output() -> None:
    provider = HeuristicWorkflowProvider()
    output = await provider.summarize_day(
        DailySummaryContext(
            report_date=date(2026, 4, 5),
            cameras=[
                CameraDailySummary(
                    camera_id=uuid.uuid4(),
                    camera_name="Main & 3rd Northbound",
                    location_name="Main St & 3rd Ave",
                    detection_count=12,
                    violation_count=4,
                    open_violation_count=1,
                    top_violation_types={"red_light": 3, "stop_line": 1},
                    last_incident_at=NOW,
                )
            ],
            total_detections=12,
            total_violations=4,
            total_open_violations=1,
            top_violation_types={"red_light": 3, "stop_line": 1},
            review_backlog=ReviewBacklog(open_violations=1, under_review_violations=0),
            watchlist=WatchlistSection(total_alerts=1, open_alerts=1, top_reasons={"wanted": 1}),
        )
    )

    report = evaluate_report_output(output)

    assert report.passed is True
    assert report.critical_count == 0
    assert report.warning_count == 0


def test_workflow_quality_flags_inconsistent_daily_totals() -> None:
    output = DailySummaryOutput(
        report_date=date(2026, 4, 5),
        generated_at=NOW,
        headline="5 violations across 1 camera scope on 2026-04-05",
        narrative="Processed 10 detections and 5 violations for 2026-04-05. Highest activity locations: Main St & 3rd Ave (2 violations).",
        markdown="\n".join(
            [
                "# Daily Summary - 2026-04-05",
                "",
                "## Report Metadata",
                "- Generated at: 2026-04-05T12:00:00+00:00",
                "## Key Totals",
                "- Detections: 10",
                "- Violations: 5",
                "## Top Violation Categories",
                "- red light: 5",
                "## Top Cameras and Junctions",
                "- Main St & 3rd Ave: 2 violations, 1 open",
                "## Review Backlog",
                "- Open: 1",
                "## Watchlist",
                "- Total alerts: 0",
                "## Camera Health",
                "- No issues",
                "## Recommended Follow-ups",
                "- Review open violations before handover.",
                "## Scope Notes",
                "- Open-state sections reflect current system state.",
            ]
        ),
        total_detections=10,
        total_violations=5,
        total_open_violations=1,
        top_violation_types={"red_light": 5},
        location_summaries=[
            CameraDailySummary(
                camera_id=uuid.uuid4(),
                camera_name="Main & 3rd Northbound",
                location_name="Main St & 3rd Ave",
                detection_count=10,
                violation_count=2,
                open_violation_count=1,
            )
        ],
        review_backlog=ReviewBacklog(open_violations=1, under_review_violations=0),
        watchlist=WatchlistSection(total_alerts=0, open_alerts=0),
        recommended_follow_ups=["Review open violations before handover."],
        scope_notes=["Open-state sections reflect current system state."],
    )

    report = evaluate_report_output(output)

    assert report.passed is False
    assert any(
        check.name == "location totals align with report total" and check.passed is False
        for check in report.checks
    )


# ── Weekly summary quality ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_weekly_summary_quality_checks_pass_for_provider_output() -> None:
    provider = HeuristicWorkflowProvider()
    output = await provider.summarize_week(
        WeeklySummaryContext(
            week_ending=date(2026, 4, 5),
            week_start=date(2026, 3, 30),
            daily_breakdowns=[
                CameraDailySummary(
                    camera_id=uuid.uuid4(),
                    camera_name="Main & 3rd Northbound",
                    location_name="Main St & 3rd Ave",
                    detection_count=80,
                    violation_count=20,
                    open_violation_count=3,
                    top_violation_types={"red_light": 15, "stop_line": 5},
                )
            ],
            total_detections=80,
            total_violations=20,
            total_open_violations=3,
            top_violation_types={"red_light": 15, "stop_line": 5},
            review_backlog=ReviewBacklog(open_violations=3, under_review_violations=1),
            watchlist=WatchlistSection(total_alerts=2, open_alerts=1, top_reasons={"stolen": 2}),
        )
    )

    report = evaluate_report_output(output)
    assert report.passed is True
    assert report.critical_count == 0


# ── Hotspot report quality ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_hotspot_report_quality_checks_pass_for_provider_output() -> None:
    provider = HeuristicWorkflowProvider()
    output = await provider.build_hotspot_report(
        HotspotReportContext(
            report_date=date(2026, 4, 5),
            lookback_days=7,
            top_n=3,
            group_by=HotspotGroupBy.CAMERA,
            hotspots=[
                HotspotEntry(
                    camera_id=uuid.uuid4(),
                    camera_name="King Fahd NB",
                    location_name="King Fahd & Tahlia",
                    violation_count=12,
                    open_count=2,
                    top_violation_types={"red_light": 10, "stop_line": 2},
                    last_violation_at=NOW,
                ),
            ],
            total_violations_in_window=30,
            total_groups_with_violations=5,
            total_cameras_with_violations=5,
        )
    )

    report = evaluate_report_output(output)
    assert report.passed is True
    assert report.critical_count == 0


def test_hotspot_report_flags_total_exceeding_window() -> None:
    output = HotspotReportOutput(
        report_date=date(2026, 4, 5),
        lookback_days=7,
        group_by=HotspotGroupBy.CAMERA,
        generated_at=NOW,
        headline="Top 1 camera hotspots over 7 days ending 2026-04-05",
        narrative="Lookback: 7 day(s) ending 2026-04-05. Total violations in window: 5.",
        markdown="\n".join([
            "# Hotspot Report",
            "",
            "## Key Totals",
            "- Violations in window: 5",
            "## Top Hotspots",
            "- King Fahd & Tahlia: 10 violations",
            "## Recommended Follow-ups",
            "- Review King Fahd & Tahlia.",
        ]),
        hotspots=[
            HotspotEntry(
                camera_id=uuid.uuid4(),
                camera_name="King Fahd NB",
                location_name="King Fahd & Tahlia",
                violation_count=10,
                open_count=0,
                top_violation_types={"red_light": 10},
            ),
        ],
        total_violations_in_window=5,  # intentionally less than hotspot total
        total_groups_with_violations=1,
        total_cameras_with_violations=1,
        recommended_follow_ups=["Review King Fahd & Tahlia."],
    )

    report = evaluate_report_output(output)
    assert report.passed is False
    assert any(
        check.name == "top hotspot total does not exceed full-window total" and check.passed is False
        for check in report.checks
    )
