from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.db.base import Base
from apps.api.app.db.enums import (
    CameraStatus,
    DetectionEventType,
    EvidenceSubjectKind,
    PlateReadStatus,
    SourceType,
    StreamKind,
    StreamStatus,
    ViolationSeverity,
    ViolationStatus,
    ViolationType,
    ZoneStatus,
    ZoneType,
)
from apps.api.app.db.models import (
    Camera,
    CameraStream,
    DetectionEvent,
    PlateRead,
    ViolationEvent,
    Zone,
)
from apps.api.app.db.session import get_db_session
from apps.api.app.main import create_app
from services.access_control.policy import AccessDeniedError
from services.evidence.schemas import (
    EvidenceAccessRole,
    EvidenceAssetKind,
    EvidenceAssetView,
    EvidenceStorageState,
)
from services.evidence.service import (
    build_violation_evidence_manifest,
    get_violation_evidence_manifest,
)


async def _make_session_factory() -> tuple[async_sessionmaker, object]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False), engine


async def _seed_incident(session) -> tuple[uuid.UUID, uuid.UUID]:
    occurred_at = datetime(2026, 4, 5, 14, 30, tzinfo=timezone.utc)
    camera = Camera(
        camera_code="CAM-EVD-001",
        name="Signalized Approach",
        location_name="King Fahd & Tahlia",
        status=CameraStatus.ACTIVE,
        calibration_config={},
    )
    stream = CameraStream(
        camera=camera,
        name="primary",
        stream_kind=StreamKind.PRIMARY,
        source_type=SourceType.RTSP,
        source_uri="rtsp://trafficmind.local/evidence",
        source_config={},
        status=StreamStatus.LIVE,
        fps_hint=10.0,
    )
    zone = Zone(
        camera=camera,
        name="stop-line-a",
        zone_type=ZoneType.STOP_LINE,
        status=ZoneStatus.ACTIVE,
        geometry={"points": [[0.1, 0.8], [0.9, 0.8]]},
        rules_config={"rules": [{"rule_type": "red_light"}]},
    )
    detection = DetectionEvent(
        camera=camera,
        stream=stream,
        zone=zone,
        event_type=DetectionEventType.LINE_CROSSING,
        occurred_at=occurred_at,
        frame_index=42,
        track_id="T-123",
        object_class="car",
        confidence=0.98,
        bbox={"x1": 120, "y1": 200, "x2": 360, "y2": 420},
        event_payload={
            "direction": "northbound",
            "track_path": [{"x": 150, "y": 210}, {"x": 195, "y": 260}, {"x": 240, "y": 310}],
        },
        image_uri="s3://trafficmind/evidence/violation-frame.jpg",
        video_uri=None,
    )
    plate_read = PlateRead(
        camera=camera,
        stream=stream,
        detection_event=detection,
        status=PlateReadStatus.OBSERVED,
        occurred_at=occurred_at,
        plate_text="ABC1234",
        normalized_plate_text="ABC1234",
        confidence=0.92,
        country_code="SA",
        region_code="RUH",
        bbox={"x1": 180, "y1": 300, "x2": 250, "y2": 340},
        crop_image_uri="s3://trafficmind/evidence/plate-crop.jpg",
        source_frame_uri="s3://trafficmind/evidence/source-frame.jpg",
        ocr_metadata={},
    )
    violation = ViolationEvent(
        camera=camera,
        stream=stream,
        zone=zone,
        detection_event=detection,
        plate_read=plate_read,
        violation_type=ViolationType.RED_LIGHT,
        severity=ViolationSeverity.HIGH,
        status=ViolationStatus.OPEN,
        occurred_at=occurred_at,
        summary="Vehicle crossed the stop line on red.",
        evidence_image_uri="s3://trafficmind/evidence/review-keyframe.jpg",
        evidence_video_uri=None,
        rule_metadata={
            "rule_type": "red_light",
            "frame_index": 42,
            "track_id": "T-123",
            "certainty": 1.0,
            "explanation": {
                "rule_type": "red_light",
                "reason": "Vehicle crossed the stop line during red.",
                "frame_index": 42,
                "conditions_satisfied": ["signal_red_at_detection", "stop_line_crossed"],
                "details": {
                    "signal_state_at_decision": "red",
                    "signal_phase": "vehicle",
                    "signal_head_id": "veh-head-1",
                    "signal_confidence": 0.99,
                },
                "track_snapshot": {
                    "track_id": "T-123",
                    "bbox": {"x1": 120, "y1": 200, "x2": 360, "y2": 420},
                },
                "zone_info": {
                    "zone_id": "stop-line-a",
                    "zone_name": "Stop Line A",
                    "zone_type": "stop_line",
                    "geometry": {"points": [[0.1, 0.8], [0.9, 0.8]]},
                },
            },
        },
    )

    session.add_all([camera, stream, zone, detection, plate_read, violation])
    await session.flush()
    return violation.id, detection.id


