"""Startup and preflight checks for stream workers."""

from __future__ import annotations

from services.runtime import (
    RuntimeCheck,
    RuntimeCheckSeverity,
    RuntimeReadinessReport,
    build_readiness_report,
    is_production_like_environment,
)
from services.streams.config import StreamSettings
from services.vision.config import VisionSettings


def build_stream_startup_report(
    settings: StreamSettings,
    *,
    detection_enabled: bool,
    tracking_enabled: bool,
    ocr_enabled: bool,
    require_model_files: bool,
    vision_settings: VisionSettings | None = None,
) -> RuntimeReadinessReport:
    checks: list[RuntimeCheck] = []
    resolved_vision_settings = vision_settings or VisionSettings()

    checks.append(
        RuntimeCheck(
            code="stream_environment",
            severity=RuntimeCheckSeverity.INFO,
            message=(
                "Stream worker environment resolved to "
                f"{settings.environment} with log level {settings.log_level}."
            ),
        )
    )

    if detection_enabled and not resolved_vision_settings.yolo_model_path.exists():
        checks.append(
            RuntimeCheck(
                code="vision_model_path",
                severity=RuntimeCheckSeverity.ERROR
                if require_model_files
                else RuntimeCheckSeverity.WARNING,
                message="The configured YOLO model path does not exist.",
                detail=(
                    "Detection-enabled worker runs require the model file "
                    "before the pipeline can start successfully."
                ),
            )
        )

    if tracking_enabled and not detection_enabled:
        checks.append(
            RuntimeCheck(
                code="tracking_without_detection",
                severity=RuntimeCheckSeverity.WARNING,
                message="Tracking is enabled while detection is disabled.",
                detail=(
                    "This CLI path expects detector output upstream; disable "
                    "tracking as well unless you are injecting detections "
                    "externally."
                ),
            )
        )

    if ocr_enabled and not detection_enabled:
        checks.append(
            RuntimeCheck(
                code="ocr_without_detection",
                severity=RuntimeCheckSeverity.WARNING,
                message="OCR is enabled while detection is disabled.",
                detail=(
                    "Plate OCR currently depends on upstream detection crops "
                    "in the stream pipeline."
                ),
            )
        )

    if is_production_like_environment(settings.environment):
        checks.append(
            RuntimeCheck(
                code="worker_mode",
                severity=RuntimeCheckSeverity.WARNING,
                message=(
                    "The stream worker still runs as a local-process CLI in a "
                    "staging/prod-like environment."
                ),
                detail=(
                    "This repository does not yet ship a hardened worker "
                    "supervisor or orchestrator deployment stack."
                ),
            )
        )

    return build_readiness_report(
        service="streams", environment=settings.environment, checks=checks
    )
