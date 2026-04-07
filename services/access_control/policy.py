"""Small, explicit access-control policy foundation.

This repo does not yet implement a full identity provider or user/session model.
Instead, routes and services resolve a request-declared role into a stable set of
permissions, then combine those permissions with resource-specific policy checks.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from services.evidence.schemas import EvidenceAccessRole

_audit_logger = logging.getLogger("trafficmind.access.audit")


class AccessPermission(StrEnum):
    VIEW_REDACTED_EVIDENCE = "view_redacted_evidence"
    VIEW_UNREDACTED_EVIDENCE = "view_unredacted_evidence"
    EXPORT_EVIDENCE = "export_evidence"
    APPROVE_REJECT_INCIDENTS = "approve_reject_incidents"
    MANAGE_WATCHLISTS = "manage_watchlists"
    MANAGE_POLICY_SETTINGS = "manage_policy_settings"
    MANAGE_MODEL_REGISTRY = "manage_model_registry"
    VIEW_SENSITIVE_AUDIT_TRAIL = "view_sensitive_audit_trail"


class AccessDeniedError(Exception):
    """Raised when the resolved role lacks one or more required permissions."""


class AccessContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: EvidenceAccessRole
    permissions: list[AccessPermission] = Field(default_factory=list)
    policy_name: str = "default_access_control_v1"
    notes: list[str] = Field(default_factory=list)

    def has_permission(self, permission: AccessPermission) -> bool:
        return permission in self.permissions


class RolePermissionMapping(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: EvidenceAccessRole
    permissions: list[AccessPermission] = Field(default_factory=list)
    description: str | None = None


class AccessPolicyDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy_name: str = "default_access_control_v1"
    mappings: list[RolePermissionMapping] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


_DEFAULT_POLICY = AccessPolicyDefinition(
    mappings=[
        RolePermissionMapping(
            role=EvidenceAccessRole.OPERATOR,
            permissions=[AccessPermission.VIEW_REDACTED_EVIDENCE],
            description="Operator-facing role with redacted evidence only.",
        ),
        RolePermissionMapping(
            role=EvidenceAccessRole.REVIEWER,
            permissions=[
                AccessPermission.VIEW_REDACTED_EVIDENCE,
                AccessPermission.APPROVE_REJECT_INCIDENTS,
                AccessPermission.VIEW_SENSITIVE_AUDIT_TRAIL,
            ],
            description="Reviewer can adjudicate incidents but not export or view original media.",
        ),
        RolePermissionMapping(
            role=EvidenceAccessRole.SUPERVISOR,
            permissions=[
                AccessPermission.VIEW_REDACTED_EVIDENCE,
                AccessPermission.EXPORT_EVIDENCE,
                AccessPermission.APPROVE_REJECT_INCIDENTS,
                AccessPermission.MANAGE_WATCHLISTS,
                AccessPermission.VIEW_SENSITIVE_AUDIT_TRAIL,
            ],
            description="Supervisor can export cases, review incidents, and operate watchlists.",
        ),
        RolePermissionMapping(
            role=EvidenceAccessRole.PRIVACY_OFFICER,
            permissions=[
                AccessPermission.VIEW_REDACTED_EVIDENCE,
                AccessPermission.VIEW_UNREDACTED_EVIDENCE,
                AccessPermission.EXPORT_EVIDENCE,
                AccessPermission.VIEW_SENSITIVE_AUDIT_TRAIL,
            ],
            description="Privacy officer can access original evidence and export it, but does not manage policies by default.",
        ),
        RolePermissionMapping(
            role=EvidenceAccessRole.EVIDENCE_ADMIN,
            permissions=[
                AccessPermission.VIEW_REDACTED_EVIDENCE,
                AccessPermission.VIEW_UNREDACTED_EVIDENCE,
                AccessPermission.EXPORT_EVIDENCE,
                AccessPermission.APPROVE_REJECT_INCIDENTS,
                AccessPermission.MANAGE_WATCHLISTS,
                AccessPermission.MANAGE_POLICY_SETTINGS,
                AccessPermission.MANAGE_MODEL_REGISTRY,
                AccessPermission.VIEW_SENSITIVE_AUDIT_TRAIL,
            ],
            description="Evidence admin has the full current permission set for this foundation.",
        ),
        RolePermissionMapping(
            role=EvidenceAccessRole.EXPORT_SERVICE,
            permissions=[
                AccessPermission.VIEW_REDACTED_EVIDENCE,
                AccessPermission.EXPORT_EVIDENCE,
            ],
            description="Service role for automated redacted export generation.",
        ),
    ],
    notes=[
        "This policy foundation reuses EvidenceAccessRole as the current request-declared actor role enum until a dedicated auth/user model exists.",
        "Permissions are intentionally coarse-grained so the model stays maintainable until a real IAM layer is introduced.",
        "Role-derived permissions are enforced in the backend; frontend policy previews are explanatory only.",
    ],
)


def get_access_policy_definition() -> AccessPolicyDefinition:
    return _DEFAULT_POLICY


def resolve_access_context(role: EvidenceAccessRole) -> AccessContext:
    for mapping in _DEFAULT_POLICY.mappings:
        if mapping.role == role:
            return AccessContext(
                role=role,
                permissions=list(mapping.permissions),
                policy_name=_DEFAULT_POLICY.policy_name,
                notes=list(_DEFAULT_POLICY.notes),
            )
    return AccessContext(role=role, permissions=[], policy_name=_DEFAULT_POLICY.policy_name, notes=list(_DEFAULT_POLICY.notes))


def audit_sensitive_access(
    *,
    context: AccessContext,
    action: str,
    resource: str,
    outcome: str,
    entity_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    payload = {
        "action": action,
        "resource": resource,
        "role": context.role.value,
        "permissions": [permission.value for permission in context.permissions],
        "outcome": outcome,
        "entity_id": entity_id,
        "details": details or {},
    }
    log_method = _audit_logger.warning if outcome == "denied" else _audit_logger.info
    log_method("access_audit %s", payload)


def require_permissions(
    *,
    context: AccessContext,
    required_permissions: Iterable[AccessPermission],
    resource: str,
    action: str,
    entity_id: str | None = None,
) -> None:
    required = list(required_permissions)
    missing = [permission for permission in required if permission not in context.permissions]
    if not missing:
        return

    audit_sensitive_access(
        context=context,
        action=action,
        resource=resource,
        entity_id=entity_id,
        outcome="denied",
        details={"missing_permissions": [permission.value for permission in missing]},
    )
    missing_text = ", ".join(permission.value for permission in missing)
    raise AccessDeniedError(
        f"Access denied: role '{context.role.value}' is missing permission(s) {missing_text} for {action} on {resource}."
    )
