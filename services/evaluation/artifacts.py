"""Helpers for building and loading file-backed evaluation artifacts."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from services.evaluation.metrics import evaluate_fixture_suite
from services.evaluation.schemas import (
    BenchmarkArtifactMetadata,
    BenchmarkFixtureSuite,
    BenchmarkReportArtifact,
    BenchmarkSuiteReport,
    EvaluationArtifactSourceKind,
    EvaluationTaskType,
)


def _dedupe_strings(values: Iterable[str]) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        normalized = value.strip()
        if normalized:
            seen.setdefault(normalized, None)
    return list(seen)


def _artifact_key(*, source_kind: EvaluationArtifactSourceKind, seed: str) -> str:
    digest = hashlib.sha1(f"{source_kind.value}:{seed}".encode("utf-8")).hexdigest()[:12]
    return f"{source_kind.value}:{digest}"


def derive_task_types(suite: BenchmarkFixtureSuite) -> list[EvaluationTaskType]:
    task_types: list[EvaluationTaskType] = []
    if suite.detection_cases:
        task_types.append(EvaluationTaskType.DETECTION)
    if suite.tracking_cases:
        task_types.append(EvaluationTaskType.TRACKING)
    if suite.ocr_cases:
        task_types.append(EvaluationTaskType.OCR)
    if suite.rule_cases:
        task_types.append(EvaluationTaskType.RULES)
    if suite.signal_cases:
        task_types.append(EvaluationTaskType.SIGNAL)
    return task_types


def derive_scenario_names(suite: BenchmarkFixtureSuite) -> list[str]:
    return [
        *[case.name for case in suite.detection_cases],
        *[case.name for case in suite.tracking_cases],
        *[case.name for case in suite.ocr_cases],
        *[case.name for case in suite.rule_cases],
        *[case.name for case in suite.signal_cases],
    ]


def build_report_artifact(
    report: BenchmarkSuiteReport,
    *,
    artifact_label: str,
    source_kind: EvaluationArtifactSourceKind,
    source_path: str | None = None,
    observed_at: datetime | None = None,
    fixture_suite: BenchmarkFixtureSuite | None = None,
    camera_ids: Iterable[str] = (),
    camera_labels: Iterable[str] = (),
    model_registry_ids: Iterable[str] = (),
    model_version_names: Iterable[str] = (),
    manual_review_summary: str | None = None,
    workflow_summary: str | None = None,
    notes: Iterable[str] = (),
) -> BenchmarkReportArtifact:
    scenario_names = derive_scenario_names(fixture_suite) if fixture_suite is not None else []
    task_types = derive_task_types(fixture_suite) if fixture_suite is not None else []
    metadata = BenchmarkArtifactMetadata(
        artifact_key=_artifact_key(
            source_kind=source_kind,
            seed=source_path or f"{artifact_label}:{report.generated_at.isoformat()}",
        ),
        artifact_label=artifact_label,
        source_kind=source_kind,
        source_path=source_path,
        observed_at=observed_at,
        generated_at=report.generated_at,
        task_types=task_types,
        scenario_names=_dedupe_strings(scenario_names),
        camera_ids=_dedupe_strings(camera_ids),
        camera_labels=_dedupe_strings(camera_labels),
        model_registry_ids=_dedupe_strings(model_registry_ids),
        model_version_names=_dedupe_strings(model_version_names),
        manual_review_summary=manual_review_summary,
        workflow_summary=workflow_summary,
        notes=_dedupe_strings(notes),
    )
    return BenchmarkReportArtifact(
        metadata=metadata,
        report=report,
        fixture_suite=fixture_suite,
    )


def build_fixture_report_artifact(
    fixture_path: Path,
    *,
    artifact_label: str | None = None,
    camera_ids: Iterable[str] = (),
    camera_labels: Iterable[str] = (),
    model_registry_ids: Iterable[str] = (),
    model_version_names: Iterable[str] = (),
    manual_review_summary: str | None = None,
    workflow_summary: str | None = None,
    notes: Iterable[str] = (),
) -> BenchmarkReportArtifact:
    suite = BenchmarkFixtureSuite.model_validate_json(fixture_path.read_text(encoding="utf-8"))
    report = evaluate_fixture_suite(suite)
    observed_at = datetime.fromtimestamp(fixture_path.stat().st_mtime, tz=UTC)
    return build_report_artifact(
        report,
        artifact_label=artifact_label or fixture_path.stem,
        source_kind=EvaluationArtifactSourceKind.FIXTURE_SUITE,
        source_path=str(fixture_path),
        observed_at=observed_at,
        fixture_suite=suite,
        camera_ids=camera_ids,
        camera_labels=camera_labels,
        model_registry_ids=model_registry_ids,
        model_version_names=model_version_names,
        manual_review_summary=manual_review_summary,
        workflow_summary=workflow_summary,
        notes=notes,
    )


def load_report_artifact(path: Path) -> BenchmarkReportArtifact:
    artifact = BenchmarkReportArtifact.model_validate_json(path.read_text(encoding="utf-8"))
    if artifact.metadata.source_path is None:
        artifact = artifact.model_copy(
            update={
                "metadata": artifact.metadata.model_copy(update={"source_path": str(path)}),
            }
        )
    return artifact


def write_report_artifact(path: Path, artifact: BenchmarkReportArtifact) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")


__all__ = [
    "build_fixture_report_artifact",
    "build_report_artifact",
    "derive_scenario_names",
    "derive_task_types",
    "load_report_artifact",
    "write_report_artifact",
]