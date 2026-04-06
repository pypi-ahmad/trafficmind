"""Typed result schemas for OCR / ANPR output.

These schemas are the contract between the OCR service and all downstream
consumers (rules engine, plate-read persistence, violations).  They are
intentionally decoupled from SQLAlchemy models and API response schemas so
the OCR service remains a standalone, importable library.

The design supports number-plate OCR as the primary use-case but keeps
the base ``OcrResult`` generic enough for road-sign or lane-sign text.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from services.vision.schemas import BBox


class OcrDomain(StrEnum):
    """Domain hint telling the engine what kind of text to expect."""

    PLATE = "plate"
    ROAD_SIGN = "road_sign"
    GENERIC = "generic"


class OcrResult(BaseModel):
    """Single text recognition result from an OCR engine.

    This is the *raw* engine output — no normalisation applied yet.
    """

    model_config = ConfigDict(frozen=True)

    recognized_text: str
    confidence: float = Field(ge=0.0, le=1.0)
    bbox: BBox | None = None
    domain: OcrDomain = OcrDomain.GENERIC
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class OcrContext(BaseModel):
    """Request context passed into OCR engines and downstream pipelines."""

    model_config = ConfigDict(frozen=True)

    domain: OcrDomain = OcrDomain.GENERIC
    country_code: str | None = Field(default=None, max_length=8)
    region_code: str | None = Field(default=None, max_length=16)
    language_hints: list[str] = Field(default_factory=list)
    frame_index: int | None = None
    timestamp: datetime | None = None
    crop_image_path: str | None = None
    source_frame_path: str | None = None
    source_bbox: BBox | None = None
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class PlateOcrResult(BaseModel):
    """Structured plate-read result after normalisation.

    Carries both the raw engine output and the cleaned plate text
    ready for persistence into the ``PlateRead`` model.
    """

    model_config = ConfigDict(frozen=True)

    raw_text: str
    normalized_text: str
    confidence: float = Field(ge=0.0, le=1.0)
    bbox: BBox | None = None
    crop_bbox: BBox | None = None
    country_code: str | None = Field(default=None, max_length=8)
    region_code: str | None = Field(default=None, max_length=16)
    crop_image_path: str | None = None
    source_frame_path: str | None = None
    frame_index: int | None = None
    timestamp: datetime | None = None
    raw_metadata: dict[str, Any] = Field(default_factory=dict)

    def to_plate_read_dict(self) -> dict[str, Any]:
        """Return a dict aligned with the ``PlateRead`` ORM model columns."""
        ocr_metadata = dict(self.raw_metadata)
        if self.crop_bbox is not None:
            ocr_metadata.setdefault("crop_bbox", self.crop_bbox.to_dict())
        return {
            "plate_text": self.raw_text,
            "normalized_plate_text": self.normalized_text,
            "confidence": self.confidence,
            "country_code": self.country_code,
            "region_code": self.region_code,
            "bbox": self.bbox.to_dict() if self.bbox else {},
            "crop_image_uri": self.crop_image_path,
            "source_frame_uri": self.source_frame_path,
            "occurred_at": self.timestamp,
            "ocr_metadata": ocr_metadata,
        }
