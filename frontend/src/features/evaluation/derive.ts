import type { ApiResult } from "@/features/operations/types";
import type {
  BenchmarkReportArtifactApi,
  EvaluationDashboardModel,
  EvaluationDetectionItem,
  EvaluationFilterOption,
  EvaluationFilterState,
  EvaluationOcrItem,
  EvaluationRuleItem,
  EvaluationSignalItem,
  EvaluationSummaryResponseApi,
  EvaluationTaskType,
  EvaluationTrackingItem,
} from "@/features/evaluation/types";

function dedupeOptions(values: string[]): EvaluationFilterOption[] {
  return Array.from(new Set(values.filter(Boolean)))
    .sort((left, right) => left.localeCompare(right))
    .map((value) => ({ value, label: value }));
}

function taskTypeOptions(values: EvaluationTaskType[]): EvaluationFilterOption[] {
  return Array.from(new Set(values))
    .sort((left, right) => left.localeCompare(right))
    .map((value) => ({
      value,
      label:
        value === "ocr"
          ? "OCR"
          : value === "rules"
            ? "Rules"
            : value === "workflow"
              ? "Manual/workflow notes"
              : `${value.charAt(0).toUpperCase()}${value.slice(1)}`,
    }));
}

function toMillis(value: string | null): number | null {
  if (!value) {
    return null;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  return parsed.getTime();
}

function sourceMatchesFilters(
  source: BenchmarkReportArtifactApi,
  filters: EvaluationFilterState,
): boolean {
  const comparisonMillis = toMillis(source.metadata.observed_at ?? source.metadata.generated_at);
  const afterMillis = toMillis(filters.dateAfter);
  const beforeMillis = toMillis(filters.dateBefore);

  if (filters.modelVersion && !source.metadata.model_version_names.includes(filters.modelVersion)) {
    return false;
  }
  if (filters.camera && !source.metadata.camera_labels.includes(filters.camera)) {
    return false;
  }
  if (afterMillis !== null && (comparisonMillis === null || comparisonMillis < afterMillis)) {
    return false;
  }
  if (beforeMillis !== null && (comparisonMillis === null || comparisonMillis > beforeMillis)) {
    return false;
  }
  return true;
}

function buildDetectionItems(
  source: BenchmarkReportArtifactApi,
  filters: EvaluationFilterState,
): EvaluationDetectionItem[] {
  if (filters.taskType && filters.taskType !== "detection") {
    return [];
  }
  const caseIndex = new Map((source.fixture_suite?.detection_cases ?? []).map((item) => [item.name, item]));
  return source.report.detection_reports
    .filter((report) => !filters.scenario || report.name === filters.scenario)
    .map((report) => {
      const fixtureCase = caseIndex.get(report.name);
      return {
        artifactKey: source.metadata.artifact_key,
        artifactLabel: source.metadata.artifact_label,
        sourceKind: source.metadata.source_kind,
        observedAt: source.metadata.observed_at,
        generatedAt: source.metadata.generated_at,
        scenarioName: report.name,
        modelVersionNames: source.metadata.model_version_names,
        cameraLabels: source.metadata.camera_labels,
        expectedCount: report.expected_count,
        predictedCount: report.predicted_count,
        matchedCount: report.matched_count,
        falsePositiveCount: report.false_positive_count,
        falseNegativeCount: report.false_negative_count,
        precision: report.precision,
        recall: report.recall,
        meanIou: report.mean_iou,
        matchedLabels: report.matched_labels,
        iouThreshold: fixtureCase?.iou_threshold ?? null,
      };
    });
}

function buildTrackingItems(
  source: BenchmarkReportArtifactApi,
  filters: EvaluationFilterState,
): EvaluationTrackingItem[] {
  if (filters.taskType && filters.taskType !== "tracking") {
    return [];
  }
  return source.report.tracking_reports
    .filter((report) => !filters.scenario || report.name === filters.scenario)
    .map((report) => ({
      artifactKey: source.metadata.artifact_key,
      artifactLabel: source.metadata.artifact_label,
      sourceKind: source.metadata.source_kind,
      observedAt: source.metadata.observed_at,
      generatedAt: source.metadata.generated_at,
      scenarioName: report.name,
      modelVersionNames: source.metadata.model_version_names,
      cameraLabels: source.metadata.camera_labels,
      objectCount: report.object_count,
      expectedObservations: report.expected_observations,
      observedObservations: report.observed_observations,
      coverageRate: report.coverage_rate,
      idSwitchCount: report.id_switch_count,
      fragmentedObjectCount: report.fragmented_object_count,
      continuityScore: report.continuity_score,
      notes: report.notes,
    }));
}

function buildOcrItems(
  source: BenchmarkReportArtifactApi,
  filters: EvaluationFilterState,
): EvaluationOcrItem[] {
  if (filters.taskType && filters.taskType !== "ocr") {
    return [];
  }
  const caseIndex = new Map((source.fixture_suite?.ocr_cases ?? []).map((item) => [item.name, item]));
  return source.report.ocr_reports
    .filter((report) => !filters.scenario || report.name === filters.scenario)
    .map((report) => ({
      artifactKey: source.metadata.artifact_key,
      artifactLabel: source.metadata.artifact_label,
      sourceKind: source.metadata.source_kind,
      observedAt: source.metadata.observed_at,
      generatedAt: source.metadata.generated_at,
      scenarioName: report.name,
      modelVersionNames: source.metadata.model_version_names,
      cameraLabels: source.metadata.camera_labels,
      sampleCount: report.sample_count,
      exactMatchCount: report.exact_match_count,
      exactMatchRate: report.exact_match_rate,
      averageCharAccuracy: report.average_char_accuracy,
      averageConfidence: report.average_confidence,
      samples: caseIndex.get(report.name)?.samples ?? [],
    }));
}

function buildRuleItems(
  source: BenchmarkReportArtifactApi,
  filters: EvaluationFilterState,
): EvaluationRuleItem[] {
  if (filters.taskType && filters.taskType !== "rules") {
    return [];
  }
  const caseIndex = new Map((source.fixture_suite?.rule_cases ?? []).map((item) => [item.name, item]));
  return source.report.rule_reports
    .filter((report) => !filters.scenario || report.name === filters.scenario)
    .map((report) => {
      const fixtureCase = caseIndex.get(report.name);
      return {
        artifactKey: source.metadata.artifact_key,
        artifactLabel: source.metadata.artifact_label,
        sourceKind: source.metadata.source_kind,
        observedAt: source.metadata.observed_at,
        generatedAt: source.metadata.generated_at,
        scenarioName: report.name,
        modelVersionNames: source.metadata.model_version_names,
        cameraLabels: source.metadata.camera_labels,
        expectedCount: report.expected_count,
        actualCount: report.actual_count,
        matchedCount: report.matched_count,
        missingCount: report.missing_count,
        unexpectedCount: report.unexpected_count,
        passRate: report.pass_rate,
        missingKeys: report.missing_keys,
        unexpectedKeys: report.unexpected_keys,
        expectedEvents: fixtureCase?.expected_events ?? [],
        actualEvents: fixtureCase?.actual_events ?? [],
      };
    });
}

function buildSignalItems(
  source: BenchmarkReportArtifactApi,
  filters: EvaluationFilterState,
): EvaluationSignalItem[] {
  if (filters.taskType && filters.taskType !== "signal") {
    return [];
  }
  const caseIndex = new Map((source.fixture_suite?.signal_cases ?? []).map((item) => [item.name, item]));
  return source.report.signal_reports
    .filter((report) => !filters.scenario || report.name === filters.scenario)
    .map((report) => ({
      artifactKey: source.metadata.artifact_key,
      artifactLabel: source.metadata.artifact_label,
      sourceKind: source.metadata.source_kind,
      observedAt: source.metadata.observed_at,
      generatedAt: source.metadata.generated_at,
      scenarioName: report.name,
      modelVersionNames: source.metadata.model_version_names,
      cameraLabels: source.metadata.camera_labels,
      sampleCount: report.sample_count,
      correctCount: report.correct_count,
      accuracy: report.accuracy,
      perClassAccuracy: report.per_class_accuracy,
      confusionPairs: report.confusion_pairs,
      samples: caseIndex.get(report.name)?.samples ?? [],
    }));
}

function buildSourceSummary(source: BenchmarkReportArtifactApi) {
  return {
    artifactKey: source.metadata.artifact_key,
    artifactLabel: source.metadata.artifact_label,
    sourceKind: source.metadata.source_kind,
    observedAt: source.metadata.observed_at,
    generatedAt: source.metadata.generated_at,
    sourcePath: source.metadata.source_path,
    taskTypes: source.metadata.task_types,
    scenarioNames: source.metadata.scenario_names,
    cameraLabels: source.metadata.camera_labels,
    modelVersionNames: source.metadata.model_version_names,
    notes: source.metadata.notes,
  };
}

function buildFilterOptions(summary: EvaluationSummaryResponseApi) {
  const taskTypes: EvaluationTaskType[] = [];
  const scenarios: string[] = [];
  const modelVersions: string[] = [];
  const cameras: string[] = [];

  summary.sources.forEach((source) => {
    taskTypes.push(...source.metadata.task_types);
    scenarios.push(...source.metadata.scenario_names);
    modelVersions.push(...source.metadata.model_version_names);
    cameras.push(...source.metadata.camera_labels);
  });
  if (summary.manual_review_summaries.length > 0) {
    taskTypes.push("workflow");
  }

  return {
    taskTypes: taskTypeOptions(taskTypes),
    scenarios: dedupeOptions(scenarios),
    modelVersions: dedupeOptions(modelVersions),
    cameras: dedupeOptions(cameras),
  };
}

export function coerceTaskType(value: string | null): EvaluationTaskType | null {
  if (
    value === "detection" ||
    value === "tracking" ||
    value === "ocr" ||
    value === "rules" ||
    value === "signal" ||
    value === "workflow"
  ) {
    return value;
  }
  return null;
}

export function buildEvaluationDashboardModel(
  result: ApiResult<EvaluationSummaryResponseApi>,
  filters: EvaluationFilterState,
): EvaluationDashboardModel {
  if (!result.ok || result.data === null) {
    return {
      ok: false,
      error: result.error ?? "Evaluation summary could not be loaded.",
      generatedAt: null,
      selectedFilters: filters,
      filterOptions: {
        taskTypes: [],
        scenarios: [],
        modelVersions: [],
        cameras: [],
      },
      stats: {
        measuredScenarioCount: 0,
        sourceCount: 0,
        storedSourceCount: 0,
        manualSummaryCount: 0,
        taggedVersionCount: 0,
      },
      sources: [],
      detectionItems: [],
      trackingItems: [],
      ocrItems: [],
      ruleItems: [],
      signalItems: [],
      manualReviewSummaries: [],
      placeholders: [],
      methodology: [],
      warnings: [],
    };
  }

  const summary = result.data;
  const filterOptions = buildFilterOptions(summary);
  const filteredSources = summary.sources.filter((source) => sourceMatchesFilters(source, filters));

  const detectionItems = filteredSources.flatMap((source) => buildDetectionItems(source, filters));
  const trackingItems = filteredSources.flatMap((source) => buildTrackingItems(source, filters));
  const ocrItems = filteredSources.flatMap((source) => buildOcrItems(source, filters));
  const ruleItems = filteredSources.flatMap((source) => buildRuleItems(source, filters));
  const signalItems = filteredSources.flatMap((source) => buildSignalItems(source, filters));
  const manualReviewSummaries = summary.manual_review_summaries.filter((summaryItem) => {
    const comparisonMillis = toMillis(summaryItem.observed_at ?? summaryItem.generated_at);
    const afterMillis = toMillis(filters.dateAfter);
    const beforeMillis = toMillis(filters.dateBefore);
    if (filters.taskType && filters.taskType !== "workflow") {
      return false;
    }
    if (filters.modelVersion && !summaryItem.model_version_names.includes(filters.modelVersion)) {
      return false;
    }
    if (filters.camera && !summaryItem.camera_labels.includes(filters.camera)) {
      return false;
    }
    if (afterMillis !== null && (comparisonMillis === null || comparisonMillis < afterMillis)) {
      return false;
    }
    if (beforeMillis !== null && (comparisonMillis === null || comparisonMillis > beforeMillis)) {
      return false;
    }
    return true;
  });
  const placeholders = summary.placeholders.filter((placeholder) => {
    if (filters.taskType === "workflow") {
      return placeholder.key === "workflow_evaluation_summaries" || placeholder.key === "manual_review_summaries";
    }
    return true;
  });

  return {
    ok: true,
    error: null,
    generatedAt: summary.generated_at,
    selectedFilters: filters,
    filterOptions,
    stats: {
      measuredScenarioCount:
        detectionItems.length +
        trackingItems.length +
        ocrItems.length +
        ruleItems.length +
        signalItems.length,
      sourceCount: filteredSources.length,
      storedSourceCount: filteredSources.filter((source) => source.metadata.source_kind === "stored_report").length,
      manualSummaryCount: manualReviewSummaries.length,
      taggedVersionCount: Array.from(
        new Set(filteredSources.flatMap((source) => source.metadata.model_version_names))
      ).length,
    },
    sources: filteredSources.map(buildSourceSummary),
    detectionItems,
    trackingItems,
    ocrItems,
    ruleItems,
    signalItems,
    manualReviewSummaries,
    placeholders,
    methodology: summary.methodology,
    warnings: summary.warnings,
  };
}

export function getSingleParam(
  value: string | string[] | undefined,
): string | null {
  if (Array.isArray(value)) {
    return value[0] ?? null;
  }
  return value ?? null;
}