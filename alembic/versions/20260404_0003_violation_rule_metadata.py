"""Add rule_metadata JSON column to violation_events.

Revision ID: 20260404_0003
Revises: 20260404_0002
Create Date: 2026-04-04 23:50:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260404_0003"
down_revision = "20260404_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "violation_events",
        sa.Column(
            "rule_metadata",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("violation_events", "rule_metadata")
