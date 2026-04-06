"""Request and response schemas for camera and ingestion management APIs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from apps.api.app.db.enums import CameraStatus, SourceType, StreamKind, StreamStatus
from apps.api.app.schemas.domain import CameraRead, CameraStreamRead

_MAX_SOURCE_URI_LENGTH = 2048
_MAX_NOTES_LENGTH = 2000


def _strip_or_reject(value: str, label: str) -> str:
    stripped = value.strip()
    if not stripped:
        msg = f"{label} must not be blank"
        raise ValueError(msg)
    return stripped


class CameraCreateRequest(BaseModel):
    """Create payload for a camera resource."""

    model_config = ConfigDict(extra="forbid")

    camera_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    location_name: str = Field(min_length=1, max_length=160)
    approach: str | None = Field(default=None, max_length=64)
    junction_id: uuid.UUID | None = None
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    status: CameraStatus = CameraStatus.PROVISIONING
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    notes: str | None = Field(default=None, max_length=_MAX_NOTES_LENGTH)
    calibration_config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("camera_code", "name", "location_name", "timezone", mode="before")
    @classmethod
    def normalize_required_strings(cls, value: str) -> str:
        return _strip_or_reject(value, "camera_code/name/location_name/timezone")

    @field_validator("approach", "notes", mode="before")
    @classmethod
    def normalize_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class CameraUpdateRequest(BaseModel):
    """Patch payload for camera updates."""

    model_config = ConfigDict(extra="forbid")

    camera_code: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    location_name: str | None = Field(default=None, min_length=1, max_length=160)
    approach: str | None = Field(default=None, max_length=64)
    junction_id: uuid.UUID | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    status: CameraStatus | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    notes: str | None = Field(default=None, max_length=_MAX_NOTES_LENGTH)
    calibration_config: dict[str, Any] | None = None
    calibration_updated_at: datetime | None = None

    @field_validator("camera_code", "name", "location_name", "timezone", mode="before")
    @classmethod
    def normalize_required_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _strip_or_reject(value, "camera_code/name/location_name/timezone")

    @field_validator("approach", "notes", mode="before")
    @classmethod
    def normalize_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> Self:
        if not self.model_fields_set:
            msg = "At least one field must be provided for update."
            raise ValueError(msg)
        return self


class CameraListResponse(BaseModel):
    """Paginated list response for cameras."""

    items: list[CameraRead]
    total: int


class CameraStreamWriteBase(BaseModel):
    """Shared validation for stream create-style payloads."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    stream_kind: StreamKind = StreamKind.PRIMARY
    source_type: SourceType
    source_uri: str = Field(min_length=1, max_length=_MAX_SOURCE_URI_LENGTH)
    source_config: dict[str, Any] = Field(default_factory=dict)
    status: StreamStatus = StreamStatus.OFFLINE
    is_enabled: bool = True
    resolution_width: int | None = Field(default=None, gt=0)
    resolution_height: int | None = Field(default=None, gt=0)
    fps_hint: float | None = Field(default=None, gt=0)

    @field_validator("name", "source_uri", mode="before")
    @classmethod
    def normalize_stream_strings(cls, value: str) -> str:
        return _strip_or_reject(value, "name/source_uri")

    @model_validator(mode="after")
    def validate_source_fields(self) -> Self:
        upload_keys = {"upload_id", "asset_name", "file_name"}
        test_keys = {"fixture_name", "generator"}

        if self.source_type == SourceType.RTSP:
            if not self.source_uri.startswith(("rtsp://", "rtsps://")):
                msg = "RTSP streams must use an rtsp:// or rtsps:// source_uri."
                raise ValueError(msg)

        if self.source_type == SourceType.UPLOAD:
            has_upload_ref = self.source_uri.startswith("upload://") or any(
                self.source_config.get(key) for key in upload_keys
            )
            if not has_upload_ref:
                msg = "Upload sources require an upload:// source_uri or upload metadata in source_config."
                raise ValueError(msg)

        if self.source_type == SourceType.FILE:
            has_scheme = "://" in self.source_uri
            if has_scheme and not self.source_uri.startswith("file://"):
                msg = "File sources must use a file:// URI or a plain local file path."
                raise ValueError(msg)

        if self.source_type == SourceType.TEST:
            has_test_ref = self.source_uri.startswith("test://") or any(
                self.source_config.get(key) for key in test_keys
            )
            if not has_test_ref:
                msg = "Test sources require a test:// source_uri or a fixture/generator in source_config."
                raise ValueError(msg)

        return self


class CameraStreamCreateRequest(CameraStreamWriteBase):
    """Create payload for a stream attached to an existing camera."""


class CameraStreamUpdateRequest(BaseModel):
    """Patch payload for stream updates."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=80)
    stream_kind: StreamKind | None = None
    source_type: SourceType | None = None
    source_uri: str | None = Field(default=None, min_length=1, max_length=_MAX_SOURCE_URI_LENGTH)
    source_config: dict[str, Any] | None = None
    status: StreamStatus | None = None
    is_enabled: bool | None = None
    resolution_width: int | None = Field(default=None, gt=0)
    resolution_height: int | None = Field(default=None, gt=0)
    fps_hint: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> Self:
        if not self.model_fields_set:
            msg = "At least one field must be provided for update."
            raise ValueError(msg)
        return self


class CameraStreamListResponse(BaseModel):
    """Paginated list response for streams."""

    items: list[CameraStreamRead]
    total: int


class VideoSourceRegistrationRequest(BaseModel):
    """Register an uploaded, file-backed, or synthetic video source."""

    model_config = ConfigDict(extra="forbid")

    camera_id: uuid.UUID | None = None
    camera: CameraCreateRequest | None = None
    stream: CameraStreamCreateRequest

    @model_validator(mode="after")
    def validate_registration(self) -> Self:
        if (self.camera_id is None) == (self.camera is None):
            msg = "Provide exactly one of camera_id or camera when registering a video source."
            raise ValueError(msg)

        if self.stream.source_type == SourceType.RTSP:
            msg = "Use the regular stream create endpoint for RTSP streams."
            raise ValueError(msg)

        return self