@pytest.mark.asyncio
async def test_build_violation_evidence_manifest_selects_expected_frames_and_assets() -> None:
    factory, engine = await _make_session_factory()
    async with factory() as session:
        violation_id, _ = await _seed_incident(session)
        await session.commit()

    async with factory() as session:
        manifest = await build_violation_evidence_manifest(
            session,
            violation_id,
            storage_namespace="review",
            access_role=EvidenceAccessRole.EVIDENCE_ADMIN,
            requested_view=EvidenceAssetView.ORIGINAL,
        )
        await session.commit()

        assert manifest.subject_kind == EvidenceSubjectKind.VIOLATION_EVENT
        assert manifest.manifest.subject.kind == EvidenceSubjectKind.VIOLATION_EVENT
        assert manifest.storage_namespace == "review"
        assert manifest.has_restricted_original_assets is False
        assert manifest.manifest.selection_policy.selection_reason == "violation_rule_frame_index"
        assert [item.frame_index for item in manifest.manifest.timeline.selected_frames] == [40, 41, 42, 43, 44]

        assets = {asset.asset_kind: asset for asset in manifest.manifest.assets}
        assert set(assets) == {
            EvidenceAssetKind.KEY_FRAME_SNAPSHOT,
            EvidenceAssetKind.OBJECT_CROP,
            EvidenceAssetKind.PLATE_CROP,
            EvidenceAssetKind.CLIP_WINDOW,
            EvidenceAssetKind.TIMELINE_METADATA,
        }

        key_frame = assets[EvidenceAssetKind.KEY_FRAME_SNAPSHOT]
        assert key_frame.available is True
        assert key_frame.uri == "s3://trafficmind/evidence/review-keyframe.jpg"
        assert "signal_state" in key_frame.render_hints["available_overlays"]
        assert "zone" in key_frame.render_hints["available_overlays"]

        object_crop = assets[EvidenceAssetKind.OBJECT_CROP]
        assert object_crop.available is False
        assert object_crop.uri is not None
        assert object_crop.uri.startswith("review://")
        assert object_crop.render_hints["available_overlays"] == []

        plate_crop = assets[EvidenceAssetKind.PLATE_CROP]
        assert plate_crop.available is True
        assert plate_crop.uri == "s3://trafficmind/evidence/plate-crop.jpg"
        assert plate_crop.render_hints["available_overlays"] == []

        clip = assets[EvidenceAssetKind.CLIP_WINDOW]
        assert clip.available is False
        assert clip.metadata["generation_mode"] == "placeholder"
        assert clip.metadata["start_frame_index"] == 30
        assert clip.metadata["end_frame_index"] == 54
        assert "signal_state" in clip.render_hints["available_overlays"]

        timeline_meta = assets[EvidenceAssetKind.TIMELINE_METADATA]
        assert timeline_meta.storage_state == EvidenceStorageState.INLINE
        assert timeline_meta.available is True
        assert timeline_meta.render_hints["available_overlays"] == []

        stored = await get_violation_evidence_manifest(
            session, violation_id,
            access_role=EvidenceAccessRole.EVIDENCE_ADMIN,
            requested_view=EvidenceAssetView.ORIGINAL,
        )
        assert stored is not None
        assert stored.id == manifest.id

    await engine.dispose()


