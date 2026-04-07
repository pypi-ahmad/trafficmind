"""Typed schemas for deterministic evaluation and benchmarking fixtures."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from services.vision.schemas import BBox


class DetectionAnnotation(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    bbox: BBox
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class DetectionBenchmarkCase(BaseModel):
    name: str
    expected: list[DetectionAnnotation] = Field(default_factory=list)
    predicted: list[DetectionAnnotation] = Field(default_factory=list)
    iou_threshold: float = Field(default=0.5, gt=0.0, le=1.0)


class DetectionBenchmarkReport(BaseModel):
    name: str
    expected_count: int
    predicted_count: int
    matched_count: int
    false_positive_count: int
    false_negative_count: int
    precision: float = Field(ge=0.0, le=1.0)
    recall: float = Field(ge=0.0, le=1.0)
    mean_iou: float | None = Field(default=None, ge=0.0, le=1.0)
    matched_labels: list[str] = Field(default_factory=list)


class TrackingAssignmentSample(BaseModel):
    model_config = ConfigDict(frozen=True)

    logical_object_id: str
    frame_index: int
    observed_track_id: str | None = None


class TrackingBenchmarkCase(BaseModel):
    name: str
    assignments: list[TrackingAssignmentSample] = Field(default_factory=list)


class TrackingBenchmarkReport(BaseModel):
    name: str
    object_count: int
    expected_observations: int
    observed_observations: int
    coverage_rate: float = Field(ge=0.0, le=1.0)
    id_switch_count: int = 0
    fragmented_object_count: int = 0
    continuity_score: float = Field(ge=0.0, le=1.0)
    notes: list[str] = Field(default_factory=list)


class PlateReadQualitySample(BaseModel):
    model_config = ConfigDict(frozen=True)

    expected_normalized_text: str
    predicted_normalized_text: str
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class OcrBenchmarkCase(BaseModel):
    name: str
    samples: list[PlateReadQualitySample] = Field(default_factory=list)


class OcrBenchmarkReport(BaseModel):
    name: str
    sample_count: int
    exact_match_count: int
    exact_match_rate: float = Field(ge=0.0, le=1.0)
    average_char_accuracy: float = Field(ge=0.0, le=1.0)
    average_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class RuleOutcomeSample(BaseModel):
    model_config = ConfigDict(frozen=True)

    frame_index: int
    stage: Literal["pre_violation", "confirmed"]
    rule_type: str
    track_id: str


class RuleSanityCase(BaseModel):
    name: str
    expected_events: list[RuleOutcomeSample] = Field(default_factory=list)
    actual_events: list[RuleOutcomeSample] = Field(default_factory=list)


class RuleSanityReport(BaseModel):
    name: str
    expected_count: int
    actual_count: int
    matched_count: int
    missing_count: int
    unexpected_count: int
    pass_rate: float = Field(ge=0.0, le=1.0)
    missing_keys: list[str] = Field(default_factory=list)
    unexpected_keys: list[str] = Field(default_factory=list)


class SignalClassificationSample(BaseModel):
    model_config = ConfigDict(frozen=True)

    expected_color: str
    predicted_color: str
    head_id: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class SignalBenchmarkCase(BaseModel):
    name: str
    samples: list[SignalClassificationSample] = Field(default_factory=list)


class SignalBenchmarkReport(BaseModel):
    name: str
    sample_count: int
    correct_count: int
    accuracy: float = Field(ge=0.0, le=1.0)
    per_class_accuracy: dict[str, float] = Field(default_factory=dict)
    confusion_pairs: list[str] = Field(default_factory=list)


class BenchmarkFixtureSuite(BaseModel):
    detection_cases: list[DetectionBenchmarkCase] = Field(default_factory=list)
    tracking_cases: list[TrackingBenchmarkCase] = Field(default_factory=list)
    ocr_cases: list[OcrBenchmarkCase] = Field(default_factory=list)
    rule_cases: list[RuleSanityCase] = Field(default_factory=list)
    signal_cases: list[SignalBenchmarkCase] = Field(default_factory=list)


class BenchmarkSuiteReport(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    detection_reports: list[DetectionBenchmarkReport] = Field(default_factory=list)
    tracking_reports: list[TrackingBenchmarkReport] = Field(default_factory=list)
    ocr_reports: list[OcrBenchmarkReport] = Field(default_factory=list)
    rule_reports: list[RuleSanityReport] = Field(default_factory=list)
    signal_reports: list[SignalBenchmarkReport] = Field(default_factory=list)


class EvaluationTaskType(StrEnum):
    DETECTION = "detection"
    TRACKING = "tracking"
    OCR = "ocr"
    RULES = "rules"
    SIGNAL = "signal"
    WORKFLOW = "workflow"


class EvaluationArtifactSourceKind(StrEnum):
    FIXTURE_SUITE = "fixture_suite"
    STORED_REPORT = "stored_report"


class BenchmarkArtifactMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    artifact_key: str
    artifact_label: str
    source_kind: EvaluationArtifactSourceKind
    source_path: str | None = None
    observed_at: datetime | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    task_types: list[EvaluationTaskType] = Field(default_factory=list)
    scenario_names: list[str] = Field(default_factory=list)
    camera_ids: list[str] = Field(default_factory=list)
    camera_labels: list[str] = Field(default_factory=list)
    model_registry_ids: list[str] = Field(default_factory=list)
    model_version_names: list[str] = Field(default_factory=list)
    manual_review_summary: str | None = None
    workflow_summary: str | None = None
    notes: list[str] = Field(default_factory=list)


class BenchmarkReportArtifact(BaseModel):
    model_config = ConfigDict(frozen=True)

    metadata: BenchmarkArtifactMetadata
    report: BenchmarkSuiteReport
    fixture_suite: BenchmarkFixtureSuite | None = None
