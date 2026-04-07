import Link from "next/link";

import { fetchExports } from "@/features/reports/api";
import type { CaseExportStatus, CaseExportSummary, CaseSubjectKind } from "@/features/reports/types";
import { formatTimestamp } from "@/features/operations/components/dashboard-primitives";
import { getSingleParam } from "@/features/operations/derive";
import { titleCase } from "@/features/shared/format-labels";

export const metadata = { title: "Reports | TrafficMind" };
export const dynamic = "force-dynamic";

const EXPORT_STATUSES: CaseExportStatus[] = ["pending", "completed", "failed"];
const SUBJECT_KINDS: CaseSubjectKind[] = ["violation_event", "detection_event", "watchlist_alert", "operational_alert"];

function coerce<T extends string>(value: string | null, allowed: readonly T[]): T | null {
  return value && (allowed as readonly string[]).includes(value) ? (value as T) : null;
}

function exportStatusLabel(status: string): string {
  const map: Record<string, string> = { pending: "Pending", completed: "Completed", failed: "Failed" };
  return map[status] ?? titleCase(status);
}

function subjectKindLabel(kind: string): string {
  const map: Record<string, string> = {
    violation_event: "Violation",
    detection_event: "Detection",
    watchlist_alert: "Watchlist alert",
    operational_alert: "Operational alert",
  };
  return map[kind] ?? titleCase(kind);
}

function exportFormatLabel(format: string): string {
  const map: Record<string, string> = { json: "JSON", markdown: "Markdown", zip_manifest: "ZIP manifest" };
  return map[format] ?? format.toUpperCase();
}

type ReportsPageProps = {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
};

