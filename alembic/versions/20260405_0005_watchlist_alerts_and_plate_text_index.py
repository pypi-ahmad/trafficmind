"""Add watchlist alert records and plate text search index.

Revision ID: 20260405_0005
Revises: 20260405_0004
Create Date: 2026-04-05 13:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260405_0005"
down_revision = "20260405_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_plate_reads_plate_text_occurred_at",
        "plate_reads",
        ["plate_text", "occurred_at"],
    )
    op.create_table(
        "watchlist_alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plate_read_id", sa.Uuid(), nullable=False),
        sa.Column("watchlist_entry_id", sa.Uuid(), nullable=True),
        sa.Column("camera_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "acknowledged",
                "resolved",
                name="watchlist_alert_status",
                native_enum=False,
            ),
            nullable=False,
            server_default="open",
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("normalized_plate_text", sa.String(32), nullable=False),
        sa.Column("plate_text", sa.String(32), nullable=False),
        sa.Column(
            "reason",
            sa.Enum(
                "stolen",
                "wanted",
                "bolo",
                "vip",
                "investigation",
                "other",
                name="watchlist_alert_reason",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("alert_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["plate_read_id"], ["plate_reads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["watchlist_entry_id"], ["watchlist_entries.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plate_read_id", "watchlist_entry_id", name="uq_watchlist_alert_plate_read_entry"),
    )
    op.create_index(
        "ix_watchlist_alerts_camera_occurred_at",
        "watchlist_alerts",
        ["camera_id", "occurred_at"],
    )
    op.create_index(
        "ix_watchlist_alerts_status_occurred_at",
        "watchlist_alerts",
        ["status", "occurred_at"],
    )
    op.create_index(
        "ix_watchlist_alerts_watchlist_entry_id",
        "watchlist_alerts",
        ["watchlist_entry_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_watchlist_alerts_watchlist_entry_id", table_name="watchlist_alerts")
    op.drop_index("ix_watchlist_alerts_status_occurred_at", table_name="watchlist_alerts")
    op.drop_index("ix_watchlist_alerts_camera_occurred_at", table_name="watchlist_alerts")
    op.drop_table("watchlist_alerts")
    op.drop_index("ix_plate_reads_plate_text_occurred_at", table_name="plate_reads")