"""Service layer for file-backed benchmark and evaluation summaries."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from apps.api.app.schemas.evaluation import (
    EvaluationManualSummaryRead,
    EvaluationPlaceholderRead,
    EvaluationSummaryRead,
)
from services.evaluation.artifacts import build_fixture_report_artifact, load_report_artifact
from services.evaluation.schemas import BenchmarkReportArtifact, EvaluationArtifactSourceKind


class EvaluationSummaryService:
    def __init__(self, *, fixture_suite_path: Path, artifact_dir: Path) -> None:
        self.fixture_suite_path = fixture_suite_path
        self.artifact_dir = artifact_dir

    def build_summary(self) -> EvaluationSummaryRead:
        warnings: list[str] = []
        sources: list[BenchmarkReportArtifact] = []

        fixture_source = self._load_fixture_source(warnings)
        if fixture_source is not None:
            sources.append(fixture_source)

        sources.extend(self._load_stored_sources(warnings))
        sources.sort(
            key=lambda source: (
                source.metadata.observed_at or source.metadata.generated_at,
                source.metadata.generated_at,
            ),
            reverse=True,
        )

        manual_review_summaries = self._build_manual_review_summaries(sources)
        placeholders = self._build_placeholders(sources, manual_review_summaries)

        methodology = [
            "Measured sections come from deterministic fixture-suite evaluation or previously stored report artifacts loaded from the local filesystem.",
            "Fixture-suite metrics are implementation-backed sanity checks over sample data; they are not live field benchmarks or leaderboard claims.",
            "Manual review and workflow summary sections appear only when an artifact explicitly includes those notes.",
            "Empty model/config version or camera tags mean the current artifact set does not include that metadata yet.",
        ]
        return EvaluationSummaryRead(
            generated_at=datetime.now(timezone.utc),
            sources=sources,
            manual_review_summaries=manual_review_summaries,
            placeholders=placeholders,
            methodology=methodology,
            warnings=warnings,
        )

    def _load_fixture_source(self, warnings: list[str]) -> BenchmarkReportArtifact | None:
        if not self.fixture_suite_path.exists():
            warnings.append(
                f"Fixture suite not found at {self.fixture_suite_path}; measured evaluation sections will be limited to stored report artifacts.",
            )
            return None
        return build_fixture_report_artifact(
            self.fixture_suite_path,
            notes=[
                "Derived live from the checked-in deterministic fixture suite.",
                "Scenario rows below reflect local sample data rather than production camera traffic.",
            ],
        )

    def _load_stored_sources(self, warnings: list[str]) -> list[BenchmarkReportArtifact]:
        if not self.artifact_dir.exists():
            warnings.append(
                f"No stored evaluation artifact directory found at {self.artifact_dir}; only live fixture-suite metrics are available.",
            )
            return []

        sources: list[BenchmarkReportArtifact] = []
        json_files = sorted(self.artifact_dir.rglob("*.json"))
        if not json_files:
            warnings.append(
                f"No stored evaluation artifacts were found under {self.artifact_dir}; manual review summaries and tagged benchmark history remain unavailable.",
            )
            return []

        for path in json_files:
            try:
                artifact = load_report_artifact(path)
            except Exception:
                warnings.append(
                    f"Skipped non-evaluation JSON artifact at {path}; files in the evaluation artifact directory must match the stored benchmark artifact schema.",
                )
                continue
            if artifact.metadata.source_kind != EvaluationArtifactSourceKind.STORED_REPORT:
                artifact = artifact.model_copy(
                    update={
                        "metadata": artifact.metadata.model_copy(
                            update={
                                "source_kind": EvaluationArtifactSourceKind.STORED_REPORT,
                                "source_path": str(path),
                            }
                        )
                    }
                )
            sources.append(artifact)
        return sources

    def _build_manual_review_summaries(
        self,
        sources: list[BenchmarkReportArtifact],
    ) -> list[EvaluationManualSummaryRead]:
        summaries: list[EvaluationManualSummaryRead] = []
        for source in sources:
            metadata = source.metadata
            if metadata.manual_review_summary is None and metadata.workflow_summary is None:
                continue
            summaries.append(
                EvaluationManualSummaryRead(
                    artifact_key=metadata.artifact_key,
                    artifact_label=metadata.artifact_label,
                    source_kind=metadata.source_kind,
                    observed_at=metadata.observed_at,
                    generated_at=metadata.generated_at,
                    manual_review_summary=metadata.manual_review_summary,
                    workflow_summary=metadata.workflow_summary,
                    model_version_names=metadata.model_version_names,
                    camera_labels=metadata.camera_labels,
                    notes=metadata.notes,
                )
            )
        return summaries

    def _build_placeholders(
        self,
        sources: list[BenchmarkReportArtifact],
        manual_review_summaries: list[EvaluationManualSummaryRead],
    ) -> list[EvaluationPlaceholderRead]:
        placeholders: list[EvaluationPlaceholderRead] = []
        if not any(source.metadata.source_kind == EvaluationArtifactSourceKind.STORED_REPORT for source in sources):
            placeholders.append(
                EvaluationPlaceholderRead(
                    key="stored_report_artifacts",
                    title="Stored benchmark history not available yet",
                    detail="The UI can read persisted evaluation artifacts from the configured outputs directory, but no stored report files are present right now.",
                )
            )
        if not manual_review_summaries:
            placeholders.append(
                EvaluationPlaceholderRead(
                    key="manual_review_summaries",
                    title="Manual review summaries not available yet",
                    detail="Current sources expose measured metrics only. Add stored artifacts with manual-review notes when you want operator-reviewed benchmark commentary in this view.",
                )
            )
        if not any(source.metadata.workflow_summary for source in sources):
            placeholders.append(
                EvaluationPlaceholderRead(
                    key="workflow_evaluation_summaries",
                    title="Workflow evaluation summaries not available yet",
                    detail="This section stays empty until an evaluation artifact explicitly records workflow or report-quality observations.",
                )
            )
        if not any(source.metadata.model_version_names or source.metadata.model_registry_ids for source in sources):
            placeholders.append(
                EvaluationPlaceholderRead(
                    key="model_version_tags",
                    title="Model/config version tags are not attached to current evaluation artifacts",
                    detail="The page supports filtering by model or config version, but the checked-in fixture suite does not claim registry linkage. Stored artifacts can add those tags explicitly.",
                )
            )
        if not any(source.metadata.camera_labels or source.metadata.camera_ids for source in sources):
            placeholders.append(
                EvaluationPlaceholderRead(
                    key="camera_tags",
                    title="Camera-tagged evaluation artifacts are not available yet",
                    detail="Camera filters are ready for stored artifacts, but the default fixture suite is scenario-based and not tied to a specific device.",
                )
            )
        return placeholders
