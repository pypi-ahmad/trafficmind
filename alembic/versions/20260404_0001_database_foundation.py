"""Database foundation for TrafficMind core domain models.

Revision ID: 20260404_0001
Revises:
Create Date: 2026-04-04 21:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260404_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cameras",
        sa.Column("camera_code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("location_name", sa.String(length=160), nullable=False),
        sa.Column("approach", sa.String(length=64), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default=sa.text("'UTC'")),
        sa.Column(
            "status",
            sa.Enum(
                "provisioning",
                "active",
                "maintenance",
                "disabled",
                name="camera_status",
                native_enum=False,
            ),
            nullable=False,
            server_default=sa.text("'provisioning'"),
        ),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("calibration_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("calibration_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cameras")),
        sa.UniqueConstraint("camera_code", name=op.f("uq_cameras_camera_code")),
    )
    op.create_index("ix_cameras_location_name", "cameras", ["location_name"], unique=False)
    op.create_index("ix_cameras_status_created_at", "cameras", ["status", "created_at"], unique=False)

    op.create_table(
        "camera_streams",
        sa.Column("camera_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column(
            "stream_kind",
            sa.Enum("primary", "substream", "auxiliary", name="stream_kind", native_enum=False),
            nullable=False,
            server_default=sa.text("'primary'"),
        ),
        sa.Column(
            "source_type",
            sa.Enum("rtsp", "upload", "file", "test", name="source_type", native_enum=False),
            nullable=False,
        ),
        sa.Column("source_uri", sa.Text(), nullable=False),
        sa.Column("source_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "status",
            sa.Enum(
                "offline",
                "connecting",
                "live",
                "error",
                "disabled",
                name="stream_status",
                native_enum=False,
            ),
            nullable=False,
            server_default=sa.text("'offline'"),
        ),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("resolution_width", sa.Integer(), nullable=True),
        sa.Column("resolution_height", sa.Integer(), nullable=True),
        sa.Column("fps_hint", sa.Float(), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], name=op.f("fk_camera_streams_camera_id_cameras"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_camera_streams")),
        sa.UniqueConstraint("camera_id", "name", name=op.f("uq_camera_streams_camera_id_name")),
    )
    op.create_index("ix_camera_streams_camera_source_type", "camera_streams", ["camera_id", "source_type"], unique=False)
    op.create_index("ix_camera_streams_status_enabled", "camera_streams", ["status", "is_enabled"], unique=False)

    op.create_table(
        "zones",
        sa.Column("camera_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "zone_type",
            sa.Enum("polygon", "line", "stop_line", "crosswalk", "roi", name="zone_type", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("draft", "active", "archived", name="zone_status", native_enum=False),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column("geometry", sa.JSON(), nullable=False),
        sa.Column("rules_config", sa.JSON(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], name=op.f("fk_zones_camera_id_cameras"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_zones")),
        sa.UniqueConstraint("camera_id", "name", name=op.f("uq_zones_camera_id_name")),
    )
    op.create_index("ix_zones_camera_status_zone_type", "zones", ["camera_id", "status", "zone_type"], unique=False)

    op.create_table(
        "detection_events",
        sa.Column("camera_id", sa.Uuid(), nullable=False),
        sa.Column("stream_id", sa.Uuid(), nullable=True),
        sa.Column("zone_id", sa.Uuid(), nullable=True),
        sa.Column(
            "event_type",
            sa.Enum(
                "detection",
                "zone_entry",
                "zone_exit",
                "line_crossing",
                "light_state",
                name="detection_event_type",
                native_enum=False,
            ),
            nullable=False,
            server_default=sa.text("'detection'"),
        ),
        sa.Column(
            "status",
            sa.Enum("new", "enriched", "suppressed", name="detection_event_status", native_enum=False),
            nullable=False,
            server_default=sa.text("'new'"),
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("frame_index", sa.Integer(), nullable=True),
        sa.Column("track_id", sa.String(length=64), nullable=True),
        sa.Column("object_class", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("bbox", sa.JSON(), nullable=False),
        sa.Column("event_payload", sa.JSON(), nullable=False),
        sa.Column("image_uri", sa.Text(), nullable=True),
        sa.Column("video_uri", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], name=op.f("fk_detection_events_camera_id_cameras"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["stream_id"], ["camera_streams.id"], name=op.f("fk_detection_events_stream_id_camera_streams"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["zone_id"], ["zones.id"], name=op.f("fk_detection_events_zone_id_zones"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_detection_events")),
    )
    op.create_index("ix_detection_events_camera_occurred_at", "detection_events", ["camera_id", "occurred_at"], unique=False)
    op.create_index("ix_detection_events_object_class_occurred_at", "detection_events", ["object_class", "occurred_at"], unique=False)
    op.create_index("ix_detection_events_status_occurred_at", "detection_events", ["status", "occurred_at"], unique=False)
    op.create_index("ix_detection_events_track_id", "detection_events", ["track_id"], unique=False)

    op.create_table(
        "plate_reads",
        sa.Column("camera_id", sa.Uuid(), nullable=False),
        sa.Column("stream_id", sa.Uuid(), nullable=True),
        sa.Column("detection_event_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "observed",
                "matched",
                "manual_review",
                "rejected",
                name="plate_read_status",
                native_enum=False,
            ),
            nullable=False,
            server_default=sa.text("'observed'"),
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("plate_text", sa.String(length=32), nullable=False),
        sa.Column("normalized_plate_text", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("country_code", sa.String(length=8), nullable=True),
        sa.Column("bbox", sa.JSON(), nullable=False),
        sa.Column("crop_image_uri", sa.Text(), nullable=True),
        sa.Column("source_frame_uri", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], name=op.f("fk_plate_reads_camera_id_cameras"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["detection_event_id"], ["detection_events.id"], name=op.f("fk_plate_reads_detection_event_id_detection_events"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["stream_id"], ["camera_streams.id"], name=op.f("fk_plate_reads_stream_id_camera_streams"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plate_reads")),
    )
    op.create_index("ix_plate_reads_camera_occurred_at", "plate_reads", ["camera_id", "occurred_at"], unique=False)
    op.create_index(
        "ix_plate_reads_normalized_plate_text_occurred_at",
        "plate_reads",
        ["normalized_plate_text", "occurred_at"],
        unique=False,
    )
    op.create_index("ix_plate_reads_status_occurred_at", "plate_reads", ["status", "occurred_at"], unique=False)

    op.create_table(
        "violation_events",
        sa.Column("camera_id", sa.Uuid(), nullable=False),
        sa.Column("stream_id", sa.Uuid(), nullable=True),
        sa.Column("zone_id", sa.Uuid(), nullable=True),
        sa.Column("detection_event_id", sa.Uuid(), nullable=True),
        sa.Column("plate_read_id", sa.Uuid(), nullable=True),
        sa.Column(
            "violation_type",
            sa.Enum(
                "red_light",
                "stop_line",
                "wrong_way",
                "pedestrian_conflict",
                "illegal_turn",
                "speeding",
                name="violation_type",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.Enum("low", "medium", "high", "critical", name="violation_severity", native_enum=False),
            nullable=False,
            server_default=sa.text("'medium'"),
        ),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "under_review",
                "confirmed",
                "dismissed",
                name="violation_status",
                native_enum=False,
            ),
            nullable=False,
            server_default=sa.text("'open'"),
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("evidence_image_uri", sa.Text(), nullable=True),
        sa.Column("evidence_video_uri", sa.Text(), nullable=True),
        sa.Column("assigned_to", sa.String(length=120), nullable=True),
        sa.Column("reviewed_by", sa.String(length=120), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], name=op.f("fk_violation_events_camera_id_cameras"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["detection_event_id"], ["detection_events.id"], name=op.f("fk_violation_events_detection_event_id_detection_events"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["plate_read_id"], ["plate_reads.id"], name=op.f("fk_violation_events_plate_read_id_plate_reads"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["stream_id"], ["camera_streams.id"], name=op.f("fk_violation_events_stream_id_camera_streams"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["zone_id"], ["zones.id"], name=op.f("fk_violation_events_zone_id_zones"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_violation_events")),
    )
    op.create_index("ix_violation_events_camera_occurred_at", "violation_events", ["camera_id", "occurred_at"], unique=False)
    op.create_index("ix_violation_events_plate_read_id", "violation_events", ["plate_read_id"], unique=False)
    op.create_index(
        "ix_violation_events_status_assigned_to_occurred_at",
        "violation_events",
        ["status", "assigned_to", "occurred_at"],
        unique=False,
    )
    op.create_index("ix_violation_events_status_occurred_at", "violation_events", ["status", "occurred_at"], unique=False)
    op.create_index("ix_violation_events_violation_type_occurred_at", "violation_events", ["violation_type", "occurred_at"], unique=False)

    op.create_table(
        "workflow_runs",
        sa.Column("camera_id", sa.Uuid(), nullable=True),
        sa.Column("detection_event_id", sa.Uuid(), nullable=True),
        sa.Column("violation_event_id", sa.Uuid(), nullable=True),
        sa.Column(
            "workflow_type",
            sa.Enum("triage", "review", "report", "assist", name="workflow_type", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "succeeded",
                "failed",
                "cancelled",
                name="workflow_status",
                native_enum=False,
            ),
            nullable=False,
            server_default=sa.text("'queued'"),
        ),
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("5")),
        sa.Column("requested_by", sa.String(length=120), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        sa.Column("result_payload", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], name=op.f("fk_workflow_runs_camera_id_cameras"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["detection_event_id"], ["detection_events.id"], name=op.f("fk_workflow_runs_detection_event_id_detection_events"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["violation_event_id"], ["violation_events.id"], name=op.f("fk_workflow_runs_violation_event_id_violation_events"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_runs")),
    )
    op.create_index("ix_workflow_runs_detection_event_id", "workflow_runs", ["detection_event_id"], unique=False)
    op.create_index("ix_workflow_runs_status_priority_created_at", "workflow_runs", ["status", "priority", "created_at"], unique=False)
    op.create_index("ix_workflow_runs_status_created_at", "workflow_runs", ["status", "created_at"], unique=False)
    op.create_index("ix_workflow_runs_violation_event_id", "workflow_runs", ["violation_event_id"], unique=False)
    op.create_index("ix_workflow_runs_workflow_type_created_at", "workflow_runs", ["workflow_type", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_workflow_runs_workflow_type_created_at", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_violation_event_id", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_status_created_at", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_status_priority_created_at", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_detection_event_id", table_name="workflow_runs")
    op.drop_table("workflow_runs")

    op.drop_index("ix_violation_events_violation_type_occurred_at", table_name="violation_events")
    op.drop_index("ix_violation_events_status_occurred_at", table_name="violation_events")
    op.drop_index("ix_violation_events_status_assigned_to_occurred_at", table_name="violation_events")
    op.drop_index("ix_violation_events_plate_read_id", table_name="violation_events")
    op.drop_index("ix_violation_events_camera_occurred_at", table_name="violation_events")
    op.drop_table("violation_events")

    op.drop_index("ix_plate_reads_status_occurred_at", table_name="plate_reads")
    op.drop_index("ix_plate_reads_normalized_plate_text_occurred_at", table_name="plate_reads")
    op.drop_index("ix_plate_reads_camera_occurred_at", table_name="plate_reads")
    op.drop_table("plate_reads")

    op.drop_index("ix_detection_events_track_id", table_name="detection_events")
    op.drop_index("ix_detection_events_status_occurred_at", table_name="detection_events")
    op.drop_index("ix_detection_events_object_class_occurred_at", table_name="detection_events")
    op.drop_index("ix_detection_events_camera_occurred_at", table_name="detection_events")
    op.drop_table("detection_events")

    op.drop_index("ix_zones_camera_status_zone_type", table_name="zones")
    op.drop_table("zones")

    op.drop_index("ix_camera_streams_status_enabled", table_name="camera_streams")
    op.drop_index("ix_camera_streams_camera_source_type", table_name="camera_streams")
    op.drop_table("camera_streams")

    op.drop_index("ix_cameras_status_created_at", table_name="cameras")
    op.drop_index("ix_cameras_location_name", table_name="cameras")
    op.drop_table("cameras")