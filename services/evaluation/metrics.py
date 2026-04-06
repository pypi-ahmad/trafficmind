"""Deterministic evaluation metrics for fixture-based benchmarking."""

from __future__ import annotations

from collections import Counter, defaultdict

from services.evaluation.schemas import (
    BenchmarkFixtureSuite,
    BenchmarkSuiteReport,
    DetectionBenchmarkCase,
    DetectionBenchmarkReport,
    OcrBenchmarkCase,
    OcrBenchmarkReport,
    PlateReadQualitySample,
    RuleOutcomeSample,
    RuleSanityCase,
    RuleSanityReport,
    SignalBenchmarkCase,
    SignalBenchmarkReport,
    TrackingBenchmarkCase,
    TrackingBenchmarkReport,
)
from services.vision.schemas import BBox


def _safe_rate(numerator: int | float, denominator: int | float) -> float:
    if denominator == 0:
        return 1.0
    return float(numerator) / float(denominator)


def _bbox_iou(lhs: BBox, rhs: BBox) -> float:
    inter_x1 = max(lhs.x1, rhs.x1)
    inter_y1 = max(lhs.y1, rhs.y1)
    inter_x2 = min(lhs.x2, rhs.x2)
    inter_y2 = min(lhs.y2, rhs.y2)
    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    intersection = inter_w * inter_h
    union = lhs.area + rhs.area - intersection
    if union <= 0.0:
        return 0.0
    return intersection / union


def evaluate_detection_case(case: DetectionBenchmarkCase) -> DetectionBenchmarkReport:
    candidates: list[tuple[float, int, int]] = []
    for expected_index, expected in enumerate(case.expected):
        for predicted_index, predicted in enumerate(case.predicted):
            if expected.label != predicted.label:
                continue
            iou = _bbox_iou(expected.bbox, predicted.bbox)
            if iou >= case.iou_threshold:
                candidates.append((iou, expected_index, predicted_index))

    candidates.sort(key=lambda item: item[0], reverse=True)

    matched_expected: set[int] = set()
    matched_predicted: set[int] = set()
    matched_ious: list[float] = []
    matched_labels: list[str] = []
    for iou, expected_index, predicted_index in candidates:
        if expected_index in matched_expected or predicted_index in matched_predicted:
            continue
        matched_expected.add(expected_index)
        matched_predicted.add(predicted_index)
        matched_ious.append(iou)
        matched_labels.append(case.expected[expected_index].label)

    matched_count = len(matched_expected)
    false_positive_count = len(case.predicted) - matched_count
    false_negative_count = len(case.expected) - matched_count
    return DetectionBenchmarkReport(
        name=case.name,
        expected_count=len(case.expected),
        predicted_count=len(case.predicted),
        matched_count=matched_count,
        false_positive_count=false_positive_count,
        false_negative_count=false_negative_count,
        precision=_safe_rate(matched_count, matched_count + false_positive_count),
        recall=_safe_rate(matched_count, matched_count + false_negative_count),
        mean_iou=(sum(matched_ious) / len(matched_ious) if matched_ious else None),
        matched_labels=matched_labels,
    )


def evaluate_tracking_case(case: TrackingBenchmarkCase) -> TrackingBenchmarkReport:
    grouped: dict[str, list] = defaultdict(list)
    for assignment in case.assignments:
        grouped[assignment.logical_object_id].append(assignment)

    expected_observations = len(case.assignments)
    observed_observations = sum(1 for assignment in case.assignments if assignment.observed_track_id is not None)
    id_switch_count = 0
    fragmented_object_count = 0
    notes: list[str] = []

    for logical_object_id, assignments in grouped.items():
        ordered = sorted(assignments, key=lambda item: item.frame_index)
        seen_track_ids = [item.observed_track_id for item in ordered if item.observed_track_id is not None]
        if not seen_track_ids:
            notes.append(f"{logical_object_id}: no tracker assignment observed")
            continue

        distinct_track_ids = list(dict.fromkeys(seen_track_ids))
        id_switch_count += max(0, len(distinct_track_ids) - 1)
        if len(set(seen_track_ids)) > 1:
            fragmented_object_count += 1
            notes.append(
                f"{logical_object_id}: fragmented across {len(set(seen_track_ids))} tracker ids"
            )

        missing_assignment_count = sum(1 for item in ordered if item.observed_track_id is None)
        if missing_assignment_count > 0:
            notes.append(
                f"{logical_object_id}: missing assignment on {missing_assignment_count} frame(s)"
            )

    continuity_score = 1.0
    if expected_observations > 0:
        continuity_score = max(0.0, (observed_observations - id_switch_count) / expected_observations)

    return TrackingBenchmarkReport(
        name=case.name,
        object_count=len(grouped),
        expected_observations=expected_observations,
        observed_observations=observed_observations,
        coverage_rate=_safe_rate(observed_observations, expected_observations),
        id_switch_count=id_switch_count,
        fragmented_object_count=fragmented_object_count,
        continuity_score=continuity_score,
        notes=notes,
    )


