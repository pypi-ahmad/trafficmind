"""Helpers for turning access-control service errors into readable route behavior."""

from __future__ import annotations

from fastapi import HTTPException, status

from services.access_control.policy import (
    AccessContext,
    AccessDeniedError,
    AccessPermission,
    audit_sensitive_access,
    require_permissions,
    resolve_access_context,
)
from services.evidence.schemas import EvidenceAccessRole


def enforce_route_permissions(
    *,
    role: EvidenceAccessRole,
    required_permissions: list[AccessPermission],
    resource: str,
    action: str,
    entity_id: str | None = None,
    audit_details: dict | None = None,
) -> AccessContext:
    context = resolve_access_context(role)
    try:
        require_permissions(
            context=context,
            required_permissions=required_permissions,
            resource=resource,
            action=action,
            entity_id=entity_id,
        )
    except AccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    audit_sensitive_access(
        context=context,
        action=action,
        resource=resource,
        entity_id=entity_id,
        outcome="allowed",
        details=audit_details,
    )
    return context