@pytest.mark.asyncio
async def test_evidence_manifest_endpoints_build_fetch_and_rebuild() -> None:
    factory, engine = await _make_session_factory()
    async with factory() as session:
        violation_id, detection_id = await _seed_incident(session)
        await session.commit()

    app = create_app()

    async def override_get_db_session() -> AsyncIterator[object]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        build_violation_response = await client.post(
            f"/api/v1/violations/{violation_id}/evidence",
            params={"storage_namespace": "exports"},
        )
        assert build_violation_response.status_code == 201
        build_violation_payload = build_violation_response.json()
        assert build_violation_payload["subject_kind"] == "violation_event"
        assert build_violation_payload["storage_namespace"] == "exports"
        assert build_violation_payload["build_revision"] == 1

        fetch_violation_response = await client.get(f"/api/v1/violations/{violation_id}/evidence")
        assert fetch_violation_response.status_code == 200
        assert fetch_violation_response.json()["manifest_key"] == build_violation_payload["manifest_key"]

        rebuild_violation_response = await client.post(
            f"/api/v1/violations/{violation_id}/evidence",
            params={"rebuild": True, "storage_namespace": "exports"},
        )
        assert rebuild_violation_response.status_code == 200
        assert rebuild_violation_response.json()["build_revision"] == 2

        build_event_response = await client.post(f"/api/v1/events/{detection_id}/evidence")
        assert build_event_response.status_code == 201
        build_event_payload = build_event_response.json()
        assert build_event_payload["subject_kind"] == "detection_event"
        assert build_event_payload["manifest"]["subject"]["object_class"] == "car"

        fetch_event_response = await client.get(f"/api/v1/events/{detection_id}/evidence")
        assert fetch_event_response.status_code == 200
        assert fetch_event_response.json()["id"] == build_event_payload["id"]

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_operator_requesting_original_evidence_endpoint_is_denied() -> None:
    factory, engine = await _make_session_factory()
    async with factory() as session:
        violation_id, _ = await _seed_incident(session)
        await session.commit()

    app = create_app()

    async def override_get_db_session() -> AsyncIterator[object]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get(
            f"/api/v1/violations/{violation_id}/evidence",
            params={"requested_view": "original", "access_role": "operator"},
        )
        assert response.status_code == 403
        assert "view_unredacted_evidence" in response.json()["detail"]

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_violation_review_endpoint_requires_permission_and_updates_review_fields() -> None:
    factory, engine = await _make_session_factory()
    async with factory() as session:
        violation_id, _ = await _seed_incident(session)
        await session.commit()

    app = create_app()

    async def override_get_db_session() -> AsyncIterator[object]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        denied = await client.post(
            f"/api/v1/violations/{violation_id}/review",
            params={"access_role": "operator"},
            json={"actor": "ops.alex", "action": "approve", "note": "Looks valid."},
        )
        assert denied.status_code == 403

        allowed = await client.post(
            f"/api/v1/violations/{violation_id}/review",
            params={"access_role": "reviewer"},
            json={"actor": "reviewer.maya", "action": "approve", "note": "Confirmed from keyframe."},
        )
        assert allowed.status_code == 200
        payload = allowed.json()
        assert payload["status"] == "confirmed"
        assert payload["reviewed_by"] == "reviewer.maya"
        assert payload["review_note"] == "Confirmed from keyframe."
        assert payload["reviewed_at"] is not None

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_access_policy_endpoint_exposes_current_role_and_requirements() -> None:
    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/v1/access/policy", params={"access_role": "reviewer"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["policy_name"] == "default_access_control_v1"
        assert payload["current_role"] == "reviewer"
        assert "approve_reject_incidents" in payload["current_permissions"]
        assert "view_unredacted_evidence" not in payload["current_permissions"]

        role_map = {item["role"]: item["permissions"] for item in payload["roles"]}
        assert "manage_policy_settings" in role_map["evidence_admin"]
        assert role_map["operator"] == ["view_redacted_evidence"]

        requirement_actions = {item["action"] for item in payload["requirements"]}
        assert "export evidence" in requirement_actions
        assert "approve or reject incidents" in requirement_actions


@pytest.mark.asyncio
async def test_service_layer_denies_operator_original_evidence_request() -> None:
    factory, engine = await _make_session_factory()
    async with factory() as session:
        violation_id, _ = await _seed_incident(session)
        await session.commit()

    async with factory() as session:
        with pytest.raises(AccessDeniedError):
            await build_violation_evidence_manifest(
                session,
                violation_id,
                access_role=EvidenceAccessRole.OPERATOR,
                requested_view=EvidenceAssetView.ORIGINAL,
            )

    await engine.dispose()


@pytest.mark.asyncio
async def test_operator_manifest_view_flags_hidden_originals_without_leaking_original_assets() -> None:
    factory, engine = await _make_session_factory()
    async with factory() as session:
        violation_id, _ = await _seed_incident(session)
        await session.commit()

    async with factory() as session:
        manifest = await build_violation_evidence_manifest(
            session,
            violation_id,
            storage_namespace="review",
        )
        await session.commit()

        assert manifest.access.resolved_view == EvidenceAssetView.REDACTED
        assert manifest.has_restricted_original_assets is True
        assert all(asset.asset_view == EvidenceAssetView.REDACTED for asset in manifest.manifest.assets)
        assert all(asset.asset_view == EvidenceAssetView.REDACTED for asset in manifest.visible_assets)

    await engine.dispose()
