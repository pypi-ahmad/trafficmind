"""Env-driven configuration for the OCR service."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]


class OcrSettings(BaseSettings):
    """Configuration for the OCR / ANPR pipeline."""

    model_config = SettingsConfigDict(
        env_prefix="OCR_",
        env_file=(_REPO_ROOT / ".env",),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    backend: str = "paddleocr"
    language: str = Field(default="en", min_length=1)
    confidence_threshold: float = Field(default=0.60, ge=0.0, le=1.0)
    default_country_code: str | None = Field(
        default=None,
        max_length=8,
        description="ISO 3166-1 alpha-2 country code (e.g. 'SA', 'US', 'AE').",
    )
    max_plate_length: int = Field(default=15, gt=0)
    min_plate_length: int = Field(default=2, gt=0)
    crop_output_dir: Path | None = Field(
        default=None,
        description="Directory to save plate crop images. None disables saving.",
    )
    use_gpu: bool = Field(
        default=True,
        description="Prefer Paddle CUDA when available; falls back to CPU if the installed Paddle build has no CUDA support.",
    )
    model_dir: Path | None = Field(
        default=None,
        description="Root directory for OCR model weights.",
    )

    @field_validator("crop_output_dir", "model_dir", mode="before")
    @classmethod
    def resolve_relative_paths(cls, value: str | Path | None) -> Path | None:
        if value is None:
            return None
        path = Path(value)
        if path.is_absolute():
            return path
        return (_REPO_ROOT / path).resolve()

    @model_validator(mode="after")
    def validate_plate_length_bounds(self) -> OcrSettings:
        if self.min_plate_length > self.max_plate_length:
            msg = "min_plate_length must be less than or equal to max_plate_length"
            raise ValueError(msg)
        return self

    def resolve_use_gpu(self) -> bool:
        """Return whether OCR should actually use Paddle CUDA."""
        if not self.use_gpu:
            return False
        try:
            import paddle

            return bool(paddle.device.is_compiled_with_cuda())
        except ImportError:
            return False


@lru_cache
def get_ocr_settings() -> OcrSettings:
    return OcrSettings()
