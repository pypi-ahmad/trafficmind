import Link from "next/link";

import { StatCard } from "@/features/operations/components/dashboard-primitives";
import { MapPanel } from "@/features/operations/components/map-panel";
import { OperationsActivityPanels } from "@/features/operations/components/operations-activity-panels";
import { OperationsSidebar } from "@/features/operations/components/operations-sidebar";
import type { SpatialOperationsModel } from "@/features/operations/types";

const actionLinkClass =
  "rounded-full border border-[rgba(23,57,69,0.14)] px-4 py-2 text-sm font-medium text-[var(--color-ink)] transition-colors hover:border-[rgba(23,57,69,0.28)]";

export function OperationsDashboard({ model }: { model: SpatialOperationsModel }) {
  const activeCameras = model.cameras.filter((camera) => camera.status === "active").length;
  const multiCameraJunctions = model.junctions.filter((junction) => junction.cameraCount > 1).length;
  const analyticsMetricLabel = model.spatialAnalytics.availability === "live" ? "Recent incidents" : "Attention hotspots";
  const analyticsMetricValue = model.spatialAnalytics.availability === "live"
    ? `${model.spatialAnalytics.totalEvents}`
    : `${model.hotspots.filter((hotspot) => hotspot.severity !== "stable").length}`;
  const analyticsMetricNote = model.spatialAnalytics.availability === "live"
    ? "This count comes from persisted violations and watchlist alerts in the configured spatial analytics window."
    : "Hotspots fall back to camera health and coordinate coverage until live spatial analytics is available.";

  return (
    <div className="mx-auto flex w-full max-w-[1500px] flex-col gap-8 px-4 py-6 sm:px-6 lg:px-10 lg:py-8">
      <header className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[linear-gradient(135deg,rgba(244,238,224,0.94),rgba(231,242,244,0.92))] p-6 shadow-[0_24px_60px_rgba(18,32,41,0.08)] lg:p-8">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-3xl">
            <p className="text-[0.75rem] font-semibold uppercase tracking-[0.3em] text-[rgba(19,32,41,0.56)]">
              Spatial Operations
            </p>
            <h1 className="mt-4 text-4xl font-semibold tracking-[-0.06em] text-[var(--color-ink)] sm:text-5xl">
              Map-first camera operations with honest spatial analytics.
            </h1>
            <p className="mt-4 max-w-2xl text-base leading-7 text-[rgba(19,32,41,0.76)] sm:text-lg">
              This view combines live camera metadata with persisted hotspot analytics when available, while keeping raw event feed gaps visible instead of pretending the backend can already drive a full GIS console.
            </p>
            <div className="mt-5 flex flex-wrap gap-3 text-sm">
              <Link href="/evaluation" className={actionLinkClass}>
                Open evaluation view
              </Link>
              <Link href="/events" className={actionLinkClass}>
                Event feed foundation
              </Link>
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-[1.5rem] bg-[rgba(255,255,255,0.74)] px-4 py-3 text-sm text-[var(--color-ink)]">
              <p className="text-[0.7rem] uppercase tracking-[0.22em] text-[rgba(19,32,41,0.54)]">Map Provider</p>
              <p className="mt-2 font-semibold">{model.provider.provider}</p>
              <p className="mt-1 text-[rgba(19,32,41,0.72)]">{model.provider.note}</p>
            </div>
            <div className="rounded-[1.5rem] bg-[rgba(255,255,255,0.74)] px-4 py-3 text-sm text-[var(--color-ink)]">
              <p className="text-[0.7rem] uppercase tracking-[0.22em] text-[rgba(19,32,41,0.54)]">Spatial Analytics</p>
              <p className="mt-2 font-semibold">{model.spatialAnalytics.availability}</p>
              <p className="mt-1 text-[rgba(19,32,41,0.72)]">{model.spatialAnalytics.note}</p>
            </div>
            <div className="rounded-[1.5rem] bg-[rgba(255,255,255,0.74)] px-4 py-3 text-sm text-[var(--color-ink)]">
              <p className="text-[0.7rem] uppercase tracking-[0.22em] text-[rgba(19,32,41,0.54)]">Raw Feed Routes</p>
              <p className="mt-2 font-semibold">{model.feeds.events.availability} / {model.feeds.violations.availability}</p>
              <p className="mt-1 text-[rgba(19,32,41,0.72)]">{model.feeds.events.note}</p>
            </div>
          </div>
        </div>
      </header>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Mapped Cameras"
          value={`${model.mappedCameras.length}/${model.cameras.length}`}
          note="Cameras with latitude and longitude can render on either the coordinate grid or a real basemap provider."
        />
        <StatCard
          label="Active Cameras"
          value={`${activeCameras}`}
          note="A live operations map is only useful if device health stays visible beside the spatial layer."
        />
        <StatCard
          label="Junction Groups"
          value={`${model.junctions.length}`}
          note={`${multiCameraJunctions} multi-camera intersections are already grouped using current location names.`}
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

      <OperationsActivityPanels model={model} />
    </div>
  );
}