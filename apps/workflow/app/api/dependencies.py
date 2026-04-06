"""FastAPI dependencies for the workflow service."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from apps.workflow.app.workflows.service import WorkflowService


def get_workflow_service(request: Request) -> WorkflowService:
    """Return the application-scoped workflow service."""

    return request.app.state.workflow_service


WorkflowServiceDep = Annotated[WorkflowService, Depends(get_workflow_service)]