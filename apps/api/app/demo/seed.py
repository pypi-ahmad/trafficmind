"""Seed a realistic synthetic demo dataset for local development and screenshots.

Usage:
    python -m apps.api.app.demo.seed --create-schema
    python -m apps.api.app.demo.seed --scenario city_center_baseline --report-path demo-seed-report.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from apps.api.app.core.config import get_settings
from apps.api.app.db.base import Base
from apps.api.app.db.enums import (
    CameraStatus,
    DetectionEventStatus,
    DetectionEventType,
    EvidenceSubjectKind,
    PlateReadStatus,
    SourceType,
    StreamKind,
    StreamStatus,
    ViolationSeverity,
    ViolationStatus,
    ViolationType,
    WorkflowStatus,
    WorkflowType,
    ZoneStatus,
    ZoneType,
)
from apps.api.app.db.models import (
    Camera,
    CameraStream,
    DetectionEvent,
    EvidenceManifest,
    PlateRead,
    ViolationEvent,
    WorkflowRun,
    Zone,
)
from services.health.assessor import HealthAssessor

SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"
_DEMO_TAG = "demo_seed"


@dataclass(slots=True)
class DemoSeedResult:
    scenario_name: str
    label: str
    description: str
    generated_at: datetime
    data_origin: str
    synthetic: bool
    counts: dict[str, int]
    health_dashboard_preview: dict[str, Any]
    walkthrough: dict[str, Any]
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_name": self.scenario_name,
            "label": self.label,
            "description": self.description,
            "generated_at": self.generated_at.isoformat(),
            "data_origin": self.data_origin,
            "synthetic": self.synthetic,
            "counts": dict(self.counts),
            "health_dashboard_preview": dict(self.health_dashboard_preview),
            "walkthrough": dict(self.walkthrough),
            "notes": list(self.notes),
        }


def list_demo_scenarios() -> list[dict[str, str]]:
    scenarios: list[dict[str, str]] = []
    for path in sorted(SCENARIOS_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        scenarios.append(
            {
                "scenario_name": payload["scenario_name"],
                "label": payload.get("label", payload["scenario_name"]),
                "description": payload.get("description", ""),
            }
        )
    return scenarios


def load_demo_scenario(scenario_name: str) -> dict[str, Any]:
    path = SCENARIOS_DIR / f"{scenario_name}.json"
    if not path.exists():
        available = ", ".join(item["scenario_name"] for item in list_demo_scenarios()) or "none"
        raise ValueError(f"Unknown demo scenario '{scenario_name}'. Available scenarios: {available}")
    return json.loads(path.read_text(encoding="utf-8"))


async def seed_demo_scenario(
    session: AsyncSession,
    *,
    scenario_name: str = "city_center_baseline",
    now: datetime | None = None,
) -> DemoSeedResult:
    resolved_now = now or datetime.now(timezone.utc)
    scenario = load_demo_scenario(scenario_name)

    await _delete_existing_demo_records(session, scenario)

    for camera_payload in scenario["cameras"]:
        session.add(_build_camera(camera_payload, scenario_name))
    for camera_payload in scenario["cameras"]:
        for stream_payload in camera_payload.get("streams", []):
            session.add(_build_stream(stream_payload, camera_payload["id"], scenario_name, resolved_now))
        for zone_payload in camera_payload.get("zones", []):
            session.add(_build_zone(zone_payload, camera_payload["id"], scenario_name))

    for event_payload in scenario.get("detection_events", []):
        session.add(_build_detection_event(event_payload, scenario_name, resolved_now))
    for plate_payload in scenario.get("plate_reads", []):
        session.add(_build_plate_read(plate_payload, scenario_name, resolved_now))
    for violation_payload in scenario.get("violations", []):
        session.add(_build_violation(violation_payload, scenario_name, resolved_now))
    for evidence_payload in scenario.get("evidence_manifests", []):
        session.add(_build_evidence_manifest(evidence_payload, scenario_name, resolved_now))
    for workflow_payload in scenario.get("workflows", []):
        session.add(_build_workflow(workflow_payload, scenario_name, resolved_now))

    await session.flush()

    cameras = await _load_seeded_cameras(session, scenario)
    health_dashboard_preview = _build_health_dashboard_preview(cameras, resolved_now)
    walkthrough = _build_walkthrough_targets(scenario)
    counts = {
        "cameras": len(scenario.get("cameras", [])),
        "streams": sum(len(camera.get("streams", [])) for camera in scenario.get("cameras", [])),
        "zones": sum(len(camera.get("zones", [])) for camera in scenario.get("cameras", [])),
        "events": len(scenario.get("detection_events", [])),
        "violations": len(scenario.get("violations", [])),
        "plate_reads": len(scenario.get("plate_reads", [])),
        "review_cases": len(scenario.get("violations", [])),
        "evidence_manifests": len(scenario.get("evidence_manifests", [])),
        "workflows": len(scenario.get("workflows", [])),
    }

    return DemoSeedResult(
        scenario_name=scenario["scenario_name"],
        label=scenario.get("label", scenario["scenario_name"]),
        description=scenario.get("description", ""),
        generated_at=resolved_now,
        data_origin=scenario.get("data_origin", _DEMO_TAG),
        synthetic=True,
        counts=counts,
        health_dashboard_preview=health_dashboard_preview,
        walkthrough=walkthrough,
        notes=[
            "This dataset is synthetic demo seed data and must not be described as real processed traffic output.",
            "Synthetic records are labeled with DEMO camera codes, TEST stream sources, and metadata tags under 'trafficmind_record_origin'.",
            "demo:// asset URIs are placeholders for screenshots and local walkthroughs; no bundled media files are shipped with this seed.",
        ],
    )


def _build_camera(payload: dict[str, Any], scenario_name: str) -> Camera:
    calibration_config = {
        "trafficmind_record_origin": _origin_tag(scenario_name, "camera"),
        "demo_mode": True,
    }
    return Camera(
        id=_uuid(payload["id"]),
        camera_code=payload["camera_code"],
        name=payload["name"],
        location_name=payload["location_name"],
        approach=payload.get("approach"),
        timezone=payload.get("timezone", "UTC"),
        status=CameraStatus(payload["status"]),
        latitude=payload.get("latitude"),
        longitude=payload.get("longitude"),
        notes=payload.get("notes"),
        calibration_config=calibration_config,
    )


def _build_stream(payload: dict[str, Any], camera_id: str, scenario_name: str, now: datetime) -> CameraStream:
    last_heartbeat_at = _resolve_relative_time(
        now,
        seconds=payload.get("last_heartbeat_seconds_ago"),
    )
    source_config = _merge_origin(
        payload.get("source_config", {}),
        scenario_name,
        record_type="stream",
    )
    return CameraStream(
        id=_uuid(payload["id"]),
        camera_id=_uuid(camera_id),
        name=payload["name"],
        stream_kind=StreamKind(payload["stream_kind"]),
        source_type=SourceType(payload["source_type"]),
        source_uri=payload["source_uri"],
        source_config=source_config,
        status=StreamStatus(payload["status"]),
        is_enabled=payload.get("is_enabled", True),
        resolution_width=payload.get("resolution_width"),
        resolution_height=payload.get("resolution_height"),
        fps_hint=payload.get("fps_hint"),
        last_heartbeat_at=last_heartbeat_at,
        last_error=payload.get("last_error"),
    )


def _build_zone(payload: dict[str, Any], camera_id: str, scenario_name: str) -> Zone:
    rules_config = _merge_origin(payload.get("rules_config", {}), scenario_name, record_type="zone")
    return Zone(
        id=_uuid(payload["id"]),
        camera_id=_uuid(camera_id),
        name=payload["name"],
        zone_type=ZoneType(payload["zone_type"]),
        status=ZoneStatus(payload["status"]),
        geometry=payload["geometry"],
        rules_config=rules_config,
    )


def _build_detection_event(payload: dict[str, Any], scenario_name: str, now: datetime) -> DetectionEvent:
    event_payload = _merge_origin(payload.get("event_payload", {}), scenario_name, record_type="detection_event")
    return DetectionEvent(
        id=_uuid(payload["id"]),
        camera_id=_uuid(payload["camera_id"]),
        stream_id=_uuid(payload["stream_id"]) if payload.get("stream_id") else None,
        zone_id=_uuid(payload["zone_id"]) if payload.get("zone_id") else None,
        event_type=DetectionEventType(payload["event_type"]),
        status=DetectionEventStatus(payload["status"]),
        occurred_at=_resolve_relative_time(now, minutes=payload.get("occurred_minutes_ago"), hours=payload.get("occurred_hours_ago")),
        frame_index=payload.get("frame_index"),
        track_id=payload.get("track_id"),
        object_class=payload["object_class"],
        confidence=payload["confidence"],
        bbox=payload["bbox"],
        event_payload=event_payload,
        image_uri=payload.get("image_uri"),
        video_uri=payload.get("video_uri"),
    )


def _build_plate_read(payload: dict[str, Any], scenario_name: str, now: datetime) -> PlateRead:
    ocr_metadata = _merge_origin(payload.get("ocr_metadata", {}), scenario_name, record_type="plate_read")
    return PlateRead(
        id=_uuid(payload["id"]),
        camera_id=_uuid(payload["camera_id"]),
        stream_id=_uuid(payload["stream_id"]) if payload.get("stream_id") else None,
        detection_event_id=_uuid(payload["detection_event_id"]) if payload.get("detection_event_id") else None,
        status=PlateReadStatus(payload["status"]),
        occurred_at=_resolve_relative_time(now, minutes=payload.get("occurred_minutes_ago"), hours=payload.get("occurred_hours_ago")),
        plate_text=payload["plate_text"],
        normalized_plate_text=payload["normalized_plate_text"],
        confidence=payload["confidence"],
        country_code=payload.get("country_code"),
        region_code=payload.get("region_code"),
        bbox=payload["bbox"],
        crop_image_uri=payload.get("crop_image_uri"),
        source_frame_uri=payload.get("source_frame_uri"),
        ocr_metadata=ocr_metadata,
    )


def _build_violation(payload: dict[str, Any], scenario_name: str, now: datetime) -> ViolationEvent:
    reviewed_at = _resolve_relative_time(now, minutes=payload.get("reviewed_minutes_ago"), hours=payload.get("reviewed_hours_ago"))
    rule_metadata = _merge_origin(payload.get("rule_metadata", {}), scenario_name, record_type="violation")
    return ViolationEvent(
        id=_uuid(payload["id"]),
        camera_id=_uuid(payload["camera_id"]),
        stream_id=_uuid(payload["stream_id"]) if payload.get("stream_id") else None,
        zone_id=_uuid(payload["zone_id"]) if payload.get("zone_id") else None,
        detection_event_id=_uuid(payload["detection_event_id"]) if payload.get("detection_event_id") else None,
        plate_read_id=_uuid(payload["plate_read_id"]) if payload.get("plate_read_id") else None,
        violation_type=ViolationType(payload["violation_type"]),
        severity=ViolationSeverity(payload["severity"]),
        status=ViolationStatus(payload["status"]),
        occurred_at=_resolve_relative_time(now, minutes=payload.get("occurred_minutes_ago"), hours=payload.get("occurred_hours_ago")),
        summary=payload.get("summary"),
        evidence_image_uri=payload.get("evidence_image_uri"),
        evidence_video_uri=payload.get("evidence_video_uri"),
        assigned_to=payload.get("assigned_to"),
        reviewed_by=payload.get("reviewed_by"),
        reviewed_at=reviewed_at,
        review_note=payload.get("review_note"),
        rule_metadata=rule_metadata,
    )


def _build_evidence_manifest(payload: dict[str, Any], scenario_name: str, now: datetime) -> EvidenceManifest:
    manifest_data = _merge_origin(payload.get("manifest_data", {}), scenario_name, record_type="evidence_manifest")
    return EvidenceManifest(
        id=_uuid(payload["id"]),
        subject_kind=EvidenceSubjectKind(payload["subject_kind"]),
        subject_id=_uuid(payload["subject_id"]),
        manifest_key=payload["manifest_key"],
        build_revision=payload.get("build_revision", 1),
        camera_id=_uuid(payload["camera_id"]),
        stream_id=_uuid(payload["stream_id"]) if payload.get("stream_id") else None,
        zone_id=_uuid(payload["zone_id"]) if payload.get("zone_id") else None,
        detection_event_id=_uuid(payload["detection_event_id"]) if payload.get("detection_event_id") else None,
        violation_event_id=_uuid(payload["violation_event_id"]) if payload.get("violation_event_id") else None,
        plate_read_id=_uuid(payload["plate_read_id"]) if payload.get("plate_read_id") else None,
        occurred_at=_resolve_relative_time(now, minutes=payload.get("occurred_minutes_ago"), hours=payload.get("occurred_hours_ago")),
        event_frame_index=payload.get("event_frame_index"),
        storage_namespace=payload.get("storage_namespace", "demo-evidence"),
        manifest_uri=payload.get("manifest_uri"),
        manifest_data=manifest_data,
    )


def _build_workflow(payload: dict[str, Any], scenario_name: str, now: datetime) -> WorkflowRun:
    input_payload = _merge_origin(payload.get("input_payload", {}), scenario_name, record_type="workflow_input")
    result_payload = payload.get("result_payload")
    if result_payload is not None:
        result_payload = _merge_origin(result_payload, scenario_name, record_type="workflow_result")
    return WorkflowRun(
        id=_uuid(payload["id"]),
        camera_id=_uuid(payload["camera_id"]) if payload.get("camera_id") else None,
        detection_event_id=_uuid(payload["detection_event_id"]) if payload.get("detection_event_id") else None,
        violation_event_id=_uuid(payload["violation_event_id"]) if payload.get("violation_event_id") else None,
        workflow_type=WorkflowType(payload["workflow_type"]),
        status=WorkflowStatus(payload["status"]),
        priority=payload.get("priority", 5),
        requested_by=payload.get("requested_by"),
        started_at=_resolve_relative_time(now, minutes=payload.get("started_minutes_ago"), hours=payload.get("started_hours_ago")),
        completed_at=_resolve_relative_time(now, minutes=payload.get("completed_minutes_ago"), hours=payload.get("completed_hours_ago")),
        input_payload=input_payload,
        result_payload=result_payload,
        error_message=payload.get("error_message"),
        created_at=_resolve_relative_time(now, minutes=payload.get("created_minutes_ago"), hours=payload.get("created_hours_ago")) or now,
        updated_at=now,
    )


async def _delete_existing_demo_records(session: AsyncSession, scenario: dict[str, Any]) -> None:
    model_id_sets = {
        EvidenceManifest: [_uuid(item["id"]) for item in scenario.get("evidence_manifests", [])],
        WorkflowRun: [_uuid(item["id"]) for item in scenario.get("workflows", [])],
        ViolationEvent: [_uuid(item["id"]) for item in scenario.get("violations", [])],
        PlateRead: [_uuid(item["id"]) for item in scenario.get("plate_reads", [])],
        DetectionEvent: [_uuid(item["id"]) for item in scenario.get("detection_events", [])],
        Zone: [_uuid(zone["id"]) for camera in scenario.get("cameras", []) for zone in camera.get("zones", [])],
        CameraStream: [_uuid(stream["id"]) for camera in scenario.get("cameras", []) for stream in camera.get("streams", [])],
        Camera: [_uuid(camera["id"]) for camera in scenario.get("cameras", [])],
    }
    for model, ids in model_id_sets.items():
        if ids:
            await session.execute(delete(model).where(model.id.in_(ids)))
    await session.flush()


async def _load_seeded_cameras(session: AsyncSession, scenario: dict[str, Any]) -> list[Camera]:
    camera_ids = [_uuid(camera["id"]) for camera in scenario.get("cameras", [])]
    statement = (
        select(Camera)
        .options(selectinload(Camera.streams))
        .where(Camera.id.in_(camera_ids))
        .order_by(Camera.camera_code)
    )
    return list((await session.execute(statement)).scalars().all())


def _build_health_dashboard_preview(cameras: list[Camera], now: datetime) -> dict[str, Any]:
    assessor = HealthAssessor()
    camera_reports = []
    for camera in cameras:
        stream_reports = [
            assessor.assess_stream(
                stream_id=stream.id,
                stream_name=stream.name,
                camera_id=stream.camera_id,
                source_type=stream.source_type.value,
                db_status=stream.status.value,
                is_enabled=stream.is_enabled,
                last_heartbeat_at=stream.last_heartbeat_at,
                last_error=stream.last_error,
                fps_hint=stream.fps_hint,
                job_state=None,
                now=now,
            )
            for stream in camera.streams
        ]
        camera_reports.append(
            assessor.assess_camera(
                camera_id=camera.id,
                camera_code=camera.camera_code,
                camera_name=camera.name,
                camera_status=camera.status.value,
                stream_reports=stream_reports,
            )
        )

    dashboard = assessor.assess_dashboard(camera_reports, active_jobs=0)
    return {
        "assessed_at": dashboard.assessed_at.isoformat(),
        "total_cameras": dashboard.total_cameras,
        "cameras_online": dashboard.cameras_online,
        "cameras_degraded": dashboard.cameras_degraded,
        "cameras_offline": dashboard.cameras_offline,
        "total_streams": dashboard.total_streams,
        "streams_online": dashboard.streams_online,
        "active_jobs": dashboard.active_jobs,
        "critical_alerts": dashboard.critical_alerts,
        "warning_alerts": dashboard.warning_alerts,
        "camera_states": [
            {
                "camera_code": report.camera_code,
                "overall_health": report.overall_health.value,
                "stream_count": len(report.streams),
            }
            for report in dashboard.cameras
        ],
    }


def _build_walkthrough_targets(scenario: dict[str, Any]) -> dict[str, Any]:
    return {
        "camera_codes": [camera["camera_code"] for camera in scenario.get("cameras", [])],
        "camera_ids": [camera["id"] for camera in scenario.get("cameras", [])],
        "review_case_ids": [violation["id"] for violation in scenario.get("violations", [])],
        "export_ready_violation_ids": [
            violation["id"]
            for violation in scenario.get("violations", [])
            if violation.get("status") in {"confirmed", "dismissed"}
        ],
        "api_hints": [
            "/api/v1/cameras",
            "/api/v1/observability/dashboard",
            "/api/v1/exports",
        ],
    }


def _merge_origin(payload: dict[str, Any], scenario_name: str, *, record_type: str) -> dict[str, Any]:
    merged = dict(payload)
    merged["trafficmind_record_origin"] = _origin_tag(scenario_name, record_type)
    return merged


def _origin_tag(scenario_name: str, record_type: str) -> dict[str, Any]:
    return {
        "mode": _DEMO_TAG,
        "synthetic": True,
        "scenario_name": scenario_name,
        "record_type": record_type,
    }


def _resolve_relative_time(
    now: datetime,
    *,
    seconds: int | float | None = None,
    minutes: int | float | None = None,
    hours: int | float | None = None,
) -> datetime | None:
    if seconds is None and minutes is None and hours is None:
        return None
    delta = timedelta(
        seconds=float(seconds or 0),
        minutes=float(minutes or 0),
        hours=float(hours or 0),
    )
    return now - delta


def _uuid(raw: str) -> uuid.UUID:
    return uuid.UUID(raw)


async def _run_cli_async(args: argparse.Namespace) -> int:
    if args.list_scenarios:
        print(json.dumps(list_demo_scenarios(), indent=2))
        return 0

    database_url = args.database_url or get_settings().database_url
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        if args.create_schema:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as session:
            report = await seed_demo_scenario(session, scenario_name=args.scenario)
            await session.commit()

        payload = report.to_dict()
        if args.report_path:
            report_path = Path(args.report_path)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        print(json.dumps(payload, indent=2))
        return 0
    finally:
        await engine.dispose()


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m apps.api.app.demo.seed")
    parser.add_argument("--scenario", default="city_center_baseline", help="Demo scenario name to seed.")
    parser.add_argument("--database-url", default=None, help="Override the database URL used for seeding.")
    parser.add_argument("--create-schema", action="store_true", help="Create database tables before seeding the demo scenario.")
    parser.add_argument("--report-path", default=None, help="Optional path to write the seed report JSON.")
    parser.add_argument("--list-scenarios", action="store_true", help="List available built-in demo scenarios and exit.")
    return parser


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()
    return asyncio.run(_run_cli_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
