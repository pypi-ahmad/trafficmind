import Link from "next/link";

import { AlertActions } from "@/app/alerts/alert-actions";
import { fetchAlerts } from "@/features/alerts/api";
import type { AlertSeverity, AlertSourceKind, AlertStatus, OperationalAlertSummary } from "@/features/alerts/types";
import { formatTimestamp } from "@/features/operations/components/dashboard-primitives";
import { getSingleParam } from "@/features/operations/derive";
import { severityLabel, titleCase } from "@/features/shared/format-labels";

export const metadata = { title: "Alerts | TrafficMind" };
export const dynamic = "force-dynamic";

const ALERT_STATUSES: AlertStatus[] = ["new", "acknowledged", "escalated", "resolved", "suppressed"];
const ALERT_SEVERITIES: AlertSeverity[] = ["critical", "high", "medium", "low", "info"];
const ALERT_SOURCES: AlertSourceKind[] = ["violation_event", "watchlist_alert", "camera_health", "stream_health", "workflow_backlog", "manual"];

function coerce<T extends string>(value: string | null, allowed: readonly T[]): T | null {
  return value && (allowed as readonly string[]).includes(value) ? (value as T) : null;
}

function alertStatusLabel(status: string): string {
  const map: Record<string, string> = {
    new: "New",
    acknowledged: "Acknowledged",
    escalated: "Escalated",
    resolved: "Resolved",
    suppressed: "Suppressed",
  };
  return map[status] ?? titleCase(status);
}

function alertSourceLabel(source: string): string {
  const map: Record<string, string> = {
    violation_event: "Violation",
    watchlist_alert: "Watchlist",
    camera_health: "Camera health",
    stream_health: "Stream health",
    workflow_backlog: "Workflow",
    manual: "Manual",
  };
  return map[source] ?? titleCase(source);
}

type AlertsPageProps = {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
};

