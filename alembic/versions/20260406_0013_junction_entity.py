"""Add junctions table and camera.junction_id foreign key.

Revision ID: 20260406_0013
Revises: 20260406_0012
Create Date: 2026-04-06 20:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260406_0013"
down_revision = "20260406_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "junctions",
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_junctions")),
        sa.UniqueConstraint("name", name=op.f("uq_junctions_name")),
    )
    op.create_index("ix_junctions_name", "junctions", ["name"], unique=False)

    op.add_column("cameras", sa.Column("junction_id", sa.Uuid(), nullable=True))
    op.create_index("ix_cameras_junction_id", "cameras", ["junction_id"], unique=False)
    with op.batch_alter_table("cameras") as batch_op:
        batch_op.create_foreign_key(
            op.f("fk_cameras_junction_id_junctions"),
            "junctions",
            ["junction_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("cameras") as batch_op:
        batch_op.drop_constraint(op.f("fk_cameras_junction_id_junctions"), type_="foreignkey")
    op.drop_index("ix_cameras_junction_id", table_name="cameras")
    op.drop_column("cameras", "junction_id")
    op.drop_index("ix_junctions_name", table_name="junctions")
    op.drop_table("junctions")
