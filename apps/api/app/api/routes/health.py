"""Health, info, and public-config endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from apps.api.app.core.config import Settings, get_settings
from apps.api.app.core.startup import build_api_readiness_report
from apps.api.app.schemas.health import (
    HealthResponse,
    InfoResponse,
    PublicConfigResponse,
    RuntimeReadinessReport,
)
from services.runtime import probe_database_connectivity

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@router.get("/health/ready", response_model=RuntimeReadinessReport)
async def readiness(
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    database_connected, database_detail = await probe_database_connectivity(settings.database_url)
    report = build_api_readiness_report(
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


@router.get("/info", response_model=InfoResponse)
async def info(settings: Annotated[Settings, Depends(get_settings)]) -> InfoResponse:
    return InfoResponse(
        app_name=settings.app_name,
        version=settings.version,
        environment=settings.environment,
        api_prefix=settings.api_prefix,
        enabled_modules=settings.enabled_modules,
        docs_url=settings.docs_url,
    )


@router.get("/config/public", response_model=PublicConfigResponse)
async def public_config(
    settings: Annotated[Settings, Depends(get_settings)],
) -> PublicConfigResponse:
    return PublicConfigResponse(
        environment=settings.environment,
        api_prefix=settings.api_prefix,
        allowed_origins=settings.allowed_origins,
        enable_vision=settings.enable_vision,
        enable_tracking=settings.enable_tracking,
        enable_ocr=settings.enable_ocr,
        enable_rules=settings.enable_rules,
        enable_workflow=settings.enable_workflow,
    )
