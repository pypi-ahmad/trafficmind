"""Extend zone_type enum with lane and restricted values.

The ORM ZoneType enum was extended with 'lane' and 'restricted' members
after the initial migration. On SQLite the column is VARCHAR-backed so
existing data is unaffected, but Alembic's type metadata must be updated
to keep autogenerate clean.

Revision ID: 20260406_0011
Revises: 20260406_0010
Create Date: 2026-04-06 18:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260406_0011"
down_revision = "20260406_0010"
branch_labels = None
depends_on = None

_NEW_ZONE_TYPE = sa.Enum(
    "polygon", "line", "stop_line", "crosswalk", "roi", "lane", "restricted",
    name="zone_type",
    native_enum=False,
)

_OLD_ZONE_TYPE = sa.Enum(
    "polygon", "line", "stop_line", "crosswalk", "roi",
    name="zone_type",
    native_enum=False,
)


def upgrade() -> None:
    with op.batch_alter_table("zones") as batch_op:
        batch_op.alter_column(
            "zone_type",
            existing_type=_OLD_ZONE_TYPE,
            type_=_NEW_ZONE_TYPE,
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("zones") as batch_op:
        batch_op.alter_column(
            "zone_type",
            existing_type=_NEW_ZONE_TYPE,
            type_=_OLD_ZONE_TYPE,
            existing_nullable=False,
        )