def _levenshtein_distance(lhs: str, rhs: str) -> int:
    if lhs == rhs:
        return 0
    if not lhs:
        return len(rhs)
    if not rhs:
        return len(lhs)

    previous_row = list(range(len(rhs) + 1))
    for lhs_index, lhs_char in enumerate(lhs, start=1):
        current_row = [lhs_index]
        for rhs_index, rhs_char in enumerate(rhs, start=1):
            insertion = current_row[rhs_index - 1] + 1
            deletion = previous_row[rhs_index] + 1
            substitution = previous_row[rhs_index - 1] + (lhs_char != rhs_char)
            current_row.append(min(insertion, deletion, substitution))
        previous_row = current_row
    return previous_row[-1]


def _character_accuracy(sample: PlateReadQualitySample) -> float:
    max_length = max(len(sample.expected_normalized_text), len(sample.predicted_normalized_text))
    if max_length == 0:
        return 1.0
    distance = _levenshtein_distance(sample.expected_normalized_text, sample.predicted_normalized_text)
    return max(0.0, 1.0 - (distance / max_length))


def evaluate_ocr_case(case: OcrBenchmarkCase) -> OcrBenchmarkReport:
    exact_match_count = sum(
        1 for sample in case.samples if sample.expected_normalized_text == sample.predicted_normalized_text
    )
    average_char_accuracy = (
        sum(_character_accuracy(sample) for sample in case.samples) / len(case.samples)
        if case.samples
        else 1.0
    )
    confidence_values = [sample.confidence for sample in case.samples if sample.confidence is not None]
    return OcrBenchmarkReport(
        name=case.name,
        sample_count=len(case.samples),
        exact_match_count=exact_match_count,
        exact_match_rate=_safe_rate(exact_match_count, len(case.samples)),
        average_char_accuracy=average_char_accuracy,
        average_confidence=(sum(confidence_values) / len(confidence_values) if confidence_values else None),
    )


def _rule_key(sample: RuleOutcomeSample) -> str:
    return f"frame={sample.frame_index}|stage={sample.stage}|rule={sample.rule_type}|track={sample.track_id}"


def evaluate_rule_case(case: RuleSanityCase) -> RuleSanityReport:
    expected_counts = Counter(_rule_key(sample) for sample in case.expected_events)
    actual_counts = Counter(_rule_key(sample) for sample in case.actual_events)
    matched_count = sum(min(expected_counts[key], actual_counts[key]) for key in expected_counts)
    missing_counter = expected_counts - actual_counts
    unexpected_counter = actual_counts - expected_counts
    missing_keys = [key for key, count in missing_counter.items() for _ in range(count)]
    unexpected_keys = [key for key, count in unexpected_counter.items() for _ in range(count)]
    return RuleSanityReport(
        name=case.name,
        expected_count=len(case.expected_events),
        actual_count=len(case.actual_events),
        matched_count=matched_count,
        missing_count=len(missing_keys),
        unexpected_count=len(unexpected_keys),
        pass_rate=_safe_rate(matched_count, len(case.expected_events)),
        missing_keys=missing_keys,
        unexpected_keys=unexpected_keys,
    )


def evaluate_fixture_suite(suite: BenchmarkFixtureSuite) -> BenchmarkSuiteReport:
    return BenchmarkSuiteReport(
        detection_reports=[evaluate_detection_case(case) for case in suite.detection_cases],
        tracking_reports=[evaluate_tracking_case(case) for case in suite.tracking_cases],
        ocr_reports=[evaluate_ocr_case(case) for case in suite.ocr_cases],
        rule_reports=[evaluate_rule_case(case) for case in suite.rule_cases],
        signal_reports=[evaluate_signal_case(case) for case in suite.signal_cases],
    )


def evaluate_signal_case(case: SignalBenchmarkCase) -> SignalBenchmarkReport:
    """Evaluate signal-state classification accuracy."""
    if not case.samples:
        return SignalBenchmarkReport(
            name=case.name, sample_count=0, correct_count=0, accuracy=1.0,
        )

    correct_count = sum(
        1 for s in case.samples if s.expected_color == s.predicted_color
    )

    # Per-class accuracy
    per_class_total: dict[str, int] = defaultdict(int)
    per_class_correct: dict[str, int] = defaultdict(int)
    confusion_pairs: list[str] = []
    for s in case.samples:
        per_class_total[s.expected_color] += 1
        if s.expected_color == s.predicted_color:
            per_class_correct[s.expected_color] += 1
        else:
            confusion_pairs.append(f"{s.expected_color}->{s.predicted_color}")
    per_class_accuracy = {
        color: _safe_rate(per_class_correct.get(color, 0), total)
        for color, total in sorted(per_class_total.items())
    }

    return SignalBenchmarkReport(
        name=case.name,
        sample_count=len(case.samples),
        correct_count=correct_count,
        accuracy=_safe_rate(correct_count, len(case.samples)),
        per_class_accuracy=per_class_accuracy,
        confusion_pairs=confusion_pairs,
    )