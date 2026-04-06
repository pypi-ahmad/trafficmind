"""Runtime environment normalization and readiness reporting helpers."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum
from urllib.parse import urlparse

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


class RuntimeEnvironment(StrEnum):
    LOCAL = "local"
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


class RuntimeCheckSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class RuntimeReadinessState(StrEnum):
    READY = "ready"
    NOT_READY = "not_ready"


class RuntimeCheck(BaseModel):
    code: str
    severity: RuntimeCheckSeverity
    message: str
    detail: str | None = None


class RuntimeReadinessReport(BaseModel):
    service: str
    environment: RuntimeEnvironment
    status: RuntimeReadinessState
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    error_count: int
    warning_count: int
    checks: list[RuntimeCheck] = Field(default_factory=list)


_ENVIRONMENT_ALIASES = {
    "local": RuntimeEnvironment.LOCAL,
    "development": RuntimeEnvironment.DEV,
    "dev": RuntimeEnvironment.DEV,
    "ci": RuntimeEnvironment.DEV,
    "test": RuntimeEnvironment.DEV,
    "staging": RuntimeEnvironment.STAGING,
    "stage": RuntimeEnvironment.STAGING,
    "prod": RuntimeEnvironment.PROD,
    "production": RuntimeEnvironment.PROD,
}

_VALID_LOG_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}


def normalize_environment(value: str | RuntimeEnvironment) -> RuntimeEnvironment:
    if isinstance(value, RuntimeEnvironment):
        return value
    normalized = value.strip().lower()
    if normalized in _ENVIRONMENT_ALIASES:
        return _ENVIRONMENT_ALIASES[normalized]
    msg = f"Unsupported environment {value!r}. Supported values: local, dev, staging, prod"
    raise ValueError(msg)


def normalize_log_level(value: str) -> str:
    normalized = value.strip().upper()
    if normalized in _VALID_LOG_LEVELS:
        return normalized
    supported_values = ", ".join(sorted(_VALID_LOG_LEVELS))
    msg = f"Unsupported log level {value!r}. Supported values: {supported_values}"
    raise ValueError(msg)


def parse_delimited_list(value: str | Iterable[str] | None) -> list[str]:
    if value is None:
        return []
    candidates = value.split(",") if isinstance(value, str) else list(value)

    normalized: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        stripped = str(item).strip()
        if not stripped:
            continue
        normalized_item = stripped.rstrip("/")
        if normalized_item in seen:
            continue
        normalized.append(normalized_item)
        seen.add(normalized_item)
    return normalized


def is_production_like_environment(value: RuntimeEnvironment | str) -> bool:
    environment = normalize_environment(value)
    return environment in {RuntimeEnvironment.STAGING, RuntimeEnvironment.PROD}


def database_backend_label(database_url: str) -> str:
    candidate = database_url.strip().lower()
    if candidate.startswith("sqlite"):
        return "sqlite"
    if candidate.startswith("postgresql"):
        return "postgresql"
    if candidate.startswith("mysql"):
        return "mysql"
    if candidate.startswith("mssql"):
        return "mssql"
    if candidate.startswith("oracle"):
        return "oracle"
    parsed = urlparse(candidate)
    return parsed.scheme or "unknown"


def is_local_url(value: str) -> bool:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "0.0.0.0"}


def build_readiness_report(
    *,
    service: str,
    environment: RuntimeEnvironment | str,
    checks: list[RuntimeCheck],
) -> RuntimeReadinessReport:
    resolved_environment = normalize_environment(environment)
    error_count = sum(1 for item in checks if item.severity == RuntimeCheckSeverity.ERROR)
    warning_count = sum(1 for item in checks if item.severity == RuntimeCheckSeverity.WARNING)
    return RuntimeReadinessReport(
        service=service,
        environment=resolved_environment,
        status=RuntimeReadinessState.NOT_READY if error_count > 0 else RuntimeReadinessState.READY,
        error_count=error_count,
        warning_count=warning_count,
        checks=checks,
    )


def log_readiness_report(logger: logging.Logger, report: RuntimeReadinessReport) -> None:
    for check in report.checks:
        message = f"[{report.service}] {check.code}: {check.message}"
        if check.detail:
            message = f"{message} ({check.detail})"
        if check.severity == RuntimeCheckSeverity.ERROR:
            logger.error(message)
        elif check.severity == RuntimeCheckSeverity.WARNING:
            logger.warning(message)
        else:
            logger.info(message)


async def probe_database_connectivity(database_url: str) -> tuple[bool, str]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True, "Database connectivity probe succeeded."
    except Exception as exc:  # pragma: no cover - exact DB failures vary by backend
        return False, f"Database connectivity probe failed: {exc}"
    finally:
        await engine.dispose()
