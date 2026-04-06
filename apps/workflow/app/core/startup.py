"""Startup and readiness checks for the workflow service."""

from __future__ import annotations

from apps.workflow.app.core.config import Settings
from services.runtime import (
    RuntimeCheck,
    RuntimeCheckSeverity,
    RuntimeReadinessReport,
    build_readiness_report,
    database_backend_label,
    is_production_like_environment,
)


def build_workflow_readiness_report(
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
                "SQLite is configured for a staging/prod-like workflow environment."
                if production_like and backend == "sqlite"
                else f"Workflow database backend resolved to {backend}."
            ),
            detail=(
                "Use a server-backed database before treating this workflow "
                "deployment as staging or production ready."
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
                message="Debug mode is enabled in a staging/prod-like workflow environment.",
            )
        )

    if production_like and settings.checkpoint_backend == "memory":
        checks.append(
            RuntimeCheck(
                code="checkpoint_backend",
                severity=RuntimeCheckSeverity.ERROR,
                message=(
                    "The workflow service still uses in-memory checkpoints in a "
                    "staging/prod-like environment."
                ),
                detail=(
                    "Resume currently works only within a single running process. "
                    "Persistent checkpoint storage is still required for "
                    "production readiness."
                ),
            )
        )
    else:
        checks.append(
            RuntimeCheck(
                code="checkpoint_backend",
                severity=RuntimeCheckSeverity.INFO,
                message=f"Workflow checkpoint backend resolved to {settings.checkpoint_backend}.",
            )
        )

    if production_like:
        checks.append(
            RuntimeCheck(
                code="provider_backend",
                severity=RuntimeCheckSeverity.WARNING,
                message=(
                    "The workflow service still runs the deterministic heuristic "
                    "provider in a staging/prod-like environment."
                ),
                detail=(
                    "This is supported and honest, but it is not a model-backed "
                    "reasoning deployment."
                ),
            )
        )
    else:
        checks.append(
            RuntimeCheck(
                code="provider_backend",
                severity=RuntimeCheckSeverity.INFO,
                message=f"Workflow provider backend resolved to {settings.provider_backend}.",
            )
        )

    if settings.openai_api_key:
        checks.append(
            RuntimeCheck(
                code="unused_openai_api_key",
                severity=RuntimeCheckSeverity.WARNING,
                message=(
                    "OPENAI_API_KEY is set, but the workflow service only supports "
                    "the heuristic backend today."
                ),
                detail=(
                    "Keep the secret out of local env files unless and until a "
                    "model-backed provider is added."
                ),
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

    return build_readiness_report(
        service="workflow", environment=settings.environment, checks=checks
    )
