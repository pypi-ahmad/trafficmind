export type EvaluationArtifactSourceKind = "fixture_suite" | "stored_report";
export type EvaluationTaskType = "detection" | "tracking" | "ocr" | "rules" | "signal" | "workflow";

export interface DetectionAnnotationApi {
  label: string;
  confidence: number | null;
  bbox: {
    x1: number;
    y1: number;
    x2: number;
    y2: number;
  };
}

export interface DetectionBenchmarkCaseApi {
  name: string;
  expected: DetectionAnnotationApi[];
  predicted: DetectionAnnotationApi[];
  iou_threshold: number;
}

export interface DetectionBenchmarkReportApi {
  name: string;
  expected_count: number;
  predicted_count: number;
  matched_count: number;
  false_positive_count: number;
  false_negative_count: number;
  precision: number;
  recall: number;
  mean_iou: number | null;
  matched_labels: string[];
}

export interface TrackingAssignmentSampleApi {
  logical_object_id: string;
  frame_index: number;
  observed_track_id: string | null;
}

export interface TrackingBenchmarkCaseApi {
  name: string;
  assignments: TrackingAssignmentSampleApi[];
}

export interface TrackingBenchmarkReportApi {
  name: string;
  object_count: number;
  expected_observations: number;
  observed_observations: number;
  coverage_rate: number;
  id_switch_count: number;
  fragmented_object_count: number;
  continuity_score: number;
  notes: string[];
}

export interface PlateReadQualitySampleApi {
  expected_normalized_text: string;
  predicted_normalized_text: string;
  confidence: number | null;
}

export interface OcrBenchmarkCaseApi {
  name: string;
  samples: PlateReadQualitySampleApi[];
}

export interface OcrBenchmarkReportApi {
  name: string;
  sample_count: number;
  exact_match_count: number;
  exact_match_rate: number;
  average_char_accuracy: number;
  average_confidence: number | null;
}

export interface RuleOutcomeSampleApi {
  frame_index: number;
  stage: "pre_violation" | "confirmed";
  rule_type: string;
  track_id: string;
}

export interface RuleSanityCaseApi {
  name: string;
  expected_events: RuleOutcomeSampleApi[];
  actual_events: RuleOutcomeSampleApi[];
}

export interface RuleSanityReportApi {
  name: string;
  expected_count: number;
  actual_count: number;
  matched_count: number;
  missing_count: number;
  unexpected_count: number;
  pass_rate: number;
  missing_keys: string[];
  unexpected_keys: string[];
}

export interface SignalClassificationSampleApi {
  expected_color: string;
  predicted_color: string;
  head_id: string | null;
  confidence: number | null;
}

export interface SignalBenchmarkCaseApi {
  name: string;
  samples: SignalClassificationSampleApi[];
}

export interface SignalBenchmarkReportApi {
  name: string;
  sample_count: number;
  correct_count: number;
  accuracy: number;
  per_class_accuracy: Record<string, number>;
  confusion_pairs: string[];
}

export interface BenchmarkFixtureSuiteApi {
  detection_cases: DetectionBenchmarkCaseApi[];
  tracking_cases: TrackingBenchmarkCaseApi[];
  ocr_cases: OcrBenchmarkCaseApi[];
  rule_cases: RuleSanityCaseApi[];
  signal_cases: SignalBenchmarkCaseApi[];
}

export interface BenchmarkSuiteReportApi {
  generated_at: string;
  detection_reports: DetectionBenchmarkReportApi[];
  tracking_reports: TrackingBenchmarkReportApi[];
  ocr_reports: OcrBenchmarkReportApi[];
  rule_reports: RuleSanityReportApi[];
  signal_reports: SignalBenchmarkReportApi[];
}

export interface BenchmarkArtifactMetadataApi {
  artifact_key: string;
  artifact_label: string;
  source_kind: EvaluationArtifactSourceKind;
  source_path: string | null;
  observed_at: string | null;
  generated_at: string;
  task_types: EvaluationTaskType[];
  scenario_names: string[];
  camera_ids: string[];
  camera_labels: string[];
  model_registry_ids: string[];
  model_version_names: string[];
  manual_review_summary: string | null;
  workflow_summary: string | null;
  notes: string[];
}

export interface BenchmarkReportArtifactApi {
  metadata: BenchmarkArtifactMetadataApi;
  report: BenchmarkSuiteReportApi;
  fixture_suite: BenchmarkFixtureSuiteApi | null;
}

export interface EvaluationManualSummaryApi {
  artifact_key: string;
  artifact_label: string;
  source_kind: EvaluationArtifactSourceKind;
  observed_at: string | null;
  generated_at: string;
  manual_review_summary: string | null;
  workflow_summary: string | null;
  model_version_names: string[];
  camera_labels: string[];
  notes: string[];
}

