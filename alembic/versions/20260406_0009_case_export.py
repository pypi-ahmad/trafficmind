"""Add case export and audit event tables.

Revision ID: 20260406_0009
Revises: 20260406_0008
Create Date: 2026-04-06 12:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260406_0009"
down_revision = "20260406_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "case_exports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "subject_kind",
            sa.Enum("violation_event", "detection_event", "watchlist_alert", "operational_alert",
                    name="case_subject_kind", native_enum=False),
            nullable=False,
        ),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column(
            "export_format",
            sa.Enum("json", "markdown", "zip_manifest", name="case_export_format", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("pending", "completed", "failed", name="case_export_status", native_enum=False),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("requested_by", sa.String(length=120), nullable=True),
        sa.Column("bundle_version", sa.String(length=16), nullable=False, server_default="1.0"),
        sa.Column("filename", sa.String(length=260), nullable=False),
        sa.Column("bundle_data", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("completeness", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_exports")),
    )
    op.create_index("ix_case_exports_subject", "case_exports", ["subject_kind", "subject_id"])
    op.create_index("ix_case_exports_status_created_at", "case_exports", ["status", "created_at"])

    op.create_table(
        "case_export_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_export_id", sa.Uuid(), nullable=False),
        sa.Column(
            "event_type",
            sa.Enum("created", "completed", "failed", "downloaded",
                    name="case_export_audit_event_type", native_enum=False),
            nullable=False,
        ),
        sa.Column("actor", sa.String(length=120), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("event_payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_export_audit_events")),
        sa.ForeignKeyConstraint(
            ["case_export_id"], ["case_exports.id"],
            name=op.f("fk_case_export_audit_events_case_export_id_case_exports"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_case_export_audit_events_export_created",
        "case_export_audit_events",
        ["case_export_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("case_export_audit_events")
    op.drop_table("case_exports")
