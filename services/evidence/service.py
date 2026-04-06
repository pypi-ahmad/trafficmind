"""Build and retrieve deterministic evidence manifests for review flows."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from services.access_control.policy import AccessPermission, require_permissions, resolve_access_context
from services.model_registry import (
    ModelRegistryService,
    build_evidence_registry_spec,
    build_model_registry_provenance_snapshot,
)

from apps.api.app.db.enums import EvidenceSubjectKind
from apps.api.app.db.models import DetectionEvent, EvidenceManifest, PlateRead, ViolationEvent
from services.evidence.privacy import (
    mask_plate_text,
    resolve_access_resolution,
    resolve_visible_assets,
    sanitize_manifest_for_access,
)
from services.evidence.schemas import (
    EvidenceAccessRole,
    EvidenceAsset,
    EvidenceAssetKind,
    EvidenceAssetView,
    EvidenceClipWindow,
    EvidenceFrameRole,
    EvidenceManifestDocument,
    EvidenceManifestRead,
    EvidenceOverlayKind,
    EvidenceRedactionStatus,
    EvidenceRedactionTarget,
    EvidenceSelectionPolicy,
    EvidenceStorageState,
    EvidenceSubjectRef,
    EvidenceTimeline,
    EvidenceTimelineFrame,
)

_SAFE_PATH_SEGMENT = re.compile(r"[^a-z0-9_-]+")
_DEFAULT_PRE_EVENT_FRAMES = 2
_DEFAULT_POST_EVENT_FRAMES = 2
_DEFAULT_FRAME_STEP = 1
_DEFAULT_CLIP_LEAD_FRAMES = 12
_DEFAULT_CLIP_TAIL_FRAMES = 12
_model_registry_service = ModelRegistryService()


class EvidenceManifestError(RuntimeError):
    """Base exception for evidence manifest operations."""


class EvidenceSubjectNotFoundError(EvidenceManifestError):
    """Raised when the requested subject record does not exist."""


def _normalize_storage_namespace(storage_namespace: str) -> str:
    normalized = storage_namespace.strip().lower()
    return normalized or "evidence"


def _slugify(value: str) -> str:
    lowered = value.strip().lower().replace(" ", "-")
    cleaned = _SAFE_PATH_SEGMENT.sub("-", lowered)
    return cleaned.strip("-") or "unknown"


def _subject_label(subject_kind: EvidenceSubjectKind) -> str:
    return "violations" if subject_kind == EvidenceSubjectKind.VIOLATION_EVENT else "events"


def _manifest_key(subject_kind: EvidenceSubjectKind, subject_id: uuid.UUID) -> str:
    return f"{subject_kind.value}:{subject_id}"


def _base_asset_prefix(
    *,
    camera_code: str,
    occurred_at: datetime,
    subject_kind: EvidenceSubjectKind,
    subject_id: uuid.UUID,
    build_revision: int,
) -> str:
    occurred_utc = occurred_at.astimezone(UTC)
    date_path = occurred_utc.strftime("%Y/%m/%d")
    return (
        f"cameras/{_slugify(camera_code)}/{date_path}/{_subject_label(subject_kind)}/"
        f"{subject_id}/r{build_revision:03d}"
    )


def _frame_token(frame_index: int | None) -> str:
    return f"f{frame_index:06d}" if frame_index is not None else "funknown"


def _asset_key(
    *,
    base_prefix: str,
    sequence: int,
    asset_kind: EvidenceAssetKind,
    extension: str,
    frame_index: int | None = None,
    extra: str | None = None,
) -> str:
    suffix = f"_{_frame_token(frame_index)}" if frame_index is not None else ""
    if extra:
        suffix = f"{suffix}_{extra}"
    return f"{base_prefix}/{sequence:03d}_{asset_kind.value}{suffix}{extension}"


def _redacted_asset_key(asset_key: str) -> str:
    prefix, separator, extension = asset_key.rpartition(".")
    if separator:
        return f"{prefix}_redacted.{extension}"
    return f"{asset_key}_redacted"


def _planned_uri(storage_namespace: str, asset_key: str) -> str:
    return f"{storage_namespace}://{asset_key}"


def _candidate_frame_index(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _pick_first_by_time[T](items: list[T], *, occurred_at_getter: str) -> T | None:
    if not items:
        return None
    return min(items, key=lambda item: (getattr(item, occurred_at_getter), str(item.id)))


def _fps_hint(
    *, detection: DetectionEvent | None, violation: ViolationEvent | None
) -> float | None:
    for stream in (
        violation.stream if violation is not None else None,
        detection.stream if detection is not None else None,
    ):
        if stream is not None and stream.fps_hint is not None and stream.fps_hint > 0:
            return stream.fps_hint
    return None


def _resolve_violation_frame_index(
    *,
    violation: ViolationEvent,
    detection: DetectionEvent | None,
    plate_read: PlateRead | None,
) -> tuple[int | None, str]:
    metadata = violation.rule_metadata or {}
    explanation = (
        metadata.get("explanation") if isinstance(metadata.get("explanation"), dict) else {}
    )
    candidates = (
        (metadata.get("frame_index"), "violation_rule_frame_index"),
        (explanation.get("frame_index"), "violation_explanation_frame_index"),
        (detection.frame_index if detection is not None else None, "detection_event_frame_index"),
        (
            plate_read.ocr_metadata.get("frame_index")
            if plate_read is not None and isinstance(plate_read.ocr_metadata, dict)
            else None,
            "plate_read_frame_index",
        ),
    )
    for value, reason in candidates:
        frame_index = _candidate_frame_index(value)
        if frame_index is not None:
            return frame_index, reason
    return None, "timestamp_only"


def _resolve_detection_frame_index(
    *,
    detection: DetectionEvent,
    violation: ViolationEvent | None,
    plate_read: PlateRead | None,
) -> tuple[int | None, str]:
    metadata = violation.rule_metadata if violation is not None else {}
    candidates = (
        (detection.frame_index, "detection_event_frame_index"),
        (
            metadata.get("frame_index") if isinstance(metadata, dict) else None,
            "linked_violation_frame_index",
        ),
        (
            plate_read.ocr_metadata.get("frame_index")
            if plate_read is not None and isinstance(plate_read.ocr_metadata, dict)
            else None,
            "plate_read_frame_index",
        ),
    )
    for value, reason in candidates:
        frame_index = _candidate_frame_index(value)
        if frame_index is not None:
            return frame_index, reason
    return None, "timestamp_only"


def _frame_timestamp(
    *, occurred_at: datetime, relative_frame_offset: int, fps_hint: float | None
) -> datetime | None:
    if fps_hint is None or fps_hint <= 0:
        return None
    return occurred_at + timedelta(seconds=relative_frame_offset / fps_hint)


def _build_timeline(
    *,
    occurred_at: datetime,
    event_frame_index: int | None,
    fps_hint: float | None,
    selection_reason: str,
) -> tuple[EvidenceSelectionPolicy, EvidenceTimeline]:
    selection_policy = EvidenceSelectionPolicy(
        event_frame_index=event_frame_index,
        pre_event_frame_count=_DEFAULT_PRE_EVENT_FRAMES,
        post_event_frame_count=_DEFAULT_POST_EVENT_FRAMES,
        frame_step=_DEFAULT_FRAME_STEP,
        clip_lead_frames=_DEFAULT_CLIP_LEAD_FRAMES,
        clip_tail_frames=_DEFAULT_CLIP_TAIL_FRAMES,
        fps_hint=fps_hint,
        selection_reason=selection_reason,
    )

    selected_frames: list[EvidenceTimelineFrame] = []
    for offset in range(-_DEFAULT_PRE_EVENT_FRAMES, _DEFAULT_POST_EVENT_FRAMES + 1):
        role = EvidenceFrameRole.EVENT
        if offset < 0:
            role = EvidenceFrameRole.PRE_EVENT
        elif offset > 0:
            role = EvidenceFrameRole.POST_EVENT
        label = "event" if offset == 0 else f"{role.value}_{abs(offset):02d}"
        selected_frames.append(
            EvidenceTimelineFrame(
                role=role,
                label=label,
                frame_index=(event_frame_index + offset)
                if event_frame_index is not None
                else None,
                relative_frame_offset=offset,
                timestamp=_frame_timestamp(
                    occurred_at=occurred_at,
                    relative_frame_offset=offset,
                    fps_hint=fps_hint,
                ),
            )
        )

    clip_window = EvidenceClipWindow(
        start_frame_index=(event_frame_index - _DEFAULT_CLIP_LEAD_FRAMES)
        if event_frame_index is not None
        else None,
        end_frame_index=(event_frame_index + _DEFAULT_CLIP_TAIL_FRAMES)
        if event_frame_index is not None
        else None,
        lead_frames=_DEFAULT_CLIP_LEAD_FRAMES,
        tail_frames=_DEFAULT_CLIP_TAIL_FRAMES,
        fps_hint=fps_hint,
        approx_duration_ms=(
            int(((_DEFAULT_CLIP_LEAD_FRAMES + _DEFAULT_CLIP_TAIL_FRAMES + 1) / fps_hint) * 1000)
            if fps_hint is not None and fps_hint > 0
            else None
        ),
        generation_mode="placeholder",
    )

    timeline = EvidenceTimeline(
        occurred_at=occurred_at,
        event_frame_index=event_frame_index,
        selected_frames=selected_frames,
        clip_window=clip_window,
    )
    return selection_policy, timeline


def _extract_signal_overlay(rule_metadata: dict[str, Any]) -> dict[str, Any] | None:
    explanation = (
        rule_metadata.get("explanation")
        if isinstance(rule_metadata.get("explanation"), dict)
        else {}
    )
    details = explanation.get("details") if isinstance(explanation.get("details"), dict) else {}
    signal_overlay = {
        key: value
        for key in (
            "signal_state_at_decision",
            "signal_state_at_detection",
            "signal_phase",
            "signal_head_id",
            "signal_confidence",
            "signal_source_kind",
            "signal_observed_sources",
            "signal_conflict_reason",
            "signal_controller_id",
            "signal_junction_id",
            "signal_phase_id",
            "signal_integration_mode",
            "pedestrian_signal_state",
            "vehicle_signal_state",
        )
        if (value := details.get(key)) is not None
    }
    return signal_overlay or None


def _render_hints(
    *,
    detection: DetectionEvent | None,
    plate_read: PlateRead | None,
    rule_metadata: dict[str, Any],
) -> dict[str, Any]:
    explanation = (
        rule_metadata.get("explanation")
        if isinstance(rule_metadata.get("explanation"), dict)
        else {}
    )
    track_snapshot = (
        explanation.get("track_snapshot")
        if isinstance(explanation.get("track_snapshot"), dict)
        else {}
    )
    zone_info = (
        explanation.get("zone_info") if isinstance(explanation.get("zone_info"), dict) else {}
    )
    overlay_payloads: dict[str, Any] = {}

    if detection is not None and detection.bbox:
        overlay_payloads[EvidenceOverlayKind.BBOX.value] = {
            "detection_bbox": detection.bbox,
            "plate_bbox": plate_read.bbox if plate_read is not None else None,
        }
    elif track_snapshot.get("bbox") is not None:
        overlay_payloads[EvidenceOverlayKind.BBOX.value] = {
            "detection_bbox": track_snapshot.get("bbox")
        }

    if zone_info:
        overlay_payloads[EvidenceOverlayKind.ZONE.value] = zone_info

    track_path = None
    if detection is not None and isinstance(detection.event_payload, dict):
        track_path = detection.event_payload.get("track_path")
    if not track_path and isinstance(track_snapshot.get("trajectory"), list):
        track_path = track_snapshot.get("trajectory")
    if track_path:
        overlay_payloads[EvidenceOverlayKind.TRACK_PATH.value] = {
            "track_id": track_snapshot.get("track_id")
            or (detection.track_id if detection is not None else None),
            "points": track_path,
        }

    signal_overlay = _extract_signal_overlay(rule_metadata)
    if signal_overlay is not None:
        overlay_payloads[EvidenceOverlayKind.SIGNAL_STATE.value] = signal_overlay

    available_overlays = [key for key in overlay_payloads]
    return {
        "supported_overlays": [kind.value for kind in EvidenceOverlayKind],
        "available_overlays": available_overlays,
        "overlay_payloads": overlay_payloads,
    }


def _no_overlay_render_hints() -> dict[str, Any]:
    return {
        "supported_overlays": [kind.value for kind in EvidenceOverlayKind],
        "available_overlays": [],
        "overlay_payloads": {},
    }


def _build_asset(
    *,
    asset_kind: EvidenceAssetKind,
    label: str,
    asset_key: str,
    source_uri: str | None,
    available: bool,
    content_type: str | None,
    frame_index: int | None,
    metadata: dict[str, Any],
    render_hints: dict[str, Any],
    storage_namespace: str,
    force_uri: str | None = None,
    force_storage_state: EvidenceStorageState | None = None,
    asset_view: EvidenceAssetView = EvidenceAssetView.ORIGINAL,
    derived_from_asset_key: str | None = None,
    redaction_status: EvidenceRedactionStatus = EvidenceRedactionStatus.NOT_REQUIRED,
    redaction_targets: list[EvidenceRedactionTarget] | None = None,
) -> EvidenceAsset:
    return EvidenceAsset(
        asset_kind=asset_kind,
        label=label,
        asset_key=asset_key,
        asset_view=asset_view,
        uri=force_uri or (source_uri if available else _planned_uri(storage_namespace, asset_key)),
        source_uri=source_uri,
        storage_state=force_storage_state
        or (EvidenceStorageState.AVAILABLE if available else EvidenceStorageState.PLANNED),
        available=available,
        content_type=content_type,
        frame_index=frame_index,
        derived_from_asset_key=derived_from_asset_key,
        redaction_status=redaction_status,
        redaction_targets=list(redaction_targets or []),
        metadata=metadata,
        render_hints=render_hints,
    )


def _asset_redaction_targets(
    *,
    asset_kind: EvidenceAssetKind,
    detection: DetectionEvent | None,
    plate_read: PlateRead | None,
) -> list[EvidenceRedactionTarget]:
    targets: list[EvidenceRedactionTarget] = []
    object_class = detection.object_class.lower() if detection is not None else ""
    human_subject = object_class in {"person", "pedestrian", "face"}

    if asset_kind in {
        EvidenceAssetKind.KEY_FRAME_SNAPSHOT,
        EvidenceAssetKind.CLIP_WINDOW,
        EvidenceAssetKind.OBJECT_CROP,
    }:
        if human_subject:
            targets.extend(
                [
                    EvidenceRedactionTarget.FACE,
                    EvidenceRedactionTarget.PERSONALLY_IDENTIFYING_DETAIL,
                ]
            )
        elif asset_kind in {EvidenceAssetKind.KEY_FRAME_SNAPSHOT, EvidenceAssetKind.CLIP_WINDOW}:
            targets.append(EvidenceRedactionTarget.PERSONALLY_IDENTIFYING_DETAIL)

    if plate_read is not None and asset_kind in {
        EvidenceAssetKind.KEY_FRAME_SNAPSHOT,
        EvidenceAssetKind.CLIP_WINDOW,
        EvidenceAssetKind.OBJECT_CROP,
        EvidenceAssetKind.PLATE_CROP,
    }:
        targets.append(EvidenceRedactionTarget.LICENSE_PLATE)

    deduped: list[EvidenceRedactionTarget] = []
    for item in targets:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _build_redacted_asset(
    asset: EvidenceAsset,
    *,
    storage_namespace: str,
) -> EvidenceAsset:
    redacted_asset_key = _redacted_asset_key(asset.asset_key)
    metadata = dict(asset.metadata)
    if "plate_text" in metadata:
        metadata["plate_text"] = mask_plate_text(metadata.get("plate_text"))
    metadata["redaction_foundation"] = True
    metadata["source_asset_key"] = asset.asset_key

    if not asset.redaction_targets:
        return asset.model_copy(
            update={
                "asset_key": redacted_asset_key,
                "asset_view": EvidenceAssetView.REDACTED,
                "derived_from_asset_key": asset.asset_key,
                "redaction_status": EvidenceRedactionStatus.NOT_REQUIRED,
                "metadata": metadata,
                "uri": None if asset.storage_state == EvidenceStorageState.INLINE else asset.uri,
            }
        )

    if asset.storage_state == EvidenceStorageState.INLINE:
        return asset.model_copy(
            update={
                "asset_key": redacted_asset_key,
                "asset_view": EvidenceAssetView.REDACTED,
                "derived_from_asset_key": asset.asset_key,
                "redaction_status": EvidenceRedactionStatus.NOT_REQUIRED,
                "metadata": metadata,
            }
        )

    return asset.model_copy(
        update={
            "asset_key": redacted_asset_key,
            "asset_view": EvidenceAssetView.REDACTED,
            "uri": _planned_uri(storage_namespace, redacted_asset_key),
            "source_uri": None,
            "storage_state": EvidenceStorageState.PLANNED,
            "available": False,
            "derived_from_asset_key": asset.asset_key,
            "redaction_status": EvidenceRedactionStatus.PLANNED,
            "metadata": metadata,
        }
    )


def _manifest_read(
    manifest: EvidenceManifest,
    *,
    access_role: EvidenceAccessRole,
    requested_view: EvidenceAssetView | None,
) -> EvidenceManifestRead:
    document = EvidenceManifestDocument.model_validate(manifest.manifest_data)
    access = resolve_access_resolution(
        policy=document.privacy_policy,
        role=access_role,
        requested_view=requested_view,
    )
    visible_assets = resolve_visible_assets(document=document, access=access)
    sanitized_document = sanitize_manifest_for_access(document=document, access=access)
    if access.resolved_view == EvidenceAssetView.REDACTED and not visible_assets and document.assets:
        access = access.model_copy(
            update={
                "resolution_notes": [
                    *access.resolution_notes,
                    "Redacted asset variants have not been materialized for this manifest yet; original asset references remain hidden.",
                ]
            }
        )
        sanitized_document = sanitized_document.model_copy(
            update={
                "audit": {
                    **sanitized_document.audit,
                    "redacted_assets_materialized": False,
                }
            }
        )
    if access.resolved_view == EvidenceAssetView.REDACTED:
        sanitized_document = sanitized_document.model_copy(
            update={
                "subject": sanitized_document.subject.model_copy(
                    update={"plate_text": mask_plate_text(sanitized_document.subject.plate_text)}
                )
            }
        )
    return EvidenceManifestRead(
        id=manifest.id,
        subject_kind=manifest.subject_kind,
        subject_id=manifest.subject_id,
        manifest_key=manifest.manifest_key,
        build_revision=manifest.build_revision,
        camera_id=manifest.camera_id,
        stream_id=manifest.stream_id,
        zone_id=manifest.zone_id,
        detection_event_id=manifest.detection_event_id,
        violation_event_id=manifest.violation_event_id,
        plate_read_id=manifest.plate_read_id,
        evidence_registry_id=manifest.evidence_registry_id,
        occurred_at=manifest.occurred_at,
        event_frame_index=manifest.event_frame_index,
        storage_namespace=manifest.storage_namespace,
        manifest_uri=manifest.manifest_uri,
        manifest=sanitized_document,
        access=access,
        visible_assets=visible_assets,
        has_restricted_original_assets=(
            access.resolved_view == EvidenceAssetView.REDACTED
            and not access.original_access_authorized
            and bool(document.assets)
        ),
        created_at=manifest.created_at,
        updated_at=manifest.updated_at,
    )


def _with_evidence_provenance(
    document: EvidenceManifestDocument,
    *,
    evidence_provenance: dict[str, Any],
) -> EvidenceManifestDocument:
    return document.model_copy(
        update={
            "audit": {
                **document.audit,
                "provenance": {
                    "evidence": evidence_provenance,
                },
            }
        }
    )


def _statement_for_violation(violation_event_id: uuid.UUID) -> Select[tuple[ViolationEvent]]:
    return (
        select(ViolationEvent)
        .options(
            selectinload(ViolationEvent.camera),
            selectinload(ViolationEvent.stream),
            selectinload(ViolationEvent.zone),
            selectinload(ViolationEvent.detection_event).selectinload(DetectionEvent.stream),
            selectinload(ViolationEvent.plate_read),
        )
        .where(ViolationEvent.id == violation_event_id)
    )


def _statement_for_detection(detection_event_id: uuid.UUID) -> Select[tuple[DetectionEvent]]:
    return (
        select(DetectionEvent)
        .options(
            selectinload(DetectionEvent.camera),
            selectinload(DetectionEvent.stream),
            selectinload(DetectionEvent.zone),
            selectinload(DetectionEvent.plate_reads),
            selectinload(DetectionEvent.violation_events).selectinload(ViolationEvent.plate_read),
        )
        .where(DetectionEvent.id == detection_event_id)
    )


async def _get_manifest_row(
    session: AsyncSession,
    *,
    subject_kind: EvidenceSubjectKind,
    subject_id: uuid.UUID,
) -> EvidenceManifest | None:
    statement = select(EvidenceManifest).where(
        EvidenceManifest.subject_kind == subject_kind,
        EvidenceManifest.subject_id == subject_id,
    )
    return await session.scalar(statement)


def _require_manifest_access(
    *,
    access_role: EvidenceAccessRole,
    requested_view: EvidenceAssetView | None,
    subject_kind: EvidenceSubjectKind,
    subject_id: uuid.UUID,
    action: str,
) -> None:
    required_permissions = [AccessPermission.VIEW_REDACTED_EVIDENCE]
    if requested_view == EvidenceAssetView.ORIGINAL:
        required_permissions.append(AccessPermission.VIEW_UNREDACTED_EVIDENCE)

    require_permissions(
        context=resolve_access_context(access_role),
        required_permissions=required_permissions,
        resource=f"{subject_kind.value}_evidence",
        action=action,
        entity_id=str(subject_id),
    )


async def get_violation_evidence_manifest(
    session: AsyncSession,
    violation_event_id: uuid.UUID,
    *,
    access_role: EvidenceAccessRole = EvidenceAccessRole.OPERATOR,
    requested_view: EvidenceAssetView | None = None,
) -> EvidenceManifestRead | None:
    _require_manifest_access(
        access_role=access_role,
        requested_view=requested_view,
        subject_kind=EvidenceSubjectKind.VIOLATION_EVENT,
        subject_id=violation_event_id,
        action="retrieve evidence manifest",
    )
    manifest = await _get_manifest_row(
        session,
        subject_kind=EvidenceSubjectKind.VIOLATION_EVENT,
        subject_id=violation_event_id,
    )
    return (
        _manifest_read(
            manifest,
            access_role=access_role,
            requested_view=requested_view,
        )
        if manifest is not None
        else None
    )


async def get_detection_evidence_manifest(
    session: AsyncSession,
    detection_event_id: uuid.UUID,
    *,
    access_role: EvidenceAccessRole = EvidenceAccessRole.OPERATOR,
    requested_view: EvidenceAssetView | None = None,
) -> EvidenceManifestRead | None:
    _require_manifest_access(
        access_role=access_role,
        requested_view=requested_view,
        subject_kind=EvidenceSubjectKind.DETECTION_EVENT,
        subject_id=detection_event_id,
        action="retrieve evidence manifest",
    )
    manifest = await _get_manifest_row(
        session,
        subject_kind=EvidenceSubjectKind.DETECTION_EVENT,
        subject_id=detection_event_id,
    )
    return (
        _manifest_read(
            manifest,
            access_role=access_role,
            requested_view=requested_view,
        )
        if manifest is not None
        else None
    )


def _violation_manifest_document(
    *,
    violation: ViolationEvent,
    detection: DetectionEvent | None,
    plate_read: PlateRead | None,
    storage_namespace: str,
    build_revision: int,
) -> EvidenceManifestDocument:
    event_frame_index, selection_reason = _resolve_violation_frame_index(
        violation=violation,
        detection=detection,
        plate_read=plate_read,
    )
    fps_hint = _fps_hint(detection=detection, violation=violation)
    selection_policy, timeline = _build_timeline(
        occurred_at=violation.occurred_at,
        event_frame_index=event_frame_index,
        fps_hint=fps_hint,
        selection_reason=selection_reason,
    )
    frame_render_hints = _render_hints(
        detection=detection,
        plate_read=plate_read,
        rule_metadata=violation.rule_metadata or {},
    )
    crop_render_hints = _no_overlay_render_hints()

    base_prefix = _base_asset_prefix(
        camera_code=violation.camera.camera_code,
        occurred_at=violation.occurred_at,
        subject_kind=EvidenceSubjectKind.VIOLATION_EVENT,
        subject_id=violation.id,
        build_revision=build_revision,
    )
    key_frame_source = violation.evidence_image_uri or (
        detection.image_uri if detection is not None else None
    )
    object_crop_source = None
    if detection is not None and isinstance(detection.event_payload, dict):
        object_crop_source = detection.event_payload.get("object_crop_uri")
    plate_crop_source = plate_read.crop_image_uri if plate_read is not None else None
    clip_source = violation.evidence_video_uri or (
        detection.video_uri if detection is not None else None
    )

    subject = EvidenceSubjectRef(
        kind=EvidenceSubjectKind.VIOLATION_EVENT,
        subject_id=violation.id,
        camera_id=violation.camera_id,
        camera_code=violation.camera.camera_code,
        stream_id=violation.stream_id,
        zone_id=violation.zone_id,
        detection_event_id=violation.detection_event_id,
        violation_event_id=violation.id,
        plate_read_id=plate_read.id if plate_read is not None else violation.plate_read_id,
        track_id=(violation.rule_metadata or {}).get("track_id")
        or (detection.track_id if detection is not None else None),
        violation_type=violation.violation_type.value,
        object_class=detection.object_class if detection is not None else None,
        plate_text=plate_read.plate_text if plate_read is not None else None,
        occurred_at=violation.occurred_at,
    )

    timeline_asset_key = _asset_key(
        base_prefix=base_prefix,
        sequence=5,
        asset_kind=EvidenceAssetKind.TIMELINE_METADATA,
        extension=".json",
    )
    assets = [
        _build_asset(
            asset_kind=EvidenceAssetKind.KEY_FRAME_SNAPSHOT,
            label="event_key_frame",
            asset_key=_asset_key(
                base_prefix=base_prefix,
                sequence=1,
                asset_kind=EvidenceAssetKind.KEY_FRAME_SNAPSHOT,
                extension=".jpg",
                frame_index=event_frame_index,
            ),
            source_uri=key_frame_source,
            available=bool(key_frame_source),
            content_type="image/jpeg",
            frame_index=event_frame_index,
            metadata={
                "frame_role": EvidenceFrameRole.EVENT.value,
                "selection_reason": selection_reason,
            },
            render_hints=frame_render_hints,
            storage_namespace=storage_namespace,
            redaction_targets=_asset_redaction_targets(
                asset_kind=EvidenceAssetKind.KEY_FRAME_SNAPSHOT,
                detection=detection,
                plate_read=plate_read,
            ),
        ),
        _build_asset(
            asset_kind=EvidenceAssetKind.OBJECT_CROP,
            label="tracked_object_crop",
            asset_key=_asset_key(
                base_prefix=base_prefix,
                sequence=2,
                asset_kind=EvidenceAssetKind.OBJECT_CROP,
                extension=".jpg",
                frame_index=event_frame_index,
            ),
            source_uri=object_crop_source,
            available=bool(object_crop_source),
            content_type="image/jpeg",
            frame_index=event_frame_index,
            metadata={
                "bbox": detection.bbox if detection is not None else None,
                "track_id": subject.track_id,
            },
            render_hints=crop_render_hints,
            storage_namespace=storage_namespace,
            redaction_targets=_asset_redaction_targets(
                asset_kind=EvidenceAssetKind.OBJECT_CROP,
                detection=detection,
                plate_read=plate_read,
            ),
        ),
        _build_asset(
            asset_kind=EvidenceAssetKind.PLATE_CROP,
            label="plate_crop",
            asset_key=_asset_key(
                base_prefix=base_prefix,
                sequence=3,
                asset_kind=EvidenceAssetKind.PLATE_CROP,
                extension=".jpg",
                frame_index=event_frame_index,
            ),
            source_uri=plate_crop_source,
            available=bool(plate_crop_source),
            content_type="image/jpeg",
            frame_index=event_frame_index,
            metadata={
                "plate_text": plate_read.plate_text if plate_read is not None else None,
                "bbox": plate_read.bbox if plate_read is not None else None,
            },
            render_hints=crop_render_hints,
            storage_namespace=storage_namespace,
            redaction_targets=_asset_redaction_targets(
                asset_kind=EvidenceAssetKind.PLATE_CROP,
                detection=detection,
                plate_read=plate_read,
            ),
        ),
        _build_asset(
            asset_kind=EvidenceAssetKind.CLIP_WINDOW,
            label="review_clip_window",
            asset_key=_asset_key(
                base_prefix=base_prefix,
                sequence=4,
                asset_kind=EvidenceAssetKind.CLIP_WINDOW,
                extension=".mp4",
                extra=(
                    f"{_frame_token(timeline.clip_window.start_frame_index)}-{_frame_token(timeline.clip_window.end_frame_index)}"
                    if timeline.clip_window.start_frame_index is not None
                    or timeline.clip_window.end_frame_index is not None
                    else None
                ),
            ),
            source_uri=clip_source,
            available=bool(clip_source),
            content_type="video/mp4",
            frame_index=event_frame_index,
            metadata=timeline.clip_window.model_dump(mode="json"),
            render_hints=frame_render_hints,
            storage_namespace=storage_namespace,
            redaction_targets=_asset_redaction_targets(
                asset_kind=EvidenceAssetKind.CLIP_WINDOW,
                detection=detection,
                plate_read=plate_read,
            ),
        ),
        _build_asset(
            asset_kind=EvidenceAssetKind.TIMELINE_METADATA,
            label="timeline_metadata",
            asset_key=timeline_asset_key,
            source_uri=None,
            available=True,
            content_type="application/json",
            frame_index=event_frame_index,
            metadata={
                "selected_frames": [
                    item.model_dump(mode="json") for item in timeline.selected_frames
                ],
                "clip_window": timeline.clip_window.model_dump(mode="json"),
            },
            render_hints=_no_overlay_render_hints(),
            storage_namespace=storage_namespace,
            force_uri=None,
            force_storage_state=EvidenceStorageState.INLINE,
        ),
    ]
    redacted_assets = [_build_redacted_asset(asset, storage_namespace=storage_namespace) for asset in assets]

    return EvidenceManifestDocument(
        subject=subject,
        storage_namespace=storage_namespace,
        selection_policy=selection_policy,
        timeline=timeline,
        assets=assets,
        redacted_assets=redacted_assets,
        active_asset_view=EvidenceAssetView.ORIGINAL,
        original_asset_count=len(assets),
        redacted_asset_count=len(redacted_assets),
        audit={
            "generated_at": datetime.now(UTC),
            "generator": "trafficmind.evidence.service.v1",
            "build_revision": build_revision,
            "selection_reason": selection_reason,
            "privacy_foundation": True,
            "source_record_ids": {
                "violation_event_id": str(violation.id),
                "detection_event_id": str(detection.id) if detection is not None else None,
                "plate_read_id": str(plate_read.id) if plate_read is not None else None,
            },
        },
    )


def _detection_manifest_document(
    *,
    detection: DetectionEvent,
    violation: ViolationEvent | None,
    plate_read: PlateRead | None,
    storage_namespace: str,
    build_revision: int,
) -> EvidenceManifestDocument:
    event_frame_index, selection_reason = _resolve_detection_frame_index(
        detection=detection,
        violation=violation,
        plate_read=plate_read,
    )
    fps_hint = _fps_hint(detection=detection, violation=violation)
    selection_policy, timeline = _build_timeline(
        occurred_at=detection.occurred_at,
        event_frame_index=event_frame_index,
        fps_hint=fps_hint,
        selection_reason=selection_reason,
    )
    frame_render_hints = _render_hints(
        detection=detection,
        plate_read=plate_read,
        rule_metadata=violation.rule_metadata if violation is not None else {},
    )
    crop_render_hints = _no_overlay_render_hints()

    base_prefix = _base_asset_prefix(
        camera_code=detection.camera.camera_code,
        occurred_at=detection.occurred_at,
        subject_kind=EvidenceSubjectKind.DETECTION_EVENT,
        subject_id=detection.id,
        build_revision=build_revision,
    )
    key_frame_source = detection.image_uri or (
        plate_read.source_frame_uri if plate_read is not None else None
    )
    object_crop_source = None
    if isinstance(detection.event_payload, dict):
        object_crop_source = detection.event_payload.get("object_crop_uri")
    plate_crop_source = plate_read.crop_image_uri if plate_read is not None else None
    clip_source = detection.video_uri or (
        violation.evidence_video_uri if violation is not None else None
    )

    subject = EvidenceSubjectRef(
        kind=EvidenceSubjectKind.DETECTION_EVENT,
        subject_id=detection.id,
        camera_id=detection.camera_id,
        camera_code=detection.camera.camera_code,
        stream_id=detection.stream_id,
        zone_id=detection.zone_id,
        detection_event_id=detection.id,
        violation_event_id=violation.id if violation is not None else None,
        plate_read_id=plate_read.id if plate_read is not None else None,
        track_id=detection.track_id,
        violation_type=violation.violation_type.value if violation is not None else None,
        object_class=detection.object_class,
        plate_text=plate_read.plate_text if plate_read is not None else None,
        occurred_at=detection.occurred_at,
    )

    assets = [
        _build_asset(
            asset_kind=EvidenceAssetKind.KEY_FRAME_SNAPSHOT,
            label="event_key_frame",
            asset_key=_asset_key(
                base_prefix=base_prefix,
                sequence=1,
                asset_kind=EvidenceAssetKind.KEY_FRAME_SNAPSHOT,
                extension=".jpg",
                frame_index=event_frame_index,
            ),
            source_uri=key_frame_source,
            available=bool(key_frame_source),
            content_type="image/jpeg",
            frame_index=event_frame_index,
            metadata={
                "frame_role": EvidenceFrameRole.EVENT.value,
                "selection_reason": selection_reason,
            },
            render_hints=frame_render_hints,
            storage_namespace=storage_namespace,
            redaction_targets=_asset_redaction_targets(
                asset_kind=EvidenceAssetKind.KEY_FRAME_SNAPSHOT,
                detection=detection,
                plate_read=plate_read,
            ),
        ),
        _build_asset(
            asset_kind=EvidenceAssetKind.OBJECT_CROP,
            label="tracked_object_crop",
            asset_key=_asset_key(
                base_prefix=base_prefix,
                sequence=2,
                asset_kind=EvidenceAssetKind.OBJECT_CROP,
                extension=".jpg",
                frame_index=event_frame_index,
            ),
            source_uri=object_crop_source,
            available=bool(object_crop_source),
            content_type="image/jpeg",
            frame_index=event_frame_index,
            metadata={"bbox": detection.bbox, "track_id": detection.track_id},
            render_hints=crop_render_hints,
            storage_namespace=storage_namespace,
            redaction_targets=_asset_redaction_targets(
                asset_kind=EvidenceAssetKind.OBJECT_CROP,
                detection=detection,
                plate_read=plate_read,
            ),
        ),
        _build_asset(
            asset_kind=EvidenceAssetKind.PLATE_CROP,
            label="plate_crop",
            asset_key=_asset_key(
                base_prefix=base_prefix,
                sequence=3,
                asset_kind=EvidenceAssetKind.PLATE_CROP,
                extension=".jpg",
                frame_index=event_frame_index,
            ),
            source_uri=plate_crop_source,
            available=bool(plate_crop_source),
            content_type="image/jpeg",
            frame_index=event_frame_index,
            metadata={
                "plate_text": plate_read.plate_text if plate_read is not None else None,
                "bbox": plate_read.bbox if plate_read is not None else None,
            },
            render_hints=crop_render_hints,
            storage_namespace=storage_namespace,
            redaction_targets=_asset_redaction_targets(
                asset_kind=EvidenceAssetKind.PLATE_CROP,
                detection=detection,
                plate_read=plate_read,
            ),
        ),
        _build_asset(
            asset_kind=EvidenceAssetKind.CLIP_WINDOW,
            label="review_clip_window",
            asset_key=_asset_key(
                base_prefix=base_prefix,
                sequence=4,
                asset_kind=EvidenceAssetKind.CLIP_WINDOW,
                extension=".mp4",
                extra=(
                    f"{_frame_token(timeline.clip_window.start_frame_index)}-{_frame_token(timeline.clip_window.end_frame_index)}"
                    if timeline.clip_window.start_frame_index is not None
                    or timeline.clip_window.end_frame_index is not None
                    else None
                ),
            ),
            source_uri=clip_source,
            available=bool(clip_source),
            content_type="video/mp4",
            frame_index=event_frame_index,
            metadata=timeline.clip_window.model_dump(mode="json"),
            render_hints=frame_render_hints,
            storage_namespace=storage_namespace,
            redaction_targets=_asset_redaction_targets(
                asset_kind=EvidenceAssetKind.CLIP_WINDOW,
                detection=detection,
                plate_read=plate_read,
            ),
        ),
        _build_asset(
            asset_kind=EvidenceAssetKind.TIMELINE_METADATA,
            label="timeline_metadata",
            asset_key=_asset_key(
                base_prefix=base_prefix,
                sequence=5,
                asset_kind=EvidenceAssetKind.TIMELINE_METADATA,
                extension=".json",
            ),
            source_uri=None,
            available=True,
            content_type="application/json",
            frame_index=event_frame_index,
            metadata={
                "selected_frames": [
                    item.model_dump(mode="json") for item in timeline.selected_frames
                ],
                "clip_window": timeline.clip_window.model_dump(mode="json"),
            },
            render_hints=_no_overlay_render_hints(),
            storage_namespace=storage_namespace,
            force_uri=None,
            force_storage_state=EvidenceStorageState.INLINE,
        ),
    ]
    redacted_assets = [_build_redacted_asset(asset, storage_namespace=storage_namespace) for asset in assets]

    return EvidenceManifestDocument(
        subject=subject,
        storage_namespace=storage_namespace,
        selection_policy=selection_policy,
        timeline=timeline,
        assets=assets,
        redacted_assets=redacted_assets,
        active_asset_view=EvidenceAssetView.ORIGINAL,
        original_asset_count=len(assets),
        redacted_asset_count=len(redacted_assets),
        audit={
            "generated_at": datetime.now(UTC),
            "generator": "trafficmind.evidence.service.v1",
            "build_revision": build_revision,
            "selection_reason": selection_reason,
            "privacy_foundation": True,
            "source_record_ids": {
                "detection_event_id": str(detection.id),
                "violation_event_id": str(violation.id) if violation is not None else None,
                "plate_read_id": str(plate_read.id) if plate_read is not None else None,
            },
        },
    )


async def build_violation_evidence_manifest(
    session: AsyncSession,
    violation_event_id: uuid.UUID,
    *,
    storage_namespace: str = "evidence",
    rebuild: bool = False,
    access_role: EvidenceAccessRole = EvidenceAccessRole.OPERATOR,
    requested_view: EvidenceAssetView | None = None,
) -> EvidenceManifestRead:
    _require_manifest_access(
        access_role=access_role,
        requested_view=requested_view,
        subject_kind=EvidenceSubjectKind.VIOLATION_EVENT,
        subject_id=violation_event_id,
        action="build evidence manifest",
    )
    storage_namespace = _normalize_storage_namespace(storage_namespace)
    statement = _statement_for_violation(violation_event_id)
    violation = await session.scalar(statement)
    if violation is None:
        msg = "Violation event not found."
        raise EvidenceSubjectNotFoundError(msg)

    existing = await _get_manifest_row(
        session,
        subject_kind=EvidenceSubjectKind.VIOLATION_EVENT,
        subject_id=violation.id,
    )
    registry_entry = await _model_registry_service.ensure_entry(
        session,
        build_evidence_registry_spec(storage_namespace=storage_namespace),
    )
    if existing is not None and not rebuild:
        needs_manifest_backfill = False
        if existing.evidence_registry_id is None:
            existing.evidence_registry_id = registry_entry.id
            needs_manifest_backfill = True
        document = EvidenceManifestDocument.model_validate(existing.manifest_data)
        provenance = build_model_registry_provenance_snapshot(registry_entry)
        if document.audit.get("provenance") != {"evidence": provenance}:
            document = _with_evidence_provenance(document, evidence_provenance=provenance)
            existing.manifest_data = document.model_dump(mode="json")
            needs_manifest_backfill = True
        if needs_manifest_backfill:
            await session.flush()
        return _manifest_read(existing, access_role=access_role, requested_view=requested_view)

    detection = violation.detection_event
    plate_read = violation.plate_read
    if plate_read is None and detection is not None:
        plate_read = _pick_first_by_time(
            list(detection.plate_reads), occurred_at_getter="occurred_at"
        )

    build_revision = (existing.build_revision + 1) if existing is not None else 1
    document = _violation_manifest_document(
        violation=violation,
        detection=detection,
        plate_read=plate_read,
        storage_namespace=storage_namespace,
        build_revision=build_revision,
    )
    document = _with_evidence_provenance(
        document,
        evidence_provenance=build_model_registry_provenance_snapshot(registry_entry),
    )

    manifest = existing or EvidenceManifest(
        subject_kind=EvidenceSubjectKind.VIOLATION_EVENT,
        subject_id=violation.id,
        manifest_key=_manifest_key(EvidenceSubjectKind.VIOLATION_EVENT, violation.id),
        camera_id=violation.camera_id,
        violation_event_id=violation.id,
        occurred_at=violation.occurred_at,
    )
    manifest.build_revision = build_revision
    manifest.camera_id = violation.camera_id
    manifest.stream_id = violation.stream_id
    manifest.zone_id = violation.zone_id
    manifest.detection_event_id = (
        detection.id if detection is not None else violation.detection_event_id
    )
    manifest.violation_event_id = violation.id
    manifest.plate_read_id = plate_read.id if plate_read is not None else violation.plate_read_id
    manifest.evidence_registry_id = registry_entry.id
    manifest.occurred_at = violation.occurred_at
    manifest.event_frame_index = document.timeline.event_frame_index
    manifest.storage_namespace = storage_namespace
    manifest.manifest_data = document.model_dump(mode="json")

    if existing is None:
        session.add(manifest)
    await session.flush()
    manifest.manifest_uri = f"evidence-manifest://{manifest.id}"
    await session.flush()
    await session.refresh(manifest)
    return _manifest_read(manifest, access_role=access_role, requested_view=requested_view)


async def build_detection_evidence_manifest(
    session: AsyncSession,
    detection_event_id: uuid.UUID,
    *,
    storage_namespace: str = "evidence",
    rebuild: bool = False,
    access_role: EvidenceAccessRole = EvidenceAccessRole.OPERATOR,
    requested_view: EvidenceAssetView | None = None,
) -> EvidenceManifestRead:
    _require_manifest_access(
        access_role=access_role,
        requested_view=requested_view,
        subject_kind=EvidenceSubjectKind.DETECTION_EVENT,
        subject_id=detection_event_id,
        action="build evidence manifest",
    )
    storage_namespace = _normalize_storage_namespace(storage_namespace)
    statement = _statement_for_detection(detection_event_id)
    detection = await session.scalar(statement)
    if detection is None:
        msg = "Detection event not found."
        raise EvidenceSubjectNotFoundError(msg)

    existing = await _get_manifest_row(
        session,
        subject_kind=EvidenceSubjectKind.DETECTION_EVENT,
        subject_id=detection.id,
    )
    registry_entry = await _model_registry_service.ensure_entry(
        session,
        build_evidence_registry_spec(storage_namespace=storage_namespace),
    )
    if existing is not None and not rebuild:
        needs_manifest_backfill = False
        if existing.evidence_registry_id is None:
            existing.evidence_registry_id = registry_entry.id
            needs_manifest_backfill = True
        document = EvidenceManifestDocument.model_validate(existing.manifest_data)
        provenance = build_model_registry_provenance_snapshot(registry_entry)
        if document.audit.get("provenance") != {"evidence": provenance}:
            document = _with_evidence_provenance(document, evidence_provenance=provenance)
            existing.manifest_data = document.model_dump(mode="json")
            needs_manifest_backfill = True
        if needs_manifest_backfill:
            await session.flush()
        return _manifest_read(existing, access_role=access_role, requested_view=requested_view)

    violation = _pick_first_by_time(
        list(detection.violation_events), occurred_at_getter="occurred_at"
    )
    plate_read = _pick_first_by_time(list(detection.plate_reads), occurred_at_getter="occurred_at")
    if plate_read is None and violation is not None:
        plate_read = violation.plate_read

    build_revision = (existing.build_revision + 1) if existing is not None else 1
    document = _detection_manifest_document(
        detection=detection,
        violation=violation,
        plate_read=plate_read,
        storage_namespace=storage_namespace,
        build_revision=build_revision,
    )
    document = _with_evidence_provenance(
        document,
        evidence_provenance=build_model_registry_provenance_snapshot(registry_entry),
    )

    manifest = existing or EvidenceManifest(
        subject_kind=EvidenceSubjectKind.DETECTION_EVENT,
        subject_id=detection.id,
        manifest_key=_manifest_key(EvidenceSubjectKind.DETECTION_EVENT, detection.id),
        camera_id=detection.camera_id,
        detection_event_id=detection.id,
        occurred_at=detection.occurred_at,
    )
    manifest.build_revision = build_revision
    manifest.camera_id = detection.camera_id
    manifest.stream_id = detection.stream_id
    manifest.zone_id = detection.zone_id
    manifest.detection_event_id = detection.id
    manifest.violation_event_id = violation.id if violation is not None else None
    manifest.plate_read_id = plate_read.id if plate_read is not None else None
    manifest.evidence_registry_id = registry_entry.id
    manifest.occurred_at = detection.occurred_at
    manifest.event_frame_index = document.timeline.event_frame_index
    manifest.storage_namespace = storage_namespace
    manifest.manifest_data = document.model_dump(mode="json")

    if existing is None:
        session.add(manifest)
    await session.flush()
    manifest.manifest_uri = f"evidence-manifest://{manifest.id}"
    await session.flush()
    await session.refresh(manifest)
    return _manifest_read(manifest, access_role=access_role, requested_view=requested_view)
