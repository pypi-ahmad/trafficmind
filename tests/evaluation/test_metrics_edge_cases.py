"""Edge-case and boundary tests for the evaluation metrics module.

These complement the fixture-suite integration test by exercising metric
functions with empty inputs, perfect scores, zero overlap, and other
boundary conditions that the single-case fixture suite does not cover.
"""

from __future__ import annotations

import pytest

from services.evaluation.metrics import (
    _bbox_iou,
    _character_accuracy,
    _levenshtein_distance,
    _safe_rate,
    evaluate_detection_case,
    evaluate_ocr_case,
    evaluate_rule_case,
    evaluate_tracking_case,
)
from services.evaluation.schemas import (
    DetectionAnnotation,
    DetectionBenchmarkCase,
    OcrBenchmarkCase,
    PlateReadQualitySample,
    RuleOutcomeSample,
    RuleSanityCase,
    TrackingAssignmentSample,
    TrackingBenchmarkCase,
)
from services.vision.schemas import BBox


# ── _safe_rate ──────────────────────────────────────────────────────────────

class TestSafeRate:
    def test_zero_denominator_returns_one(self) -> None:
        assert _safe_rate(0, 0) == 1.0

    def test_normal_division(self) -> None:
        assert _safe_rate(3, 4) == pytest.approx(0.75)

    def test_float_inputs(self) -> None:
        assert _safe_rate(1.5, 3.0) == pytest.approx(0.5)


# ── _bbox_iou ───────────────────────────────────────────────────────────────

class TestBboxIou:
    def test_identical_boxes_return_one(self) -> None:
        box = BBox(x1=0, y1=0, x2=100, y2=100)
        assert _bbox_iou(box, box) == pytest.approx(1.0)

    def test_no_overlap_returns_zero(self) -> None:
        a = BBox(x1=0, y1=0, x2=10, y2=10)
        b = BBox(x1=20, y1=20, x2=30, y2=30)
        assert _bbox_iou(a, b) == pytest.approx(0.0)

    def test_partial_overlap(self) -> None:
        a = BBox(x1=0, y1=0, x2=10, y2=10)
        b = BBox(x1=5, y1=5, x2=15, y2=15)
        # intersection = 5*5=25, union = 100+100-25=175
        assert _bbox_iou(a, b) == pytest.approx(25 / 175)

    def test_zero_area_box(self) -> None:
        a = BBox(x1=5, y1=5, x2=5, y2=5)
        b = BBox(x1=0, y1=0, x2=10, y2=10)
        assert _bbox_iou(a, b) == pytest.approx(0.0)

    def test_contained_box(self) -> None:
        outer = BBox(x1=0, y1=0, x2=100, y2=100)
        inner = BBox(x1=25, y1=25, x2=75, y2=75)
        # intersection = 50*50=2500, union = 10000+2500-2500=10000
        assert _bbox_iou(outer, inner) == pytest.approx(2500 / 10000)


# ── _levenshtein_distance ──────────────────────────────────────────────────

class TestLevenshtein:
    def test_identical_strings(self) -> None:
        assert _levenshtein_distance("ABC", "ABC") == 0

    def test_empty_strings(self) -> None:
        assert _levenshtein_distance("", "") == 0

    def test_one_empty(self) -> None:
        assert _levenshtein_distance("ABC", "") == 3
        assert _levenshtein_distance("", "ABC") == 3

    def test_single_substitution(self) -> None:
        assert _levenshtein_distance("ABC", "AXC") == 1

    def test_insertion_and_deletion(self) -> None:
        assert _levenshtein_distance("AB", "ABC") == 1
        assert _levenshtein_distance("ABC", "AB") == 1


# ── _character_accuracy ────────────────────────────────────────────────────

class TestCharacterAccuracy:
    def test_perfect_match(self) -> None:
        sample = PlateReadQualitySample(
            expected_normalized_text="ABC1234",
            predicted_normalized_text="ABC1234",
        )
        assert _character_accuracy(sample) == pytest.approx(1.0)

    def test_completely_wrong(self) -> None:
        sample = PlateReadQualitySample(
            expected_normalized_text="AAAA",
            predicted_normalized_text="BBBB",
        )
        assert _character_accuracy(sample) == pytest.approx(0.0)

    def test_both_empty(self) -> None:
        sample = PlateReadQualitySample(
            expected_normalized_text="",
            predicted_normalized_text="",
        )
        assert _character_accuracy(sample) == pytest.approx(1.0)


# ── evaluate_detection_case edge cases ─────────────────────────────────────

