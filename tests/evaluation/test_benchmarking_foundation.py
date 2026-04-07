from __future__ import annotations

from pathlib import Path

import pytest

from services.evaluation.__main__ import main
from services.evaluation.metrics import evaluate_fixture_suite
from services.evaluation.schemas import BenchmarkFixtureSuite, BenchmarkReportArtifact

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "evaluation" / "benchmark_suite.json"


def _load_fixture_suite() -> BenchmarkFixtureSuite:
    return BenchmarkFixtureSuite.model_validate_json(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_fixture_suite_reports_expected_metrics() -> None:
    report = evaluate_fixture_suite(_load_fixture_suite())

    # --- Detection ---
    assert len(report.detection_reports) == 3

    detection = report.detection_reports[0]
    assert detection.matched_count == 2
    assert detection.false_positive_count == 1
    assert detection.false_negative_count == 0
    assert detection.precision == pytest.approx(2 / 3)
    assert detection.recall == pytest.approx(1.0)

    crowded = report.detection_reports[1]
    assert crowded.matched_count == 3
    assert crowded.false_negative_count == 1  # 4th vehicle missed
    assert crowded.recall == pytest.approx(3 / 4)

    empty_frame = report.detection_reports[2]
    assert empty_frame.matched_count == 0
    assert empty_frame.precision == pytest.approx(1.0)
    assert empty_frame.recall == pytest.approx(1.0)

    # --- Tracking ---
    assert len(report.tracking_reports) == 2

    tracking = report.tracking_reports[0]
    assert tracking.coverage_rate == pytest.approx(0.75)
    assert tracking.id_switch_count == 1
    assert tracking.fragmented_object_count == 1
    assert tracking.continuity_score == pytest.approx(0.5)

    stable = report.tracking_reports[1]
    assert stable.coverage_rate == pytest.approx(1.0)
    assert stable.id_switch_count == 0
    assert stable.continuity_score == pytest.approx(1.0)

    # --- OCR ---
    assert len(report.ocr_reports) == 2

    ocr = report.ocr_reports[0]
    assert ocr.sample_count == 2
    assert ocr.exact_match_count == 1
    assert ocr.exact_match_rate == pytest.approx(0.5)
    assert ocr.average_char_accuracy == pytest.approx((1.0 + (6 / 7)) / 2)

    # --- Rules ---
    assert len(report.rule_reports) == 2

    rule = report.rule_reports[0]
    assert rule.matched_count == 1
    assert rule.missing_count == 1
    assert rule.unexpected_count == 1
    assert rule.pass_rate == pytest.approx(0.5)

    perfect_rule = report.rule_reports[1]
    assert perfect_rule.matched_count == 2
    assert perfect_rule.pass_rate == pytest.approx(1.0)

    # --- Signal classification ---
    assert len(report.signal_reports) == 1
    signal = report.signal_reports[0]
    assert signal.sample_count == 5
    assert signal.correct_count == 3
    assert signal.accuracy == pytest.approx(3 / 5)
    assert signal.per_class_accuracy["red"] == pytest.approx(0.5)
    assert signal.per_class_accuracy["green"] == pytest.approx(0.5)
    assert signal.per_class_accuracy["yellow"] == pytest.approx(1.0)
    assert len(signal.confusion_pairs) == 2


def test_evaluation_cli_emits_json_report(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main([str(FIXTURE_PATH)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert '"detection_reports"' in captured.out
    assert '"tracking_reports"' in captured.out
    assert '"signal_reports"' in captured.out


def test_evaluation_cli_can_write_stored_artifact(tmp_path: Path) -> None:
    output_path = tmp_path / "nightly-eval.json"

    exit_code = main(
        [
            str(FIXTURE_PATH),
            "--output",
            str(output_path),
            "--artifact-label",
            "nightly-eval",
            "--model-version",
            "yolo26x.pt",
            "--camera-label",
            "CAM-EVAL-001",
            "--manual-review-summary",
            "Reviewed two OCR edge cases manually.",
            "--workflow-summary",
            "Workflow evaluation stayed stable.",
            "--note",
            "Generated during CI dry-run.",
        ]
    )

    assert exit_code == 0
    assert output_path.exists()
    artifact = BenchmarkReportArtifact.model_validate_json(output_path.read_text(encoding="utf-8"))
    assert artifact.metadata.artifact_label == "nightly-eval"
    assert artifact.metadata.model_version_names == ["yolo26x.pt"]
    assert artifact.metadata.camera_labels == ["CAM-EVAL-001"]
    assert artifact.metadata.manual_review_summary == "Reviewed two OCR edge cases manually."
    assert artifact.metadata.workflow_summary == "Workflow evaluation stayed stable."
    assert artifact.report.detection_reports[0].name == "mixed_vehicle_person_detection"
