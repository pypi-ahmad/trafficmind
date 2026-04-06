"""FastAPI entrypoint for the TrafficMind workflow service."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from apps.api.app.db.session import get_session_factory
from apps.workflow.app.api.router import router as workflow_router
from apps.workflow.app.core.config import Settings, get_settings
from apps.workflow.app.core.logging import configure_logging
from apps.workflow.app.core.startup import build_workflow_readiness_report
from apps.workflow.app.workflows.repository import SqlAlchemyWorkflowRepository
from apps.workflow.app.workflows.service import WorkflowService
from services.runtime import (
    RuntimeReadinessState,
    log_readiness_report,
    probe_database_connectivity,
)

logger = logging.getLogger(__name__)


def build_workflow_service(settings: Settings) -> WorkflowService:
    """Construct the application-scoped workflow service."""

    session_factory = get_session_factory(settings.database_url)
    repository = SqlAlchemyWorkflowRepository(session_factory)
    return WorkflowService(repository=repository, settings=settings)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    database_connected, database_detail = await probe_database_connectivity(
        settings.database_url
    )
    startup_report = build_workflow_readiness_report(
        settings,
        database_connected=database_connected,
        database_detail=database_detail,
    )
    app.state.startup_readiness_report = startup_report
    log_readiness_report(logger, startup_report)
    if settings.strict_startup_checks and startup_report.status == RuntimeReadinessState.NOT_READY:
        raise RuntimeError("Workflow startup readiness checks failed under strict mode.")
    yield


def create_app(
    service: WorkflowService | None = None, settings: Settings | None = None
) -> FastAPI:
    """Create the workflow FastAPI application."""

    resolved_settings = settings if settings is not None else get_settings()
    configure_logging(resolved_settings.log_level)
    workflow_service = service or build_workflow_service(resolved_settings)

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.version,
        debug=resolved_settings.debug,
        docs_url=resolved_settings.docs_url,
        openapi_url=resolved_settings.openapi_url,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.workflow_service = workflow_service
    app.include_router(workflow_router, prefix=resolved_settings.api_prefix)
    return app


app = create_app()
