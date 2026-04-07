import Link from "next/link";

import type {
  EvaluationDashboardModel,
  EvaluationFilterOption,
  EvaluationTaskType,
} from "@/features/evaluation/types";
import { EvidencePrivacyPolicyPreview } from "@/features/evidence/components/evidence-privacy-status";
import { EVIDENCE_ACCESS_ROLES, type EvidenceAccessRole, type AccessPolicyRead } from "@/features/evidence/types";
import { formatTimestamp, StatCard } from "@/features/operations/components/dashboard-primitives";
import { titleCase, accessRoleLabel } from "@/features/shared/format-labels";

const actionLinkClass =
  "rounded-full border border-[rgba(23,57,69,0.14)] px-4 py-2 text-sm font-medium text-[var(--color-ink)] transition-colors hover:border-[rgba(23,57,69,0.28)]";

function sourceKindLabel(value: string): string {
  switch (value) {
    case "fixture_suite":
      return "Benchmark Test";
    case "stored_report":
      return "Stored Artifact";
    default:
      return titleCase(value);
  }
}

function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "Not available";
  }
  return `${(value * 100).toFixed(1)}%`;
}

function formatDecimal(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "Not available";
  }
  return value.toFixed(2);
}

function taskTypeLabel(taskType: EvaluationTaskType): string {
  switch (taskType) {
    case "ocr":
      return "OCR";
    case "rules":
      return "Rules";
    default:
      return `${taskType.charAt(0).toUpperCase()}${taskType.slice(1)}`;
  }
}

