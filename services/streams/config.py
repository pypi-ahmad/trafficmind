"""Runtime configuration for the stream processing layer."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from services.runtime import RuntimeEnvironment, normalize_environment, normalize_log_level

_REPO_ROOT = Path(__file__).resolve().parents[2]


class StreamSettings(BaseSettings):
    """Env-driven configuration for stream workers and the orchestrator."""

    model_config = SettingsConfigDict(
        env_prefix="STREAM_",
        env_file=(_REPO_ROOT / ".env",),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    environment: RuntimeEnvironment = Field(
        default=RuntimeEnvironment.LOCAL,
        validation_alias=AliasChoices("STREAM_ENV", "TRAFFICMIND_ENV", "APP_ENV"),
    )
    log_level: str = Field(
        default="INFO",
        validation_alias=AliasChoices("STREAM_LOG_LEVEL", "TRAFFICMIND_LOG_LEVEL", "LOG_LEVEL"),
    )
    strict_startup_checks: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "STREAM_STRICT_STARTUP_CHECKS", "TRAFFICMIND_STRICT_STARTUP_CHECKS"
        ),
    )

    # ── concurrency ─────────────────────────────────────────────
    max_concurrent_jobs: int = Field(
        default=4,
        ge=1,
        description="Maximum number of stream-processing jobs that can run simultaneously.",
    )

    # ── frame acquisition ───────────────────────────────────────
    default_frame_step: int = Field(
        default=1,
        ge=1,
        description="Process every Nth frame.  1 = every frame.",
    )
    default_max_processing_fps: float | None = Field(
        default=None,
        gt=0.0,
        description="Optional cap for inference cadence; frames above this rate are skipped.",
    )
    reconnect_delay_seconds: float = Field(
        default=5.0,
        ge=0.0,
        description="Seconds to wait before retrying a failed RTSP/stream connection.",
    )
    max_reconnect_attempts: int = Field(
        default=10,
        ge=0,
        description="Maximum reconnect retries before marking the job as failed.  0 = unlimited.",
    )
    frame_timeout_seconds: float = Field(
        default=30.0,
        ge=1.0,
        description=(
            "Seconds without a successful frame read before the source is considered stale."
        ),
    )

    # ── pipeline ────────────────────────────────────────────────
    enable_detection: bool = True
    enable_tracking: bool = True
    enable_ocr: bool = False
    enable_rules: bool = True

    # ── metrics / heartbeat ─────────────────────────────────────
    heartbeat_interval_seconds: float = Field(
        default=5.0,
        ge=1.0,
        description="Frequency at which workers report their status.",
    )
    metrics_window_size: int = Field(
        default=120,
        ge=10,
        description="Number of recent frame timings kept for rolling-average FPS calculation.",
    )

    # ── file playback ───────────────────────────────────────────
    file_loop: bool = Field(
        default=False,
        description="Loop file-based sources instead of completing after the last frame.",
    )
    drop_frames_when_behind: bool = Field(
        default=True,
        description="Skip extra frames on live sources when inference falls behind real time.",
    )
    max_backpressure_frame_drops: int = Field(
        default=4,
        ge=0,
        description="Maximum additional frames to drop after one slow inference cycle.",
    )
    metrics_log_interval_seconds: float = Field(
        default=5.0,
        ge=0.5,
        description="How often workers log inference-loop metrics while running.",
    )

    @field_validator("environment", mode="before")
    @classmethod
    def validate_environment(cls, value: str | RuntimeEnvironment) -> RuntimeEnvironment:
        return normalize_environment(value)

    @field_validator("log_level", mode="before")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        return normalize_log_level(value)


@lru_cache
def get_stream_settings() -> StreamSettings:
    return StreamSettings()
