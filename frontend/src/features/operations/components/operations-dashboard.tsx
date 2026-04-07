import Link from "next/link";

import { formatTimestamp, StatCard } from "@/features/operations/components/dashboard-primitives";
import { MapPanel } from "@/features/operations/components/map-panel";
import { OperationsActivityPanels, OperationsRecentFeedPanels } from "@/features/operations/components/operations-activity-panels";
import { OperationsSidebar } from "@/features/operations/components/operations-sidebar";
import { availabilityDisplayLabel, eventStatusLabel, severityLabel } from "@/features/shared/format-labels";
import type { SpatialOperationsModel } from "@/features/operations/types";

const actionLinkClass =
  "rounded-full border border-[rgba(23,57,69,0.14)] px-4 py-2 text-sm font-medium text-[var(--color-ink)] transition-colors hover:border-[rgba(23,57,69,0.28)]";

export function OperationsDashboard({ model, dataAsOf }: { model: SpatialOperationsModel; dataAsOf: string }) {
  const activeCameras = model.cameras.filter((camera) => camera.status === "active").length;
  const multiCameraJunctions = model.junctions.filter((junction) => junction.cameraCount > 1).length;
  const analyticsMetricLabel = model.spatialAnalytics.availability === "live" ? "Recent incidents" : "Attention hotspots";
  const analyticsMetricValue = model.spatialAnalytics.availability === "live"
    ? `${model.spatialAnalytics.totalEvents}`
    : `${model.hotspots.filter((hotspot) => hotspot.severity !== "stable").length}`;
  const analyticsMetricNote = model.spatialAnalytics.availability === "live"
    ? "Based on violations and alerts in the current monitoring window."
    : "Based on camera health and coverage until live analytics is available.";

  const feedSummaryNote =
    model.feedSummary.totalEvents + model.feedSummary.totalViolations > 0
      ? `${model.feedSummary.totalEvents} detections and ${model.feedSummary.totalViolations} violations across ${model.feedSummary.eventCounts.length} cameras.`
      : model.feeds.events.availability === "live"
        ? "Connected — no incidents recorded yet."
        : "Incident feeds are not yet connected.";

  const feedsConnected =
    model.feeds.events.availability === "live" && model.feeds.violations.availability === "live";
  const allServicesOk = feedsConnected && model.spatialAnalytics.availability === "live";
  const systemStatusLabel = allServicesOk
    ? "All services connected"
    : feedsConnected
      ? "Feeds connected · Analytics pending"
      : "Some services pending";
  const systemStatusDot = allServicesOk
    ? "bg-[var(--color-ok)]"
    : feedsConnected
      ? "bg-[var(--color-warning)]"
      : "bg-[rgba(19,32,41,0.32)]";

  return (
    <div className="mx-auto flex w-full max-w-[1500px] flex-col gap-8 px-4 py-6 sm:px-6 lg:px-10 lg:py-8">
      <header className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[linear-gradient(135deg,rgba(244,238,224,0.94),rgba(231,242,244,0.92))] p-6 shadow-[0_24px_60px_rgba(18,32,41,0.08)] lg:p-8">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-3xl">
            <p className="text-[0.75rem] font-semibold uppercase tracking-[0.3em] text-[rgba(19,32,41,0.56)]">
              Operations Dashboard
            </p>
            <h1 className="mt-4 text-4xl font-semibold tracking-[-0.06em] text-[var(--color-ink)] sm:text-5xl">
              Camera Operations Overview
            </h1>
            <p className="mt-4 max-w-2xl text-base leading-7 text-[rgba(19,32,41,0.76)] sm:text-lg">
              Monitor your camera network, review incidents by location, and track operational status across all connected intersections.
            </p>
            <div className="mt-5 flex flex-wrap items-center gap-3 text-sm">
              <Link href="/cases" className={actionLinkClass}>
                View Cases
              </Link>
              <span className="text-xs text-[rgba(19,32,41,0.48)]">Data as of {formatTimestamp(dataAsOf)}</span>
            </div>
          </div>

          <details className="group">
            <summary className="flex cursor-pointer list-none items-center gap-2 rounded-full bg-[rgba(255,255,255,0.60)] px-4 py-2 text-xs font-medium text-[rgba(19,32,41,0.68)] transition-colors hover:bg-[rgba(255,255,255,0.80)] [&::-webkit-details-marker]:hidden">
              <span className={`inline-block h-2 w-2 rounded-full ${systemStatusDot}`} />
              <span>System Status: {systemStatusLabel}</span>
              <span className="ml-1 text-[rgba(19,32,41,0.36)] transition-transform group-open:rotate-90">▸</span>
            </summary>
            <div className="mt-3 grid gap-3 sm:grid-cols-3">
              <div className="rounded-[1.5rem] bg-[rgba(255,255,255,0.74)] px-4 py-3 text-sm text-[var(--color-ink)]">
                <p className="text-[0.7rem] uppercase tracking-[0.22em] text-[rgba(19,32,41,0.54)]">Map Status</p>
                <p className="mt-2 font-semibold">{model.provider.displayName}</p>
                <p className="mt-1 text-[rgba(19,32,41,0.72)]">{model.provider.note}</p>
              </div>
              <div className="rounded-[1.5rem] bg-[rgba(255,255,255,0.74)] px-4 py-3 text-sm text-[var(--color-ink)]">
                <p className="text-[0.7rem] uppercase tracking-[0.22em] text-[rgba(19,32,41,0.54)]">Analytics Status</p>
                <p className="mt-2 font-semibold">{availabilityDisplayLabel(model.spatialAnalytics.availability)}</p>
                <p className="mt-1 text-[rgba(19,32,41,0.72)]">{model.spatialAnalytics.note}</p>
              </div>
              <div className="rounded-[1.5rem] bg-[rgba(255,255,255,0.74)] px-4 py-3 text-sm text-[var(--color-ink)]">
                <p className="text-[0.7rem] uppercase tracking-[0.22em] text-[rgba(19,32,41,0.54)]">Incident Feeds</p>
                <p className="mt-2 font-semibold">{availabilityDisplayLabel(model.feeds.events.availability)} / {availabilityDisplayLabel(model.feeds.violations.availability)}</p>
                <p className="mt-1 text-[rgba(19,32,41,0.72)]">{feedSummaryNote}</p>
              </div>
            </div>
          </details>
        </div>
      </header>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <StatCard
          label="Mapped Cameras"
          value={`${model.mappedCameras.length}/${model.cameras.length}`}
          note="Cameras with map coordinates that can be shown on the map."
        />
        <StatCard
          label="Active Cameras"
          value={`${activeCameras}`}
          note="Currently active cameras in the network."
        />
        <StatCard
          label="Intersections"
          value={`${model.junctions.length}`}
          note={`${multiCameraJunctions} multi-camera intersections grouped by location.`}
        />
        <StatCard
          label="Camera Detections"
          value={model.feeds.events.availability === "live" ? `${model.feedSummary.totalEvents}` : "—"}
          note={model.feeds.events.availability === "live"
            ? model.eventSummaryTotals
              ? `By status: ${Object.entries(model.eventSummaryTotals.by_status).map(([k, v]) => `${eventStatusLabel(k)} ${v}`).join(", ")}.`
              : `Across ${model.feedSummary.eventCounts.length} cameras in the monitoring window.`
            : "Waiting for detection data."}
        />
        <StatCard
          label="Violations"
          value={model.feeds.violations.availability === "live" ? `${model.feedSummary.totalViolations}` : "—"}
          note={model.feeds.violations.availability === "live"
            ? model.violationSummaryTotals
              ? `By severity: ${Object.entries(model.violationSummaryTotals.by_severity).map(([k, v]) => `${severityLabel(k)} ${v}`).join(", ")}.`
              : `Across ${model.feedSummary.violationCounts.length} cameras in the monitoring window.`
            : "Waiting for violation data."}
        />
        <StatCard
          label={analyticsMetricLabel}
          value={analyticsMetricValue}
          note={analyticsMetricNote}
        />
      </section>

      <section className="grid gap-6 xl:grid-cols-[minmax(0,1.65fr)_minmax(24rem,0.9fr)]">
        <MapPanel model={model} />
        <OperationsSidebar model={model} />
      </section>

      <OperationsRecentFeedPanels model={model} />

      <OperationsActivityPanels model={model} />
    </div>
  );
}