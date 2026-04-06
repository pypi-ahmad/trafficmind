"""Domain enums shared by ORM models and Pydantic schemas."""

from __future__ import annotations

from enum import StrEnum

# ---------------------------------------------------------------------------
# Canonical enums — imported from the shared_types package so that the
# deterministic service layer never has to depend on apps.api.*.
# Re-exported here for full backward compatibility with existing consumers.
# ---------------------------------------------------------------------------
from packages.shared_types.enums import (  # noqa: F401
    DetectionEventStatus,
    DetectionEventType,
    ReIdMatchStatus,
    ReIdSubjectType,
    RuleType,
    ViolationLifecycleStage,
    ViolationSeverity,
    ViolationStatus,
    ViolationType,
    ZoneType,
)


class CameraStatus(StrEnum):
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    MAINTENANCE = "maintenance"
    DISABLED = "disabled"


class StreamKind(StrEnum):
    PRIMARY = "primary"
    SUBSTREAM = "substream"
    AUXILIARY = "auxiliary"


class SourceType(StrEnum):
    RTSP = "rtsp"
    UPLOAD = "upload"
    FILE = "file"
    TEST = "test"


class StreamStatus(StrEnum):
    OFFLINE = "offline"
    CONNECTING = "connecting"
    LIVE = "live"
    ERROR = "error"
    DISABLED = "disabled"


class ZoneStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class ModelRegistryTaskType(StrEnum):
    DETECTION_MODEL = "detection_model"
    TRACKING_CONFIG = "tracking_config"
    OCR_MODEL = "ocr_model"
    RULES_CONFIG = "rules_config"
    EVIDENCE_CONFIG = "evidence_config"


class PlateReadStatus(StrEnum):
    OBSERVED = "observed"
    MATCHED = "matched"
    MANUAL_REVIEW = "manual_review"
    REJECTED = "rejected"


class WatchlistEntryStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    DISABLED = "disabled"


class WatchlistReason(StrEnum):
    STOLEN = "stolen"
    WANTED = "wanted"
    BOLO = "bolo"
    VIP = "vip"
    INVESTIGATION = "investigation"
    OTHER = "other"


class WatchlistAlertStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class OperationalAlertSeverity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class OperationalAlertStatus(StrEnum):
    NEW = "new"
    ACKNOWLEDGED = "acknowledged"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"


class OperationalAlertSourceKind(StrEnum):
    VIOLATION_EVENT = "violation_event"
    WATCHLIST_ALERT = "watchlist_alert"
    CAMERA_HEALTH = "camera_health"
    STREAM_HEALTH = "stream_health"
    WORKFLOW_BACKLOG = "workflow_backlog"
    MANUAL = "manual"


class AlertRoutingChannel(StrEnum):
    EMAIL = "email"
    WEBHOOK = "webhook"
    SMS = "sms"
    SLACK = "slack"
    TEAMS = "teams"


class AlertDeliveryState(StrEnum):
    PLANNED = "planned"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


class AlertAuditEventType(StrEnum):
    CREATED = "created"
    DEDUPLICATED = "deduplicated"
    ROUTED = "routed"
    ESCALATED = "escalated"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"


class EvidenceSubjectKind(StrEnum):
    DETECTION_EVENT = "detection_event"
    VIOLATION_EVENT = "violation_event"


class WorkflowType(StrEnum):
    TRIAGE = "triage"
    REVIEW = "review"
    REPORT = "report"
    ASSIST = "assist"


class WorkflowStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Case Export
# ---------------------------------------------------------------------------


class CaseExportStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class CaseExportFormat(StrEnum):
    JSON = "json"
    MARKDOWN = "markdown"
    ZIP_MANIFEST = "zip_manifest"


class CaseSubjectKind(StrEnum):
    VIOLATION_EVENT = "violation_event"
    DETECTION_EVENT = "detection_event"
    WATCHLIST_ALERT = "watchlist_alert"
    OPERATIONAL_ALERT = "operational_alert"


class CaseExportAuditEventType(StrEnum):
    CREATED = "created"
    COMPLETED = "completed"
    FAILED = "failed"
    DOWNLOADED = "downloaded"