function FilterSelect({
  name,
  label,
  value,
  options,
  placeholder,
  disabled,
}: {
  name: string;
  label: string;
  value: string | null;
  options: EvaluationFilterOption[];
  placeholder: string;
  disabled?: boolean;
}) {
  return (
    <label className="flex flex-col gap-2 text-sm text-[rgba(19,32,41,0.78)]">
      <span className="text-[0.72rem] font-semibold uppercase tracking-[0.18em] text-[rgba(19,32,41,0.52)]">{label}</span>
      <select
        name={name}
        defaultValue={value ?? ""}
        disabled={disabled}
        className="rounded-[1rem] border border-[rgba(23,57,69,0.14)] bg-[rgba(255,255,255,0.92)] px-4 py-3 text-sm text-[var(--color-ink)] outline-none transition-colors focus:border-[rgba(23,57,69,0.28)] disabled:cursor-not-allowed disabled:bg-[rgba(245,241,233,0.7)]"
      >
        <option value="">{placeholder}</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function EmptySection({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="rounded-[1.4rem] border border-dashed border-[rgba(23,57,69,0.18)] bg-[rgba(246,240,229,0.72)] p-5">
      <p className="text-sm font-semibold text-[var(--color-ink)]">{title}</p>
      <p className="mt-2 text-sm leading-6 text-[rgba(19,32,41,0.72)]">{detail}</p>
    </div>
  );
}

export function EvaluationDashboard({
  model,
  accessPolicy,
  accessRole,
  accessPolicyError,
}: {
  model: EvaluationDashboardModel;
  accessPolicy: AccessPolicyRead | null;
  accessRole: EvidenceAccessRole;
  accessPolicyError?: string | null;
}) {
  const hasActiveFilters = Boolean(
    model.selectedFilters.taskType ||
      model.selectedFilters.scenario ||
      model.selectedFilters.modelVersion ||
      model.selectedFilters.camera ||
      model.selectedFilters.dateAfter ||
      model.selectedFilters.dateBefore
  );
  const scenarioFilterDisabled = model.selectedFilters.taskType === "workflow" || model.filterOptions.scenarios.length === 0;

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-[1520px] flex-col gap-6 px-4 py-8 sm:px-6 lg:px-10">

      <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[linear-gradient(135deg,rgba(243,236,225,0.96),rgba(230,242,244,0.92))] p-8 shadow-[0_24px_60px_rgba(18,32,41,0.08)]">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-4xl">
            <p className="text-[0.75rem] font-semibold uppercase tracking-[0.26em] text-[rgba(19,32,41,0.56)]">
              Evaluation
            </p>
            <h1 className="mt-4 text-4xl font-semibold tracking-[-0.06em] text-[var(--color-ink)] sm:text-5xl">
              Model Evaluation Results
            </h1>
            <p className="mt-4 max-w-3xl text-base leading-7 text-[rgba(19,32,41,0.76)] sm:text-lg">
              Review detection, tracking, and OCR performance from benchmark tests and stored evaluation reports. Results shown here are from controlled test sets, not production data.
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <div className="rounded-[1.5rem] bg-[rgba(255,255,255,0.76)] px-4 py-3 text-sm text-[var(--color-ink)]">
              <p className="text-[0.7rem] uppercase tracking-[0.22em] text-[rgba(19,32,41,0.52)]">Data generated</p>
              <p className="mt-2 font-semibold">{formatTimestamp(model.generatedAt)}</p>
              <p className="mt-1 text-[rgba(19,32,41,0.72)]">Most recent evaluation summary</p>
            </div>
            <div className="rounded-[1.5rem] bg-[rgba(255,255,255,0.76)] px-4 py-3 text-sm text-[var(--color-ink)]">
              <p className="text-[0.7rem] uppercase tracking-[0.22em] text-[rgba(19,32,41,0.52)]">Measured sources</p>
              <p className="mt-2 font-semibold">{model.stats.sourceCount}</p>
              <p className="mt-1 text-[rgba(19,32,41,0.72)]">Benchmark tests and stored reports</p>
            </div>
            <div className="rounded-[1.5rem] bg-[rgba(255,255,255,0.76)] px-4 py-3 text-sm text-[var(--color-ink)]">
              <p className="text-[0.7rem] uppercase tracking-[0.22em] text-[rgba(19,32,41,0.52)]">Manual notes</p>
              <p className="mt-2 font-semibold">{model.stats.manualSummaryCount}</p>
              <p className="mt-1 text-[rgba(19,32,41,0.72)]">Shown when artifacts include manual notes</p>
            </div>
          </div>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Measured Rows"
          value={`${model.stats.measuredScenarioCount}`}
          note="Result rows visible after applying current filters."
        />
        <StatCard
          label="Stored Artifacts"
          value={`${model.stats.storedSourceCount}`}
          note="Report files discovered in the evaluation directory."
        />
        <StatCard
          label="Tagged Versions"
          value={`${model.stats.taggedVersionCount}`}
          note="Distinct model or config version tags in the current artifact set."
        />
      </section>

      <section className="grid gap-6 xl:grid-cols-[minmax(0,1.7fr)_minmax(22rem,0.95fr)]">
        <div className="flex flex-col gap-6">
          <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-6 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">
                  Filters
                </p>
                <h2 className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">
                  Filter Results
                </h2>
              </div>
              {hasActiveFilters ? (
                <Link href="/evaluation" className={actionLinkClass}>
                  Reset filters
                </Link>
              ) : null}
            </div>

            <form className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3" action="/evaluation">
              <FilterSelect
                name="taskType"
                label="Task type"
                value={model.selectedFilters.taskType}
                options={model.filterOptions.taskTypes}
                placeholder="All task types"
              />
              <FilterSelect
                name="scenario"
                label="Scenario"
                value={model.selectedFilters.scenario}
                options={model.filterOptions.scenarios}
                placeholder={scenarioFilterDisabled ? "Scenario filter applies to measured rows only" : "All scenarios"}
                disabled={scenarioFilterDisabled}
              />
              <FilterSelect
                name="modelVersion"
                label="Model/config version"
                value={model.selectedFilters.modelVersion}
                options={model.filterOptions.modelVersions}
                placeholder={model.filterOptions.modelVersions.length === 0 ? "No tagged versions available" : "All tagged versions"}
                disabled={model.filterOptions.modelVersions.length === 0}
              />
              <FilterSelect
                name="camera"
                label="Camera"
                value={model.selectedFilters.camera}
                options={model.filterOptions.cameras}
                placeholder={model.filterOptions.cameras.length === 0 ? "No camera tags available" : "All tagged cameras"}
                disabled={model.filterOptions.cameras.length === 0}
              />
              <label className="flex flex-col gap-2 text-sm text-[rgba(19,32,41,0.78)]">
                <span className="text-[0.72rem] font-semibold uppercase tracking-[0.18em] text-[rgba(19,32,41,0.52)]">Observed after</span>
                <input
                  type="datetime-local"
                  name="dateAfter"
                  defaultValue={model.selectedFilters.dateAfter ?? ""}
                  className="rounded-[1rem] border border-[rgba(23,57,69,0.14)] bg-[rgba(255,255,255,0.92)] px-4 py-3 text-sm text-[var(--color-ink)] outline-none transition-colors focus:border-[rgba(23,57,69,0.28)]"
                />
              </label>
              <label className="flex flex-col gap-2 text-sm text-[rgba(19,32,41,0.78)]">
                <span className="text-[0.72rem] font-semibold uppercase tracking-[0.18em] text-[rgba(19,32,41,0.52)]">Observed before</span>
                <input
                  type="datetime-local"
                  name="dateBefore"
                  defaultValue={model.selectedFilters.dateBefore ?? ""}
                  className="rounded-[1rem] border border-[rgba(23,57,69,0.14)] bg-[rgba(255,255,255,0.92)] px-4 py-3 text-sm text-[var(--color-ink)] outline-none transition-colors focus:border-[rgba(23,57,69,0.28)]"
                />
              </label>
              <div className="md:col-span-2 xl:col-span-3 flex flex-wrap gap-3 pt-2">
                <button
                  type="submit"
                  className="rounded-full bg-[var(--color-ink)] px-5 py-2.5 text-sm font-medium text-[var(--color-paper)] transition-opacity hover:opacity-92"
                >
                  Apply filters
                </button>
                <p className="self-center text-sm text-[rgba(19,32,41,0.64)]">
                  Filters apply to measured result rows. Empty version or camera filters mean no tags are present in the current artifacts.
                </p>
              </div>
            </form>
          </section>

          {!model.ok ? (
            <EmptySection
              title="Evaluation data could not be loaded"
              detail={model.error ?? "The evaluation data could not be loaded right now. Please try again later."}
            />
          ) : (
            <>
              <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-6 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">
                      Benchmark Results
                    </p>
                    <h2 className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">
                      Measured Results
                    </h2>
                  </div>
                  <span className="rounded-full bg-[rgba(56,183,118,0.14)] px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-[var(--color-ok-ink)]">
                    measured
                  </span>
                </div>

                <div className="mt-5 grid gap-5 xl:grid-cols-2">
                  <div className="rounded-[1.5rem] bg-[rgba(243,237,228,0.74)] p-5">
                    <div className="flex items-center justify-between gap-3">
                      <h3 className="text-xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">Detection Accuracy</h3>
                      <span className="rounded-full bg-[rgba(19,32,41,0.08)] px-3 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-[rgba(19,32,41,0.72)]">
                        {model.detectionItems.length} scenarios
                      </span>
                    </div>
                    {model.detectionItems.length === 0 ? (
                      <p className="mt-4 text-sm leading-6 text-[rgba(19,32,41,0.72)]">No detection scenarios match the current filters.{hasActiveFilters ? <> <Link href="/evaluation" className="underline underline-offset-2 hover:text-[var(--color-ink)]">Clear filters</Link></> : null}</p>
                    ) : (
                      <div className="mt-4 space-y-4">
                        {model.detectionItems.map((item) => (
                          <div key={`${item.artifactKey}:${item.scenarioName}`} className="rounded-[1.25rem] bg-[rgba(255,255,255,0.74)] p-4">
                            <div className="flex flex-wrap items-center justify-between gap-3">
                              <div>
                                <p className="font-semibold text-[var(--color-ink)]">{item.scenarioName}</p>
                                <p className="mt-1 text-sm text-[rgba(19,32,41,0.64)]">{item.artifactLabel} · {sourceKindLabel(item.sourceKind)}</p>
                              </div>
                              <p className="text-sm text-[rgba(19,32,41,0.6)]">Observed {formatTimestamp(item.observedAt ?? item.generatedAt)}</p>
                            </div>
                            <div className="mt-4 grid gap-3 sm:grid-cols-3">
                              <div><p className="text-xs uppercase tracking-[0.16em] text-[rgba(19,32,41,0.52)]">Detection precision</p><p className="mt-1 text-lg font-semibold text-[var(--color-ink)]">{formatPercent(item.precision)}</p></div>
                              <div><p className="text-xs uppercase tracking-[0.16em] text-[rgba(19,32,41,0.52)]">Detection recall</p><p className="mt-1 text-lg font-semibold text-[var(--color-ink)]">{formatPercent(item.recall)}</p></div>
                              <div><p className="text-xs uppercase tracking-[0.16em] text-[rgba(19,32,41,0.52)]">Matched IoU</p><p className="mt-1 text-lg font-semibold text-[var(--color-ink)]">{formatDecimal(item.meanIou)}</p></div>
                            </div>
                            <p className="mt-3 text-sm leading-6 text-[rgba(19,32,41,0.72)]">
                              Predicted {item.predictedCount} annotations against {item.expectedCount} expected annotations, with {item.matchedCount} matched, {item.falsePositiveCount} false positives, and {item.falseNegativeCount} false negatives.
                              {item.iouThreshold !== null ? ` IoU threshold: ${item.iouThreshold.toFixed(2)}.` : ""}
                            </p>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="rounded-[1.5rem] bg-[rgba(243,237,228,0.74)] p-5">
                    <div className="flex items-center justify-between gap-3">
                      <h3 className="text-xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">Tracking Continuity</h3>
                      <span className="rounded-full bg-[rgba(19,32,41,0.08)] px-3 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-[rgba(19,32,41,0.72)]">
                        {model.trackingItems.length} scenarios
                      </span>
                    </div>
                    {model.trackingItems.length === 0 ? (
                      <p className="mt-4 text-sm leading-6 text-[rgba(19,32,41,0.72)]">No tracking scenarios match the current filters.{hasActiveFilters ? <> <Link href="/evaluation" className="underline underline-offset-2 hover:text-[var(--color-ink)]">Clear filters</Link></> : null}</p>
                    ) : (
                      <div className="mt-4 space-y-4">
                        {model.trackingItems.map((item) => (
                          <div key={`${item.artifactKey}:${item.scenarioName}`} className="rounded-[1.25rem] bg-[rgba(255,255,255,0.74)] p-4">
                            <div className="flex flex-wrap items-center justify-between gap-3">
                              <div>
                                <p className="font-semibold text-[var(--color-ink)]">{item.scenarioName}</p>
                                <p className="mt-1 text-sm text-[rgba(19,32,41,0.64)]">{item.artifactLabel} · {sourceKindLabel(item.sourceKind)}</p>
                              </div>
                              <p className="text-sm text-[rgba(19,32,41,0.6)]">Observed {formatTimestamp(item.observedAt ?? item.generatedAt)}</p>
                            </div>
                            <div className="mt-4 grid gap-3 sm:grid-cols-3">
                              <div><p className="text-xs uppercase tracking-[0.16em] text-[rgba(19,32,41,0.52)]">Assignment coverage</p><p className="mt-1 text-lg font-semibold text-[var(--color-ink)]">{formatPercent(item.coverageRate)}</p></div>
                              <div><p className="text-xs uppercase tracking-[0.16em] text-[rgba(19,32,41,0.52)]">ID switches</p><p className="mt-1 text-lg font-semibold text-[var(--color-ink)]">{item.idSwitchCount}</p></div>
                              <div><p className="text-xs uppercase tracking-[0.16em] text-[rgba(19,32,41,0.52)]">Continuity score</p><p className="mt-1 text-lg font-semibold text-[var(--color-ink)]">{formatPercent(item.continuityScore)}</p></div>
                            </div>
                            <p className="mt-3 text-sm leading-6 text-[rgba(19,32,41,0.72)]">
                              {item.observedObservations} observed assignments across {item.expectedObservations} expected observations for {item.objectCount} logical objects. {item.fragmentedObjectCount} object(s) were fragmented across multiple track IDs.
                            </p>
                            {item.notes.length > 0 ? (
                              <ul className="mt-3 space-y-1 text-sm leading-6 text-[rgba(19,32,41,0.72)]">
                                {item.notes.slice(0, 3).map((note) => (
                                  <li key={note}>- {note}</li>
                                ))}
                              </ul>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="rounded-[1.5rem] bg-[rgba(243,237,228,0.74)] p-5">
                    <div className="flex items-center justify-between gap-3">
                      <h3 className="text-xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">OCR Accuracy</h3>
                      <span className="rounded-full bg-[rgba(19,32,41,0.08)] px-3 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-[rgba(19,32,41,0.72)]">
                        {model.ocrItems.length} scenarios
                      </span>
                    </div>
                    {model.ocrItems.length === 0 ? (
                      <p className="mt-4 text-sm leading-6 text-[rgba(19,32,41,0.72)]">No OCR scenarios match the current filters.{hasActiveFilters ? <> <Link href="/evaluation" className="underline underline-offset-2 hover:text-[var(--color-ink)]">Clear filters</Link></> : null}</p>
                    ) : (
                      <div className="mt-4 space-y-4">
                        {model.ocrItems.map((item) => (
                          <div key={`${item.artifactKey}:${item.scenarioName}`} className="rounded-[1.25rem] bg-[rgba(255,255,255,0.74)] p-4">
                            <div className="flex flex-wrap items-center justify-between gap-3">
                              <div>
                                <p className="font-semibold text-[var(--color-ink)]">{item.scenarioName}</p>
                                <p className="mt-1 text-sm text-[rgba(19,32,41,0.64)]">{item.artifactLabel} · {sourceKindLabel(item.sourceKind)}</p>
                              </div>
                              <p className="text-sm text-[rgba(19,32,41,0.6)]">Observed {formatTimestamp(item.observedAt ?? item.generatedAt)}</p>
                            </div>
                            <div className="mt-4 grid gap-3 sm:grid-cols-3">
                              <div><p className="text-xs uppercase tracking-[0.16em] text-[rgba(19,32,41,0.52)]">Exact plate match</p><p className="mt-1 text-lg font-semibold text-[var(--color-ink)]">{formatPercent(item.exactMatchRate)}</p></div>
                              <div><p className="text-xs uppercase tracking-[0.16em] text-[rgba(19,32,41,0.52)]">Avg char accuracy</p><p className="mt-1 text-lg font-semibold text-[var(--color-ink)]">{formatPercent(item.averageCharAccuracy)}</p></div>
                              <div><p className="text-xs uppercase tracking-[0.16em] text-[rgba(19,32,41,0.52)]">Mean confidence</p><p className="mt-1 text-lg font-semibold text-[var(--color-ink)]">{formatDecimal(item.averageConfidence)}</p></div>
                            </div>
                            <p className="mt-3 text-sm leading-6 text-[rgba(19,32,41,0.72)]">
                              {item.exactMatchCount} exact normalized text matches across {item.sampleCount} OCR sample(s).
                            </p>
                            {item.samples.length > 0 ? (
                              <div className="mt-4 overflow-x-auto">
                                <table className="min-w-full text-left text-sm">
                                  <thead className="text-[0.68rem] uppercase tracking-[0.16em] text-[rgba(19,32,41,0.52)]">
                                    <tr>
                                      <th className="pb-2 pr-4">Expected</th>
                                      <th className="pb-2 pr-4">Predicted</th>
                                      <th className="pb-2">Confidence</th>
                                    </tr>
                                  </thead>
                                  <tbody className="text-[rgba(19,32,41,0.76)]">
                                    {item.samples.slice(0, 4).map((sample, index) => (
                                      <tr key={`${item.scenarioName}:${index}`} className="border-t border-[rgba(23,57,69,0.08)]">
                                        <td className="py-2 pr-4 font-medium">{sample.expected_normalized_text}</td>
                                        <td className="py-2 pr-4">{sample.predicted_normalized_text}</td>
                                        <td className="py-2">{formatDecimal(sample.confidence)}</td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="rounded-[1.5rem] bg-[rgba(243,237,228,0.74)] p-5">
                    <div className="flex items-center justify-between gap-3">
                      <h3 className="text-xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">Rule Validation</h3>
                      <span className="rounded-full bg-[rgba(19,32,41,0.08)] px-3 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-[rgba(19,32,41,0.72)]">
                        {model.ruleItems.length} scenarios
                      </span>
                    </div>
                    {model.ruleItems.length === 0 ? (
                      <p className="mt-4 text-sm leading-6 text-[rgba(19,32,41,0.72)]">No rule scenarios match the current filters.{hasActiveFilters ? <> <Link href="/evaluation" className="underline underline-offset-2 hover:text-[var(--color-ink)]">Clear filters</Link></> : null}</p>
                    ) : (
                      <div className="mt-4 space-y-4">
                        {model.ruleItems.map((item) => (
                          <div key={`${item.artifactKey}:${item.scenarioName}`} className="rounded-[1.25rem] bg-[rgba(255,255,255,0.74)] p-4">
                            <div className="flex flex-wrap items-center justify-between gap-3">
                              <div>
                                <p className="font-semibold text-[var(--color-ink)]">{item.scenarioName}</p>
                                <p className="mt-1 text-sm text-[rgba(19,32,41,0.64)]">{item.artifactLabel} · {sourceKindLabel(item.sourceKind)}</p>
                              </div>
                              <p className="text-sm text-[rgba(19,32,41,0.6)]">Observed {formatTimestamp(item.observedAt ?? item.generatedAt)}</p>
                            </div>
                            <div className="mt-4 grid gap-3 sm:grid-cols-3">
                              <div><p className="text-xs uppercase tracking-[0.16em] text-[rgba(19,32,41,0.52)]">Expected-event match</p><p className="mt-1 text-lg font-semibold text-[var(--color-ink)]">{formatPercent(item.passRate)}</p></div>
                              <div><p className="text-xs uppercase tracking-[0.16em] text-[rgba(19,32,41,0.52)]">Missing expected</p><p className="mt-1 text-lg font-semibold text-[var(--color-ink)]">{item.missingCount}</p></div>
                              <div><p className="text-xs uppercase tracking-[0.16em] text-[rgba(19,32,41,0.52)]">Unexpected actual</p><p className="mt-1 text-lg font-semibold text-[var(--color-ink)]">{item.unexpectedCount}</p></div>
                            </div>
                            <p className="mt-3 text-sm leading-6 text-[rgba(19,32,41,0.72)]">
                              Matched {item.matchedCount} of {item.expectedCount} expected rule outcomes. The evaluator observed {item.actualCount} actual outcome(s) in this scenario.
                            </p>
                            {(item.missingKeys.length > 0 || item.unexpectedKeys.length > 0) ? (
                              <div className="mt-3 space-y-2 text-sm leading-6 text-[rgba(19,32,41,0.72)]">
                                {item.missingKeys.length > 0 ? <p>Missing: {item.missingKeys.join(", ")}</p> : null}
                                {item.unexpectedKeys.length > 0 ? <p>Unexpected: {item.unexpectedKeys.join(", ")}</p> : null}
                              </div>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="rounded-[1.5rem] bg-[rgba(243,237,228,0.74)] p-5 xl:col-span-2">
                    <div className="flex items-center justify-between gap-3">
                      <h3 className="text-xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">Signal Classification</h3>
                      <span className="rounded-full bg-[rgba(19,32,41,0.08)] px-3 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-[rgba(19,32,41,0.72)]">
                        {model.signalItems.length} scenarios
                      </span>
                    </div>
                    {model.signalItems.length === 0 ? (
                      <p className="mt-4 text-sm leading-6 text-[rgba(19,32,41,0.72)]">No signal-classification scenarios match the current filters.</p>
                    ) : (
                      <div className="mt-4 grid gap-4 lg:grid-cols-2">
                        {model.signalItems.map((item) => (
                          <div key={`${item.artifactKey}:${item.scenarioName}`} className="rounded-[1.25rem] bg-[rgba(255,255,255,0.74)] p-4">
                            <div className="flex flex-wrap items-center justify-between gap-3">
                              <div>
                                <p className="font-semibold text-[var(--color-ink)]">{item.scenarioName}</p>
                                <p className="mt-1 text-sm text-[rgba(19,32,41,0.64)]">{item.artifactLabel} · {sourceKindLabel(item.sourceKind)}</p>
                              </div>
                              <p className="text-sm text-[rgba(19,32,41,0.6)]">Observed {formatTimestamp(item.observedAt ?? item.generatedAt)}</p>
                            </div>
                            <div className="mt-4 grid gap-3 sm:grid-cols-3">
                              <div><p className="text-xs uppercase tracking-[0.16em] text-[rgba(19,32,41,0.52)]">Sample accuracy</p><p className="mt-1 text-lg font-semibold text-[var(--color-ink)]">{formatPercent(item.accuracy)}</p></div>
                              <div><p className="text-xs uppercase tracking-[0.16em] text-[rgba(19,32,41,0.52)]">Correct labels</p><p className="mt-1 text-lg font-semibold text-[var(--color-ink)]">{item.correctCount}/{item.sampleCount}</p></div>
                              <div><p className="text-xs uppercase tracking-[0.16em] text-[rgba(19,32,41,0.52)]">Confusion entries</p><p className="mt-1 text-lg font-semibold text-[var(--color-ink)]">{item.confusionPairs.length}</p></div>
                            </div>
                            {Object.keys(item.perClassAccuracy).length > 0 ? (
                              <p className="mt-3 text-sm leading-6 text-[rgba(19,32,41,0.72)]">
                                Per-class accuracy: {Object.entries(item.perClassAccuracy)
                                  .map(([color, value]) => `${color} ${formatPercent(value)}`)
                                  .join(", ")}
                              </p>
                            ) : null}
                            {item.confusionPairs.length > 0 ? (
                              <p className="mt-3 text-sm leading-6 text-[rgba(19,32,41,0.72)]">Confusion pairs: {item.confusionPairs.join(", ")}</p>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </section>

              <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-6 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">
                      Review Notes
                    </p>
                    <h2 className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">
                      Manual Review and Workflow Notes
                    </h2>
                  </div>
                  <span className="rounded-full bg-[rgba(226,176,71,0.18)] px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-[var(--color-warning-ink)]">
                    manual summaries
                  </span>
                </div>
                {model.manualReviewSummaries.length === 0 ? (
                  <p className="mt-5 text-sm leading-6 text-[rgba(19,32,41,0.72)]">
                    No stored report in the current result set includes manual review or workflow notes. The default benchmark test is measured-only.
                  </p>
                ) : (
                  <div className="mt-5 grid gap-4 lg:grid-cols-2">
                    {model.manualReviewSummaries.map((summary) => (
                      <div key={summary.artifact_key} className="rounded-[1.4rem] bg-[rgba(243,237,228,0.74)] p-4">
                        <div className="flex items-center justify-between gap-3">
                          <p className="font-semibold text-[var(--color-ink)]">{summary.artifact_label}</p>
                          <span className="rounded-full bg-[rgba(19,32,41,0.08)] px-3 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-[rgba(19,32,41,0.72)]">
                            {sourceKindLabel(summary.source_kind)}
                          </span>
                        </div>
                        {summary.manual_review_summary ? <p className="mt-3 text-sm leading-6 text-[rgba(19,32,41,0.74)]">{summary.manual_review_summary}</p> : null}
                        {summary.workflow_summary ? <p className="mt-3 text-sm leading-6 text-[rgba(19,32,41,0.74)]">{summary.workflow_summary}</p> : null}
                        {summary.notes.length > 0 ? <p className="mt-3 text-sm leading-6 text-[rgba(19,32,41,0.68)]">Notes: {summary.notes.join(" · ")}</p> : null}
                      </div>
                    ))}
                  </div>
                )}
              </section>

              {model.placeholders.length > 0 ? (
                <section className="rounded-[2rem] border border-dashed border-[rgba(23,57,69,0.14)] bg-[rgba(255,255,255,0.72)] p-6">
                  <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.44)]">
                    Additional Categories
                  </p>
                  <p className="mt-2 text-sm leading-6 text-[rgba(19,32,41,0.62)]">
                    Some evaluation categories do not have results in the current data set.
                  </p>
                  <div className="mt-4 grid gap-4 lg:grid-cols-2">
                    {model.placeholders.map((placeholder) => (
                      <EmptySection key={placeholder.key} title={placeholder.title} detail={placeholder.detail} />
                    ))}
                  </div>
                </section>
              ) : null}
            </>
          )}
        </div>

        <aside className="flex flex-col gap-5">
          <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-5 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
            <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Source inventory</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">Evaluation Sources</h2>
            <div className="mt-5 space-y-4">
              {model.sources.length === 0 ? (
                <p className="text-sm leading-6 text-[rgba(19,32,41,0.72)]">No evaluation sources are available for the current filter set.</p>
              ) : (
                model.sources.map((source) => (
                  <div key={source.artifactKey} className="rounded-[1.4rem] bg-[rgba(243,237,228,0.74)] p-4">
                    <div className="flex items-center justify-between gap-3">
                      <p className="font-semibold text-[var(--color-ink)]">{source.artifactLabel}</p>
                      <span className="rounded-full bg-[rgba(19,32,41,0.08)] px-3 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-[rgba(19,32,41,0.72)]">
                        {sourceKindLabel(source.sourceKind)}
                      </span>
                    </div>
                    <p className="mt-3 text-sm text-[rgba(19,32,41,0.68)]">Observed {formatTimestamp(source.observedAt ?? source.generatedAt)}</p>
                    <p className="mt-2 text-sm leading-6 text-[rgba(19,32,41,0.74)]">Scenario rows: {source.scenarioNames.length}</p>
                    {source.modelVersionNames.length > 0 ? (
                      <p className="mt-2 text-sm leading-6 text-[rgba(19,32,41,0.74)]">Versions: {source.modelVersionNames.join(", ")}</p>
                    ) : null}
                    {source.cameraLabels.length > 0 ? (
                      <p className="mt-2 text-sm leading-6 text-[rgba(19,32,41,0.74)]">Cameras: {source.cameraLabels.join(", ")}</p>
                    ) : null}
                    {source.taskTypes.length > 0 ? (
                      <p className="mt-2 text-sm leading-6 text-[rgba(19,32,41,0.74)]">Task types: {source.taskTypes.map(taskTypeLabel).join(", ")}</p>
                    ) : null}
                    {source.sourcePath ? (
                      <p className="mt-2 break-all font-mono text-xs leading-6 text-[rgba(19,32,41,0.58)]">{source.sourcePath}</p>
                    ) : null}
                    {source.notes.length > 0 ? (
                      <ul className="mt-3 space-y-1 text-sm leading-6 text-[rgba(19,32,41,0.72)]">
                        {source.notes.map((note) => (
                          <li key={note}>- {note}</li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                ))
              )}
            </div>
          </section>

          <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-5 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
            <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Interpretation notes</p>
            <div className="mt-4 space-y-3 text-sm leading-6 text-[rgba(19,32,41,0.74)]">
              {model.methodology.map((item) => (
                <p key={item}>{item}</p>
              ))}
            </div>
            {model.warnings.length > 0 ? (
              <div className="mt-5 rounded-[1.4rem] bg-[rgba(240,90,79,0.08)] p-4 text-sm leading-6 text-[rgba(128,41,35,0.9)]">
                <p className="text-[0.72rem] font-semibold uppercase tracking-[0.18em] text-[rgba(128,41,35,0.72)]">Warnings</p>
                <ul className="mt-3 space-y-2">
                  {model.warnings.map((warning) => (
                    <li key={warning}>- {warning}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </section>
        </aside>
      </section>

      {/* ── Evidence access preview (admin) ─────────────── */}
      <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-6 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
        <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Access Management</p>
        <h2 className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">Evidence Access Permissions</h2>
        <p className="mt-3 text-sm leading-6 text-[rgba(19,32,41,0.74)]">
          Select a role to preview what evidence and actions it can access. This is a read-only preview — actual permissions are enforced by the server.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          {EVIDENCE_ACCESS_ROLES.map((role) => {
            const isActive = role === accessRole;
            return (
              <Link
                key={role}
                href={`/evaluation?accessRole=${role}`}
                className={`rounded-full px-4 py-2 text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-[var(--color-ink)] text-[var(--color-paper)]"
                    : "border border-[rgba(23,57,69,0.14)] text-[var(--color-ink)] hover:border-[rgba(23,57,69,0.28)]"
                }`}
              >
                {accessRoleLabel(role)}
              </Link>
            );
          })}
        </div>
      </section>

      <EvidencePrivacyPolicyPreview
        policy={accessPolicy}
        selectedRole={accessRole}
        error={accessPolicyError}
      />
    </main>
  );
}