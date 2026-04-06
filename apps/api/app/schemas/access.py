"""Schemas for exposing the current access-control foundation."""

from __future__ import annotations

from pydantic import Field

from apps.api.app.schemas.domain import ORMSchema
from services.access_control.policy import AccessPermission
from services.evidence.schemas import EvidenceAccessRole


class AccessRolePermissionRead(ORMSchema):
    role: EvidenceAccessRole
    permissions: list[AccessPermission] = Field(default_factory=list)
    description: str | None = None


class AccessRequirementRead(ORMSchema):
    action: str
    permissions: list[AccessPermission] = Field(default_factory=list)
    note: str | None = None


class AccessPolicyRead(ORMSchema):
    policy_name: str
    current_role: EvidenceAccessRole
    current_permissions: list[AccessPermission] = Field(default_factory=list)
    roles: list[AccessRolePermissionRead] = Field(default_factory=list)
    requirements: list[AccessRequirementRead] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
