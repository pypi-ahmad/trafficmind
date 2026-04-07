import Link from "next/link";

import { ViolationActions } from "@/app/cases/violation-actions";
import { fetchCameraDetail, fetchEventsFeed, fetchViolationsFeed, fetchEventSummaryTotals, fetchViolationSummaryTotals } from "@/features/operations/api";
import { formatTimestamp } from "@/features/operations/components/dashboard-primitives";
import { buildCaseFeedHref, getSingleParam } from "@/features/operations/derive";
import { violationTypeLabel, violationStatusLabel, eventStatusLabel, eventTypeLabel, titleCase, severityLabel } from "@/features/shared/format-labels";
import type { DetectionEventReadApi, DetectionEventStatus, ViolationEventReadApi, ViolationStatus, ViolationTypeName } from "@/features/operations/types";

export const metadata = { title: "Cases | TrafficMind" };
export const dynamic = "force-dynamic";

const PAGE_SIZE = 20;
const VIOLATION_TYPES: ViolationTypeName[] = ["red_light", "speeding", "illegal_turn", "stop_line", "wrong_way", "illegal_parking", "no_stopping", "pedestrian_conflict", "bus_stop_violation", "stalled_vehicle"];
const VIOLATION_STATUSES: ViolationStatus[] = ["open", "under_review", "confirmed", "dismissed"];
const EVENT_STATUSES: DetectionEventStatus[] = ["new", "enriched", "suppressed"];
const TIME_PRESETS = [
  { key: "1h", label: "Last hour", hours: 1 },
  { key: "24h", label: "Last 24h", hours: 24 },
  { key: "7d", label: "Last 7 days", hours: 168 },
  { key: "30d", label: "Last 30 days", hours: 720 },
] as const;
type TimePresetKey = typeof TIME_PRESETS[number]["key"];

function coerce<T extends string>(value: string | null, allowed: readonly T[]): T | null {
  return value && (allowed as readonly string[]).includes(value) ? (value as T) : null;
}

type CasesPageProps = {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
};

