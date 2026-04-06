"""Response schemas for file-backed evaluation and benchmarking summaries."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from services.evaluation.schemas import BenchmarkReportArtifact, EvaluationArtifactSourceKind


class EvaluationManualSummaryRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_key: str
    artifact_label: str
    source_kind: EvaluationArtifactSourceKind
    observed_at: datetime | None = None
    generated_at: datetime
    manual_review_summary: str | None = None
    workflow_summary: str | None = None
    model_version_names: list[str] = Field(default_factory=list)
    camera_labels: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class EvaluationPlaceholderRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    title: str
    detail: str


class EvaluationSummaryRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    sources: list[BenchmarkReportArtifact] = Field(default_factory=list)
    manual_review_summaries: list[EvaluationManualSummaryRead] = Field(default_factory=list)
    placeholders: list[EvaluationPlaceholderRead] = Field(default_factory=list)
    methodology: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)