class TestDetectionEdgeCases:
    def test_empty_expected_and_predicted(self) -> None:
        report = evaluate_detection_case(
            DetectionBenchmarkCase(name="empty", expected=[], predicted=[])
        )
        assert report.matched_count == 0
        assert report.false_positive_count == 0
        assert report.false_negative_count == 0
        assert report.precision == pytest.approx(1.0)
        assert report.recall == pytest.approx(1.0)
        assert report.mean_iou is None

    def test_all_false_positives(self) -> None:
        report = evaluate_detection_case(
            DetectionBenchmarkCase(
                name="all_fp",
                expected=[],
                predicted=[
                    DetectionAnnotation(label="car", bbox=BBox(x1=0, y1=0, x2=10, y2=10), confidence=0.9),
                ],
            )
        )
        assert report.matched_count == 0
        assert report.false_positive_count == 1
        assert report.false_negative_count == 0
        assert report.precision == pytest.approx(0.0)

    def test_all_false_negatives(self) -> None:
        report = evaluate_detection_case(
            DetectionBenchmarkCase(
                name="all_fn",
                expected=[
                    DetectionAnnotation(label="car", bbox=BBox(x1=0, y1=0, x2=10, y2=10)),
                ],
                predicted=[],
            )
        )
        assert report.matched_count == 0
        assert report.false_negative_count == 1
        assert report.recall == pytest.approx(0.0)

    def test_label_mismatch_prevents_matching(self) -> None:
        box = BBox(x1=0, y1=0, x2=100, y2=100)
        report = evaluate_detection_case(
            DetectionBenchmarkCase(
                name="label_mismatch",
                expected=[DetectionAnnotation(label="car", bbox=box)],
                predicted=[DetectionAnnotation(label="person", bbox=box, confidence=0.9)],
            )
        )
        assert report.matched_count == 0
        assert report.false_positive_count == 1
        assert report.false_negative_count == 1

    def test_below_iou_threshold_is_not_matched(self) -> None:
        report = evaluate_detection_case(
            DetectionBenchmarkCase(
                name="below_threshold",
                iou_threshold=0.9,
                expected=[DetectionAnnotation(label="car", bbox=BBox(x1=0, y1=0, x2=100, y2=100))],
                predicted=[DetectionAnnotation(label="car", bbox=BBox(x1=50, y1=50, x2=150, y2=150), confidence=0.8)],
            )
        )
        # IoU of these two boxes is ~1929/17071 ≈ 0.113 — well below 0.9
        assert report.matched_count == 0

    def test_perfect_detection(self) -> None:
        box = BBox(x1=10, y1=10, x2=50, y2=50)
        report = evaluate_detection_case(
            DetectionBenchmarkCase(
                name="perfect",
                expected=[DetectionAnnotation(label="car", bbox=box)],
                predicted=[DetectionAnnotation(label="car", bbox=box, confidence=0.99)],
            )
        )
        assert report.matched_count == 1
        assert report.precision == pytest.approx(1.0)
        assert report.recall == pytest.approx(1.0)
        assert report.mean_iou == pytest.approx(1.0)


# ── evaluate_tracking_case edge cases ──────────────────────────────────────

class TestTrackingEdgeCases:
    def test_empty_assignments(self) -> None:
        report = evaluate_tracking_case(
            TrackingBenchmarkCase(name="empty", assignments=[])
        )
        assert report.object_count == 0
        assert report.coverage_rate == pytest.approx(1.0)
        assert report.id_switch_count == 0
        assert report.continuity_score == pytest.approx(1.0)

    def test_perfect_tracking(self) -> None:
        report = evaluate_tracking_case(
            TrackingBenchmarkCase(
                name="perfect",
                assignments=[
                    TrackingAssignmentSample(logical_object_id="obj-1", frame_index=0, observed_track_id="t-1"),
                    TrackingAssignmentSample(logical_object_id="obj-1", frame_index=1, observed_track_id="t-1"),
                    TrackingAssignmentSample(logical_object_id="obj-1", frame_index=2, observed_track_id="t-1"),
                ],
            )
        )
        assert report.coverage_rate == pytest.approx(1.0)
        assert report.id_switch_count == 0
        assert report.fragmented_object_count == 0
        assert report.continuity_score == pytest.approx(1.0)

    def test_all_missing_assignments(self) -> None:
        report = evaluate_tracking_case(
            TrackingBenchmarkCase(
                name="all_missing",
                assignments=[
                    TrackingAssignmentSample(logical_object_id="obj-1", frame_index=0, observed_track_id=None),
                    TrackingAssignmentSample(logical_object_id="obj-1", frame_index=1, observed_track_id=None),
                ],
            )
        )
        assert report.coverage_rate == pytest.approx(0.0)
        assert report.continuity_score == pytest.approx(0.0)

    def test_multi_object_independent_tracking(self) -> None:
        report = evaluate_tracking_case(
            TrackingBenchmarkCase(
                name="multi_obj",
                assignments=[
                    TrackingAssignmentSample(logical_object_id="a", frame_index=0, observed_track_id="t-1"),
                    TrackingAssignmentSample(logical_object_id="a", frame_index=1, observed_track_id="t-1"),
                    TrackingAssignmentSample(logical_object_id="b", frame_index=0, observed_track_id="t-2"),
                    TrackingAssignmentSample(logical_object_id="b", frame_index=1, observed_track_id="t-3"),
                ],
            )
        )
        assert report.object_count == 2
        assert report.id_switch_count == 1  # object b: t-2 -> t-3
        assert report.fragmented_object_count == 1


