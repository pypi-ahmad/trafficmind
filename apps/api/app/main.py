"""TrafficMind API — FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.app.api.router import v1_router
from apps.api.app.core.config import Settings, get_settings
from apps.api.app.core.logging import setup_logging
from apps.api.app.core.startup import build_api_readiness_report
from services.runtime import (
    RuntimeReadinessState,
    log_readiness_report,
    probe_database_connectivity,
)
from services.signals.config import get_signal_settings
from services.signals.integration import SignalIntegrationService
from services.streams.orchestrator import StreamOrchestrator

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown hooks."""
    settings: Settings = app.state.settings
    logger.info(
        "Starting %s v%s [%s]",
        settings.app_name,
        settings.version,
        settings.environment,
    )
    logger.info("Enabled modules: %s", settings.enabled_modules)

    database_connected, database_detail = await probe_database_connectivity(
        settings.database_url
    )
    startup_report = build_api_readiness_report(
        settings,
        database_connected=database_connected,
        database_detail=database_detail,
    )
    app.state.startup_readiness_report = startup_report
    log_readiness_report(logger, startup_report)
    if settings.strict_startup_checks and startup_report.status == RuntimeReadinessState.NOT_READY:
        raise RuntimeError("API startup readiness checks failed under strict mode.")

    orchestrator = StreamOrchestrator()
    app.state.orchestrator = orchestrator
    logger.info(
        "Stream orchestrator ready (max_concurrent=%d)",
        orchestrator.settings.max_concurrent_jobs,
    )

    yield

    logger.info("Stopping stream orchestrator…")
    await orchestrator.stop_all()
    logger.info("Shutting down %s", settings.app_name)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and return the FastAPI application instance."""
    resolved_settings = settings if settings is not None else get_settings()
    setup_logging(resolved_settings)

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.version,
        docs_url=resolved_settings.docs_url,
        redoc_url=resolved_settings.redoc_url,
        openapi_url=resolved_settings.openapi_url,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    signal_settings = get_signal_settings()
    app.state.signal_integration_service = SignalIntegrationService(
        vision_min_confidence=signal_settings.confidence_threshold,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(v1_router, prefix=resolved_settings.api_prefix)

    return app


app = create_app()
