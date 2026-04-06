"""Render a commit-safe environment profile template into a concrete env file."""

from __future__ import annotations

import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE_SOURCES = {
    "local": REPO_ROOT / ".env.example",
    "dev": REPO_ROOT / "infra" / "env" / "dev.env.example",
    "staging": REPO_ROOT / "infra" / "env" / "staging.env.example",
    "prod": REPO_ROOT / "infra" / "env" / "prod.env.example",
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render a TrafficMind env profile template into a target file."
    )
    parser.add_argument("--profile", choices=sorted(PROFILE_SOURCES), default="local")
    parser.add_argument("--output", default=str(REPO_ROOT / ".env"))
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the output file if it already exists.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    source = PROFILE_SOURCES[args.profile]
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = (REPO_ROOT / output_path).resolve()

    if output_path.exists() and not args.force:
        parser.error(f"Output file already exists: {output_path}. Use --force to overwrite it.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"Rendered {args.profile} profile from {source} to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
