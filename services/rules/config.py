"""Env-driven configuration for the traffic rules engine."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]


class RulesSettings(BaseSettings):
    """Configuration for the traffic rules engine."""

    model_config = SettingsConfigDict(
        env_prefix="RULES_",
        env_file=(_REPO_ROOT / ".env",),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    default_cooldown_seconds: float = Field(default=30.0, ge=0.0)
    max_violations_per_track: int = Field(default=50, gt=0)
    candidate_timeout_seconds: float = Field(
        default=2.0,
        gt=0.0,
        description="Maximum age of an unconfirmed pre-violation candidate before it is discarded.",
    )
    min_signal_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum signal-head confidence required for flagship rules to "
            "treat the signal state as usable.  Below this threshold the "
            "state is treated as UNKNOWN and no candidate is created."
        ),
    )
    enable_debug_logging: bool = Field(default=False)


@lru_cache
def get_rules_settings() -> RulesSettings:
    return RulesSettings()
