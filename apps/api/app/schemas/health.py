"""Response models for health, info, and public config endpoints."""

from __future__ import annotations

from pydantic import BaseModel

from services.runtime import RuntimeReadinessReport


class HealthResponse(BaseModel):
    """GET /health response."""

    status: str = "ok"


class InfoResponse(BaseModel):
    """GET /info response — non-sensitive runtime metadata."""

    app_name: str
    version: str
    environment: str
    api_prefix: str
    enabled_modules: list[str]
    docs_url: str


class PublicConfigResponse(BaseModel):
    """GET /config/public — client-safe configuration subset."""

    environment: str
    api_prefix: str
    allowed_origins: list[str]
    enable_vision: bool
    enable_tracking: bool
    enable_ocr: bool
    enable_rules: bool
    enable_workflow: bool


__all__ = [
    "HealthResponse",
    "InfoResponse",
    "PublicConfigResponse",
    "RuntimeReadinessReport",
]