# ── evaluate_ocr_case edge cases ──────────────────────────────────────────

class TestOcrEdgeCases:
    def test_empty_samples(self) -> None:
        report = evaluate_ocr_case(
            OcrBenchmarkCase(name="empty", samples=[])
        )
        assert report.sample_count == 0
        assert report.exact_match_rate == pytest.approx(1.0)
        assert report.average_char_accuracy == pytest.approx(1.0)
        assert report.average_confidence is None

    def test_perfect_ocr(self) -> None:
        report = evaluate_ocr_case(
            OcrBenchmarkCase(
                name="perfect",
                samples=[
                    PlateReadQualitySample(
                        expected_normalized_text="ABC1234",
                        predicted_normalized_text="ABC1234",
                        confidence=0.99,
                    ),
                ],
            )
        )
        assert report.exact_match_count == 1
        assert report.exact_match_rate == pytest.approx(1.0)
        assert report.average_char_accuracy == pytest.approx(1.0)
        assert report.average_confidence == pytest.approx(0.99)

    def test_all_wrong_ocr(self) -> None:
        report = evaluate_ocr_case(
            OcrBenchmarkCase(
                name="all_wrong",
                samples=[
                    PlateReadQualitySample(
                        expected_normalized_text="AAAA",
                        predicted_normalized_text="BBBB",
                    ),
                ],
            )
        )
        assert report.exact_match_count == 0
        assert report.exact_match_rate == pytest.approx(0.0)
        assert report.average_char_accuracy == pytest.approx(0.0)


# ── evaluate_rule_case edge cases ──────────────────────────────────────────

class TestRuleEdgeCases:
    def test_empty_events(self) -> None:
        report = evaluate_rule_case(
            RuleSanityCase(name="empty", expected_events=[], actual_events=[])
        )
        assert report.matched_count == 0
        assert report.missing_count == 0
        assert report.unexpected_count == 0
        assert report.pass_rate == pytest.approx(1.0)

    def test_perfect_match(self) -> None:
        events = [
            RuleOutcomeSample(frame_index=0, stage="pre_violation", rule_type="red_light", track_id="v-1"),
            RuleOutcomeSample(frame_index=1, stage="confirmed", rule_type="red_light", track_id="v-1"),
        ]
        report = evaluate_rule_case(
            RuleSanityCase(name="perfect", expected_events=events, actual_events=events)
        )
        assert report.matched_count == 2
        assert report.missing_count == 0
        assert report.unexpected_count == 0
        assert report.pass_rate == pytest.approx(1.0)

    def test_all_missing(self) -> None:
        events = [
            RuleOutcomeSample(frame_index=0, stage="confirmed", rule_type="red_light", track_id="v-1"),
        ]
        report = evaluate_rule_case(
            RuleSanityCase(name="all_missing", expected_events=events, actual_events=[])
        )
        assert report.matched_count == 0
        assert report.missing_count == 1
        assert report.pass_rate == pytest.approx(0.0)

    def test_all_unexpected(self) -> None:
        events = [
            RuleOutcomeSample(frame_index=0, stage="confirmed", rule_type="red_light", track_id="v-1"),
        ]
        report = evaluate_rule_case(
            RuleSanityCase(name="all_unexpected", expected_events=[], actual_events=events)
        )
        assert report.matched_count == 0
        assert report.unexpected_count == 1
        assert report.pass_rate == pytest.approx(1.0)  # 0 expected = trivially all matched
