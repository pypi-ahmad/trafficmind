"""Env-driven configuration for the tracking service."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]


class TrackingSettings(BaseSettings):
    """Configuration for deterministic multi-object tracking."""

    model_config = SettingsConfigDict(
        env_prefix="TRACKING_",
        env_file=(_REPO_ROOT / ".env",),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    backend: str = "bytetrack"
    frame_rate: int = Field(default=30, gt=0)
    trajectory_history_size: int = Field(default=64, gt=1)
    track_activation_threshold: float = Field(default=0.25, ge=0.0, le=1.0)
    minimum_matching_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    minimum_consecutive_frames: int = Field(default=1, gt=0)
    lost_track_buffer: int = Field(default=30, ge=0)


@lru_cache
def get_tracking_settings() -> TrackingSettings:
    return TrackingSettings()
