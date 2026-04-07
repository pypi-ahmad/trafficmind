"""CLI entry point for fixture-based benchmark evaluation."""

from __future__ import annotations

import argparse
from pathlib import Path

from services.evaluation.artifacts import build_fixture_report_artifact, write_report_artifact
from services.evaluation.metrics import evaluate_fixture_suite
from services.evaluation.schemas import BenchmarkFixtureSuite


def _default_fixture_path() -> Path:
    return Path("tests/fixtures/evaluation/benchmark_suite.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run deterministic sample-data benchmarks for TrafficMind.",
    )
    parser.add_argument(
        "fixture_suite",
        nargs="?",
        default=str(_default_fixture_path()),
        help="Path to a benchmark fixture suite JSON file.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional path to write a stored evaluation artifact JSON file.",
    )
    parser.add_argument(
        "--artifact-label",
        default=None,
        help="Human-readable label for the stored artifact.",
    )
    parser.add_argument(
        "--model-version",
        action="append",
        default=[],
        help="Optional model/config version label to attach to the stored artifact. Repeat to add more than one.",
    )
    parser.add_argument(
        "--model-registry-id",
        action="append",
        default=[],
        help="Optional model registry id to attach to the stored artifact. Repeat to add more than one.",
    )
    parser.add_argument(
        "--camera-id",
        action="append",
        default=[],
        help="Optional camera id to attach to the stored artifact. Repeat to add more than one.",
    )
    parser.add_argument(
        "--camera-label",
        action="append",
        default=[],
        help="Optional camera label to attach to the stored artifact. Repeat to add more than one.",
    )
    parser.add_argument(
        "--manual-review-summary",
        default=None,
        help="Optional human review summary for this evaluation artifact.",
    )
    parser.add_argument(
        "--workflow-summary",
        default=None,
        help="Optional workflow or report-quality summary for this evaluation artifact.",
    )
    parser.add_argument(
        "--note",
        action="append",
        default=[],
        help="Optional note to embed in the stored artifact. Repeat to add more than one.",
    )
    args = parser.parse_args(argv)

    fixture_path = Path(args.fixture_suite)
    suite = BenchmarkFixtureSuite.model_validate_json(fixture_path.read_text(encoding="utf-8"))
    report = evaluate_fixture_suite(suite)
    if args.output:
        artifact = build_fixture_report_artifact(
            fixture_path,
            artifact_label=args.artifact_label,
            camera_ids=args.camera_id,
            camera_labels=args.camera_label,
            model_registry_ids=args.model_registry_id,
            model_version_names=args.model_version,
            manual_review_summary=args.manual_review_summary,
            workflow_summary=args.workflow_summary,
            notes=args.note,
        )
        write_report_artifact(Path(args.output), artifact)
    print(report.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