export default async function AlertsPage({ searchParams }: AlertsPageProps) {
  const params = await searchParams;
  const statusFilter = coerce(getSingleParam(params.status), ALERT_STATUSES);
  const severityFilter = coerce(getSingleParam(params.severity), ALERT_SEVERITIES);
  const sourceFilter = coerce(getSingleParam(params.source), ALERT_SOURCES);
  const page = Math.max(1, Number(getSingleParam(params.page)) || 1);
  const PAGE_SIZE = 30;

  const result = await fetchAlerts({
    status: statusFilter ?? undefined,
    severity: severityFilter ?? undefined,
    sourceKind: sourceFilter ?? undefined,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  });

  const alerts: OperationalAlertSummary[] = result.ok && result.data ? result.data.items : [];
  const total = result.ok && result.data ? result.data.total : 0;
  const live = result.ok && result.data !== null;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const hasActiveFilters = !!(statusFilter || severityFilter || sourceFilter);

  function buildFilterHref(overrides: Record<string, string | null>): string {
    const next = new URLSearchParams();
    const fields: Record<string, string | null> = {
      status: statusFilter,
      severity: severityFilter,
      source: sourceFilter,
      ...overrides,
    };
    if (!("page" in overrides)) fields.page = null;
    for (const [key, value] of Object.entries(fields)) {
      if (value) next.set(key, value);
    }
    const qs = next.toString();
    return qs ? `/alerts?${qs}` : "/alerts";
  }

  const chipClass = "rounded-full px-3 py-1.5 text-xs font-medium transition-colors";
  const activeChipClass = `${chipClass} bg-[var(--color-ink)] text-[var(--color-paper)]`;
  const inactiveChipClass = `${chipClass} border border-[rgba(23,57,69,0.14)] text-[var(--color-ink)] hover:border-[rgba(23,57,69,0.28)]`;

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-6xl flex-col gap-6 px-4 py-8 sm:px-6">
      {/* ── Hero ─────────────────────────────────────── */}
      <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[linear-gradient(135deg,rgba(244,238,224,0.94),rgba(231,242,244,0.92))] p-8 shadow-[0_24px_60px_rgba(18,32,41,0.08)]">
        <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Operational Alerts</p>
        <h1 className="mt-3 text-4xl font-semibold tracking-[-0.06em] text-[var(--color-ink)]">
          {live
            ? total > 0
              ? `${total} Alert${total === 1 ? "" : "s"}`
              : "No Alerts"
            : "Alerts Unavailable"}
        </h1>
        <p className="mt-4 max-w-3xl text-base leading-7 text-[rgba(19,32,41,0.74)]">
          {live
            ? total === 0 && !hasActiveFilters
              ? "All clear — no alerts have been raised. Alerts are generated when policy rules detect notable conditions such as violations, health issues, or watchlist hits."
              : total === 0
                ? "No alerts match your current filters. Try clearing a filter to see more."
                : "Review and manage operational alerts raised by system policies. Alerts track violations, health issues, watchlist hits, and other notable conditions."
            : "The alert feed could not be reached. Try reloading the page, or check that the system is running."}
        </p>
        {hasActiveFilters ? (
          <div className="mt-6">
            <Link href="/alerts" className="rounded-full bg-[rgba(23,57,69,0.08)] px-4 py-2 text-sm font-medium text-[var(--color-ink)] transition-colors hover:bg-[rgba(23,57,69,0.14)]">
              Clear all filters
            </Link>
          </div>
        ) : null}
      </section>

      {/* ── Filters ─────────────────────────────────────── */}
      <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-6 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
        <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Filter Alerts</p>
        <div className="mt-4 space-y-4">
          <div>
            <p className="mb-2 text-xs font-medium text-[rgba(19,32,41,0.56)]">Status</p>
            <div className="flex flex-wrap gap-2">
              {ALERT_STATUSES.map((s) => (
                <Link key={s} href={buildFilterHref({ status: statusFilter === s ? null : s })} className={statusFilter === s ? activeChipClass : inactiveChipClass}>
                  {alertStatusLabel(s)}
                </Link>
              ))}
            </div>
          </div>
          <div>
            <p className="mb-2 text-xs font-medium text-[rgba(19,32,41,0.56)]">Severity</p>
            <div className="flex flex-wrap gap-2">
              {ALERT_SEVERITIES.map((s) => (
                <Link key={s} href={buildFilterHref({ severity: severityFilter === s ? null : s })} className={severityFilter === s ? activeChipClass : inactiveChipClass}>
                  {severityLabel(s)}
                </Link>
              ))}
            </div>
          </div>
          <div>
            <p className="mb-2 text-xs font-medium text-[rgba(19,32,41,0.56)]">Source</p>
            <div className="flex flex-wrap gap-2">
              {ALERT_SOURCES.map((s) => (
                <Link key={s} href={buildFilterHref({ source: sourceFilter === s ? null : s })} className={sourceFilter === s ? activeChipClass : inactiveChipClass}>
                  {alertSourceLabel(s)}
                </Link>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── Alert list ──────────────────────────────────── */}
      {alerts.length > 0 ? (
        <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-6 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Alert Feed</p>
              <p className="mt-1 text-sm text-[rgba(19,32,41,0.62)]">{total} alert{total === 1 ? "" : "s"} matching filters</p>
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
            {alerts.map((a) => (
              <div key={a.id} className="flex items-start gap-4 py-4 first:pt-0 last:pb-0">
                <span className={`mt-1 inline-block rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] ${a.severity === "critical" || a.severity === "high" ? "bg-[rgba(240,90,79,0.14)] text-[var(--color-danger)]" : a.severity === "medium" ? "bg-[rgba(226,176,71,0.16)] text-[var(--color-warning-ink)]" : "bg-[rgba(56,183,118,0.14)] text-[var(--color-ok-ink)]"}`}>
                  {severityLabel(a.severity)}
                </span>
                <div className="flex-1">
                  <p className="font-semibold text-[var(--color-ink)]">{a.title}</p>
                  {a.summary ? <p className="mt-1 text-sm text-[rgba(19,32,41,0.72)]">{a.summary}</p> : null}
                  <p className="mt-1 text-xs text-[rgba(19,32,41,0.5)]">
                    {formatTimestamp(a.occurred_at)} · {alertStatusLabel(a.status)} · {alertSourceLabel(a.source_kind)}
                    {a.occurrence_count > 1 ? ` · ${a.occurrence_count} occurrences` : null}
                    {a.acknowledged_by ? ` · Acked by ${a.acknowledged_by}` : null}
                  </p>
                  <div className="mt-2">
                    <AlertActions alertId={a.id} currentStatus={a.status} />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : live ? (
        <section className="rounded-[2rem] border border-dashed border-[rgba(23,57,69,0.18)] bg-[rgba(246,240,229,0.72)] p-6">
          <p className="text-sm font-semibold text-[var(--color-ink)]">No alerts match your filters</p>
          <p className="mt-2 text-sm leading-6 text-[rgba(19,32,41,0.72)]">
            Try clearing a filter to widen the results, or check back later.
          </p>
          {hasActiveFilters ? (
            <div className="mt-4">
              <Link href="/alerts" className="rounded-full bg-[rgba(23,57,69,0.08)] px-4 py-2 text-sm font-medium text-[var(--color-ink)] transition-colors hover:bg-[rgba(23,57,69,0.14)]">
                Clear all filters
              </Link>
            </div>
          ) : null}
        </section>
      ) : null}
    </main>
  );
}
