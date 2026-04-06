"""Top-level router for the workflow service."""

from fastapi import APIRouter

from apps.workflow.app.api.routes import health, workflows

router = APIRouter()
router.include_router(health.router)
router.include_router(workflows.router)