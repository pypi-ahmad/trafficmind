"""Add structured evidence manifest records.

Revision ID: 20260405_0006
Revises: 20260405_0005
Create Date: 2026-04-05 15:30:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260405_0006"
down_revision = "20260405_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evidence_manifests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "subject_kind",
            sa.Enum(
                "detection_event",
                "violation_event",
                name="evidence_subject_kind",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("manifest_key", sa.String(length=160), nullable=False),
        sa.Column("build_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("camera_id", sa.Uuid(), nullable=False),
        sa.Column("stream_id", sa.Uuid(), nullable=True),
        sa.Column("zone_id", sa.Uuid(), nullable=True),
        sa.Column("detection_event_id", sa.Uuid(), nullable=True),
        sa.Column("violation_event_id", sa.Uuid(), nullable=True),
        sa.Column("plate_read_id", sa.Uuid(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_frame_index", sa.Integer(), nullable=True),
        sa.Column("storage_namespace", sa.String(length=64), nullable=False, server_default="evidence"),
        sa.Column("manifest_uri", sa.Text(), nullable=True),
        sa.Column("manifest_data", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["stream_id"], ["camera_streams.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["zone_id"], ["zones.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["detection_event_id"], ["detection_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["violation_event_id"], ["violation_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["plate_read_id"], ["plate_reads.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("manifest_key"),
        sa.UniqueConstraint("subject_kind", "subject_id", name="uq_evidence_manifests_subject"),
    )
    op.create_index(
        "ix_evidence_manifests_camera_occurred_at",
        "evidence_manifests",
        ["camera_id", "occurred_at"],
    )
    op.create_index(
        "ix_evidence_manifests_manifest_key",
        "evidence_manifests",
        ["manifest_key"],
    )
    op.create_index(
        "ix_evidence_manifests_detection_event_id",
        "evidence_manifests",
        ["detection_event_id"],
    )
    op.create_index(
        "ix_evidence_manifests_violation_event_id",
        "evidence_manifests",
        ["violation_event_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_manifests_violation_event_id", table_name="evidence_manifests")
    op.drop_index("ix_evidence_manifests_detection_event_id", table_name="evidence_manifests")
    op.drop_index("ix_evidence_manifests_manifest_key", table_name="evidence_manifests")
    op.drop_index("ix_evidence_manifests_camera_occurred_at", table_name="evidence_manifests")
    op.drop_table("evidence_manifests")
