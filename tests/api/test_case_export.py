"""Integration tests for case export and audit-ready evidence bundle generation."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

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
from apps.api.app.db.session import get_db_session
from apps.api.app.main import create_app


@pytest.fixture
async def client() -> AsyncIterator[tuple[AsyncClient, async_sessionmaker]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app()

    async def override_get_db_session() -> AsyncIterator[object]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c, session_factory


@pytest.fixture
async def seeded_violation(
    client: tuple[AsyncClient, async_sessionmaker],
) -> tuple[AsyncClient, async_sessionmaker, dict]:
    """Seed a full violation scenario: camera → stream → zone → detection → plate read → violation → evidence → workflow."""
    http, session_factory = client
    occurred = datetime(2026, 4, 5, 14, 30, tzinfo=timezone.utc)

    async with session_factory() as session:
        camera = Camera(
            camera_code="CAM-EXPORT-001",
            name="Export Test Camera",
            location_name="1st Ave & Main",
            status=CameraStatus.ACTIVE,
            latitude=40.7128,
            longitude=-74.006,
        )
        stream = CameraStream(
            camera=camera,
            name="primary",
            stream_kind=StreamKind.PRIMARY,
            source_type=SourceType.RTSP,
            source_uri="rtsp://cam-export-001.local/primary",
            status=StreamStatus.LIVE,
            is_enabled=True,
        )
        zone = Zone(
            camera=camera,
            name="intersection-stop-line",
            zone_type="stop_line",
            status="active",
            geometry={"type": "LineString", "coordinates": [[0, 0], [100, 0]]},
            rules_config={"red_light_min_dwell_ms": 500},
        )
        detection = DetectionEvent(
            camera=camera,
            stream=stream,
            zone=zone,
            event_type=DetectionEventType.LINE_CROSSING,
            status=DetectionEventStatus.ENRICHED,
            occurred_at=occurred,
            frame_index=14520,
            track_id="trk-00042",
            object_class="car",
            confidence=0.96,
            bbox={"x1": 200, "y1": 300, "x2": 400, "y2": 500},
            event_payload={"speed_kmh": 62, "light_state": "red"},
            image_uri="s3://evidence/cam-export-001/frame-14520.jpg",
        )
        plate_read = PlateRead(
            camera=camera,
            stream=stream,
            detection_event=detection,
            status=PlateReadStatus.OBSERVED,
            occurred_at=occurred,
            plate_text="XY-789-ZZ",
            normalized_plate_text="XY789ZZ",
            confidence=0.91,
            bbox={"x1": 250, "y1": 420, "x2": 350, "y2": 460},
            crop_image_uri="s3://evidence/cam-export-001/plate-14520.jpg",
            ocr_metadata={"engine": "trafficmind-ocr-v2"},
        )
        violation = ViolationEvent(
            camera=camera,
            stream=stream,
            zone=zone,
            detection_event=detection,
            plate_read=plate_read,
            violation_type=ViolationType.RED_LIGHT,
            severity=ViolationSeverity.HIGH,
            status=ViolationStatus.CONFIRMED,
            occurred_at=occurred,
            summary="Vehicle crossed the stop-line 1.2s after the light turned red.",
            evidence_image_uri="s3://evidence/cam-export-001/frame-14520.jpg",
            evidence_video_uri="s3://evidence/cam-export-001/clip-14520.mp4",
            assigned_to="reviewer.jane",
            reviewed_by="reviewer.jane",
            reviewed_at=datetime(2026, 4, 5, 15, 0, tzinfo=timezone.utc),
            review_note="Clear red-light violation confirmed from evidence.",
            rule_metadata={"rule_id": "rl-001", "dwell_ms": 1200, "light_state": "red"},
        )
        session.add_all([camera, stream, zone, detection, plate_read, violation])
        await session.flush()

        evidence = EvidenceManifest(
            subject_kind=EvidenceSubjectKind.VIOLATION_EVENT,
            subject_id=violation.id,
            manifest_key=f"violation:{violation.id}",
            build_revision=1,
            camera=camera,
            stream=stream,
            zone=zone,
            detection_event=detection,
            violation_event=violation,
            plate_read=plate_read,
            occurred_at=occurred,
            event_frame_index=14520,
            storage_namespace="evidence",
            manifest_uri="s3://evidence/cam-export-001/manifest-14520.json",
            manifest_data={
                "frames": ["frame-14520.jpg", "frame-14521.jpg"],
                "clips": ["clip-14520.mp4"],
                "plates": ["plate-14520.jpg"],
            },
        )
        workflow = WorkflowRun(
            camera=camera,
            detection_event=detection,
            violation_event=violation,
            workflow_type=WorkflowType.REVIEW,
            status=WorkflowStatus.SUCCEEDED,
            priority=3,
            requested_by="system",
            started_at=datetime(2026, 4, 5, 14, 31, tzinfo=timezone.utc),
            completed_at=datetime(2026, 4, 5, 14, 35, tzinfo=timezone.utc),
            input_payload={"violation_id": str(violation.id)},
            result_payload={"decision": "confirmed", "confidence": 0.97},
        )

        session.add_all([evidence, workflow])
        await session.commit()

        for obj in [camera, stream, zone, detection, plate_read, violation, evidence, workflow]:
            await session.refresh(obj)

        return http, session_factory, {
            "camera_id": str(camera.id),
            "stream_id": str(stream.id),
            "zone_id": str(zone.id),
            "detection_event_id": str(detection.id),
            "plate_read_id": str(plate_read.id),
            "violation_event_id": str(violation.id),
            "evidence_manifest_id": str(evidence.id),
            "workflow_run_id": str(workflow.id),
        }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_violation_as_json_with_full_bundle(seeded_violation: tuple) -> None:
    """A JSON export of a fully-reviewed violation yields a complete, structured bundle."""
    http, _sf, ids = seeded_violation

    resp = await http.post(
        "/api/v1/exports",
        json={
            "subject_kind": "violation_event",
            "subject_id": ids["violation_event_id"],
            "export_format": "json",
            "requested_by": "reviewer.jane",
            "access_role": "evidence_admin",
            "requested_view": "original",
        },
    )
    assert resp.status_code == 201
    export = resp.json()

    assert export["status"] == "completed"
    assert export["subject_kind"] == "violation_event"
    assert export["subject_id"] == ids["violation_event_id"]
    assert export["export_format"] == "json"
    assert export["requested_by"] == "reviewer.jane"
    assert export["filename"].endswith(".json")
    assert "violation_event" in export["filename"]
    assert ids["violation_event_id"][:8] in export["filename"]
    assert export["id"][:8] in export["filename"]

    bundle = export["bundle_data"]
    assert bundle["format_version"] == "1.0"
    assert bundle["bundle_metadata"]["bundle_id"] == export["id"]
    assert bundle["bundle_metadata"]["filename"] == export["filename"]
    assert bundle["source_references"]["subject"]["id"] == ids["violation_event_id"]
    assert bundle["source_references"]["camera_id"] == ids["camera_id"]
    assert bundle["source_references"]["plate_read_ids"] == [ids["plate_read_id"]]
    assert bundle["source_references"]["workflow_run_ids"] == [ids["workflow_run_id"]]

    # Incident
    assert bundle["incident"]["violation_type"] == "red_light"
    assert bundle["incident"]["severity"] == "high"
    assert bundle["incident"]["status"] == "confirmed"
    assert bundle["incident_summary"]["summary"] == "Vehicle crossed the stop-line 1.2s after the light turned red."

    # Camera
    assert bundle["camera"]["camera_code"] == "CAM-EXPORT-001"

    # Evidence
    assert len(bundle["evidence_manifests"]) == 1
    assert bundle["evidence_manifests"][0]["manifest_key"].startswith("violation:")
    assert bundle["evidence_manifests"][0]["subject_id"] == ids["violation_event_id"]
    assert bundle["evidence_manifests"][0]["event_frame_index"] == 14520
    assert bundle["evidence_manifests"][0]["asset_counts"]["frames"] == 2

    # Plate reads
    assert len(bundle["plate_reads"]) == 1
    assert bundle["plate_reads"][0]["normalized_plate_text"] == "XY789ZZ"
    assert bundle["plate_reads"][0]["status"] == "observed"
    assert bundle["plate_reads"][0]["detection_event_id"] == ids["detection_event_id"]
    assert bundle["plate_reads"][0]["source_frame_uri"] is None

    # Detection context
    assert bundle["detection_context"]["track_id"] == "trk-00042"
    assert bundle["detection_context"]["object_class"] == "car"
    assert bundle["detection_context"]["stream_id"] == ids["stream_id"]
    assert bundle["detection_context"]["zone_id"] == ids["zone_id"]
    assert bundle["track_metadata"]["available"] is True
    assert bundle["track_metadata"]["track_id"] == "trk-00042"

    # Review trail
    assert bundle["review"]["reviewed_by"] == "reviewer.jane"
    assert bundle["review"]["status"] == "confirmed"
    assert bundle["review"]["review_note"] is not None
    assert bundle["review"]["is_reviewed"] is True
    assert bundle["review"]["review_signals"]["has_review_timestamp"] is True
    assert bundle["review"]["actions_taken"][0]["action"] == "assigned"

    # Rule explanation
    assert bundle["rule_explanation"]["rule_id"] == "rl-001"
    assert bundle["rule_explanation"]["available"] is True

    # Workflow decisions
    assert len(bundle["workflow_decisions"]) == 1
    assert bundle["workflow_decisions"][0]["status"] == "succeeded"
    assert bundle["workflow_decisions"][0]["decision"] == "confirmed"
    assert bundle["workflow_decisions"][0]["result_payload"]["decision"] == "confirmed"

    # Audit trail
    assert bundle["audit_trail"]["status_history_complete"] is False
    assert len(bundle["audit_trail"]["timeline"]) >= 4
    assert bundle["audit_trail"]["reviewers"] == ["reviewer.jane"]
    assert any(event["event_type"] == "workflow_completed" and event.get("action_taken") == "confirmed" for event in bundle["audit_trail"]["timeline"])

    # Completeness
    completeness = export["completeness"]
    assert completeness["is_complete"] is True
    assert completeness["has_evidence"] is True
    assert completeness["has_plate_read"] is True
    assert completeness["has_review"] is True
    assert completeness["has_workflow"] is True
    assert completeness["has_track_metadata"] is True
    assert completeness["has_rule_explanation"] is True
    assert completeness["missing_assets"] == []

    # Retrieve the export again
    get_resp = await http.get(
        f"/api/v1/exports/{export['id']}",
        params={"access_role": "evidence_admin"},
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == export["id"]

    # Audit events
    assert [event["event_type"] for event in get_resp.json()["audit_events"]] == ["created", "completed"]


@pytest.mark.asyncio
async def test_export_markdown_format(seeded_violation: tuple) -> None:
    """A markdown export returns human-readable text in bundle_data.report_text."""
    http, _sf, ids = seeded_violation

    resp = await http.post(
        "/api/v1/exports",
        json={
            "subject_kind": "violation_event",
            "subject_id": ids["violation_event_id"],
            "export_format": "markdown",
            "requested_by": "supervisor.bob",
            "access_role": "evidence_admin",
            "requested_view": "original",
        },
    )
    assert resp.status_code == 201
    export = resp.json()
    assert export["status"] == "completed"
    assert export["filename"].endswith(".md")

    bundle = export["bundle_data"]
    report = bundle["report_text"]
    assert "# Case Export Report" in report
    assert "RED_LIGHT" in report.upper() or "red_light" in report
    assert "reviewer.jane" in report
    assert "XY789ZZ" in report or "XY-789-ZZ" in report


@pytest.mark.asyncio
async def test_export_defaults_to_redacted_and_hides_original_media_references(
    seeded_violation: tuple,
) -> None:
    http, _sf, ids = seeded_violation

    resp = await http.post(
        "/api/v1/exports",
        json={
            "subject_kind": "violation_event",
            "subject_id": ids["violation_event_id"],
            "export_format": "json",
            "requested_by": "archiver.system",
        },
    )
    assert resp.status_code == 201

    export = resp.json()
    assert export["status"] == "completed"

    bundle = export["bundle_data"]
    assert bundle["privacy"]["asset_view"] == "redacted"
    assert bundle["incident"]["evidence_image_uri"] is None
    assert bundle["detection_context"]["image_uri"] is None
    assert bundle["plate_reads"][0]["crop_image_uri"] is None
    assert bundle["plate_reads"][0]["source_frame_uri"] is None
    assert bundle["plate_reads"][0]["plate_text"] != "XY-789-ZZ"
    assert bundle["evidence_manifests"][0]["manifest_uri"] is None
    assert bundle["evidence_manifests"][0]["manifest_data"]["frames"] == []
    assert "privacy_redaction_notice" in bundle["evidence_manifests"][0]["manifest_data"]


@pytest.mark.asyncio
async def test_export_service_detail_hides_sensitive_audit_sections(seeded_violation: tuple) -> None:
    http, _sf, ids = seeded_violation

    create_resp = await http.post(
        "/api/v1/exports",
        json={
            "subject_kind": "violation_event",
            "subject_id": ids["violation_event_id"],
            "export_format": "json",
        },
    )
    assert create_resp.status_code == 201
    export_id = create_resp.json()["id"]

    detail_resp = await http.get(
        f"/api/v1/exports/{export_id}",
        params={"access_role": "export_service"},
    )
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["audit_events"] == []
    assert detail["bundle_data"]["review"]["restricted"] is True
    assert detail["bundle_data"]["workflow_decisions"] == []
    assert detail["bundle_data"]["audit_trail"]["restricted"] is True
    assert detail["bundle_data"]["privacy"]["audit_trail_visible"] is False


@pytest.mark.asyncio
async def test_export_records_missing_assets_honestly(
    client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    """When evidence or plate reads are missing, completeness records the gaps."""
    http, session_factory = client
    occurred = datetime(2026, 4, 5, 16, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        camera = Camera(
            camera_code="CAM-SPARSE-001",
            name="Sparse Camera",
            location_name="Side St",
            status=CameraStatus.ACTIVE,
        )
        violation = ViolationEvent(
            camera=camera,
            violation_type=ViolationType.STALLED_VEHICLE,
            severity=ViolationSeverity.LOW,
            status=ViolationStatus.OPEN,
            occurred_at=occurred,
            summary="Stalled vehicle detected with no plate or evidence.",
            rule_metadata={},
        )
        session.add_all([camera, violation])
        await session.commit()
        await session.refresh(violation)
        violation_id = str(violation.id)

    resp = await http.post(
        "/api/v1/exports",
        json={
            "subject_kind": "violation_event",
            "subject_id": violation_id,
            "export_format": "json",
        },
    )
    assert resp.status_code == 201
    export = resp.json()
    assert export["status"] == "completed"

    completeness = export["completeness"]
    assert completeness["is_complete"] is False
    assert completeness["has_evidence"] is False
    assert completeness["has_plate_read"] is False
    assert completeness["has_review"] is False
    assert completeness["has_workflow"] is False
    assert completeness["has_track_metadata"] is False
    assert completeness["has_rule_explanation"] is False
    assert len(completeness["missing_assets"]) > 0

    bundle = export["bundle_data"]
    assert bundle["plate_reads"] == []
    assert bundle["evidence_manifests"] == []
    assert bundle["workflow_decisions"] == []
    assert bundle["source_references"]["plate_read_ids"] == []
    assert bundle["source_references"]["workflow_run_ids"] == []


@pytest.mark.asyncio
async def test_list_exports_with_filters(seeded_violation: tuple) -> None:
    """List exports and filter by subject."""
    http, _sf, ids = seeded_violation

    await http.post(
        "/api/v1/exports",
        json={
            "subject_kind": "violation_event",
            "subject_id": ids["violation_event_id"],
            "export_format": "json",
        },
    )

    list_resp = await http.get(
        "/api/v1/exports",
        params={"subject_kind": "violation_event", "access_role": "export_service"},
    )
    assert list_resp.status_code == 200
    result = list_resp.json()
    assert result["total"] >= 1
    assert all(item["subject_kind"] == "violation_event" for item in result["items"])


@pytest.mark.asyncio
async def test_export_not_found_returns_404(
    client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    http, _sf = client

    resp = await http.post(
        "/api/v1/exports",
        json={
            "subject_kind": "violation_event",
            "subject_id": "00000000-0000-0000-0000-000000000099",
            "export_format": "json",
        },
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_export_zip_manifest_format(seeded_violation: tuple) -> None:
    """A zip_manifest export lists all asset URIs and includes the structured data."""
    http, _sf, ids = seeded_violation

    resp = await http.post(
        "/api/v1/exports",
        json={
            "subject_kind": "violation_event",
            "subject_id": ids["violation_event_id"],
            "export_format": "zip_manifest",
            "requested_by": "archiver.system",
            "access_role": "evidence_admin",
            "requested_view": "original",
        },
    )
    assert resp.status_code == 201
    export = resp.json()
    assert export["status"] == "completed"
    assert export["filename"].endswith(".zip-manifest.json")

    bundle = export["bundle_data"]
    assert "asset_manifest" in bundle
    assert bundle["asset_manifest"]["archive_generated"] is False
    assert bundle["asset_manifest"]["asset_count"] > 0
    assert isinstance(bundle["asset_manifest"]["assets"], list)
    # Each asset entry should have uri and kind
    for asset in bundle["asset_manifest"]["assets"]:
        assert "uri" in asset
        assert "kind" in asset


@pytest.mark.asyncio
async def test_export_download_audit_event_is_recorded(seeded_violation: tuple) -> None:
    """Bundle retrieval should be auditable without requiring a real binary download endpoint yet."""
    http, _sf, ids = seeded_violation

    export_resp = await http.post(
        "/api/v1/exports",
        json={
            "subject_kind": "violation_event",
            "subject_id": ids["violation_event_id"],
            "export_format": "json",
            "requested_by": "reviewer.jane",
            "access_role": "evidence_admin",
            "requested_view": "original",
        },
    )
    assert export_resp.status_code == 201
    export_id = export_resp.json()["id"]

    download_resp = await http.post(
        f"/api/v1/exports/{export_id}/downloads",
        params={"access_role": "evidence_admin"},
        json={"actor": "ops.supervisor", "note": "Bundle copied into the external case system."},
    )
    assert download_resp.status_code == 200

    detail = download_resp.json()
    assert [event["event_type"] for event in detail["audit_events"]] == ["created", "completed", "downloaded"]
    assert detail["audit_events"][-1]["actor"] == "ops.supervisor"
    assert detail["audit_events"][-1]["event_payload"]["filename"] == detail["filename"]