export interface EvaluationPlaceholderApi {
  key: string;
  title: string;
  detail: string;
}

export interface EvaluationSummaryResponseApi {
  generated_at: string;
  sources: BenchmarkReportArtifactApi[];
  manual_review_summaries: EvaluationManualSummaryApi[];
  placeholders: EvaluationPlaceholderApi[];
  methodology: string[];
  warnings: string[];
}

export interface EvaluationFilterOption {
  value: string;
  label: string;
}

export interface EvaluationFilterState {
  taskType: EvaluationTaskType | null;
  scenario: string | null;
  modelVersion: string | null;
  camera: string | null;
  dateAfter: string | null;
  dateBefore: string | null;
}

export interface EvaluationDetectionItem {
  artifactKey: string;
  artifactLabel: string;
  sourceKind: EvaluationArtifactSourceKind;
  observedAt: string | null;
  generatedAt: string;
  scenarioName: string;
  modelVersionNames: string[];
  cameraLabels: string[];
  expectedCount: number;
  predictedCount: number;
  matchedCount: number;
  falsePositiveCount: number;
  falseNegativeCount: number;
  precision: number;
  recall: number;
  meanIou: number | null;
  matchedLabels: string[];
  iouThreshold: number | null;
}

export interface EvaluationTrackingItem {
  artifactKey: string;
  artifactLabel: string;
  sourceKind: EvaluationArtifactSourceKind;
  observedAt: string | null;
  generatedAt: string;
  scenarioName: string;
  modelVersionNames: string[];
  cameraLabels: string[];
  objectCount: number;
  expectedObservations: number;
  observedObservations: number;
  coverageRate: number;
  idSwitchCount: number;
  fragmentedObjectCount: number;
  continuityScore: number;
  notes: string[];
}

export interface EvaluationOcrItem {
  artifactKey: string;
  artifactLabel: string;
  sourceKind: EvaluationArtifactSourceKind;
  observedAt: string | null;
  generatedAt: string;
  scenarioName: string;
  modelVersionNames: string[];
  cameraLabels: string[];
  sampleCount: number;
  exactMatchCount: number;
  exactMatchRate: number;
  averageCharAccuracy: number;
  averageConfidence: number | null;
  samples: PlateReadQualitySampleApi[];
}

export interface EvaluationRuleItem {
  artifactKey: string;
  artifactLabel: string;
  sourceKind: EvaluationArtifactSourceKind;
  observedAt: string | null;
  generatedAt: string;
  scenarioName: string;
  modelVersionNames: string[];
  cameraLabels: string[];
  expectedCount: number;
  actualCount: number;
  matchedCount: number;
  missingCount: number;
  unexpectedCount: number;
  passRate: number;
  missingKeys: string[];
  unexpectedKeys: string[];
  expectedEvents: RuleOutcomeSampleApi[];
  actualEvents: RuleOutcomeSampleApi[];
}

export interface EvaluationSignalItem {
  artifactKey: string;
  artifactLabel: string;
  sourceKind: EvaluationArtifactSourceKind;
  observedAt: string | null;
  generatedAt: string;
  scenarioName: string;
  modelVersionNames: string[];
  cameraLabels: string[];
  sampleCount: number;
  correctCount: number;
  accuracy: number;
  perClassAccuracy: Record<string, number>;
  confusionPairs: string[];
  samples: SignalClassificationSampleApi[];
}

export interface EvaluationSourceSummary {
  artifactKey: string;
  artifactLabel: string;
  sourceKind: EvaluationArtifactSourceKind;
  observedAt: string | null;
  generatedAt: string;
  sourcePath: string | null;
  taskTypes: EvaluationTaskType[];
  scenarioNames: string[];
  cameraLabels: string[];
  modelVersionNames: string[];
  notes: string[];
}

export interface EvaluationDashboardModel {
  ok: boolean;
  error: string | null;
  generatedAt: string | null;
  selectedFilters: EvaluationFilterState;
  filterOptions: {
    taskTypes: EvaluationFilterOption[];
    scenarios: EvaluationFilterOption[];
    modelVersions: EvaluationFilterOption[];
    cameras: EvaluationFilterOption[];
  };
  stats: {
    measuredScenarioCount: number;
    sourceCount: number;
    storedSourceCount: number;
    manualSummaryCount: number;
    taggedVersionCount: number;
  };
  sources: EvaluationSourceSummary[];
  detectionItems: EvaluationDetectionItem[];
  trackingItems: EvaluationTrackingItem[];
  ocrItems: EvaluationOcrItem[];
  ruleItems: EvaluationRuleItem[];
  signalItems: EvaluationSignalItem[];
  manualReviewSummaries: EvaluationManualSummaryApi[];
  placeholders: EvaluationPlaceholderApi[];
  methodology: string[];
  warnings: string[];
}