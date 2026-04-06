"""Startup and readiness checks for the API service."""

from __future__ import annotations

from apps.api.app.core.config import Settings
from services.runtime import (
    RuntimeCheck,
    RuntimeCheckSeverity,
    RuntimeReadinessReport,
    build_readiness_report,
    database_backend_label,
    is_local_url,
    is_production_like_environment,
)


def build_api_readiness_report(
    settings: Settings,
    *,
    database_connected: bool | None = None,
    database_detail: str | None = None,
) -> RuntimeReadinessReport:
    checks: list[RuntimeCheck] = []
    production_like = is_production_like_environment(settings.environment)
    backend = database_backend_label(settings.database_url)

    checks.append(
        RuntimeCheck(
            code="database_backend",
            severity=(
                RuntimeCheckSeverity.ERROR
                if production_like and backend == "sqlite"
                else RuntimeCheckSeverity.INFO
            ),
            message=(
                "SQLite is configured for a staging/prod-like API environment."
                if production_like and backend == "sqlite"
                else f"API database backend resolved to {backend}."
            ),
            detail=(
                "Use a server-backed database such as PostgreSQL before "
                "treating this deployment as staging or production ready."
                if production_like and backend == "sqlite"
                else None
            ),
        )
    )

    if settings.debug and production_like:
        checks.append(
            RuntimeCheck(
                code="debug_mode",
                severity=RuntimeCheckSeverity.ERROR,
                message="Debug mode is enabled in a staging/prod-like API environment.",
                detail=(
                    "Disable debug mode before using strict startup checks "
                    "outside local development."
                ),
            )
        )

    if not settings.allowed_origins:
        checks.append(
            RuntimeCheck(
                code="cors_origins",
                severity=RuntimeCheckSeverity.WARNING,
                message="No allowed CORS origins are configured for the API.",
                detail=(
                    "Browser clients will fail until "
                    "TRAFFICMIND_ALLOWED_ORIGINS or ALLOWED_ORIGINS is set."
                ),
            )
        )
    elif production_like and any(is_local_url(origin) for origin in settings.allowed_origins):
        checks.append(
            RuntimeCheck(
                code="cors_localhost",
                severity=RuntimeCheckSeverity.WARNING,
                message=(
                    "Localhost origins are still present in a staging/prod-like API environment."
                ),
                detail="Tighten TRAFFICMIND_ALLOWED_ORIGINS for non-local deployments.",
            )
        )

    if settings.enable_vision and not settings.yolo_model_path.exists():
        checks.append(
            RuntimeCheck(
                code="vision_model_path",
                severity=RuntimeCheckSeverity.WARNING,
                message="The configured YOLO model path does not exist.",
                detail=(
                    "The API can still serve storage-backed routes, but worker "
                    "startup will fail until the model file is present."
                ),
            )
        )

    if not settings.evaluation_fixture_suite_path.exists():
        checks.append(
            RuntimeCheck(
                code="evaluation_fixture_suite",
                severity=RuntimeCheckSeverity.WARNING,
                message="The configured evaluation fixture suite path does not exist.",
                detail="The evaluation summary route will fall back to stored artifacts only.",
            )
        )

    if database_connected is not None:
        checks.append(
            RuntimeCheck(
                code="database_connectivity",
                severity=RuntimeCheckSeverity.INFO
                if database_connected
                else RuntimeCheckSeverity.ERROR,
                message=(
                    database_detail or "Database connectivity probe succeeded."
                    if database_connected
                    else database_detail or "Database connectivity probe failed."
                ),
            )
        )

    return build_readiness_report(service="api", environment=settings.environment, checks=checks)
