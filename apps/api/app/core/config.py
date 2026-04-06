"""Application configuration via pydantic-settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from services.runtime import (
    RuntimeEnvironment,
    normalize_environment,
    normalize_log_level,
    parse_delimited_list,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
API_ROOT = REPO_ROOT / "apps" / "api"


class Settings(BaseSettings):
    """Centralised, env-driven configuration for the TrafficMind API."""

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", API_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        enable_decoding=False,
        populate_by_name=True,
    )

    # ── identity ────────────────────────────────────────────────
    app_name: str = Field(
        "TrafficMind API",
        validation_alias=AliasChoices("TRAFFICMIND_APP_NAME", "APP_NAME"),
    )
    version: str = "0.1.0"
    environment: RuntimeEnvironment = Field(
        RuntimeEnvironment.LOCAL,
        validation_alias=AliasChoices("TRAFFICMIND_ENV", "APP_ENV"),
    )
    debug: bool = Field(False, validation_alias=AliasChoices("TRAFFICMIND_DEBUG", "DEBUG"))
    strict_startup_checks: bool = Field(
        False,
        validation_alias=AliasChoices(
            "TRAFFICMIND_STRICT_STARTUP_CHECKS", "STRICT_STARTUP_CHECKS"
        ),
    )

    # ── server ──────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = Field(8000, validation_alias=AliasChoices("API_PORT", "PORT"))
    api_prefix: str = Field(
        "/api/v1", validation_alias=AliasChoices("TRAFFICMIND_API_PREFIX", "API_PREFIX")
    )
    allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        validation_alias=AliasChoices("TRAFFICMIND_ALLOWED_ORIGINS", "ALLOWED_ORIGINS"),
    )

    # ── logging ─────────────────────────────────────────────────
    log_level: str = Field(
        "INFO", validation_alias=AliasChoices("TRAFFICMIND_LOG_LEVEL", "LOG_LEVEL")
    )

    # ── database ────────────────────────────────────────────────
    database_url: str = Field(
        "sqlite+aiosqlite:///./trafficmind.db",
        validation_alias=AliasChoices("TRAFFICMIND_DATABASE_URL", "DATABASE_URL"),
    )

    # ── redis ───────────────────────────────────────────────────
    redis_url: str = Field(
        "redis://localhost:6379/0",
        validation_alias=AliasChoices("TRAFFICMIND_REDIS_URL", "REDIS_URL"),
    )

    # ── models / CV ─────────────────────────────────────────────
    model_dir: Path = Field(
        REPO_ROOT / "models", validation_alias=AliasChoices("TRAFFICMIND_MODEL_DIR", "MODEL_DIR")
    )
    yolo_model_path: Path = Field(
        REPO_ROOT / "models" / "yolo26x.pt",
        validation_alias=AliasChoices("TRAFFICMIND_YOLO_MODEL_PATH", "YOLO_MODEL_PATH"),
    )
    evaluation_fixture_suite_path: Path = Field(
        REPO_ROOT / "tests" / "fixtures" / "evaluation" / "benchmark_suite.json",
        validation_alias=AliasChoices(
            "TRAFFICMIND_EVALUATION_FIXTURE_SUITE_PATH",
            "EVALUATION_FIXTURE_SUITE_PATH",
        ),
    )
    evaluation_artifact_dir: Path = Field(
        REPO_ROOT / "outputs" / "evaluation",
        validation_alias=AliasChoices(
            "TRAFFICMIND_EVALUATION_ARTIFACT_DIR",
            "EVALUATION_ARTIFACT_DIR",
        ),
    )

    # ── feature flags (enabled service modules) ─────────────────
    enable_vision: bool = True
    enable_tracking: bool = True
    enable_ocr: bool = False  # gated until plate-detection strategy decided
    enable_rules: bool = True
    enable_workflow: bool = True

    @field_validator(
        "model_dir",
        "yolo_model_path",
        "evaluation_fixture_suite_path",
        "evaluation_artifact_dir",
        mode="before",
    )
    @classmethod
    def resolve_repo_relative_paths(cls, value: str | Path) -> Path:
        """Resolve relative model paths against the repository root."""
        path = Path(value)
        if path.is_absolute():
            return path
        return (REPO_ROOT / path).resolve()

    @field_validator("environment", mode="before")
    @classmethod
    def validate_environment(cls, value: str | RuntimeEnvironment) -> RuntimeEnvironment:
        return normalize_environment(value)

    @field_validator("log_level", mode="before")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        return normalize_log_level(value)

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def validate_allowed_origins(cls, value: str | list[str] | None) -> list[str]:
        return parse_delimited_list(value)

    @field_validator("api_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        if not value.startswith("/"):
            msg = "api_prefix must start with '/'"
            raise ValueError(msg)
        return value.rstrip("/") or "/"

    @property
    def enabled_modules(self) -> list[str]:
        """Return the list of module names whose flags are on."""
        mapping = {
            "vision": self.enable_vision,
            "tracking": self.enable_tracking,
            "ocr": self.enable_ocr,
            "rules": self.enable_rules,
            "workflow": self.enable_workflow,
        }
        return [name for name, on in mapping.items() if on]

    @property
    def docs_url(self) -> str:
        """Return the versioned Swagger UI path."""
        return f"{self.api_prefix}/docs"

    @property
    def redoc_url(self) -> str:
        """Return the versioned ReDoc path."""
        return f"{self.api_prefix}/redoc"

    @property
    def openapi_url(self) -> str:
        """Return the versioned OpenAPI document path."""
        return f"{self.api_prefix}/openapi.json"


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings instance."""
    return Settings()
