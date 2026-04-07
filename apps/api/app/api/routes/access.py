"""Access-control policy preview endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Query

from apps.api.app.schemas.access import (
    AccessPolicyRead,
    AccessRequirementRead,
    AccessRolePermissionRead,
)
from services.access_control.policy import (
    AccessPermission,
    get_access_policy_definition,
    resolve_access_context,
)
from services.evidence.schemas import EvidenceAccessRole

router = APIRouter(prefix="/access", tags=["access"])


@router.get("/policy", response_model=AccessPolicyRead)
async def get_access_policy(
    access_role: EvidenceAccessRole = Query(
        EvidenceAccessRole.OPERATOR,
        description="Request-declared role used to preview the effective permission set",
    ),
) -> AccessPolicyRead:
    policy = get_access_policy_definition()
    context = resolve_access_context(access_role)
    return AccessPolicyRead(
        policy_name=policy.policy_name,
        current_role=context.role,
        current_permissions=context.permissions,
        roles=[
            AccessRolePermissionRead(
                role=mapping.role,
                permissions=mapping.permissions,
                description=mapping.description,
            )
            for mapping in policy.mappings
        ],
        requirements=[
            AccessRequirementRead(
                action="view redacted evidence",
                permissions=[AccessPermission.VIEW_REDACTED_EVIDENCE],
                note="Required for standard evidence API reads.",
            ),
            AccessRequirementRead(
                action="view unredacted evidence",
                permissions=[AccessPermission.VIEW_UNREDACTED_EVIDENCE],
                note="Required before the request can even ask for original evidence references.",
            ),
            AccessRequirementRead(
                action="export evidence",
                permissions=[AccessPermission.EXPORT_EVIDENCE],
                note="Required for creating, listing, retrieving, and downloading case exports.",
            ),
            AccessRequirementRead(
                action="approve or reject incidents",
                permissions=[AccessPermission.APPROVE_REJECT_INCIDENTS],
                note="Required for explicit violation review actions.",
            ),
            AccessRequirementRead(
                action="manage watchlists",
                permissions=[AccessPermission.MANAGE_WATCHLISTS],
                note="Required for watchlist CRUD and manual watchlist checks.",
            ),
            AccessRequirementRead(
                action="manage policy settings",
                permissions=[AccessPermission.MANAGE_POLICY_SETTINGS],
                note="Required for alert routing target and policy management endpoints.",
            ),
            AccessRequirementRead(
                action="manage model registry",
                permissions=[AccessPermission.MANAGE_MODEL_REGISTRY],
                note="Required for creating or updating model/config registry entries.",
            ),
            AccessRequirementRead(
                action="view sensitive audit trail",
                permissions=[AccessPermission.VIEW_SENSITIVE_AUDIT_TRAIL],
                note="Controls review identities, workflow decisions, export audit events, and similar audit-facing details.",
            ),
        ],
        notes=policy.notes,
    )
