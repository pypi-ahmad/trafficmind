"""Add watchlist_entries table.

Revision ID: 20260405_0004
Revises: 20260404_0003
Create Date: 2026-04-05 12:00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260405_0004"
down_revision = "20260404_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "watchlist_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("normalized_plate_text", sa.String(32), nullable=False),
        sa.Column("plate_text_display", sa.String(32), nullable=False),
        sa.Column(
            "reason",
            sa.Enum(
                "stolen", "wanted", "bolo", "vip", "investigation", "other",
                name="watchlist_reason",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "active", "expired", "disabled",
                name="watchlist_entry_status",
                native_enum=False,
            ),
            nullable=False,
            server_default="active",
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("added_by", sa.String(120), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("alert_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("country_code", sa.String(8), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_plate_text", "reason", name="uq_watchlist_plate_reason"),
    )
    op.create_index(
        "ix_watchlist_entries_normalized_plate_text",
        "watchlist_entries",
        ["normalized_plate_text"],
    )
    op.create_index(
        "ix_watchlist_entries_status_reason",
        "watchlist_entries",
        ["status", "reason"],
    )


def downgrade() -> None:
    op.drop_index("ix_watchlist_entries_status_reason", table_name="watchlist_entries")
    op.drop_index("ix_watchlist_entries_normalized_plate_text", table_name="watchlist_entries")
    op.drop_table("watchlist_entries")
