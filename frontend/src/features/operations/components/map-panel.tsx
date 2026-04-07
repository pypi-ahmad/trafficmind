import Link from "next/link";

import { MapSurface } from "@/features/operations/components/map-surface";
import {
  availabilityClass,
  availabilityLabel,
  formatWindowLabel,
} from "@/features/operations/components/dashboard-primitives";
import { buildEventFeedHref } from "@/features/operations/derive";
import type { SpatialOperationsModel } from "@/features/operations/types";

const LEGEND_ITEMS = [
  { label: "Junction marker", className: "border border-[rgba(244,149,72,0.42)] bg-[rgba(244,149,72,0.12)]" },
  { label: "Active camera", className: "bg-[var(--color-ok)]" },
  { label: "Watch camera", className: "bg-[var(--color-warning)]" },
  { label: "Critical camera", className: "bg-[var(--color-danger)]" },
];

export function MapPanel({ model }: { model: SpatialOperationsModel }) {
  const selectedEventFeedHref = buildEventFeedHref({
    cameraId: model.selectedCamera?.id ?? undefined,
    junctionId: model.selectedJunction?.id ?? undefined,
  });
  const analyticsWindow = formatWindowLabel(
    model.spatialAnalytics.periodStart,
    model.spatialAnalytics.periodEnd,
  );

  return (
    <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(249,245,238,0.82)] p-4 shadow-[0_22px_50px_rgba(18,32,41,0.06)] sm:p-5">
      <div className="mb-4 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-[0.72rem] font-semibold uppercase tracking-[0.22em] text-[rgba(19,32,41,0.56)]">
            Map Layer
          </p>
          <h2 className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">
            Cameras, grouped junctions, and location signals
          </h2>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-[rgba(19,32,41,0.72)]">
            Camera pins use exact coordinates when available. Junction markers are grouped by shared location name.
          </p>
        </div>

        <div className="flex flex-wrap gap-3">
          <span className={`rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] ${availabilityClass(model.spatialAnalytics.availability)}`}>
            Analytics {availabilityLabel(model.spatialAnalytics.availability)}
          </span>
          <Link
            href={selectedEventFeedHref}
            className="rounded-full bg-[var(--color-ink)] px-4 py-2 text-sm font-medium text-[var(--color-paper)] transition-transform hover:-translate-y-0.5"
          >
            Open event filters
          </Link>
        </div>
      </div>

      <div className="mb-4 grid gap-3 md:grid-cols-3">
        <div className="rounded-[1.5rem] bg-[rgba(255,255,255,0.74)] px-4 py-3 text-sm text-[var(--color-ink)]">
          <p className="text-[0.7rem] uppercase tracking-[0.22em] text-[rgba(19,32,41,0.54)]">Analytics Window</p>
          <p className="mt-2 font-semibold">{analyticsWindow}</p>
          <p className="mt-1 text-[rgba(19,32,41,0.72)]">{model.spatialAnalytics.note}</p>
        </div>
        <div className="rounded-[1.5rem] bg-[rgba(255,255,255,0.74)] px-4 py-3 text-sm text-[var(--color-ink)]">
          <p className="text-[0.7rem] uppercase tracking-[0.22em] text-[rgba(19,32,41,0.54)]">Map Provider</p>
          <p className="mt-2 font-semibold">{model.provider.displayName}</p>
          <p className="mt-1 text-[rgba(19,32,41,0.72)]">{model.provider.note}</p>
        </div>
        <div className="rounded-[1.5rem] bg-[rgba(255,255,255,0.74)] px-4 py-3 text-sm text-[var(--color-ink)]">
          <p className="text-[0.7rem] uppercase tracking-[0.22em] text-[rgba(19,32,41,0.54)]">Selection Links</p>
          <p className="mt-2 font-semibold">Dashboard, detail, and feed stay in sync</p>
          <p className="mt-1 text-[rgba(19,32,41,0.72)]">Map markers, hotspot cards, and incident cards all route back into the same camera or junction context.</p>
        </div>
      </div>

      <div className="mb-4 flex flex-wrap gap-2 text-xs text-[rgba(19,32,41,0.68)]">
        {LEGEND_ITEMS.map((item) => (
          <span key={item.label} className="inline-flex items-center gap-2 rounded-full bg-[rgba(255,255,255,0.74)] px-3 py-2">
            <span className={`h-3 w-3 rounded-full ${item.className}`} />
            {item.label}
          </span>
        ))}
      </div>

      <MapSurface provider={model.provider} cameras={model.cameras} markers={model.mapMarkers} />

      {model.spatialAnalytics.warnings.length > 0 ? (
        <div className="mt-4 rounded-[1.5rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.72)] p-4 text-sm text-[rgba(19,32,41,0.74)]">
          <p className="text-[0.72rem] font-semibold uppercase tracking-[0.22em] text-[rgba(19,32,41,0.56)]">
            Spatial warnings
          </p>
          <div className="mt-3 space-y-2">
            {model.spatialAnalytics.warnings.slice(0, 3).map((warning) => (
              <p key={warning}>{warning}</p>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}