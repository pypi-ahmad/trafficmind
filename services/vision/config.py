"""Vision service configuration.

Separate from the API's ``Settings`` so the vision service can run
standalone (CLI, notebook, worker process) without importing FastAPI.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]


class VisionSettings(BaseSettings):
    """Env-driven configuration for the vision inference service."""

    model_config = SettingsConfigDict(
        env_prefix="VISION_",
        env_file=(_REPO_ROOT / ".env",),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── model paths ─────────────────────────────────────────────
    model_dir: Path = _REPO_ROOT / "models"
    yolo_model_path: Path = _REPO_ROOT / "models" / "yolo26x.pt"

    # ── device ──────────────────────────────────────────────────
    device: str = Field(
        default="auto",
        description="Torch device: 'auto', 'cpu', 'cuda', 'cuda:0', etc.",
    )

    # ── thresholds ──────────────────────────────────────────────
    confidence_threshold: float = Field(default=0.25, ge=0.0, le=1.0)
    iou_threshold: float = Field(default=0.45, ge=0.0, le=1.0)

    # ── inference options ───────────────────────────────────────
    image_size: int = Field(default=640, gt=0)
    half_precision: bool = Field(
        default=True,
        description="Use FP16 inference when running on CUDA.",
    )
    max_detections: int = Field(default=300, gt=0)

    @field_validator("model_dir", "yolo_model_path", mode="before")
    @classmethod
    def resolve_relative_paths(cls, value: str | Path) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return (_REPO_ROOT / path).resolve()

    def resolve_device(self) -> str:
        """Return the concrete torch device string."""
        if self.device != "auto":
            return self.device
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"


@lru_cache
def get_vision_settings() -> VisionSettings:
    return VisionSettings()
