"""Env-driven configuration for the re-identification service."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]


class ReIdSettings(BaseSettings):
    """Configuration for multi-camera re-identification."""

    model_config = SettingsConfigDict(
        env_prefix="REID_",
        env_file=(_REPO_ROOT / ".env",),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -- embedding --
    embedding_model: str = Field(
        default="resnet50-market1501",
        description="Name of the appearance embedding model.",
    )
    embedding_dimension: int = Field(
        default=512,
        ge=1,
        description="Expected embedding dimension.",
    )

    # -- matching thresholds --
    high_confidence_threshold: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Similarity >= this is HIGH confidence.",
    )
    medium_confidence_threshold: float = Field(
        default=0.70,
        ge=0.0,
        le=1.0,
        description="Similarity >= this is MEDIUM confidence (below → LOW).",
    )
    auto_confirm_threshold: float = Field(
        default=0.90,
        ge=0.0,
        le=1.0,
        description="Similarity >= this auto-confirms matches.",
    )
    candidate_ttl_seconds: int = Field(
        default=3600,
        ge=60,
        description="TTL for unresolved candidate matches before they expire.",
    )

    # -- search --
    default_top_k: int = Field(default=10, ge=1)
    default_min_similarity: float = Field(default=0.5, ge=0.0, le=1.0)

    # -- privacy --
    person_reid_enabled: bool = Field(
        default=False,
        description="Enable person re-id.  Disabled by default for privacy.",
    )


@lru_cache(maxsize=1)
def get_reid_settings() -> ReIdSettings:
    """Return cached settings singleton."""
    return ReIdSettings()
