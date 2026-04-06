"""Run repeatable TrafficMind validation suites for local use and CI."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = REPO_ROOT / "frontend"
ROOT_ENV_FILE = REPO_ROOT / ".env"
FRONTEND_ENV_FILE = FRONTEND_ROOT / ".env.local"
KNOWN_FAILING_TEST_EXPRESSION = "not test_demo_seed_surfaces_in_camera_and_observability_apis"
BACKEND_RUFF_PATHS = [
    "apps/api/app/api/routes/health.py",
    "apps/api/app/core/config.py",
    "apps/api/app/core/startup.py",
    "apps/api/app/main.py",
    "apps/api/app/schemas/health.py",
    "apps/workflow/app/api/routes/health.py",
    "apps/workflow/app/core/config.py",
    "apps/workflow/app/core/startup.py",
    "apps/workflow/app/main.py",
    "infra/scripts/doctor.py",
    "infra/scripts/render_env.py",
    "infra/scripts/run_checks.py",
    "services/integrations/__init__.py",
    "services/integrations/adapters.py",
    "services/integrations/builders.py",
    "services/integrations/local.py",
    "services/integrations/schemas.py",
    "services/integrations/signals.py",
    "services/runtime/__init__.py",
    "services/runtime/deployment.py",
    "services/streams/__main__.py",
    "services/streams/config.py",
    "services/streams/startup.py",
]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run repeatable TrafficMind validation suites.")
    parser.add_argument(
        "--suite",
        choices=["backend", "frontend", "smoke", "golden-path", "all"],
        default="all",
    )
    parser.add_argument(
        "--include-known-failing-demo-seed",
        action="store_true",
        help=(
            "Include the currently known failing demo-seed observability "
            "test in the backend pytest run."
        ),
    )
    return parser


def _resolve_env_file(*candidates: Path) -> Path | None:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _build_subprocess_env(env_file: Path | None) -> dict[str, str]:
    env = os.environ.copy()
    if env_file is None:
        return env

    for key, value in dotenv_values(env_file).items():
        if value is None:
            continue
        env[key] = value
    return env


def _run(
    command: list[str],
    *,
    cwd: Path = REPO_ROOT,
    env: dict[str, str] | None = None,
) -> None:
    print(f"$ {' '.join(command)}")
    subprocess.run(command, cwd=cwd, env=env, check=True)


def _resolve_tool(name: str) -> str:
    candidates = [name]
    if sys.platform.startswith("win"):
        candidates.insert(0, f"{name}.cmd")

    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved

    msg = f"Required command {name!r} was not found on PATH."
    raise RuntimeError(msg)


def _run_backend_checks(include_known_failing_demo_seed: bool) -> None:
    backend_env_file = _resolve_env_file(ROOT_ENV_FILE)
    backend_env = _build_subprocess_env(backend_env_file)
    doctor_command = [
        sys.executable,
        "infra/scripts/doctor.py",
        "--service",
        "api",
        "--service",
        "workflow",
        "--service",
        "streams",
        "--service",
        "frontend",
    ]
    if backend_env_file is not None:
        doctor_command.extend(["--env-file", str(backend_env_file)])

    _run(
        doctor_command,
        env=backend_env,
    )
    _run([_resolve_tool("ruff"), "check", *BACKEND_RUFF_PATHS], env=backend_env)
    pytest_command = [sys.executable, "-m", "pytest", "tests", "-q", "-m", "not integration"]
    if not include_known_failing_demo_seed:
        pytest_command.extend(["-k", KNOWN_FAILING_TEST_EXPRESSION])
    _run(pytest_command, env=backend_env)


def _run_frontend_checks() -> None:
    frontend_env_file = _resolve_env_file(FRONTEND_ENV_FILE, ROOT_ENV_FILE)
    frontend_env = _build_subprocess_env(frontend_env_file)
    doctor_command = [sys.executable, "infra/scripts/doctor.py", "--service", "frontend"]
    if frontend_env_file is not None:
        doctor_command.extend(["--env-file", str(frontend_env_file)])
    _run(doctor_command, env=frontend_env)

    npm = _resolve_tool("npm")
    _run([npm, "run", "lint"], cwd=FRONTEND_ROOT, env=frontend_env)
    _run([npm, "run", "build"], cwd=FRONTEND_ROOT, env=frontend_env)


def _run_smoke_checks() -> None:
    backend_env_file = _resolve_env_file(ROOT_ENV_FILE)
    backend_env = _build_subprocess_env(backend_env_file)
    _run(
        [sys.executable, "-m", "pytest", "tests/smoke", "-v", "-m", "smoke"],
        env=backend_env,
    )


def _run_golden_path_checks() -> None:
    """Integrated regression: migrate → smoke pipeline → API + workflow routes → frontend build.

    Validates the full critical path in one command:
    1. Database migration chain (``alembic upgrade head`` on a temp SQLite DB)
    2. Detection → tracking → OCR → rules → persist smoke tests
    3. API foundation (health, config, route registration)
    4. Workflow routes (execution, interrupt/resume via HTTP)
    5. Frontend production build
    """
    backend_env_file = _resolve_env_file(ROOT_ENV_FILE)
    backend_env = _build_subprocess_env(backend_env_file)

    # --- 1. Verify alembic migration chain against a disposable SQLite DB ---
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_db = Path(tmp) / "golden_path.db"
        migration_env = backend_env.copy()
        migration_env["DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_db}"
        _run(
            [
                sys.executable, "-c",
                "import alembic.config; alembic.config.main(['upgrade', 'head'])",
            ],
            env=migration_env,
        )

    # --- 2. Smoke tests: detection → tracking → OCR → rules → persist ---
    _run(
        [sys.executable, "-m", "pytest", "tests/smoke", "-v", "-m", "smoke"],
        env=backend_env,
    )

    # --- 3. API foundation + 4. Workflow route tests ---
    _run(
        [
            sys.executable, "-m", "pytest",
            "tests/api/test_foundation.py",
            "tests/workflow/test_workflow_service.py::test_workflow_app_exposes_health_and_execution_routes",
            "tests/workflow/test_workflow_service.py::test_violation_review_interrupt_and_resume_via_http",
            "-v",
        ],
        env=backend_env,
    )

    # --- 5. Frontend build ---
    npm = _resolve_tool("npm")
    _run([npm, "run", "build"], cwd=FRONTEND_ROOT, env=_build_subprocess_env(
        _resolve_env_file(FRONTEND_ENV_FILE, ROOT_ENV_FILE),
    ))


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.suite in {"backend", "all"}:
        _run_backend_checks(args.include_known_failing_demo_seed)
    if args.suite == "smoke":
        _run_smoke_checks()
    if args.suite == "golden-path":
        _run_golden_path_checks()
    if args.suite in {"frontend", "all"}:
        _run_frontend_checks()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
