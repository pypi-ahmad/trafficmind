"""Helpers for deriving audit-friendly registry specs from current runtime settings."""

from __future__ import annotations

from pathlib import Path

from services.model_registry.schemas import ModelRegistrySpec, ModelRegistryTaskType
from services.ocr.config import OcrSettings, get_ocr_settings
from services.rules.config import RulesSettings, get_rules_settings
from services.rules.schemas import ViolationRecord
from services.tracking.config import TrackingSettings, get_tracking_settings
from services.vision.config import VisionSettings, get_vision_settings


def _path_name(value: Path | None) -> str | None:
    return value.name if value is not None else None


def build_detector_registry_spec(settings: VisionSettings | None = None) -> ModelRegistrySpec:
    current = settings or get_vision_settings()
    return ModelRegistrySpec(
        task_type=ModelRegistryTaskType.DETECTION_MODEL,
        model_family="yolo",
        version_name=current.yolo_model_path.name,
        config_bundle={
            **current.model_dump(mode="json"),
            "backend": "yolo",
            "resolved_device": current.resolve_device(),
            "model_path": str(current.yolo_model_path),
        },
        notes="Auto-derived from the current vision inference runtime settings.",
        entry_metadata={"auto_generated": True, "source": "vision_settings"},
    )


def build_tracking_registry_spec(settings: TrackingSettings | None = None) -> ModelRegistrySpec:
    current = settings or get_tracking_settings()
    return ModelRegistrySpec(
        task_type=ModelRegistryTaskType.TRACKING_CONFIG,
        model_family=current.backend,
        version_name="trafficmind.tracking.runtime.v1",
        config_bundle={
            **current.model_dump(mode="json"),
            "runtime_version": "trafficmind.tracking.runtime.v1",
        },
        notes="Auto-derived from the current tracking runtime settings.",
        entry_metadata={"auto_generated": True, "source": "tracking_settings"},
    )


def build_ocr_registry_spec(settings: OcrSettings | None = None) -> ModelRegistrySpec:
    current = settings or get_ocr_settings()
    version_name = _path_name(current.model_dir) or "runtime-default"
    return ModelRegistrySpec(
        task_type=ModelRegistryTaskType.OCR_MODEL,
        model_family=current.backend,
        version_name=version_name,
        config_bundle={
            **current.model_dump(mode="json"),
            "resolved_use_gpu": current.resolve_use_gpu(),
            "resolved_device": current.resolve_device(),
        },
        notes="Auto-derived from the current OCR runtime settings.",
        entry_metadata={"auto_generated": True, "source": "ocr_settings"},
    )


def build_rules_registry_spec(
    record: ViolationRecord,
    settings: RulesSettings | None = None,
) -> ModelRegistrySpec:
    current = settings or get_rules_settings()
    return ModelRegistrySpec(
        task_type=ModelRegistryTaskType.RULES_CONFIG,
        model_family=f"traffic_rules_engine:{record.rule_type.value}",
        version_name="trafficmind.rules.runtime.v1",
        config_bundle={
            "runtime_version": "trafficmind.rules.runtime.v1",
            "engine_settings": current.model_dump(mode="json"),
            "rule_type": record.rule_type.value,
            "rule_config": record.explanation.rule_config,
        },
        notes="Derived from the current rules-engine settings and the confirmed rule bundle on the emitted violation.",
        entry_metadata={"auto_generated": True, "source": "rules_engine"},
    )


def build_evidence_registry_spec(*, storage_namespace: str) -> ModelRegistrySpec:
    from services.evidence.schemas import EvidencePrivacyPolicy

    policy = EvidencePrivacyPolicy()
    return ModelRegistrySpec(
        task_type=ModelRegistryTaskType.EVIDENCE_CONFIG,
        model_family="evidence_manifest_builder",
        version_name="trafficmind.evidence.service.v1",
        config_bundle={
            "storage_namespace": storage_namespace,
            "privacy_policy_name": policy.policy_name,
            "default_asset_view": policy.default_asset_view.value,
            "default_export_view": policy.default_export_view.value,
            "preserve_original_assets": policy.preserve_original_assets,
            "redaction_targets": [target.value for target in policy.redaction_targets],
        },
        notes="Auto-derived from the evidence manifest builder defaults and privacy policy.",
        entry_metadata={"auto_generated": True, "source": "evidence_service"},
    )
