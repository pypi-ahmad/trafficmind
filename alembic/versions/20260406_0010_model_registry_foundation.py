"""Add model registry entries and provenance foreign keys.

Revision ID: 20260406_0010
Revises: 20260406_0009
Create Date: 2026-04-06 14:30:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260406_0010"
down_revision = "20260406_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_registry_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "task_type",
            sa.Enum(
                "detection_model",
                "tracking_config",
                "ocr_model",
                "rules_config",
                "evidence_config",
                name="model_registry_task_type",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("model_family", sa.String(length=120), nullable=False),
        sa.Column("version_name", sa.String(length=160), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("config_bundle", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("entry_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("config_hash", name="uq_model_registry_entries_config_hash"),
    )
    op.create_index(
        "ix_model_registry_entries_task_type_active",
        "model_registry_entries",
        ["task_type", "is_active"],
    )
    op.create_index(
        "ix_model_registry_entries_family_version",
        "model_registry_entries",
        ["model_family", "version_name"],
    )

    with op.batch_alter_table("detection_events") as batch_op:
        batch_op.add_column(sa.Column("detector_registry_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("tracker_registry_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_detection_events_detector_registry_id_model_registry_entries",
            "model_registry_entries",
            ["detector_registry_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_detection_events_tracker_registry_id_model_registry_entries",
            "model_registry_entries",
            ["tracker_registry_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_detection_events_detector_registry_id", ["detector_registry_id"])
        batch_op.create_index("ix_detection_events_tracker_registry_id", ["tracker_registry_id"])

    with op.batch_alter_table("plate_reads") as batch_op:
        batch_op.add_column(sa.Column("ocr_registry_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_plate_reads_ocr_registry_id_model_registry_entries",
            "model_registry_entries",
            ["ocr_registry_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_plate_reads_ocr_registry_id", ["ocr_registry_id"])

    with op.batch_alter_table("violation_events") as batch_op:
        batch_op.add_column(sa.Column("rules_registry_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_violation_events_rules_registry_id_model_registry_entries",
            "model_registry_entries",
            ["rules_registry_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_violation_events_rules_registry_id", ["rules_registry_id"])

    with op.batch_alter_table("evidence_manifests") as batch_op:
        batch_op.add_column(sa.Column("evidence_registry_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_evidence_manifests_evidence_registry_id_model_registry_entries",
            "model_registry_entries",
            ["evidence_registry_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_evidence_manifests_evidence_registry_id", ["evidence_registry_id"])


def downgrade() -> None:
    with op.batch_alter_table("evidence_manifests") as batch_op:
        batch_op.drop_index("ix_evidence_manifests_evidence_registry_id")
        batch_op.drop_constraint(
            "fk_evidence_manifests_evidence_registry_id_model_registry_entries",
            type_="foreignkey",
        )
        batch_op.drop_column("evidence_registry_id")

    with op.batch_alter_table("violation_events") as batch_op:
        batch_op.drop_index("ix_violation_events_rules_registry_id")
        batch_op.drop_constraint(
            "fk_violation_events_rules_registry_id_model_registry_entries",
            type_="foreignkey",
        )
        batch_op.drop_column("rules_registry_id")

    with op.batch_alter_table("plate_reads") as batch_op:
        batch_op.drop_index("ix_plate_reads_ocr_registry_id")
        batch_op.drop_constraint(
            "fk_plate_reads_ocr_registry_id_model_registry_entries",
            type_="foreignkey",
        )
        batch_op.drop_column("ocr_registry_id")

    with op.batch_alter_table("detection_events") as batch_op:
        batch_op.drop_index("ix_detection_events_tracker_registry_id")
        batch_op.drop_index("ix_detection_events_detector_registry_id")
        batch_op.drop_constraint(
            "fk_detection_events_tracker_registry_id_model_registry_entries",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_detection_events_detector_registry_id_model_registry_entries",
            type_="foreignkey",
        )
        batch_op.drop_column("tracker_registry_id")
        batch_op.drop_column("detector_registry_id")

    op.drop_index("ix_model_registry_entries_family_version", table_name="model_registry_entries")
    op.drop_index("ix_model_registry_entries_task_type_active", table_name="model_registry_entries")
    op.drop_table("model_registry_entries")
