"""Add OCR metadata fields to plate_reads.

Revision ID: 20260404_0002
Revises: 20260404_0001
Create Date: 2026-04-04 23:40:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260404_0002"
down_revision = "20260404_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plate_reads", sa.Column("region_code", sa.String(length=16), nullable=True))
    op.add_column(
        "plate_reads",
        sa.Column("ocr_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )


def downgrade() -> None:
    op.drop_column("plate_reads", "ocr_metadata")
    op.drop_column("plate_reads", "region_code")