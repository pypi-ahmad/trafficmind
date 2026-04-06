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
    device: str | None = Field(
        default=None,
        description=(
            "PaddleOCR 3.x device string: 'gpu:0', 'cpu', etc.\n"
            "None (default) → auto-detects via paddle.device.is_compiled_with_cuda():\n"
            "  • Paddle CUDA wheel installed → 'gpu:0'.\n"
            "  • Paddle CPU-only wheel installed → 'cpu' (most common on Windows).\n"
            "Set 'cpu' explicitly to force CPU even when a CUDA wheel is present."
        ),
    )
    model_dir: Path | None = Field(
        default=None,
        description="Root directory for OCR model weights.",
    )

    # Kept for backward compat with OCR_USE_GPU env var
    use_gpu: bool = Field(
        default=True,
        exclude=True,
        description=(
            "Legacy flag; prefer ``device``.\n"
            "When ``device`` is None and ``use_gpu`` is True (the default), the "
            "engine auto-detects whether the installed PaddlePaddle build has CUDA "
            "support.  Set ``use_gpu=False`` (or ``OCR_USE_GPU=false``) to force "
            "CPU unconditionally."
        ),
    )
    enable_mkldnn: bool = Field(
        default=False,
        description=(
            "Enable oneDNN (MKL-DNN) acceleration. Disabled by default due to "
            "PaddlePaddle 3.x oneDNN bugs on Windows; enable on Linux if desired."
        ),
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

    def resolve_device(self) -> str:
        """Return the PaddleOCR 3.x ``device`` string.

        Resolution order:
        1. If ``OCR_DEVICE`` is explicitly set, return it as-is.
        2. If ``OCR_USE_GPU`` is ``false``, return ``"cpu"``.
        3. Auto-detect: ``"gpu:0"`` when ``paddle.device.is_compiled_with_cuda()``
           is ``True``; otherwise ``"cpu"``.

        On Windows, only CPU-only PaddlePaddle wheels are published
        by upstream, so auto-detection always resolves to ``"cpu"``.
        On Linux with ``paddlepaddle-gpu`` installed, this resolves to
        ``"gpu:0"`` automatically.
        """
        if self.device is not None:
            return self.device
        if not self.use_gpu:
            return "cpu"
        try:
            import paddle

            if paddle.device.is_compiled_with_cuda():
                return "gpu:0"
        except ImportError:
            pass
        return "cpu"

    def resolve_use_gpu(self) -> bool:
        """Return whether OCR should actually use Paddle CUDA.

        Kept for backward compatibility; delegates to :meth:`resolve_device`.
        """
        return self.resolve_device().startswith("gpu")


@lru_cache
def get_ocr_settings() -> OcrSettings:
    return OcrSettings()
