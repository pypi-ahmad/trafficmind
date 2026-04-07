import Link from "next/link";

import {
  availabilityClass,
  availabilityLabel,
  formatTimestamp,
  statusClass,
} from "@/features/operations/components/dashboard-primitives";
import { violationTypeLabel, eventTypeLabel, titleCase, cameraStatusLabel, severityLabel } from "@/features/shared/format-labels";
import type { SpatialOperationsModel } from "@/features/operations/types";

const actionLinkClass =
  "rounded-full border border-[rgba(23,57,69,0.14)] px-4 py-2 text-sm font-medium text-[var(--color-ink)] transition-colors hover:border-[rgba(23,57,69,0.28)]";

export function OperationsActivityPanels({ model }: { model: SpatialOperationsModel }) {
  return (
    <section className="grid gap-6 xl:grid-cols-[minmax(0,1.08fr)_minmax(0,0.92fr)]">
      <div className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.78)] p-5 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-[0.72rem] font-semibold uppercase tracking-[0.22em] text-[rgba(19,32,41,0.56)]">
              Incidents
            </p>
            <h2 className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">
              Top Incidents by Location
            </h2>
          </div>
          <Link href="/cases" className={actionLinkClass}>
            View all incidents
          </Link>
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-2">
          {model.incidentSummaries.map((summary) => (
            <div key={summary.id} className="rounded-[1.5rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(243,237,228,0.72)] p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <span className={`inline-flex rounded-full px-3 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.16em] ${availabilityClass(summary.availability)}`}>
                    {availabilityLabel(summary.availability)}
                  </span>
                  <p className="mt-3 text-lg font-semibold text-[var(--color-ink)]">{summary.title}</p>
                </div>
                <div className="text-right">
                  <p className="text-[0.68rem] uppercase tracking-[0.16em] text-[rgba(19,32,41,0.54)]">Incidents</p>
                  <p className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">
                    {summary.incidentCount ?? "--"}
                  </p>
                </div>
              </div>
              <p className="mt-3 text-sm leading-6 text-[rgba(19,32,41,0.72)]">{summary.note}</p>
              {summary.trendLabel ? (
                <p className="mt-2 text-xs uppercase tracking-[0.16em] text-[rgba(19,32,41,0.54)]">{summary.trendLabel}</p>
              ) : null}
              <div className="mt-4 flex flex-wrap gap-2 text-sm">
                <Link href={summary.dashboardHref} className={actionLinkClass}>
                  Show on map
                </Link>
                <Link href={summary.eventFeedHref} className={actionLinkClass}>
                  View incidents
                </Link>
                {summary.cameraDetailHref ? (
                  <Link href={summary.cameraDetailHref} className={actionLinkClass}>
                    Camera details
                  </Link>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.78)] p-5 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
        <p className="text-[0.72rem] font-semibold uppercase tracking-[0.22em] text-[rgba(19,32,41,0.56)]">
          Cameras
        </p>
        <h2 className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">Camera Fleet</h2>
        <div className="mt-5 space-y-3">
          {model.cameras.length > 0 ? model.cameras.map((camera) => {
            const isSelected = camera.id === model.selectedCamera?.id;
            return (
              <div
                key={camera.id}
                className={`rounded-[1.5rem] border bg-[rgba(243,237,228,0.72)] p-4 ${isSelected ? "border-[rgba(244,149,72,0.44)] shadow-[0_0_0_3px_rgba(244,149,72,0.12)]" : "border-[rgba(23,57,69,0.12)]"}`}
              >
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <div className="flex flex-wrap items-center gap-3">
                      <p className="font-semibold text-[var(--color-ink)]">{camera.name}</p>
                      <span className={`rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] ${statusClass(camera.status)}`}>
                        {cameraStatusLabel(camera.status)}
                      </span>
                    </div>
                    <p className="mt-2 text-sm text-[rgba(19,32,41,0.72)]">{camera.locationName}</p>
                  </div>
                  <div className="grid gap-1 text-sm text-[rgba(19,32,41,0.68)] sm:text-right">
                    <span>{camera.coordinates ? `${camera.coordinates.latitude.toFixed(3)}, ${camera.coordinates.longitude.toFixed(3)}` : "No coordinates"}</span>
                    <span>{camera.streamCount} stream{camera.streamCount === 1 ? "" : "s"}</span>
                  </div>
                </div>
                <div className="mt-4 flex flex-wrap gap-2 text-sm">
                  <Link href={camera.dashboardHref} className={actionLinkClass}>
                    Show on map
                  </Link>
                  <Link href={camera.detailHref} className={actionLinkClass}>
                    Camera details
                  </Link>
                  <Link href={camera.eventFeedHref} className={actionLinkClass}>
                    View incidents
                  </Link>
                </div>
              </div>
            );
          }) : (
            <div className="rounded-[1.5rem] border border-dashed border-[rgba(23,57,69,0.16)] p-6 text-sm text-[rgba(19,32,41,0.72)]">
              No cameras are registered yet. Cameras are added and configured by a system administrator.
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function RecentViolationsFeed({ model }: { model: SpatialOperationsModel }) {
  if (model.recentViolations.length === 0) {
    return null;
  }

  return (
    <div className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.78)] p-5 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="text-[0.72rem] font-semibold uppercase tracking-[0.22em] text-[rgba(19,32,41,0.56)]">
            Recent Violations
          </p>
          <p className="mt-1 text-sm text-[rgba(19,32,41,0.68)]">
            {model.recentViolations.length} most recent violations
          </p>
        </div>
        <Link href="/cases" className={actionLinkClass}>
          View all
        </Link>
      </div>
      <div className="mt-4 divide-y divide-[rgba(23,57,69,0.08)]">
        {model.recentViolations.slice(0, 5).map((v) => (
          <div key={v.id} className="flex items-start gap-3 py-3 first:pt-0 last:pb-0">
            <span className={`mt-0.5 inline-block rounded-full px-2.5 py-0.5 text-[0.68rem] font-semibold uppercase tracking-[0.14em] ${v.severity === "critical" ? "bg-[rgba(240,90,79,0.14)] text-[var(--color-danger)]" : v.severity === "high" ? "bg-[rgba(240,90,79,0.10)] text-[var(--color-danger)]" : v.severity === "medium" ? "bg-[rgba(226,176,71,0.16)] text-[var(--color-warning-ink)]" : "bg-[rgba(56,183,118,0.14)] text-[var(--color-ok-ink)]"}`}>
              {severityLabel(v.severity)}
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-[var(--color-ink)]">{violationTypeLabel(v.violation_type)}</p>
              <p className="mt-0.5 text-xs text-[rgba(19,32,41,0.6)]">
                {formatTimestamp(v.occurred_at)} · {titleCase(v.status)}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function RecentEventsFeed({ model }: { model: SpatialOperationsModel }) {
  if (model.recentEvents.length === 0) {
    return null;
  }

  return (
    <div className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.78)] p-5 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="text-[0.72rem] font-semibold uppercase tracking-[0.22em] text-[rgba(19,32,41,0.56)]">
            Recent Camera Detections
          </p>
          <p className="mt-1 text-sm text-[rgba(19,32,41,0.68)]">
            {model.recentEvents.length} most recent detections
          </p>
        </div>
        <Link href="/cases" className={actionLinkClass}>
          View all
        </Link>
      </div>
      <div className="mt-4 divide-y divide-[rgba(23,57,69,0.08)]">
        {model.recentEvents.slice(0, 5).map((e) => (
          <div key={e.id} className="flex items-start gap-3 py-3 first:pt-0 last:pb-0">
            <span className="mt-0.5 inline-block rounded-full bg-[rgba(56,183,118,0.14)] px-2.5 py-0.5 text-[0.68rem] font-semibold uppercase tracking-[0.14em] text-[var(--color-ok-ink)]">
              {titleCase(e.object_class)}
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-[var(--color-ink)]">
                {eventTypeLabel(e.event_type)}
              </p>
              <p className="mt-0.5 text-xs text-[rgba(19,32,41,0.6)]">
                {formatTimestamp(e.occurred_at)}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function OperationsRecentFeedPanels({ model }: { model: SpatialOperationsModel }) {
  if (model.recentViolations.length === 0 && model.recentEvents.length === 0) {
    return (
      <section className="rounded-[2rem] border border-dashed border-[rgba(23,57,69,0.16)] bg-[rgba(246,240,229,0.72)] p-6 text-center">
        <p className="text-sm font-semibold text-[var(--color-ink)]">No recent activity</p>
        <p className="mt-2 text-sm leading-6 text-[rgba(19,32,41,0.72)]">
          Violations and detections will appear here as cameras report events.
        </p>
      </section>
    );
  }

  return (
    <section className="grid gap-6 xl:grid-cols-2">
      <RecentViolationsFeed model={model} />
      <RecentEventsFeed model={model} />
    </section>
  );
}