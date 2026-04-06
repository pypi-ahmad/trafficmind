"""Live local smoke checks for the TrafficMind golden path.

This script verifies the services a developer started locally:
1. API readiness
2. Workflow readiness
3. Real API list/feed routes
4. One workflow execution route
5. Frontend page rendering against the live backend

It is intentionally local-first and does not claim production orchestration.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_API_BASE_URL = "http://127.0.0.1:8000/api/v1"
DEFAULT_WORKFLOW_BASE_URL = "http://127.0.0.1:8010/api/v1"
DEFAULT_FRONTEND_BASE_URL = "http://127.0.0.1:3000"
DEFAULT_FRONTEND_SENTINEL = "Map-first camera operations with honest spatial analytics."


@dataclass(frozen=True)
class SmokeCheckResult:
    name: str
    detail: str


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run live local smoke checks for the TrafficMind golden path."
    )
    parser.add_argument(
        "--env-file",
        default=None,
        help="Optional env file to load before resolving URLs. Defaults to .env when present.",
    )
    parser.add_argument("--api-base-url", default=None)
    parser.add_argument("--workflow-base-url", default=None)
    parser.add_argument("--frontend-base-url", default=None)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--expect-demo-data",
        action="store_true",
        help="Require non-empty cameras and persisted feed records, matching the demo-seeded flow.",
    )
    return parser


def _resolve_env_file(path: str | None) -> Path | None:
    if path is None:
        default_path = REPO_ROOT / ".env"
        return default_path if default_path.exists() else None

    env_path = Path(path)
    if not env_path.is_absolute():
        env_path = (REPO_ROOT / env_path).resolve()
    return env_path


def _load_env(path: Path | None) -> None:
    if path is None:
        return
    if not path.exists():
        raise FileNotFoundError(f"Env file not found: {path}")

    for key, value in dotenv_values(path).items():
        if value is None:
            continue
        os.environ[key] = value


def _normalize_base_url(value: str) -> str:
    return value.rstrip("/")


def _resolve_api_base_url(explicit: str | None) -> str:
    return _normalize_base_url(
        explicit
        or os.getenv("TRAFFICMIND_API_BASE_URL")
        or os.getenv("NEXT_PUBLIC_TRAFFICMIND_API_BASE_URL")
        or os.getenv("NEXT_PUBLIC_API_BASE_URL")
        or DEFAULT_API_BASE_URL
    )


def _resolve_workflow_base_url(explicit: str | None) -> str:
    return _normalize_base_url(
        explicit
        or os.getenv("TRAFFICMIND_WORKFLOW_BASE_URL")
        or DEFAULT_WORKFLOW_BASE_URL
    )


def _resolve_frontend_base_url(explicit: str | None) -> str:
    return _normalize_base_url(
        explicit or os.getenv("TRAFFICMIND_FRONTEND_BASE_URL") or DEFAULT_FRONTEND_BASE_URL
    )


def _wait_for_json(
    client: httpx.Client,
    url: str,
    *,
    timeout_seconds: float,
    expected_status: int,
    validator: callable[[dict[str, Any]], tuple[bool, str]],
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_error: str | None = None

    while time.monotonic() < deadline:
        try:
            response = client.get(url)
            if response.status_code != expected_status:
                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                time.sleep(1.0)
                continue
            payload = response.json()
            ok, detail = validator(payload)
            if ok:
                return payload
            last_error = detail
        except Exception as exc:  # pragma: no cover - defensive live smoke path
            last_error = str(exc)
        time.sleep(1.0)

    raise RuntimeError(f"Timed out waiting for {url}: {last_error or 'unknown error'}")


def _wait_for_text(
    client: httpx.Client,
    url: str,
    *,
    timeout_seconds: float,
    expected_text: str,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    last_error: str | None = None

    while time.monotonic() < deadline:
        try:
            response = client.get(url)
            if response.status_code != 200:
                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                time.sleep(1.0)
                continue
            if expected_text in response.text:
                return response.text
            last_error = f"Expected text not found in response from {url}"
        except Exception as exc:  # pragma: no cover - defensive live smoke path
            last_error = str(exc)
        time.sleep(1.0)

    raise RuntimeError(f"Timed out waiting for {url}: {last_error or 'unknown error'}")


def _check_api_routes(
    client: httpx.Client,
    api_base_url: str,
    *,
    expect_demo_data: bool,
) -> tuple[list[SmokeCheckResult], str | None]:
    results: list[SmokeCheckResult] = []

    cameras_response = client.get(f"{api_base_url}/cameras", params={"limit": 1})
    cameras_response.raise_for_status()
    cameras_payload = cameras_response.json()
    camera_total = int(cameras_payload.get("total", 0))
    camera_id = None
    camera_name = None
    if cameras_payload.get("items"):
        camera_id = cameras_payload["items"][0]["id"]
        camera_name = cameras_payload["items"][0].get("name")
    if expect_demo_data and camera_total < 1:
        raise RuntimeError("Expected demo data, but /cameras returned zero records.")
    results.append(SmokeCheckResult("api cameras", f"/cameras responded with total={camera_total}"))

    events_response = client.get(f"{api_base_url}/events", params={"limit": 1})
    events_response.raise_for_status()
    events_payload = events_response.json()
    event_total = int(events_payload.get("total", 0))
    results.append(SmokeCheckResult("api events feed", f"/events responded with total={event_total}"))

    violations_response = client.get(f"{api_base_url}/violations", params={"limit": 1})
    violations_response.raise_for_status()
    violations_payload = violations_response.json()
    violation_total = int(violations_payload.get("total", 0))
    results.append(
        SmokeCheckResult(
            "api violations feed",
            f"/violations responded with total={violation_total}",
        )
    )

    if expect_demo_data and (event_total + violation_total) < 1:
        raise RuntimeError(
            "Expected demo data, but /events and /violations returned no persisted records."
        )

    workflow_totals = client.get(f"{api_base_url}/events/summary/totals")
    workflow_totals.raise_for_status()
    total_payload = workflow_totals.json()
    results.append(
        SmokeCheckResult(
            "api summary totals",
            f"/events/summary/totals responded with total={int(total_payload.get('total', 0))}",
        )
    )

    return results, camera_id if camera_name is None else f"{camera_id}|{camera_name}"


def _check_operator_assist(client: httpx.Client, workflow_base_url: str) -> SmokeCheckResult:
    response = client.post(
        f"{workflow_base_url}/workflows/operator-assist",
        json={
            "query": "show all red-light violations",
            "requested_by": "local.smoke",
            "require_human_review": False,
        },
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("workflow_name") != "operator_assist":
        raise RuntimeError("Workflow smoke check returned an unexpected workflow_name.")
    if payload.get("status") != "succeeded":
        raise RuntimeError(
            f"Workflow smoke check did not succeed: status={payload.get('status')}"
        )
    return SmokeCheckResult(
        "workflow operator-assist",
        f"operator-assist succeeded with run_id={payload.get('run_id')}",
    )


def _check_frontend(
    client: httpx.Client,
    frontend_base_url: str,
    *,
    timeout_seconds: float,
    camera_context: str | None,
) -> list[SmokeCheckResult]:
    home_page_html = _wait_for_text(
        client,
        f"{frontend_base_url}/",
        timeout_seconds=timeout_seconds,
        expected_text=DEFAULT_FRONTEND_SENTINEL,
    )

    results = [
        SmokeCheckResult(
            "frontend home page",
            "home page rendered successfully",
        )
    ]

    if camera_context:
        camera_id, _, camera_name = camera_context.partition("|")
        if camera_name and camera_name not in home_page_html:
            raise RuntimeError(
                "Frontend home page rendered, but the API-backed camera fleet content "
                f"did not include {camera_name!r}."
            )
        if camera_name:
            results[0] = SmokeCheckResult(
                "frontend home page",
                f"home page rendered with live camera content for {camera_name}",
            )

        events_page_html = _wait_for_text(
            client,
            f"{frontend_base_url}/events?cameraId={camera_id}",
            timeout_seconds=timeout_seconds,
            expected_text="Event &amp; violation feed",
        )
        if camera_name and camera_name not in events_page_html:
            raise RuntimeError(
                "Frontend events page rendered, but the selected camera detail did not "
                f"include {camera_name!r}."
            )

        detail = (
            f"events page rendered with live camera context for {camera_name}"
            if camera_name
            else "events page rendered with camera context"
        )
        results.append(SmokeCheckResult("frontend events page", detail))

    return results


def _print_result(result: SmokeCheckResult) -> None:
    print(f"[PASS] {result.name}: {result.detail}")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        env_file = _resolve_env_file(args.env_file)
        _load_env(env_file)
        api_base_url = _resolve_api_base_url(args.api_base_url)
        workflow_base_url = _resolve_workflow_base_url(args.workflow_base_url)
        frontend_base_url = _resolve_frontend_base_url(args.frontend_base_url)

        print("TrafficMind local smoke check")
        print(f"  api:      {api_base_url}")
        print(f"  workflow: {workflow_base_url}")
        print(f"  frontend: {frontend_base_url}")
        print(f"  env file: {env_file if env_file else '(none)'}")
        print("")

        with httpx.Client(timeout=5.0, follow_redirects=True) as client:
            api_ready = _wait_for_json(
                client,
                f"{api_base_url}/health/ready",
                timeout_seconds=args.timeout,
                expected_status=200,
                validator=lambda payload: (
                    payload.get("status") == "ready",
                    f"API readiness returned status={payload.get('status')}",
                ),
            )
            _print_result(
                SmokeCheckResult(
                    "api readiness",
                    f"ready in {api_ready.get('environment', 'unknown')} environment",
                )
            )

            workflow_ready = _wait_for_json(
                client,
                f"{workflow_base_url}/health/ready",
                timeout_seconds=args.timeout,
                expected_status=200,
                validator=lambda payload: (
                    payload.get("status") == "ready",
                    f"Workflow readiness returned status={payload.get('status')}",
                ),
            )
            _print_result(
                SmokeCheckResult(
                    "workflow readiness",
                    f"ready in {workflow_ready.get('environment', 'unknown')} environment",
                )
            )

            api_results, camera_context = _check_api_routes(
                client,
                api_base_url,
                expect_demo_data=args.expect_demo_data,
            )
            for result in api_results:
                _print_result(result)

            _print_result(_check_operator_assist(client, workflow_base_url))

            frontend_results = _check_frontend(
                client,
                frontend_base_url,
                timeout_seconds=args.timeout,
                camera_context=camera_context,
            )
            for result in frontend_results:
                _print_result(result)

        print("")
        print("Smoke path proved:")
        print("- the migrated database is reachable by both Python services")
        print("- the API feed routes respond with real JSON payloads")
        print("- the workflow service executes a grounded workflow over stored data")
        print("- the Next.js UI renders against the live local backend")
        print("")
        print("Still manual / not covered:")
        print("- browser-only interactions such as map pan/zoom and UI clicks")
        print("- GPU-backed model inference and long-running worker jobs")
        print("- external delivery adapters and non-local deployments")
        return 0
    except Exception as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
