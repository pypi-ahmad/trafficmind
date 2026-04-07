"""Pydantic schemas for case export and audit-ready evidence bundles."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from apps.api.app.db.enums import (
    CaseExportAuditEventType,
    CaseExportFormat,
    CaseExportStatus,
    CaseSubjectKind,
)
from apps.api.app.schemas.domain import ORMSchema
from services.evidence.schemas import EvidenceAccessRole, EvidenceAssetView

# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CaseExportCreateRequest(ORMSchema):
    subject_kind: CaseSubjectKind
    subject_id: uuid.UUID
    export_format: CaseExportFormat = CaseExportFormat.JSON
    requested_by: str | None = Field(default=None, max_length=120)
    access_role: EvidenceAccessRole = EvidenceAccessRole.EXPORT_SERVICE
    requested_view: EvidenceAssetView | None = None


class CaseExportAuditActionRequest(ORMSchema):
    actor: str = Field(min_length=1, max_length=120)
    note: str | None = None


# ---------------------------------------------------------------------------
# Audit event
# ---------------------------------------------------------------------------


class CaseExportAuditEventRead(ORMSchema):
    id: uuid.UUID
    case_export_id: uuid.UUID
    event_type: CaseExportAuditEventType
    actor: str | None = None
    note: str | None = None
    event_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Export read schemas
# ---------------------------------------------------------------------------


class CaseExportSummaryRead(ORMSchema):
    id: uuid.UUID
    subject_kind: CaseSubjectKind
    subject_id: uuid.UUID
    export_format: CaseExportFormat
    status: CaseExportStatus
    requested_by: str | None = None
    bundle_version: str
    filename: str
    completeness: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CaseExportDetailRead(CaseExportSummaryRead):
    bundle_data: dict[str, Any] = Field(default_factory=dict)
    audit_events: list[CaseExportAuditEventRead] = Field(default_factory=list)


class CaseExportListResult(ORMSchema):
    items: list[CaseExportSummaryRead] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0