export default async function ReportsPage({ searchParams }: ReportsPageProps) {
  const params = await searchParams;
  const statusFilter = coerce(getSingleParam(params.status), EXPORT_STATUSES);
  const subjectFilter = coerce(getSingleParam(params.subject), SUBJECT_KINDS);
  const page = Math.max(1, Number(getSingleParam(params.page)) || 1);
  const PAGE_SIZE = 30;

  const result = await fetchExports({
    status: statusFilter ?? undefined,
    subjectKind: subjectFilter ?? undefined,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  });

  const exports: CaseExportSummary[] = result.ok && result.data ? result.data.items : [];
  const total = result.ok && result.data ? result.data.total : 0;
  const live = result.ok && result.data !== null;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const hasActiveFilters = !!(statusFilter || subjectFilter);

  function buildFilterHref(overrides: Record<string, string | null>): string {
    const next = new URLSearchParams();
    const fields: Record<string, string | null> = {
      status: statusFilter,
      subject: subjectFilter,
      ...overrides,
    };
    if (!("page" in overrides)) fields.page = null;
    for (const [key, value] of Object.entries(fields)) {
      if (value) next.set(key, value);
    }
    const qs = next.toString();
    return qs ? `/reports?${qs}` : "/reports";
  }

  const chipClass = "rounded-full px-3 py-1.5 text-xs font-medium transition-colors";
  const activeChipClass = `${chipClass} bg-[var(--color-ink)] text-[var(--color-paper)]`;
  const inactiveChipClass = `${chipClass} border border-[rgba(23,57,69,0.14)] text-[var(--color-ink)] hover:border-[rgba(23,57,69,0.28)]`;

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-6xl flex-col gap-6 px-4 py-8 sm:px-6">
      {/* ── Hero ─────────────────────────────────────── */}
      <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[linear-gradient(135deg,rgba(244,238,224,0.94),rgba(231,242,244,0.92))] p-8 shadow-[0_24px_60px_rgba(18,32,41,0.08)]">
        <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Case Reports</p>
        <h1 className="mt-3 text-4xl font-semibold tracking-[-0.06em] text-[var(--color-ink)]">
          {live
            ? total > 0
              ? `${total} Export${total === 1 ? "" : "s"}`
              : "No Exports Yet"
            : "Reports Unavailable"}
        </h1>
        <p className="mt-4 max-w-3xl text-base leading-7 text-[rgba(19,32,41,0.74)]">
          {live
            ? total === 0 && !hasActiveFilters
              ? "Case exports appear here once generated. Exports package violation, detection, or alert data into structured bundles for audit and review."
              : total === 0
                ? "No exports match your current filters. Try clearing a filter to see more."
                : "Browse and download exported case bundles. Exports are created from violations, detections, and alerts for audit-ready evidence packaging."
            : "The export feed could not be reached. Try reloading the page, or check that the system is running."}
        </p>
        {hasActiveFilters ? (
          <div className="mt-6">
            <Link href="/reports" className="rounded-full bg-[rgba(23,57,69,0.08)] px-4 py-2 text-sm font-medium text-[var(--color-ink)] transition-colors hover:bg-[rgba(23,57,69,0.14)]">
              Clear all filters
            </Link>
          </div>
        ) : null}
      </section>

      {/* ── Filters ─────────────────────────────────────── */}
      <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-6 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
        <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Filter Exports</p>
        <div className="mt-4 space-y-4">
          <div>
            <p className="mb-2 text-xs font-medium text-[rgba(19,32,41,0.56)]">Status</p>
            <div className="flex flex-wrap gap-2">
              {EXPORT_STATUSES.map((s) => (
                <Link key={s} href={buildFilterHref({ status: statusFilter === s ? null : s })} className={statusFilter === s ? activeChipClass : inactiveChipClass}>
                  {exportStatusLabel(s)}
                </Link>
              ))}
            </div>
          </div>
          <div>
            <p className="mb-2 text-xs font-medium text-[rgba(19,32,41,0.56)]">Subject type</p>
            <div className="flex flex-wrap gap-2">
              {SUBJECT_KINDS.map((s) => (
                <Link key={s} href={buildFilterHref({ subject: subjectFilter === s ? null : s })} className={subjectFilter === s ? activeChipClass : inactiveChipClass}>
                  {subjectKindLabel(s)}
                </Link>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── Export list ──────────────────────────────────── */}
      {exports.length > 0 ? (
        <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-6 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Export History</p>
              <p className="mt-1 text-sm text-[rgba(19,32,41,0.62)]">{total} export{total === 1 ? "" : "s"}</p>
            </div>
            {totalPages > 1 ? (
              <div className="flex items-center gap-2 text-sm">
                {page > 1 ? (
                  <Link href={buildFilterHref({ page: String(page - 1) })} className="rounded-full border border-[rgba(23,57,69,0.14)] px-3 py-1 text-xs font-medium text-[var(--color-ink)] hover:border-[rgba(23,57,69,0.28)]">
                    ← Prev
                  </Link>
                ) : null}
                <span className="text-xs text-[rgba(19,32,41,0.56)]">{(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, total)} of {total}</span>
                {page < totalPages ? (
                  <Link href={buildFilterHref({ page: String(page + 1) })} className="rounded-full border border-[rgba(23,57,69,0.14)] px-3 py-1 text-xs font-medium text-[var(--color-ink)] hover:border-[rgba(23,57,69,0.28)]">
                    Next →
                  </Link>
                ) : null}
              </div>
            ) : null}
          </div>
          <div className="mt-4 divide-y divide-[rgba(23,57,69,0.08)]">
            {exports.map((ex) => (
              <div key={ex.id} className="flex items-start gap-4 py-4 first:pt-0 last:pb-0">
                <span className={`mt-1 inline-block rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] ${ex.status === "completed" ? "bg-[rgba(56,183,118,0.14)] text-[var(--color-ok-ink)]" : ex.status === "failed" ? "bg-[rgba(240,90,79,0.14)] text-[var(--color-danger)]" : "bg-[rgba(226,176,71,0.14)] text-[var(--color-warning-ink)]"}`}>
                  {exportStatusLabel(ex.status)}
                </span>
                <div className="flex-1">
                  <p className="font-semibold text-[var(--color-ink)]">{ex.filename}</p>
                  <p className="mt-1 text-sm text-[rgba(19,32,41,0.72)]">
                    {subjectKindLabel(ex.subject_kind)} · {exportFormatLabel(ex.export_format)} · v{ex.bundle_version}
                  </p>
                  <p className="mt-1 text-xs text-[rgba(19,32,41,0.5)]">
                    Created {formatTimestamp(ex.created_at)}
                    {ex.completed_at ? ` · Completed ${formatTimestamp(ex.completed_at)}` : null}
                    {ex.requested_by ? ` · By ${ex.requested_by}` : null}
                  </p>
                  {ex.error_message ? (
                    <p className="mt-1 text-xs text-[var(--color-danger)]">{ex.error_message}</p>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : live ? (
        <section className="rounded-[2rem] border border-dashed border-[rgba(23,57,69,0.18)] bg-[rgba(246,240,229,0.72)] p-6">
          <p className="text-sm font-semibold text-[var(--color-ink)]">No exports match your filters</p>
          <p className="mt-2 text-sm leading-6 text-[rgba(19,32,41,0.72)]">
            Exports are generated from case reviews and alert investigations. Once created, they appear here for download and audit.
          </p>
          {hasActiveFilters ? (
            <div className="mt-4">
              <Link href="/reports" className="rounded-full bg-[rgba(23,57,69,0.08)] px-4 py-2 text-sm font-medium text-[var(--color-ink)] transition-colors hover:bg-[rgba(23,57,69,0.14)]">
                Clear all filters
              </Link>
            </div>
          ) : null}
        </section>
      ) : null}
    </main>
  );
}
