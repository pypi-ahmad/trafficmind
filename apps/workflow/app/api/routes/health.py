"""Health and info endpoints for the workflow service."""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from apps.workflow.app.core.startup import build_workflow_readiness_report
from services.runtime import RuntimeReadinessReport, probe_database_connectivity

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", response_model=RuntimeReadinessReport)
async def readiness(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    database_connected, database_detail = await probe_database_connectivity(settings.database_url)
    report = build_workflow_readiness_report(
        settings,
        database_connected=database_connected,
        database_detail=database_detail,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK
        if report.status == "ready"
        else status.HTTP_503_SERVICE_UNAVAILABLE,
        content=report.model_dump(mode="json"),
    )


@router.get("/info")
async def info(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    service = request.app.state.workflow_service
    return {
        "app_name": settings.app_name,
        "version": settings.version,
        "environment": settings.environment,
        "provider_backend": service.provider_backend,
        "checkpoint_backend": service.checkpoint_backend,
        "durability_note": service.durability_note,
        "docs_url": settings.docs_url,
    }
