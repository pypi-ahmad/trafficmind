"""Add multi-camera re-identification tables.

Revision ID: 20260405_0007
Revises: 20260405_0006
Create Date: 2026-04-05 16:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260405_0007"
down_revision = "20260405_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- cross_camera_entities --
    op.create_table(
        "cross_camera_entities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "subject_type",
            sa.Enum("vehicle", "person", name="reid_subject_type", native_enum=False),
            nullable=False,
        ),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("representative_image_uri", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("reid_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cross_camera_entities_subject_type", "cross_camera_entities", ["subject_type"])
    op.create_index("ix_cross_camera_entities_first_seen_at", "cross_camera_entities", ["first_seen_at"])

    # -- reid_sightings --
    op.create_table(
        "reid_sightings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("camera_id", sa.Uuid(), nullable=False),
        sa.Column("track_id", sa.String(length=128), nullable=False),
        sa.Column(
            "subject_type",
            sa.Enum("vehicle", "person", name="reid_sighting_subject_type", native_enum=False),
            nullable=False,
        ),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("representative_detection_event_id", sa.Uuid(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("embedding_vector", sa.JSON(), nullable=True),
        sa.Column("embedding_model", sa.String(length=120), nullable=True),
        sa.Column("bbox_snapshot", sa.JSON(), nullable=True),
        sa.Column("image_uri", sa.Text(), nullable=True),
        sa.Column("reid_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["entity_id"], ["cross_camera_entities.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["representative_detection_event_id"], ["detection_events.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("camera_id", "track_id", "first_seen_at", name="uq_reid_sightings_camera_track_first_seen"),
    )
    op.create_index("ix_reid_sightings_camera_id", "reid_sightings", ["camera_id"])
    op.create_index("ix_reid_sightings_subject_type", "reid_sightings", ["subject_type"])
    op.create_index("ix_reid_sightings_entity_id", "reid_sightings", ["entity_id"])
    op.create_index("ix_reid_sightings_camera_track", "reid_sightings", ["camera_id", "track_id"])
    op.create_index("ix_reid_sightings_first_seen_at", "reid_sightings", ["first_seen_at"])
    op.create_index("ix_reid_sightings_detection_event_id", "reid_sightings", ["representative_detection_event_id"])

    # -- reid_matches --
    op.create_table(
        "reid_matches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sighting_a_id", sa.Uuid(), nullable=False),
        sa.Column("sighting_b_id", sa.Uuid(), nullable=False),
        sa.Column("pair_key", sa.String(length=73), nullable=False),
        sa.Column("similarity_score", sa.Float(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("candidate", "confirmed", "rejected", "expired", name="reid_match_status", native_enum=False),
            nullable=False,
            server_default="candidate",
        ),
        sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(length=120), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("reid_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["sighting_a_id"], ["reid_sightings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sighting_b_id"], ["reid_sightings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pair_key", name="uq_reid_match_pair_key"),
    )
    op.create_index("ix_reid_matches_status", "reid_matches", ["status"])
    op.create_index("ix_reid_matches_pair_key", "reid_matches", ["pair_key"])
    op.create_index("ix_reid_matches_proposed_at", "reid_matches", ["proposed_at"])
    op.create_index("ix_reid_matches_sighting_a_id", "reid_matches", ["sighting_a_id"])
    op.create_index("ix_reid_matches_sighting_b_id", "reid_matches", ["sighting_b_id"])


def downgrade() -> None:
    op.drop_index("ix_reid_matches_sighting_b_id", table_name="reid_matches")
    op.drop_index("ix_reid_matches_sighting_a_id", table_name="reid_matches")
    op.drop_index("ix_reid_matches_proposed_at", table_name="reid_matches")
    op.drop_index("ix_reid_matches_pair_key", table_name="reid_matches")
    op.drop_index("ix_reid_matches_status", table_name="reid_matches")
    op.drop_table("reid_matches")

    op.drop_index("ix_reid_sightings_detection_event_id", table_name="reid_sightings")
    op.drop_index("ix_reid_sightings_first_seen_at", table_name="reid_sightings")
    op.drop_index("ix_reid_sightings_camera_track", table_name="reid_sightings")
    op.drop_index("ix_reid_sightings_entity_id", table_name="reid_sightings")
    op.drop_index("ix_reid_sightings_subject_type", table_name="reid_sightings")
    op.drop_index("ix_reid_sightings_camera_id", table_name="reid_sightings")
    op.drop_table("reid_sightings")

    op.drop_index("ix_cross_camera_entities_first_seen_at", table_name="cross_camera_entities")
    op.drop_index("ix_cross_camera_entities_subject_type", table_name="cross_camera_entities")
    op.drop_table("cross_camera_entities")
