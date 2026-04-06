"""Configuration for the traffic-light signal classification service."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]


class SignalSettings(BaseSettings):
    """Env-driven configuration for signal-state classification."""

    model_config = SettingsConfigDict(
        env_prefix="SIGNAL_",
        env_file=(_REPO_ROOT / ".env",),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── classifier backend ──────────────────────────────────────
    backend: str = Field(
        default="hsv_histogram",
        description="Signal classifier backend name (registry key).",
    )
    confidence_threshold: float = Field(
        default=0.35,
        ge=0.0,
        le=1.0,
        description="Minimum confidence to accept a color classification.",
    )
    min_crop_pixels: int = Field(
        default=12,
        gt=0,
        description="Minimum width/height (pixels) of a traffic-light crop to attempt classification.",
    )

    # ── temporal smoothing (hysteresis) ─────────────────────────
    smoothing_window: int = Field(
        default=5,
        ge=1,
        description="Number of recent frames to consider for majority-vote smoothing.",
    )
    transition_threshold: int = Field(
        default=3,
        ge=1,
        description="Minimum consecutive same-color votes to accept a state transition.",
    )
    unknown_after_missed_frames: int = Field(
        default=10,
        ge=1,
        description="Revert a signal head to UNKNOWN if unobserved for this many frames.",
    )

    # ── HSV backend tuning ──────────────────────────────────────
    hsv_red_hue_ranges: list[tuple[int, int]] = Field(
        default=[(0, 10), (160, 180)],
        description="H ranges in [0,180) that count as red.",
    )
    hsv_yellow_hue_range: tuple[int, int] = Field(
        default=(15, 35),
        description="H range in [0,180) that counts as yellow.",
    )
    hsv_green_hue_range: tuple[int, int] = Field(
        default=(36, 85),
        description="H range in [0,180) that counts as green.",
    )
    hsv_saturation_floor: int = Field(
        default=50,
        ge=0,
        le=255,
        description="Minimum S value to include a pixel in color voting.",
    )
    hsv_value_floor: int = Field(
        default=80,
        ge=0,
        le=255,
        description="Minimum V value to include a pixel in color voting.",
    )


@lru_cache
def get_signal_settings() -> SignalSettings:
    return SignalSettings()
