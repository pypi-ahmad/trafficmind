"""Database layer exports for models, metadata, and session helpers."""

from apps.api.app.db.base import Base
from apps.api.app.db.enums import CameraStatus, SourceType, StreamKind, StreamStatus
from apps.api.app.db.models import (
    Camera,
    CameraStream,
    CrossCameraEntity,
    DetectionEvent,
    EvidenceManifest,
    PlateRead,
    ReIdMatch,
    ReIdSighting,
    ViolationEvent,
    WatchlistAlert,
    WatchlistEntry,
    WorkflowRun,
    Zone,
)
from apps.api.app.db.session import get_db_session, get_engine, get_session_factory

__all__ = [
    "Base",
    "Camera",
    "CameraStatus",
    "CameraStream",
    "CrossCameraEntity",
    "DetectionEvent",
    "EvidenceManifest",
    "PlateRead",
    "ReIdMatch",
    "ReIdSighting",
    "SourceType",
    "StreamKind",
    "StreamStatus",
    "ViolationEvent",
    "WatchlistAlert",
    "WatchlistEntry",
    "WorkflowRun",
    "Zone",
    "get_db_session",
    "get_engine",
    "get_session_factory",
]
