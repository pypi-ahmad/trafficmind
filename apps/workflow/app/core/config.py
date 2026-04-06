"""Application configuration for the TrafficMind workflow service."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from services.runtime import RuntimeEnvironment, normalize_environment, normalize_log_level

REPO_ROOT = Path(__file__).resolve().parents[4]
WORKFLOW_ROOT = REPO_ROOT / "apps" / "workflow"


class Settings(BaseSettings):
    """Centralised, env-driven configuration for the workflow service."""

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", WORKFLOW_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        env_prefix="WORKFLOW_",
        populate_by_name=True,
    )

    app_name: str = Field(
        default="TrafficMind Workflow",
        validation_alias=AliasChoices("WORKFLOW_APP_NAME", "APP_NAME"),
    )
    version: str = "0.1.0"
    environment: RuntimeEnvironment = Field(
        default=RuntimeEnvironment.LOCAL,
        validation_alias=AliasChoices("WORKFLOW_ENV", "TRAFFICMIND_ENV", "APP_ENV"),
    )
    debug: bool = Field(default=False, validation_alias=AliasChoices("WORKFLOW_DEBUG", "DEBUG"))
    strict_startup_checks: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "WORKFLOW_STRICT_STARTUP_CHECKS", "TRAFFICMIND_STRICT_STARTUP_CHECKS"
        ),
    )

    host: str = "0.0.0.0"
    port: int = Field(default=8010, validation_alias=AliasChoices("WORKFLOW_PORT", "PORT"))
    api_prefix: str = Field(
        default="/api/v1", validation_alias=AliasChoices("WORKFLOW_API_PREFIX", "API_PREFIX")
    )
    log_level: str = Field(
        default="INFO", validation_alias=AliasChoices("WORKFLOW_LOG_LEVEL", "LOG_LEVEL")
    )

    database_url: str = Field(
        default="sqlite+aiosqlite:///./trafficmind.db",
        validation_alias=AliasChoices(
            "WORKFLOW_DATABASE_URL", "TRAFFICMIND_DATABASE_URL", "DATABASE_URL"
        ),
    )

    provider_backend: str = Field(default="heuristic")
    openai_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("WORKFLOW_OPENAI_API_KEY", "OPENAI_API_KEY")
    )
    openai_model: str = "gpt-4.1-mini"

    checkpoint_backend: str = Field(default="memory")
    enable_human_interrupts: bool = True

    @field_validator("environment", mode="before")
    @classmethod
    def validate_environment(cls, value: str | RuntimeEnvironment) -> RuntimeEnvironment:
        return normalize_environment(value)

    @field_validator("log_level", mode="before")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        return normalize_log_level(value)

    @field_validator("provider_backend")
    @classmethod
    def validate_provider_backend(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized != "heuristic":
            msg = "workflow provider backend must currently be 'heuristic'"
            raise ValueError(msg)
        return normalized

    @field_validator("checkpoint_backend")
    @classmethod
    def validate_checkpoint_backend(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized != "memory":
            msg = "workflow checkpoint backend must currently be 'memory'"
            raise ValueError(msg)
        return normalized

    @field_validator("api_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        if not value.startswith("/"):
            msg = "api_prefix must start with '/'"
            raise ValueError(msg)
        return value.rstrip("/") or "/"

    @property
    def docs_url(self) -> str:
        return f"{self.api_prefix}/docs"

    @property
    def openapi_url(self) -> str:
        return f"{self.api_prefix}/openapi.json"


@lru_cache
def get_settings() -> Settings:
    """Return the cached workflow settings instance."""

    return Settings()
