"""Focused tests for the deterministic operator-assist planner."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import uuid

import pytest

from apps.api.app.db.enums import DetectionEventType, PlateReadStatus, ViolationStatus, ViolationType, ZoneType
from apps.workflow.app.workflows.operator_assist import plan_operator_assist_request
from apps.workflow.app.workflows.schemas import (
    OperatorAssistIntent,
    OperatorAssistRequest,
)

NOW = datetime(2026, 4, 5, 14, 0, tzinfo=timezone.utc)


# --- Intent detection ---


@pytest.mark.parametrize(
    "query, expected_intent",
    [
        ("show line crossing events near junction 4 this morning", OperatorAssistIntent.SEARCH_EVENTS),
        ("show plate reads similar to AB12 in the last 24 hours", OperatorAssistIntent.SEARCH_PLATES),
        ("show all red-light violations from main", OperatorAssistIntent.SEARCH_VIOLATIONS),
        ("list speeding violations last 2 hours", OperatorAssistIntent.SEARCH_VIOLATIONS),
        ("find wrong-way violations at downtown", OperatorAssistIntent.SEARCH_VIOLATIONS),
        ("display stop-line violations", OperatorAssistIntent.SEARCH_VIOLATIONS),
        ("show trucks stopped in restricted zone last night", OperatorAssistIntent.SEARCH_VIOLATIONS),
        ("why was this pedestrian-on-red alert fired", OperatorAssistIntent.EXPLAIN_VIOLATION),
        ("explain this violation", OperatorAssistIntent.EXPLAIN_VIOLATION),
        ("what caused this alert", OperatorAssistIntent.EXPLAIN_VIOLATION),
        ("what triggered this event", OperatorAssistIntent.EXPLAIN_VIOLATION),
        ("summarize repeated incidents at king fahd", OperatorAssistIntent.SUMMARIZE_REPEATED_INCIDENTS),
        ("hello how are you", OperatorAssistIntent.UNKNOWN),
    ],
)
def test_intent_detection(query: str, expected_intent: OperatorAssistIntent) -> None:
    plan = plan_operator_assist_request(OperatorAssistRequest(query=query), now=NOW)
    assert plan.intent == expected_intent, f"Query {query!r} expected {expected_intent}, got {plan.intent}"


# --- Violation type aliases ---


@pytest.mark.parametrize(
    "query, expected_type",
    [
        ("show red-light violations", ViolationType.RED_LIGHT),
        ("show red light violations", ViolationType.RED_LIGHT),
        ("show pedestrian-on-red violations", ViolationType.PEDESTRIAN_CONFLICT),
        ("show pedestrian on red violations", ViolationType.PEDESTRIAN_CONFLICT),
        ("show stop-line violations", ViolationType.STOP_LINE),
        ("show wrong-way violations", ViolationType.WRONG_WAY),
        ("find speeding violations", ViolationType.SPEEDING),
        ("list illegal turn violations", ViolationType.ILLEGAL_TURN),
        ("list illegal parking violations", ViolationType.ILLEGAL_PARKING),
        ("show all violations", None),
    ],
)
def test_violation_type_detection(query: str, expected_type: ViolationType | None) -> None:
    plan = plan_operator_assist_request(OperatorAssistRequest(query=query), now=NOW)
    assert plan.violation_type == expected_type


# --- Camera hint extraction and article stripping ---


@pytest.mark.parametrize(
    "query, expected_hint",
    [
        ("show violations from main st in the last 2 hours", "main st"),
        ("show violations from the main intersection in the last 2 hours", "main intersection"),
        ("show violations from a busy overpass in the last hour", "busy overpass"),
        ("show violations at king fahd in the last 3 hours", "king fahd"),
        ("show violations at the downtown junction in the last day", "downtown junction"),
        ("show line crossing events near junction 4 this morning", "junction 4"),
        ("summarize repeated incidents at this junction", None),
        ("show all violations last 2 hours", None),
    ],
)
def test_camera_hint_extraction(query: str, expected_hint: str | None) -> None:
    plan = plan_operator_assist_request(OperatorAssistRequest(query=query), now=NOW)
    assert plan.camera_hint == expected_hint


# --- Time range parsing ---


def test_explicit_hour_window() -> None:
    plan = plan_operator_assist_request(
        OperatorAssistRequest(query="show violations last 3 hours"), now=NOW
    )
    assert plan.start_at == NOW - timedelta(hours=3)
    assert plan.end_at == NOW


def test_explicit_day_window() -> None:
    plan = plan_operator_assist_request(
        OperatorAssistRequest(query="summarize repeated incidents last 14 days"), now=NOW
    )
    assert plan.start_at == NOW - timedelta(days=14)
    assert plan.end_at == NOW


def test_today_window() -> None:
    plan = plan_operator_assist_request(
        OperatorAssistRequest(query="show violations today"), now=NOW
    )
    expected_start = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
    assert plan.start_at == expected_start
    assert plan.end_at == NOW


def test_this_morning_window() -> None:
    plan = plan_operator_assist_request(
        OperatorAssistRequest(query="show line crossing events this morning"), now=NOW
    )
    assert plan.start_at == NOW.replace(hour=6, minute=0, second=0, microsecond=0)
    assert plan.end_at == NOW.replace(hour=12, minute=0, second=0, microsecond=0)
    assert any("this morning" in item.lower() for item in plan.rationale)


def test_last_night_window() -> None:
    plan = plan_operator_assist_request(
        OperatorAssistRequest(query="show trucks stopped in restricted zone last night"), now=NOW
    )
    assert plan.start_at == datetime(2026, 4, 4, 18, 0, tzinfo=timezone.utc)
    assert plan.end_at == datetime(2026, 4, 5, 6, 0, tzinfo=timezone.utc)
    assert any("last night" in item.lower() for item in plan.rationale)


def test_default_search_window_24h() -> None:
    plan = plan_operator_assist_request(
        OperatorAssistRequest(query="show all red-light violations"), now=NOW
    )
    assert plan.intent == OperatorAssistIntent.SEARCH_VIOLATIONS
    assert plan.start_at == NOW - timedelta(hours=24)
    assert plan.end_at == NOW


def test_default_plate_search_window_24h() -> None:
    plan = plan_operator_assist_request(
        OperatorAssistRequest(query="show plate reads similar to AB12"), now=NOW
    )
    assert plan.intent == OperatorAssistIntent.SEARCH_PLATES
    assert plan.start_at == NOW - timedelta(hours=24)
    assert plan.end_at == NOW


def test_default_summary_window_7d() -> None:
    plan = plan_operator_assist_request(
        OperatorAssistRequest(query="summarize repeated incidents at main"), now=NOW
    )
    assert plan.intent == OperatorAssistIntent.SUMMARIZE_REPEATED_INCIDENTS
    assert plan.start_at == NOW - timedelta(days=7)
    assert plan.end_at == NOW


# --- Explicit violation_event_id ---


def test_explicit_violation_event_id_from_request() -> None:
    vid = uuid.uuid4()
    plan = plan_operator_assist_request(
        OperatorAssistRequest(query="why was this alert fired", violation_event_id=vid), now=NOW
    )
    assert plan.explicit_violation_event_id == vid
    assert plan.intent == OperatorAssistIntent.EXPLAIN_VIOLATION


def test_uuid_extracted_from_query_text() -> None:
    vid = uuid.uuid4()
    plan = plan_operator_assist_request(
        OperatorAssistRequest(query=f"explain violation {vid}"), now=NOW
    )
    assert plan.explicit_violation_event_id == vid


def test_explain_without_violation_id_warns_in_rationale() -> None:
    plan = plan_operator_assist_request(
        OperatorAssistRequest(query="explain this violation"), now=NOW
    )
    assert plan.intent == OperatorAssistIntent.EXPLAIN_VIOLATION
    assert plan.explicit_violation_event_id is None
    assert any("stored violation reference" in r for r in plan.rationale)


# --- require_human_review propagation (tested at graph level in service tests) ---


def test_max_results_passed_through() -> None:
    plan = plan_operator_assist_request(
        OperatorAssistRequest(query="show red-light violations", max_results=25), now=NOW
    )
    assert plan.max_results == 25


def test_event_search_extracts_event_type_and_status() -> None:
    plan = plan_operator_assist_request(
        OperatorAssistRequest(query="show enriched line crossing events near junction 4 this morning"), now=NOW
    )
    assert plan.intent == OperatorAssistIntent.SEARCH_EVENTS
    assert plan.event_type == DetectionEventType.LINE_CROSSING
    assert plan.event_status is not None
    assert plan.event_status.value == "enriched"


def test_plate_search_extracts_partial_plate_and_status() -> None:
    plan = plan_operator_assist_request(
        OperatorAssistRequest(query="show matched plate reads similar to AB12 in the last 24 hours"), now=NOW
    )
    assert plan.intent == OperatorAssistIntent.SEARCH_PLATES
    assert plan.plate_text == "AB12"
    assert plan.partial_plate is True
    assert plan.plate_status == PlateReadStatus.MATCHED


def test_stop_related_violation_search_extracts_zone_object_and_status_filters() -> None:
    plan = plan_operator_assist_request(
        OperatorAssistRequest(query="show open trucks stopped in restricted zone last night"), now=NOW
    )
    assert plan.intent == OperatorAssistIntent.SEARCH_VIOLATIONS
    assert plan.object_class == "truck"
    assert plan.zone_type == ZoneType.RESTRICTED
    assert plan.violation_status == ViolationStatus.OPEN
    assert {item.value for item in plan.violation_types} == {"no_stopping", "stalled_vehicle", "illegal_parking"}
