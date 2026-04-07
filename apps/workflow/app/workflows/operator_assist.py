"""Deterministic planning helpers for operator-assist workflow requests.

The operator-assist graph must route natural-language requests into
structured, auditable retrieval plans before any response synthesis occurs.
This module intentionally uses deterministic parsing and defaults so the
workflow stays grounded in stored platform data.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

from apps.api.app.db.enums import (
    DetectionEventStatus,
    DetectionEventType,
    PlateReadStatus,
    ViolationStatus,
    ViolationType,
    ZoneType,
)
from apps.workflow.app.workflows.schemas import (
    OperatorAssistIntent,
    OperatorAssistPlan,
    OperatorAssistRequest,
)
from services.ocr.normalizer import normalize_plate_text

_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)

_CAMERA_HINT_BOUNDARY = (
    r"(?=\s+in\s+the\s+last|\s+over\s+the\s+last|\s+last\s+\d+\s+(?:hours?|days?)|"
    r"\s+past\s+\d+\s+(?:hours?|days?)|\s+last\s+night|\s+this\s+morning|"
    r"\s+today|\s+with\s+|\s+where\s+|$)"
)

_CAMERA_HINT_PATTERNS = (
    re.compile(rf"\bfrom\s+(.+?){_CAMERA_HINT_BOUNDARY}"),
    re.compile(rf"\bat\s+(.+?){_CAMERA_HINT_BOUNDARY}"),
    re.compile(rf"\bnear\s+(.+?){_CAMERA_HINT_BOUNDARY}"),
)

_VIOLATION_ALIASES: tuple[tuple[str, ViolationType], ...] = (
    ("pedestrian-on-red", ViolationType.PEDESTRIAN_CONFLICT),
    ("pedestrian on red", ViolationType.PEDESTRIAN_CONFLICT),
    ("pedestrian conflict", ViolationType.PEDESTRIAN_CONFLICT),
    ("red-light", ViolationType.RED_LIGHT),
    ("red light", ViolationType.RED_LIGHT),
    ("stop-line", ViolationType.STOP_LINE),
    ("stop line", ViolationType.STOP_LINE),
    ("wrong-way", ViolationType.WRONG_WAY),
    ("wrong way", ViolationType.WRONG_WAY),
    ("illegal turn", ViolationType.ILLEGAL_TURN),
    ("speeding", ViolationType.SPEEDING),
    ("illegal parking", ViolationType.ILLEGAL_PARKING),
    ("no stopping", ViolationType.NO_STOPPING),
    ("bus stop violation", ViolationType.BUS_STOP_VIOLATION),
    ("bus stop occupation", ViolationType.BUS_STOP_VIOLATION),
    ("stalled vehicle", ViolationType.STALLED_VEHICLE),
)

_EVENT_TYPE_ALIASES: tuple[tuple[str, DetectionEventType], ...] = (
    ("line-crossing", DetectionEventType.LINE_CROSSING),
    ("line crossing", DetectionEventType.LINE_CROSSING),
    ("zone entry", DetectionEventType.ZONE_ENTRY),
    ("zone-entry", DetectionEventType.ZONE_ENTRY),
    ("zone exit", DetectionEventType.ZONE_EXIT),
    ("zone-exit", DetectionEventType.ZONE_EXIT),
    ("light state", DetectionEventType.LIGHT_STATE),
    ("signal state", DetectionEventType.LIGHT_STATE),
    ("detection", DetectionEventType.DETECTION),
)

_OBJECT_CLASS_ALIASES: tuple[tuple[str, str], ...] = (
    ("pedestrians", "pedestrian"),
    ("pedestrian", "pedestrian"),
    ("people", "person"),
    ("person", "person"),
    ("trucks", "truck"),
    ("truck", "truck"),
    ("buses", "bus"),
    ("bus", "bus"),
    ("cars", "car"),
    ("car", "car"),
    ("motorcycles", "motorcycle"),
    ("motorcycle", "motorcycle"),
)

_ZONE_TYPE_ALIASES: tuple[tuple[str, ZoneType], ...] = (
    ("restricted zone", ZoneType.RESTRICTED),
    ("restricted area", ZoneType.RESTRICTED),
    ("stop line", ZoneType.STOP_LINE),
    ("crosswalk", ZoneType.CROSSWALK),
    ("lane", ZoneType.LANE),
)

_VIOLATION_STATUS_ALIASES: tuple[tuple[str, ViolationStatus], ...] = (
    ("under review", ViolationStatus.UNDER_REVIEW),
    ("confirmed", ViolationStatus.CONFIRMED),
    ("dismissed", ViolationStatus.DISMISSED),
    ("open", ViolationStatus.OPEN),
)

_PLATE_STATUS_ALIASES: tuple[tuple[str, PlateReadStatus], ...] = (
    ("manual review", PlateReadStatus.MANUAL_REVIEW),
    ("matched", PlateReadStatus.MATCHED),
    ("rejected", PlateReadStatus.REJECTED),
    ("observed", PlateReadStatus.OBSERVED),
)

_EVENT_STATUS_ALIASES: tuple[tuple[str, DetectionEventStatus], ...] = (
    ("enriched", DetectionEventStatus.ENRICHED),
    ("suppressed", DetectionEventStatus.SUPPRESSED),
    ("new", DetectionEventStatus.NEW),
)

_PLATE_SIMILAR_PATTERN = re.compile(
    r"\b(?:similar to|like|partial(?:\s+plate)?|plate\s+reads?\s+similar to)\s+([A-Za-z0-9][A-Za-z0-9\-\s]{1,15}?)(?=\s+in\b|\s+from\b|\s+at\b|\s+near\b|\s+with\b|$)",
    re.IGNORECASE,
)
_PLATE_EXACT_PATTERN = re.compile(
    r"\bplate(?:\s+reads?)?(?:\s+for)?\s+([A-Za-z0-9][A-Za-z0-9\-\s]{1,15}?)(?=\s+in\b|\s+from\b|\s+at\b|\s+near\b|\s+with\b|$)",
    re.IGNORECASE,
)


def plan_operator_assist_request(
    request: OperatorAssistRequest,
    *,
    now: datetime | None = None,
) -> OperatorAssistPlan:
    """Translate a natural-language request into a typed retrieval plan."""
    now = now or datetime.now(timezone.utc)
    normalized_query = " ".join(request.query.strip().lower().split())
    rationale: list[str] = []

    explicit_violation_event_id = request.violation_event_id or _extract_uuid(request.query)
    if explicit_violation_event_id is not None:
        rationale.append("Using an explicit violation_event_id as the explanation anchor.")

    intent = _detect_intent(normalized_query)
    rationale.append(f"Mapped the operator request to intent {intent.value!r}.")

    violation_type = _detect_violation_type(normalized_query)
    violation_types = _detect_violation_types(normalized_query, violation_type=violation_type)
    if violation_type is not None:
        rationale.append(f"Matched violation type filter {violation_type.value!r} from the query text.")
    elif violation_types:
        rationale.append(
            "Mapped stop-related language to stored violation types "
            + ", ".join(item.value for item in violation_types)
            + "."
        )

    event_type = _detect_event_type(normalized_query)
    if event_type is not None:
        rationale.append(f"Matched event type filter {event_type.value!r} from the query text.")

    object_class = _detect_object_class(normalized_query)
    if object_class is not None:
        rationale.append(f"Matched object class filter {object_class!r} from the query text.")

    zone_type = _detect_zone_type(normalized_query)
    if zone_type is not None:
        rationale.append(f"Matched zone type filter {zone_type.value!r} from the query text.")

    plate_text, partial_plate = _extract_plate_text(request.query)
    if plate_text is not None:
        match_mode = "partial" if partial_plate else "exact"
        rationale.append(f"Detected {match_mode} plate-text filter {plate_text!r}.")

    event_status = _detect_event_status(normalized_query) if intent == OperatorAssistIntent.SEARCH_EVENTS else None
    violation_status = _detect_violation_status(normalized_query) if intent == OperatorAssistIntent.SEARCH_VIOLATIONS else None
    plate_status = _detect_plate_status(normalized_query) if intent == OperatorAssistIntent.SEARCH_PLATES else None
    if event_status is not None:
        rationale.append(f"Matched event status filter {event_status.value!r} from the query text.")
    if violation_status is not None:
        rationale.append(f"Matched violation status filter {violation_status.value!r} from the query text.")
    if plate_status is not None:
        rationale.append(f"Matched plate status filter {plate_status.value!r} from the query text.")

    camera_hint = None
    if request.camera_id is not None:
        rationale.append("Using the camera_id supplied by the caller as the camera scope.")
    else:
        camera_hint = _extract_camera_hint(normalized_query)
        if camera_hint is not None:
            rationale.append(f"Detected camera/location hint {camera_hint!r}.")
        elif "this junction" in normalized_query or "this camera" in normalized_query:
            rationale.append("The query references a local camera scope, but no camera_id was supplied.")

    start_at, end_at, time_note = _extract_time_range(normalized_query, now=now)
    if start_at is not None and end_at is not None:
        rationale.append(f"Detected explicit time window from {start_at.isoformat()} to {end_at.isoformat()}.")
        if time_note is not None:
            rationale.append(time_note)
    elif intent in {
        OperatorAssistIntent.SEARCH_EVENTS,
        OperatorAssistIntent.SEARCH_PLATES,
        OperatorAssistIntent.SEARCH_VIOLATIONS,
    }:
        start_at = now - timedelta(hours=24)
        end_at = now
        rationale.append("No explicit time window found; defaulted the search to the last 24 hours.")
    elif intent == OperatorAssistIntent.SUMMARIZE_REPEATED_INCIDENTS:
        start_at = now - timedelta(days=7)
        end_at = now
        rationale.append("No explicit time window found; defaulted the repeated-incident summary to the last 7 days.")

    if intent == OperatorAssistIntent.EXPLAIN_VIOLATION and explicit_violation_event_id is None:
        rationale.append("Explanation queries require a specific stored violation reference.")

    return OperatorAssistPlan(
        intent=intent,
        raw_query=request.query,
        normalized_query=normalized_query,
        camera_hint=camera_hint,
        start_at=start_at,
        end_at=end_at,
        event_type=event_type,
        event_status=event_status,
        violation_type=violation_type,
        violation_types=violation_types,
        violation_status=violation_status,
        plate_status=plate_status,
        object_class=object_class,
        zone_type=zone_type,
        plate_text=plate_text,
        partial_plate=partial_plate,
        explicit_violation_event_id=explicit_violation_event_id,
        max_results=request.max_results,
        rationale=rationale,
    )


def _detect_intent(normalized_query: str) -> OperatorAssistIntent:
    explain_triggers = ("why", "explain", "what caused", "what triggered")
    explain_anchors = ("alert", "violation", "fired", "event")
    if any(trigger in normalized_query for trigger in explain_triggers) and any(
        anchor in normalized_query for anchor in explain_anchors
    ):
        return OperatorAssistIntent.EXPLAIN_VIOLATION
    if any(token in normalized_query for token in ("summarize repeated incidents", "repeated incidents", "summary of repeated incidents")):
        return OperatorAssistIntent.SUMMARIZE_REPEATED_INCIDENTS
    if _looks_like_plate_search(normalized_query):
        return OperatorAssistIntent.SEARCH_PLATES
    if _looks_like_violation_search(normalized_query):
        return OperatorAssistIntent.SEARCH_VIOLATIONS
    if _looks_like_event_search(normalized_query):
        return OperatorAssistIntent.SEARCH_EVENTS
    return OperatorAssistIntent.UNKNOWN


def _looks_like_plate_search(normalized_query: str) -> bool:
    return any(token in normalized_query for token in ("plate read", "plate reads", "plates", "anpr", "similar to"))


def _looks_like_violation_search(normalized_query: str) -> bool:
    if "violation" in normalized_query or _detect_violation_type(normalized_query) is not None:
        return True
    if _detect_violation_types(normalized_query, violation_type=None):
        return True
    return any(token in normalized_query for token in ("open", "dismissed", "confirmed", "under review"))


def _looks_like_event_search(normalized_query: str) -> bool:
    if " event" in normalized_query or normalized_query.startswith("event ") or "events" in normalized_query:
        return True
    return _detect_event_type(normalized_query) is not None


def _detect_violation_type(normalized_query: str) -> ViolationType | None:
    for alias, violation_type in _VIOLATION_ALIASES:
        if alias in normalized_query:
            return violation_type
    return None


def _detect_violation_types(normalized_query: str, *, violation_type: ViolationType | None) -> list[ViolationType]:
    if violation_type is not None:
        return [violation_type]
    if "bus stop" in normalized_query:
        return [ViolationType.BUS_STOP_VIOLATION]
    if "stalled" in normalized_query:
        return [ViolationType.STALLED_VEHICLE]
    if "parking" in normalized_query:
        return [ViolationType.ILLEGAL_PARKING]
    if any(token in normalized_query for token in ("stopped", "stationary")):
        return [ViolationType.NO_STOPPING, ViolationType.STALLED_VEHICLE, ViolationType.ILLEGAL_PARKING]
    return []


def _detect_event_type(normalized_query: str) -> DetectionEventType | None:
    for alias, event_type in _EVENT_TYPE_ALIASES:
        if alias in normalized_query:
            return event_type
    return None


def _detect_object_class(normalized_query: str) -> str | None:
    for alias, object_class in _OBJECT_CLASS_ALIASES:
        if re.search(rf"\b{re.escape(alias)}\b", normalized_query):
            return object_class
    return None


def _detect_zone_type(normalized_query: str) -> ZoneType | None:
    for alias, zone_type in _ZONE_TYPE_ALIASES:
        if alias in normalized_query:
            return zone_type
    return None


def _detect_violation_status(normalized_query: str) -> ViolationStatus | None:
    for alias, status in _VIOLATION_STATUS_ALIASES:
        if alias in normalized_query:
            return status
    return None


def _detect_plate_status(normalized_query: str) -> PlateReadStatus | None:
    for alias, status in _PLATE_STATUS_ALIASES:
        if alias in normalized_query:
            return status
    return None


def _detect_event_status(normalized_query: str) -> DetectionEventStatus | None:
    for alias, status in _EVENT_STATUS_ALIASES:
        if alias in normalized_query:
            return status
    return None


def _extract_uuid(raw_query: str) -> uuid.UUID | None:
    match = _UUID_RE.search(raw_query)
    if match is None:
        return None
    return uuid.UUID(match.group(0))


_LEADING_ARTICLES = re.compile(r"^(?:the|a|an)\s+", re.IGNORECASE)


def _extract_camera_hint(normalized_query: str) -> str | None:
    for pattern in _CAMERA_HINT_PATTERNS:
        match = pattern.search(normalized_query)
        if match is None:
            continue
        candidate = match.group(1).strip(" .,?!")
        if candidate in {"this junction", "this camera"}:
            return None
        candidate = _LEADING_ARTICLES.sub("", candidate).strip()
        if candidate:
            return candidate
    return None


def _extract_plate_text(raw_query: str) -> tuple[str | None, bool]:
    for pattern, partial in ((_PLATE_SIMILAR_PATTERN, True), (_PLATE_EXACT_PATTERN, False)):
        match = pattern.search(raw_query)
        if match is None:
            continue
        candidate = normalize_plate_text(match.group(1))
        if candidate:
            return candidate, partial
    return None, False


def _extract_time_range(normalized_query: str, *, now: datetime) -> tuple[datetime | None, datetime | None, str | None]:
    if "today" in normalized_query:
        start_at = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start_at, now, None

    if "this morning" in normalized_query:
        start_at = now.replace(hour=6, minute=0, second=0, microsecond=0)
        end_at = min(now, now.replace(hour=12, minute=0, second=0, microsecond=0))
        if end_at < start_at:
            start_at = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_at = now
        return start_at, end_at, "Interpreted 'this morning' as 06:00-12:00 in the workflow clock timezone."

    if "last night" in normalized_query:
        today_six = now.replace(hour=6, minute=0, second=0, microsecond=0)
        if now < today_six:
            end_at = now
            start_at = (now - timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
        else:
            end_at = today_six
            start_at = (today_six - timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
        return start_at, end_at, "Interpreted 'last night' as 18:00-06:00 in the workflow clock timezone."

    hour_match = re.search(r"\b(?:last|past)\s+(\d+)\s+hours?\b", normalized_query)
    if hour_match is not None:
        hours = int(hour_match.group(1))
        return now - timedelta(hours=hours), now, None

    day_match = re.search(r"\b(?:last|past)\s+(\d+)\s+days?\b", normalized_query)
    if day_match is not None:
        days = int(day_match.group(1))
        return now - timedelta(days=days), now, None

    return None, None, None
