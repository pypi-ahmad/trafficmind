"""Integration tests for model registry and provenance tracking foundations."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.db.base import Base
from apps.api.app.db.enums import CameraStatus, SourceType, StreamKind, StreamStatus, ViolationSeverity, ViolationType, ZoneStatus, ZoneType
from apps.api.app.db.models import Camera, CameraStream, ModelRegistryEntry, Zone
from apps.api.app.db.session import get_db_session
from apps.api.app.main import create_app
from services.evidence.service import build_violation_evidence_manifest
from services.model_registry.schemas import ModelRegistryTaskType
from services.ocr.persistence import save_plate_read
from services.ocr.schemas import PlateOcrResult
from services.rules.persistence import save_violation
from services.rules.schemas import Explanation, RuleType, ViolationRecord
from services.vision.persistence import save_detection_event
from services.vision.schemas import BBox, Detection, ObjectCategory


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


async def _seed_camera_stack(session) -> tuple[Camera, CameraStream, Zone]:
    camera = Camera(
        camera_code="CAM-PROV-001",
        name="Provenance Camera",
        location_name="King Fahd & Main",
        status=CameraStatus.ACTIVE,
        calibration_config={},
    )
    stream = CameraStream(
        camera=camera,
        name="primary",
        stream_kind=StreamKind.PRIMARY,
        source_type=SourceType.RTSP,
        source_uri="rtsp://trafficmind.local/provenance/cam-001",
        status=StreamStatus.LIVE,
        fps_hint=15.0,
    )
    zone = Zone(
        camera=camera,
        name="stop-line-a",
        zone_type=ZoneType.STOP_LINE,
        status=ZoneStatus.ACTIVE,
        geometry={"points": [[0.1, 0.8], [0.9, 0.8]]},
        rules_config={
            "rules": [
                {
                    "rule_type": "red_light",
                    "severity": "high",
                    "confirmation_frames": 2,
                    "min_post_crossing_seconds": 0.15,
                }
            ]
        },
    )
    session.add_all([camera, stream, zone])
    await session.flush()
    return camera, stream, zone


@pytest.mark.asyncio
async def test_model_registry_routes_require_admin_write_and_support_audit_reads(
    client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    client, _session_factory = client

    denied = await client.post(
        "/api/v1/model-registry",
        json={
            "task_type": "detection_model",
            "model_family": "yolo26",
            "version_name": "yolo26x.pt",
            "config_bundle": {"confidence_threshold": 0.25},
            "notes": "default runtime detector",
        },
    )
    assert denied.status_code == 403
    assert "manage_model_registry" in denied.json()["detail"]

    created = await client.post(
        "/api/v1/model-registry",
        params={"access_role": "evidence_admin"},
        json={
            "task_type": "detection_model",
            "model_family": "yolo26",
            "version_name": "yolo26x.pt",
            "config_bundle": {"confidence_threshold": 0.25, "iou_threshold": 0.45},
            "notes": "default runtime detector",
            "entry_metadata": {"owner": "vision-team"},
        },
    )
    assert created.status_code == 201
    created_payload = created.json()
    assert created_payload["task_type"] == "detection_model"
    assert created_payload["model_family"] == "yolo26"
    assert created_payload["config_hash"]
    assert created_payload["is_active"] is True

    listed = await client.get(
        "/api/v1/model-registry",
        params={"access_role": "reviewer", "task_type": "detection_model"},
    )
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == created_payload["id"]

    patched = await client.patch(
        f"/api/v1/model-registry/{created_payload['id']}",
        params={"access_role": "evidence_admin"},
        json={"is_active": False, "notes": "retired after experiment"},
    )
    assert patched.status_code == 200
    assert patched.json()["is_active"] is False
    assert patched.json()["notes"] == "retired after experiment"


@pytest.mark.asyncio
async def test_runtime_provenance_is_attached_to_events_reads_violations_and_evidence(
    client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    _client, session_factory = client
    occurred_at = datetime(2026, 4, 6, 16, 30, tzinfo=timezone.utc)

    async with session_factory() as session:
        camera, stream, zone = await _seed_camera_stack(session)

        detection = await save_detection_event(
            session,
            Detection(
                class_name="car",
                category=ObjectCategory.VEHICLE,
                confidence=0.96,
                bbox=BBox(x1=120, y1=200, x2=360, y2=420),
                track_id="trk-0001",
                frame_index=42,
                timestamp=occurred_at,
            ),
            camera_id=camera.id,
            stream_id=stream.id,
            zone_id=zone.id,
            event_type="line_crossing",
            event_payload={"light_state": "red"},
        )

        plate_read = await save_plate_read(
            session,
            PlateOcrResult(
                raw_text="ABC1234",
                normalized_text="ABC1234",
                confidence=0.91,
                bbox=BBox(x1=180, y1=300, x2=250, y2=340),
                timestamp=occurred_at,
                frame_index=42,
                raw_metadata={"engine": "paddleocr"},
            ),
            camera_id=camera.id,
            stream_id=stream.id,
            detection_event_id=detection.id,
            match_watchlist=False,
        )

        violation = await save_violation(
            session,
            ViolationRecord(
                rule_type=RuleType.RED_LIGHT,
                violation_type=ViolationType.RED_LIGHT,
                severity=ViolationSeverity.HIGH,
                zone_id=str(zone.id),
                zone_name=zone.name,
                track_id="trk-0001",
                occurred_at=occurred_at,
                frame_index=42,
                explanation=Explanation(
                    rule_type=RuleType.RED_LIGHT,
                    reason="Vehicle crossed the stop line on red.",
                    rule_config={"confirmation_frames": 2, "requires_red_light": True},
                ),
            ),
            camera_id=camera.id,
            stream_id=stream.id,
            zone_id=zone.id,
            detection_event_id=detection.id,
            plate_read_id=plate_read.id,
        )
        await session.flush()

        manifest = await build_violation_evidence_manifest(session, violation.id)
        await session.commit()

        assert detection.detector_registry_id is not None
        assert detection.tracker_registry_id is not None
        assert plate_read.ocr_registry_id is not None
        assert violation.rules_registry_id is not None
        assert manifest.evidence_registry_id is not None

        detector_provenance = detection.event_payload["provenance"]["detector"]
        tracker_provenance = detection.event_payload["provenance"]["tracker"]
        ocr_provenance = plate_read.ocr_metadata["provenance"]["ocr"]
        rules_provenance = violation.rule_metadata["provenance"]["rules"]
        evidence_provenance = manifest.manifest.audit["provenance"]["evidence"]

        assert detector_provenance["task_type"] == ModelRegistryTaskType.DETECTION_MODEL.value
        assert detector_provenance["version_name"] == "yolo26x.pt"
        assert tracker_provenance["task_type"] == ModelRegistryTaskType.TRACKING_CONFIG.value
        assert tracker_provenance["version_name"] == "trafficmind.tracking.runtime.v1"
        assert ocr_provenance["task_type"] == ModelRegistryTaskType.OCR_MODEL.value
        assert rules_provenance["task_type"] == ModelRegistryTaskType.RULES_CONFIG.value
        assert rules_provenance["version_name"] == "trafficmind.rules.runtime.v1"
        assert evidence_provenance["task_type"] == ModelRegistryTaskType.EVIDENCE_CONFIG.value
        assert evidence_provenance["version_name"] == "trafficmind.evidence.service.v1"

        registry_rows = list((await session.execute(ModelRegistryEntry.__table__.select())).mappings().all())
        task_types = {row["task_type"] for row in registry_rows}
        assert task_types == {
            ModelRegistryTaskType.DETECTION_MODEL.value,
            ModelRegistryTaskType.TRACKING_CONFIG.value,
            ModelRegistryTaskType.OCR_MODEL.value,
            ModelRegistryTaskType.RULES_CONFIG.value,
            ModelRegistryTaskType.EVIDENCE_CONFIG.value,
        }

        rules_entry = await session.get(ModelRegistryEntry, violation.rules_registry_id)
        assert rules_entry is not None
        assert rules_entry.config_bundle["rule_type"] == "red_light"
        assert rules_entry.config_bundle["runtime_version"] == "trafficmind.rules.runtime.v1"
        assert rules_entry.config_bundle["rule_config"]["confirmation_frames"] == 2
        assert rules_provenance["config_hash"] == rules_entry.config_hash