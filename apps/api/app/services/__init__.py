"""Business-logic services."""

from __future__ import annotations

from apps.api.app.services.errors import (
    ConflictError,
    NotFoundError,
    ServiceError,
    ServiceValidationError,
)

__all__ = [
    "AlertingService",
    "CameraService",
    "CaseExportService",
    "ConflictError",
    "HotspotAnalyticsService",
    "NotFoundError",
    "ServiceError",
    "ServiceValidationError",
]


def __getattr__(name: str):
    if name == "AlertingService":
        from apps.api.app.services.alerts import AlertingService

        return AlertingService
    if name == "CameraService":
        from apps.api.app.services.cameras import CameraService

        return CameraService
    if name == "CaseExportService":
        from apps.api.app.services.exports import CaseExportService

        return CaseExportService
    if name == "HotspotAnalyticsService":
        from apps.api.app.services.hotspots import HotspotAnalyticsService

        return HotspotAnalyticsService
    raise AttributeError(f"module 'apps.api.app.services' has no attribute {name!r}")