export default async function CasesPage({ searchParams }: CasesPageProps) {
  const params = await searchParams;
  const cameraId = getSingleParam(params.cameraId);
  const junctionId = getSingleParam(params.junctionId);

  // Filter params from URL
  const violationType = coerce(getSingleParam(params.violationType), VIOLATION_TYPES);
  const violationStatus = coerce(getSingleParam(params.violationStatus), VIOLATION_STATUSES);
  const eventStatus = coerce(getSingleParam(params.eventStatus), EVENT_STATUSES);
  const timePreset = coerce(getSingleParam(params.timePreset), TIME_PRESETS.map((p) => p.key) as TimePresetKey[]);
  const occurredBefore = getSingleParam(params.occurredBefore);
  const now = new Date();
  // Derive occurredAfter from the stable preset key, falling back to explicit param
  const occurredAfter = timePreset
    ? new Date(now.getTime() - TIME_PRESETS.find((p) => p.key === timePreset)!.hours * 3_600_000).toISOString()
    : getSingleParam(params.occurredAfter);
  const eventsPage = Math.max(1, Number(getSingleParam(params.eventsPage)) || 1);
  const violationsPage = Math.max(1, Number(getSingleParam(params.violationsPage)) || 1);

  const [eventsResult, violationsResult, cameraResult, eventTotals, violationTotals] = await Promise.all([
    fetchEventsFeed({
      limit: PAGE_SIZE,
      offset: (eventsPage - 1) * PAGE_SIZE,
      cameraId,
      status: eventStatus,
      occurredAfter,
      occurredBefore,
    }),
    fetchViolationsFeed({
      limit: PAGE_SIZE,
      offset: (violationsPage - 1) * PAGE_SIZE,
      cameraId,
      violationType,
      status: violationStatus,
      occurredAfter,
      occurredBefore,
    }),
    cameraId ? fetchCameraDetail(cameraId) : Promise.resolve(null),
    fetchEventSummaryTotals({
      cameraId,
      occurredAfter: occurredAfter ?? undefined,
      occurredBefore: occurredBefore ?? undefined,
    }),
    fetchViolationSummaryTotals({
      cameraId,
      occurredAfter: occurredAfter ?? undefined,
      occurredBefore: occurredBefore ?? undefined,
    }),
  ]);

  const selectedCamera = cameraResult && cameraResult.ok ? cameraResult.data : null;
  const events: DetectionEventReadApi[] = eventsResult.ok && eventsResult.data ? eventsResult.data.items : [];
  const violations: ViolationEventReadApi[] = violationsResult.ok && violationsResult.data ? violationsResult.data.items : [];
  const eventsTotal = eventsResult.ok && eventsResult.data ? eventsResult.data.total : 0;
  const violationsTotal = violationsResult.ok && violationsResult.data ? violationsResult.data.total : 0;
  const eventsLive = eventsResult.ok && eventsResult.data !== null;
  const violationsLive = violationsResult.ok && violationsResult.data !== null;

  const eventsTotalPages = Math.max(1, Math.ceil(eventsTotal / PAGE_SIZE));
  const violationsTotalPages = Math.max(1, Math.ceil(violationsTotal / PAGE_SIZE));

  const evTotals = eventTotals.ok && eventTotals.data ? eventTotals.data : null;
  const viTotals = violationTotals.ok && violationTotals.data ? violationTotals.data : null;

  function buildFilterHref(overrides: Record<string, string | null>): string {
    const next = new URLSearchParams();
    if (cameraId) next.set("cameraId", cameraId);
    if (junctionId) next.set("junctionId", junctionId);

    const fields: Record<string, string | null> = {
      violationType: violationType,
      violationStatus: violationStatus,
      eventStatus: eventStatus,
      timePreset: timePreset,
      occurredAfter: timePreset ? null : occurredAfter,
      occurredBefore: occurredBefore,
      ...overrides,
    };

    // Reset pagination when filters change (unless pagination itself is changing)
    if (!("eventsPage" in overrides)) fields.eventsPage = null;
    if (!("violationsPage" in overrides)) fields.violationsPage = null;

    for (const [key, value] of Object.entries(fields)) {
      if (value) next.set(key, value);
    }
    return `/cases?${next.toString()}`;
  }

  const hasActiveFilters = !!(violationType || violationStatus || eventStatus || timePreset || occurredAfter || occurredBefore);
  const chipClass = "rounded-full px-3 py-1.5 text-xs font-medium transition-colors";
  const activeChipClass = `${chipClass} bg-[var(--color-ink)] text-[var(--color-paper)]`;
  const inactiveChipClass = `${chipClass} border border-[rgba(23,57,69,0.14)] text-[var(--color-ink)] hover:border-[rgba(23,57,69,0.28)]`;

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-6xl flex-col gap-6 px-4 py-8 sm:px-6">
      {selectedCamera ? (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <Link href={`/cameras/${selectedCamera.id}`} className="rounded-full border border-[rgba(23,57,69,0.14)] px-4 py-2 font-medium text-[var(--color-ink)] transition-colors hover:border-[rgba(23,57,69,0.28)]">
            Camera details
          </Link>
        </div>
      ) : null}

      <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[linear-gradient(135deg,rgba(244,238,224,0.94),rgba(231,242,244,0.92))] p-8 shadow-[0_24px_60px_rgba(18,32,41,0.08)]">
        <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Case Review</p>
        <h1 className="mt-3 text-4xl font-semibold tracking-[-0.06em] text-[var(--color-ink)]">
          {violationsLive
            ? selectedCamera
              ? `Cases for ${selectedCamera.name}`
              : violationsTotal > 0
                ? `${violationsTotal} Case${violationsTotal === 1 ? "" : "s"} to Review`
                : "No Open Cases"
            : eventsLive
              ? "Detection Activity"
              : "Case Review Unavailable"}
        </h1>
        <p className="mt-4 max-w-3xl text-base leading-7 text-[rgba(19,32,41,0.74)]">
          {violationsLive || eventsLive
            ? selectedCamera
              ? `Showing violations and detections for ${selectedCamera.name} at ${selectedCamera.location_name}. Clear the camera filter to see all cases.`
              : violationsTotal === 0 && violationsLive
                ? "All clear — no violations match your current filters. Try a wider time window or clear filters to check other cases."
                : "Review flagged violations, update case status, and drill into supporting detections. Use the filters below to focus on what needs attention."
            : "The case review feeds could not be reached. Try reloading the page, or check that the system is running."}
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          {cameraId ? (
            <Link href={buildFilterHref({ cameraId: null } as Record<string, string | null>).replace("cameraId=", "")} className="rounded-full bg-[rgba(23,57,69,0.08)] px-4 py-2 text-sm font-medium text-[var(--color-ink)] transition-colors hover:bg-[rgba(23,57,69,0.14)]">
              Clear camera filter
            </Link>
          ) : null}
          {cameraId ? <span className="rounded-full bg-[rgba(255,255,255,0.72)] px-4 py-2 text-sm font-medium text-[var(--color-ink)]">Camera: {selectedCamera?.name ?? cameraId}</span> : null}
          {junctionId ? <span className="rounded-full bg-[rgba(255,255,255,0.72)] px-4 py-2 text-sm font-medium text-[var(--color-ink)]">Intersection: {junctionId}</span> : null}
          {hasActiveFilters ? (
            <Link href={buildCaseFeedHref({ cameraId: cameraId ?? undefined, junctionId: junctionId ?? undefined })} className="rounded-full bg-[rgba(23,57,69,0.08)] px-4 py-2 text-sm font-medium text-[var(--color-ink)] transition-colors hover:bg-[rgba(23,57,69,0.14)]">
              Clear all filters
            </Link>
          ) : null}
        </div>
      </section>

      {/* ── Filters ─────────────────────────────────────── */}
      <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-6 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
        <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Narrow Your Cases</p>

        <div className="mt-4 space-y-4">
          <div>
            <p className="mb-2 text-xs font-medium text-[rgba(19,32,41,0.56)]">Time window</p>
            <div className="flex flex-wrap gap-2">
              {TIME_PRESETS.map((preset) => {
                const isActive = timePreset === preset.key;
                return (
                  <Link key={preset.key} href={buildFilterHref({ timePreset: isActive ? null : preset.key, occurredAfter: null, occurredBefore: null })} className={isActive ? activeChipClass : inactiveChipClass}>
                    {preset.label}
                  </Link>
                );
              })}
            </div>
          </div>

          <div>
            <p className="mb-2 text-xs font-medium text-[rgba(19,32,41,0.56)]">Case type</p>
            <div className="flex flex-wrap items-start gap-x-6 gap-y-3">
              <div>
                <p className="mb-1.5 text-[0.65rem] font-medium uppercase tracking-[0.14em] text-[rgba(19,32,41,0.38)]">Signal &amp; Speed</p>
                <div className="flex flex-wrap gap-2">
                  {(["red_light", "stop_line", "speeding"] as const).map((vt) => (
                    <Link key={vt} href={buildFilterHref({ violationType: violationType === vt ? null : vt })} className={violationType === vt ? activeChipClass : inactiveChipClass}>
                      {violationTypeLabel(vt)}
                    </Link>
                  ))}
                </div>
              </div>
              <div>
                <p className="mb-1.5 text-[0.65rem] font-medium uppercase tracking-[0.14em] text-[rgba(19,32,41,0.38)]">Movement &amp; Safety</p>
                <div className="flex flex-wrap gap-2">
                  {(["illegal_turn", "wrong_way", "pedestrian_conflict"] as const).map((vt) => (
                    <Link key={vt} href={buildFilterHref({ violationType: violationType === vt ? null : vt })} className={violationType === vt ? activeChipClass : inactiveChipClass}>
                      {violationTypeLabel(vt)}
                    </Link>
                  ))}
                </div>
              </div>
              <div>
                <p className="mb-1.5 text-[0.65rem] font-medium uppercase tracking-[0.14em] text-[rgba(19,32,41,0.38)]">Parking &amp; Stopping</p>
                <div className="flex flex-wrap gap-2">
                  {(["illegal_parking", "no_stopping", "bus_stop_violation", "stalled_vehicle"] as const).map((vt) => (
                    <Link key={vt} href={buildFilterHref({ violationType: violationType === vt ? null : vt })} className={violationType === vt ? activeChipClass : inactiveChipClass}>
                      {violationTypeLabel(vt)}
                    </Link>
                  ))}
                </div>
              </div>
            </div>
          </div>

          <div className="flex flex-wrap gap-6">
            <div>
              <p className="mb-2 text-xs font-medium text-[rgba(19,32,41,0.56)]">Case status</p>
              <div className="flex flex-wrap gap-2">
                {VIOLATION_STATUSES.map((vs) => (
                  <Link key={vs} href={buildFilterHref({ violationStatus: violationStatus === vs ? null : vs })} className={violationStatus === vs ? activeChipClass : inactiveChipClass}>
                    {violationStatusLabel(vs)}
                  </Link>
                ))}
              </div>
            </div>
            <div>
              <p className="mb-2 text-xs font-medium text-[rgba(19,32,41,0.56)]">Detection status</p>
              <div className="flex flex-wrap gap-2">
                {EVENT_STATUSES.map((es) => (
                  <Link key={es} href={buildFilterHref({ eventStatus: eventStatus === es ? null : es })} className={eventStatus === es ? activeChipClass : inactiveChipClass}>
                    {eventStatusLabel(es)}
                  </Link>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Summary stats ─────────────────────────────────── */}
      <section className="grid gap-6 lg:grid-cols-2">
        <div className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-6 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
          <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Violations to Review</p>
          <p className="mt-3 text-2xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">
            {violationsLive ? `${violationsTotal} case${violationsTotal === 1 ? "" : "s"}` : (violationsResult.status ? "Service error — try again shortly" : "Cannot reach server")}
          </p>
          {viTotals ? (
            <div className="mt-3 space-y-2">
              <div className="flex flex-wrap gap-2">
                {Object.entries(viTotals.by_severity).map(([key, count]) => (
                  <span key={key} className={`rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[0.12em] ${key === "critical" || key === "high" ? "bg-[rgba(240,90,79,0.12)] text-[var(--color-danger)]" : key === "medium" ? "bg-[rgba(226,176,71,0.14)] text-[var(--color-warning-ink)]" : "bg-[rgba(56,183,118,0.12)] text-[var(--color-ok-ink)]"}`}>
                    {severityLabel(key)}: {count}
                  </span>
                ))}
              </div>
              <div className="flex flex-wrap gap-2">
                {Object.entries(viTotals.by_status).map(([key, count]) => (
                  <span key={key} className="rounded-full bg-[rgba(23,57,69,0.06)] px-3 py-1 text-xs font-medium text-[rgba(19,32,41,0.72)]">
                    {violationStatusLabel(key)}: {count}
                  </span>
                ))}
              </div>
            </div>
          ) : null}
          <p className="mt-3 text-sm leading-6 text-[rgba(19,32,41,0.74)]">
            {violationsLive
              ? `Showing ${violations.length} of ${violationsTotal} (page ${violationsPage}/${violationsTotalPages}).`
              : violationsResult.error ?? "The violations feed could not be reached."}
          </p>
        </div>
        <div className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-6 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
          <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Supporting Detections</p>
          <p className="mt-3 text-2xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">
            {eventsLive ? `${eventsTotal} detection${eventsTotal === 1 ? "" : "s"}` : (eventsResult.status ? "Service error — try again shortly" : "Cannot reach server")}
          </p>
          {evTotals ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {Object.entries(evTotals.by_status).map(([key, count]) => (
                <span key={key} className="rounded-full bg-[rgba(23,57,69,0.06)] px-3 py-1 text-xs font-medium text-[rgba(19,32,41,0.72)]">
                  {eventStatusLabel(key)}: {count}
                </span>
              ))}
            </div>
          ) : null}
          <p className="mt-3 text-sm leading-6 text-[rgba(19,32,41,0.74)]">
            {eventsLive
              ? `Camera detections that support the cases above (page ${eventsPage}/${eventsTotalPages}).`
              : eventsResult.error ?? "The detection feed could not be reached."}
          </p>
        </div>
      </section>

      {violations.length > 0 ? (
        <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-6 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Review Queue</p>
              <p className="mt-1 text-sm text-[rgba(19,32,41,0.62)]">{violationsTotal} violation{violationsTotal === 1 ? "" : "s"} matching current filters</p>
            </div>
            {violationsTotalPages > 1 ? (
              <div className="flex items-center gap-2 text-sm">
                {violationsPage > 1 ? (
                  <Link href={buildFilterHref({ violationsPage: String(violationsPage - 1) })} className="rounded-full border border-[rgba(23,57,69,0.14)] px-3 py-1 text-xs font-medium text-[var(--color-ink)] hover:border-[rgba(23,57,69,0.28)]">
                    ← Prev
                  </Link>
                ) : null}
                <span className="text-xs text-[rgba(19,32,41,0.56)]">{(violationsPage - 1) * PAGE_SIZE + 1}–{Math.min(violationsPage * PAGE_SIZE, violationsTotal)} of {violationsTotal}</span>
                {violationsPage < violationsTotalPages ? (
                  <Link href={buildFilterHref({ violationsPage: String(violationsPage + 1) })} className="rounded-full border border-[rgba(23,57,69,0.14)] px-3 py-1 text-xs font-medium text-[var(--color-ink)] hover:border-[rgba(23,57,69,0.28)]">
                    Next →
                  </Link>
                ) : null}
              </div>
            ) : null}
          </div>
          <div className="mt-4 divide-y divide-[rgba(23,57,69,0.08)]">
            {violations.map((v) => (
              <div key={v.id} className="flex items-start gap-4 py-4 first:pt-0 last:pb-0">
                <span className={`mt-1 inline-block rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] ${v.severity === "critical" ? "bg-[rgba(240,90,79,0.14)] text-[var(--color-danger)]" : v.severity === "high" ? "bg-[rgba(240,90,79,0.10)] text-[var(--color-danger)]" : v.severity === "medium" ? "bg-[rgba(226,176,71,0.16)] text-[var(--color-warning-ink)]" : "bg-[rgba(56,183,118,0.14)] text-[var(--color-ok-ink)]"}`}>
                  {severityLabel(v.severity)}
                </span>
                <div className="flex-1">
                  <p className="font-semibold text-[var(--color-ink)]">{violationTypeLabel(v.violation_type)}</p>
                  <p className="mt-1 text-sm text-[rgba(19,32,41,0.72)]">{v.summary ?? "No summary available"}</p>
                  <p className="mt-1 text-xs text-[rgba(19,32,41,0.5)]">
                    {formatTimestamp(v.occurred_at)} · {violationStatusLabel(v.status)}
                    {v.assigned_to ? ` · Assigned: ${v.assigned_to}` : null}
                    {v.reviewed_by ? ` · Reviewed by ${v.reviewed_by}` : null}
                  </p>
                  <div className="mt-2">
                    <ViolationActions violationId={v.id} currentStatus={v.status} />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : violationsLive ? (
        <section className="rounded-[2rem] border border-dashed border-[rgba(23,57,69,0.18)] bg-[rgba(246,240,229,0.72)] p-6">
          <p className="text-sm font-semibold text-[var(--color-ink)]">No violations match your filters</p>
          <p className="mt-2 text-sm leading-6 text-[rgba(19,32,41,0.72)]">
            Try widening the time window, changing the case type, or clearing all filters to see the full queue.
          </p>
          {hasActiveFilters ? (
            <div className="mt-4">
              <Link href={buildCaseFeedHref({ cameraId: cameraId ?? undefined, junctionId: junctionId ?? undefined })} className="rounded-full bg-[rgba(23,57,69,0.08)] px-4 py-2 text-sm font-medium text-[var(--color-ink)] transition-colors hover:bg-[rgba(23,57,69,0.14)]">
                Clear all filters
              </Link>
            </div>
          ) : null}
        </section>
      ) : null}

      {events.length > 0 ? (
        <details className="group">
          <summary className="cursor-pointer rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-6 shadow-[0_18px_40px_rgba(18,32,41,0.06)] list-none">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Supporting Detections</p>
                <p className="mt-1 text-sm text-[rgba(19,32,41,0.62)]">{eventsTotal} camera detection{eventsTotal === 1 ? "" : "s"} — expand to inspect</p>
              </div>
              <span className="text-sm text-[rgba(19,32,41,0.5)] group-open:hidden">Show ▸</span>
              <span className="hidden text-sm text-[rgba(19,32,41,0.5)] group-open:inline">Hide ▾</span>
            </div>
          </summary>
          <div className="mt-4 rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-6 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
            <div className="flex items-center justify-between">
              <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Detections</p>
            {eventsTotalPages > 1 ? (
              <div className="flex items-center gap-2 text-sm">
                {eventsPage > 1 ? (
                  <Link href={buildFilterHref({ eventsPage: String(eventsPage - 1) })} className="rounded-full border border-[rgba(23,57,69,0.14)] px-3 py-1 text-xs font-medium text-[var(--color-ink)] hover:border-[rgba(23,57,69,0.28)]">
                    ← Prev
                  </Link>
                ) : null}
                <span className="text-xs text-[rgba(19,32,41,0.56)]">{(eventsPage - 1) * PAGE_SIZE + 1}–{Math.min(eventsPage * PAGE_SIZE, eventsTotal)} of {eventsTotal}</span>
                {eventsPage < eventsTotalPages ? (
                  <Link href={buildFilterHref({ eventsPage: String(eventsPage + 1) })} className="rounded-full border border-[rgba(23,57,69,0.14)] px-3 py-1 text-xs font-medium text-[var(--color-ink)] hover:border-[rgba(23,57,69,0.28)]">
                    Next →
                  </Link>
                ) : null}
              </div>
            ) : null}
          </div>
          <div className="mt-4 divide-y divide-[rgba(23,57,69,0.08)]">
            {events.map((e) => (
              <div key={e.id} className="flex items-start gap-4 py-4 first:pt-0 last:pb-0">
                <span className="mt-1 inline-block rounded-full bg-[rgba(56,183,118,0.14)] px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-[var(--color-ok-ink)]">
                  {titleCase(e.object_class)}
                </span>
                <div className="flex-1">
                  <p className="font-semibold text-[var(--color-ink)]">{eventTypeLabel(e.event_type)}</p>
                  <p className="mt-1 text-xs text-[rgba(19,32,41,0.5)]">
                    {formatTimestamp(e.occurred_at)} · {eventStatusLabel(e.status)}
                  </p>
                </div>
              </div>
            ))}
          </div>
          </div>
        </details>
      ) : eventsLive ? (
        <section className="rounded-[2rem] border border-dashed border-[rgba(23,57,69,0.18)] bg-[rgba(246,240,229,0.72)] p-6">
          <p className="text-sm font-semibold text-[var(--color-ink)]">No supporting detections</p>
          <p className="mt-2 text-sm leading-6 text-[rgba(19,32,41,0.72)]">
            No camera detections were found for the current filter set. Detections appear here as cameras report activity.
          </p>
        </section>
      ) : null}

      {selectedCamera ? (
        <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-6 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
          <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Filtered by Camera</p>
          <h2 className="mt-3 text-2xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">{selectedCamera.name}</h2>
          <p className="mt-3 text-sm leading-6 text-[rgba(19,32,41,0.74)]">
            Cases above are scoped to this camera. Clear the filter to see all cases, or view full camera details.
          </p>
          <div className="mt-5 flex flex-wrap gap-3 text-sm">
            <Link href={buildCaseFeedHref({ cameraId: selectedCamera.id, junctionId: junctionId ?? undefined })} className="rounded-full border border-[rgba(23,57,69,0.14)] px-4 py-2 font-medium text-[var(--color-ink)] transition-colors hover:border-[rgba(23,57,69,0.28)]">
              Keep current filters
            </Link>
            <Link href={`/cameras/${selectedCamera.id}`} className="rounded-full border border-[rgba(23,57,69,0.14)] px-4 py-2 font-medium text-[var(--color-ink)] transition-colors hover:border-[rgba(23,57,69,0.28)]">
              Camera details
            </Link>
          </div>
        </section>
      ) : null}
    </main>
  );
}