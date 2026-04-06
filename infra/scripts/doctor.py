"""Run configuration and readiness diagnostics across TrafficMind services."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from dotenv import dotenv_values

if TYPE_CHECKING:
    from services.runtime import RuntimeCheck, RuntimeReadinessReport

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate TrafficMind runtime configuration across services."
    )
    parser.add_argument(
        "--service",
        action="append",
        choices=["all", "api", "workflow", "streams", "frontend"],
        help="Service to check. Repeat to run multiple checks. Defaults to all.",
    )
    parser.add_argument(
        "--env-file", default=None, help="Optional env file to load before running checks."
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit JSON instead of a human-readable report."
    )
    return parser


def _selected_services(values: list[str] | None) -> list[str]:
    if not values or "all" in values:
        return ["api", "workflow", "streams", "frontend"]
    return values


def _load_env_file(path: str | None) -> None:
    if not path:
        return
    env_path = Path(path)
    if not env_path.is_absolute():
        env_path = (REPO_ROOT / env_path).resolve()
    if not env_path.exists():
        raise FileNotFoundError(f"Env file not found: {env_path}")

    for key, value in dotenv_values(env_path).items():
        if value is None:
            continue
        os.environ[key] = value


async def _build_api_report() -> RuntimeReadinessReport:
    from apps.api.app.core.config import Settings
    from apps.api.app.core.startup import build_api_readiness_report
    from services.runtime import probe_database_connectivity

    settings = Settings()
    connected, detail = await probe_database_connectivity(settings.database_url)
    return build_api_readiness_report(
        settings, database_connected=connected, database_detail=detail
    )


async def _build_workflow_report() -> RuntimeReadinessReport:
    from apps.workflow.app.core.config import Settings
    from apps.workflow.app.core.startup import build_workflow_readiness_report
    from services.runtime import probe_database_connectivity

    settings = Settings()
    connected, detail = await probe_database_connectivity(settings.database_url)
    return build_workflow_readiness_report(
        settings, database_connected=connected, database_detail=detail
    )


def _build_streams_report() -> RuntimeReadinessReport:
    from services.streams.config import StreamSettings
    from services.streams.startup import build_stream_startup_report

    settings = StreamSettings()
    return build_stream_startup_report(
        settings,
        detection_enabled=settings.enable_detection,
        tracking_enabled=settings.enable_tracking,
        ocr_enabled=settings.enable_ocr,
        require_model_files=False,
    )


def _is_valid_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _build_frontend_report() -> RuntimeReadinessReport:
    from services.runtime import (
        RuntimeCheck,
        RuntimeCheckSeverity,
        build_readiness_report,
        is_local_url,
        is_production_like_environment,
        normalize_environment,
    )

    checks: list[RuntimeCheck] = []
    environment = normalize_environment(os.getenv("TRAFFICMIND_ENV", "local"))
    production_like = is_production_like_environment(environment)

    canonical_base_url = os.getenv("TRAFFICMIND_API_BASE_URL") or os.getenv(
        "NEXT_PUBLIC_TRAFFICMIND_API_BASE_URL"
    )
    legacy_base_url = os.getenv("NEXT_PUBLIC_API_BASE_URL")
    api_base_url = canonical_base_url or legacy_base_url
    uses_local_api_base_url = bool(api_base_url and production_like and is_local_url(api_base_url))

    if not api_base_url:
        checks.append(
            RuntimeCheck(
                code="frontend_api_base_url",
                severity=RuntimeCheckSeverity.WARNING,
                message="No frontend API base URL is configured.",
                detail=(
                    "The frontend will fall back to http://127.0.0.1:8000/api/v1 "
                    "unless TRAFFICMIND_API_BASE_URL or "
                    "NEXT_PUBLIC_TRAFFICMIND_API_BASE_URL is set."
                ),
            )
        )
    elif not _is_valid_http_url(api_base_url):
        checks.append(
            RuntimeCheck(
                code="frontend_api_base_url",
                severity=RuntimeCheckSeverity.ERROR,
                message="The configured frontend API base URL is not a valid http(s) URL.",
                detail=f"Received: {api_base_url}",
            )
        )
    else:
        checks.append(
            RuntimeCheck(
                code="frontend_api_base_url",
                severity=(
                    RuntimeCheckSeverity.ERROR
                    if uses_local_api_base_url
                    else RuntimeCheckSeverity.INFO
                ),
                message=(
                    "The frontend still points at a localhost API in a "
                    "staging/prod-like environment."
                    if uses_local_api_base_url
                    else f"Frontend API base URL resolved to {api_base_url}."
                ),
                detail=(
                    "Set TRAFFICMIND_API_BASE_URL or "
                    "NEXT_PUBLIC_TRAFFICMIND_API_BASE_URL to a non-local endpoint "
                    "before claiming a remote deployment."
                    if uses_local_api_base_url
                    else None
                ),
            )
        )

    if legacy_base_url and not canonical_base_url:
        checks.append(
            RuntimeCheck(
                code="legacy_frontend_api_alias",
                severity=RuntimeCheckSeverity.WARNING,
                message=(
                    "The frontend is still relying on the legacy NEXT_PUBLIC_API_BASE_URL alias."
                ),
                detail=(
                    "Use NEXT_PUBLIC_TRAFFICMIND_API_BASE_URL or "
                    "TRAFFICMIND_API_BASE_URL as the canonical variable name."
                ),
            )
        )

    requested_provider = os.getenv("NEXT_PUBLIC_MAP_PROVIDER", "coordinate-grid")
    style_url = os.getenv("NEXT_PUBLIC_MAP_STYLE_URL")
    if requested_provider == "maplibre" and not style_url:
        checks.append(
            RuntimeCheck(
                code="frontend_map_provider",
                severity=RuntimeCheckSeverity.WARNING,
                message="MapLibre was requested but NEXT_PUBLIC_MAP_STYLE_URL is not configured.",
                detail="The frontend will fall back to the coordinate-grid surface.",
            )
        )

    return build_readiness_report(service="frontend", environment=environment, checks=checks)


async def _collect_reports(services: list[str]) -> list[RuntimeReadinessReport]:
    reports: list[RuntimeReadinessReport] = []
    for service in services:
        if service == "api":
            reports.append(await _build_api_report())
        elif service == "workflow":
            reports.append(await _build_workflow_report())
        elif service == "streams":
            reports.append(_build_streams_report())
        elif service == "frontend":
            reports.append(_build_frontend_report())
    return reports


def _print_human_report(reports: list[RuntimeReadinessReport]) -> None:
    for report in reports:
        summary = (
            f"[{report.service}] {report.status} "
            f"(environment={report.environment}, errors={report.error_count}, "
            f"warnings={report.warning_count})"
        )
        print(summary)
        if not report.checks:
            print("  - no checks were emitted")
            continue
        for check in report.checks:
            print(f"  - {check.severity.upper()} {check.code}: {check.message}")
            if check.detail:
                print(f"    {check.detail}")


async def _main_async(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _load_env_file(args.env_file)
    reports = await _collect_reports(_selected_services(args.service))
    if args.json:
        print(
            json.dumps(
                {"reports": [report.model_dump(mode="json") for report in reports]}, indent=2
            )
        )
    else:
        _print_human_report(reports)
    return 0 if all(report.status == "ready" for report in reports) else 1


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_main_async(argv))


if __name__ == "__main__":
    raise SystemExit(main())
