"""Add operational alert routing and escalation foundation.

Revision ID: 20260406_0008
Revises: 20260405_0007
Create Date: 2026-04-06 10:00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260406_0008"
down_revision = "20260405_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alert_routing_targets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "channel",
            sa.Enum("email", "webhook", "sms", "slack", "teams", name="alert_routing_channel", native_enum=False),
            nullable=False,
        ),
        sa.Column("destination", sa.Text(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("target_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("channel", "destination", name="uq_alert_routing_targets_channel_destination"),
    )
    op.create_index(
        "ix_alert_routing_targets_channel_enabled",
        "alert_routing_targets",
        ["channel", "is_enabled"],
    )

    op.create_table(
        "alert_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "source_kind",
            sa.Enum(
                "violation_event",
                "watchlist_alert",
                "camera_health",
                "stream_health",
                "workflow_backlog",
                "manual",
                name="operational_alert_source_kind",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("condition_key", sa.String(length=80), nullable=False),
        sa.Column(
            "min_severity",
            sa.Enum(
                "info",
                "low",
                "medium",
                "high",
                "critical",
                name="operational_alert_severity",
                native_enum=False,
            ),
            nullable=False,
            server_default="medium",
        ),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("dedup_window_seconds", sa.Integer(), nullable=False, server_default="900"),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("policy_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(
        "ix_alert_policies_source_condition_enabled",
        "alert_policies",
        ["source_kind", "condition_key", "is_enabled"],
    )

    op.create_table(
        "alert_policy_routes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("routing_target_id", sa.Uuid(), nullable=False),
        sa.Column("escalation_level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delay_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("route_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["policy_id"], ["alert_policies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["routing_target_id"], ["alert_routing_targets.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("policy_id", "routing_target_id", "escalation_level", name="uq_alert_policy_routes_step"),
    )
    op.create_index(
        "ix_alert_policy_routes_policy_escalation",
        "alert_policy_routes",
        ["policy_id", "escalation_level", "delay_seconds"],
    )
    op.create_index(
        "ix_alert_policy_routes_target_id",
        "alert_policy_routes",
        ["routing_target_id"],
    )

    op.create_table(
        "operational_alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=True),
        sa.Column("camera_id", sa.Uuid(), nullable=True),
        sa.Column("stream_id", sa.Uuid(), nullable=True),
        sa.Column("detection_event_id", sa.Uuid(), nullable=True),
        sa.Column("violation_event_id", sa.Uuid(), nullable=True),
        sa.Column("watchlist_alert_id", sa.Uuid(), nullable=True),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=True),
        sa.Column(
            "source_kind",
            sa.Enum(
                "violation_event",
                "watchlist_alert",
                "camera_health",
                "stream_health",
                "workflow_backlog",
                "manual",
                name="operational_alert_instance_source_kind",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("condition_key", sa.String(length=80), nullable=False),
        sa.Column(
            "severity",
            sa.Enum(
                "info",
                "low",
                "medium",
                "high",
                "critical",
                name="operational_alert_instance_severity",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "new",
                "acknowledged",
                "escalated",
                "resolved",
                "suppressed",
                name="operational_alert_status",
                native_enum=False,
            ),
            nullable=False,
            server_default="new",
        ),
        sa.Column("dedup_key", sa.String(length=240), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("escalation_level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("escalation_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_routed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.String(length=120), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(length=120), nullable=True),
        sa.Column("suppressed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suppressed_by", sa.String(length=120), nullable=True),
        sa.Column("source_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("alert_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["policy_id"], ["alert_policies.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["stream_id"], ["camera_streams.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["detection_event_id"], ["detection_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["violation_event_id"], ["violation_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["watchlist_alert_id"], ["watchlist_alerts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_operational_alerts_status_occurred_at",
        "operational_alerts",
        ["status", "occurred_at"],
    )
    op.create_index(
        "ix_operational_alerts_policy_status",
        "operational_alerts",
        ["policy_id", "status"],
    )
    op.create_index(
        "ix_operational_alerts_camera_status",
        "operational_alerts",
        ["camera_id", "status"],
    )
    op.create_index(
        "ix_operational_alerts_dedup_key",
        "operational_alerts",
        ["dedup_key"],
    )
    op.create_index(
        "ix_operational_alerts_source_kind_condition",
        "operational_alerts",
        ["source_kind", "condition_key"],
    )

    op.create_table(
        "alert_delivery_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("alert_id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=True),
        sa.Column("routing_target_id", sa.Uuid(), nullable=True),
        sa.Column("escalation_level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "delivery_state",
            sa.Enum("planned", "sent", "failed", "skipped", name="alert_delivery_state", native_enum=False),
            nullable=False,
            server_default="planned",
        ),
        sa.Column(
            "channel",
            sa.Enum("email", "webhook", "sms", "slack", "teams", name="alert_delivery_channel", native_enum=False),
            nullable=False,
        ),
        sa.Column("destination", sa.Text(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("delivery_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["alert_id"], ["operational_alerts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["policy_id"], ["alert_policies.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["routing_target_id"], ["alert_routing_targets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_alert_delivery_attempts_alert_created_at",
        "alert_delivery_attempts",
        ["alert_id", "created_at"],
    )
    op.create_index(
        "ix_alert_delivery_attempts_state_created_at",
        "alert_delivery_attempts",
        ["delivery_state", "created_at"],
    )
    op.create_index(
        "ix_alert_delivery_attempts_target_id",
        "alert_delivery_attempts",
        ["routing_target_id"],
    )

    op.create_table(
        "alert_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("alert_id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=True),
        sa.Column(
            "event_type",
            sa.Enum(
                "created",
                "deduplicated",
                "routed",
                "escalated",
                "acknowledged",
                "resolved",
                "suppressed",
                name="alert_audit_event_type",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "status_after",
            sa.Enum(
                "new",
                "acknowledged",
                "escalated",
                "resolved",
                "suppressed",
                name="alert_audit_status",
                native_enum=False,
            ),
            nullable=True,
        ),
        sa.Column("actor", sa.String(length=120), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("event_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["alert_id"], ["operational_alerts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["policy_id"], ["alert_policies.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_alert_audit_events_alert_created_at",
        "alert_audit_events",
        ["alert_id", "created_at"],
    )
    op.create_index(
        "ix_alert_audit_events_event_type",
        "alert_audit_events",
        ["event_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_alert_audit_events_event_type", table_name="alert_audit_events")
    op.drop_index("ix_alert_audit_events_alert_created_at", table_name="alert_audit_events")
    op.drop_table("alert_audit_events")

    op.drop_index("ix_alert_delivery_attempts_target_id", table_name="alert_delivery_attempts")
    op.drop_index("ix_alert_delivery_attempts_state_created_at", table_name="alert_delivery_attempts")
    op.drop_index("ix_alert_delivery_attempts_alert_created_at", table_name="alert_delivery_attempts")
    op.drop_table("alert_delivery_attempts")

    op.drop_index("ix_operational_alerts_source_kind_condition", table_name="operational_alerts")
    op.drop_index("ix_operational_alerts_dedup_key", table_name="operational_alerts")
    op.drop_index("ix_operational_alerts_camera_status", table_name="operational_alerts")
    op.drop_index("ix_operational_alerts_policy_status", table_name="operational_alerts")
    op.drop_index("ix_operational_alerts_status_occurred_at", table_name="operational_alerts")
    op.drop_table("operational_alerts")

    op.drop_index("ix_alert_policy_routes_target_id", table_name="alert_policy_routes")
    op.drop_index("ix_alert_policy_routes_policy_escalation", table_name="alert_policy_routes")
    op.drop_table("alert_policy_routes")

    op.drop_index("ix_alert_policies_source_condition_enabled", table_name="alert_policies")
    op.drop_table("alert_policies")

    op.drop_index("ix_alert_routing_targets_channel_enabled", table_name="alert_routing_targets")
    op.drop_table("alert_routing_targets")
