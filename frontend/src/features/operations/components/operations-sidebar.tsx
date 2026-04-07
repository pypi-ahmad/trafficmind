import Link from "next/link";

import {
  availabilityClass,
  availabilityLabel,
  formatTimestamp,
  severityClass,
  statusClass,
} from "@/features/operations/components/dashboard-primitives";
import { cameraStatusLabel, severityLabel } from "@/features/shared/format-labels";
import type { HotspotSummary, SpatialOperationsModel } from "@/features/operations/types";

const actionLinkClass =
  "rounded-full border border-[rgba(23,57,69,0.14)] px-4 py-2 text-sm font-medium text-[var(--color-ink)] transition-colors hover:border-[rgba(23,57,69,0.28)]";

function HotspotActions({ hotspot }: { hotspot: HotspotSummary }) {
  return (
    <div className="mt-4 flex flex-wrap gap-2 text-sm">
      <Link href={hotspot.dashboardHref} className={actionLinkClass}>
        Show on map
      </Link>
      <Link href={hotspot.eventFeedHref} className={actionLinkClass}>
        View incidents
      </Link>
      {hotspot.cameraDetailHref ? (
        <Link href={hotspot.cameraDetailHref} className={actionLinkClass}>
          Camera details
        </Link>
      ) : null}
    </div>
  );
}

export function OperationsSidebar({ model }: { model: SpatialOperationsModel }) {
  const selectedCamera = model.selectedCamera;
  const selectedJunction = model.selectedJunction;
  const selectedCameraDetail = model.selectedCameraDetail;
  const selectedIncidentSummary = model.selectedIncidentSummary;
  const selectedHotspots = model.selectedHotspots;

  return (
    <aside className="flex flex-col gap-5">
      <div className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.78)] p-5 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-[0.72rem] font-semibold uppercase tracking-[0.22em] text-[rgba(19,32,41,0.56)]">
              Selection
            </p>
            <h2 className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">
              {selectedCamera ? selectedCamera.name : selectedJunction ? selectedJunction.name : "No selection"}
            </h2>
          </div>
          {selectedCamera ? (
            <span className={`rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] ${statusClass(selectedCamera.status)}`}>
              {cameraStatusLabel(selectedCamera.status)}
            </span>
          ) : selectedIncidentSummary ? (
            <span className={`rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] ${availabilityClass(selectedIncidentSummary.availability)}`}>
              {availabilityLabel(selectedIncidentSummary.availability)}
            </span>
          ) : null}
        </div>

        {selectedCamera ? (
          <div className="mt-5 space-y-5">
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-[rgba(19,32,41,0.5)]">Location</p>
                <p className="mt-2 text-sm text-[rgba(19,32,41,0.84)]">{selectedCamera.locationName}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-[rgba(19,32,41,0.5)]">Approach</p>
                <p className="mt-2 text-sm text-[rgba(19,32,41,0.84)]">{selectedCamera.approach ?? "Unassigned"}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-[rgba(19,32,41,0.5)]">Coordinates</p>
                <p className="mt-2 text-sm text-[rgba(19,32,41,0.84)]">
                  {selectedCamera.coordinates
                    ? `${selectedCamera.coordinates.latitude.toFixed(3)}, ${selectedCamera.coordinates.longitude.toFixed(3)}`
                    : "Not mapped"}
                </p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-[rgba(19,32,41,0.5)]">Updated</p>
                <p className="mt-2 text-sm text-[rgba(19,32,41,0.84)]">{formatTimestamp(selectedCamera.updatedAt)}</p>
              </div>
            </div>

            {selectedIncidentSummary ? (
              <div className="rounded-[1.4rem] bg-[rgba(243,237,228,0.86)] p-4">
                <p className="text-xs uppercase tracking-[0.18em] text-[rgba(19,32,41,0.5)]">Recent activity</p>
                <p className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">
                  {selectedIncidentSummary.incidentCount ?? "—"}
                </p>
                <p className="mt-2 text-sm leading-6 text-[rgba(19,32,41,0.72)]">{selectedIncidentSummary.note}</p>
              </div>
            ) : null}

            {selectedCameraDetail ? (
              <div className="rounded-[1.4rem] bg-[rgba(243,237,228,0.86)] p-4">
                <p className="text-xs uppercase tracking-[0.18em] text-[rgba(19,32,41,0.5)]">Camera Details</p>
                <div className="mt-3 grid gap-4 sm:grid-cols-3">
                  <div>
                    <p className="text-2xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">{selectedCameraDetail.streams.length}</p>
                    <p className="text-sm text-[rgba(19,32,41,0.7)]">Attached streams</p>
                  </div>
                  <div>
                    <p className="text-2xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">{selectedCameraDetail.zones.length}</p>
                    <p className="text-sm text-[rgba(19,32,41,0.7)]">Configured zones</p>
                  </div>
                  <div>
                    <p className="text-2xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">{selectedCameraDetail.timezone}</p>
                    <p className="text-sm text-[rgba(19,32,41,0.7)]">Timezone</p>
                  </div>
                </div>
              </div>
            ) : null}

            <div className="rounded-[1.4rem] bg-[rgba(243,237,228,0.86)] p-4 text-sm text-[rgba(19,32,41,0.74)]">
              <p className="text-xs uppercase tracking-[0.18em] text-[rgba(19,32,41,0.5)]">Intersection</p>
              <p className="mt-2 leading-6">
                {selectedJunction
                  ? `${selectedJunction.name} — ${selectedJunction.cameraCount} camera${selectedJunction.cameraCount === 1 ? "" : "s"} grouped by shared location.`
                  : "This camera is not yet linked to an intersection group."}
              </p>
            </div>

            <div className="flex flex-wrap gap-3">
              <Link href={selectedCamera.detailHref} className={actionLinkClass}>
                Camera details
              </Link>
              <Link href={selectedCamera.eventFeedHref} className={actionLinkClass}>
                View incidents
              </Link>
              <Link href={selectedJunction?.dashboardHref ?? selectedCamera.dashboardHref} className={actionLinkClass}>
                View intersection
              </Link>
            </div>
          </div>
        ) : selectedJunction ? (
          <div className="mt-5 space-y-5">
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-[rgba(19,32,41,0.5)]">Grouped cameras</p>
                <p className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">{selectedJunction.cameraCount}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-[rgba(19,32,41,0.5)]">Mapped cameras</p>
                <p className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">{selectedJunction.mappedCameraCount}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-[rgba(19,32,41,0.5)]">Active cameras</p>
                <p className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">{selectedJunction.activeCameraCount}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-[rgba(19,32,41,0.5)]">Recent incidents</p>
                <p className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">{selectedIncidentSummary?.incidentCount ?? "—"}</p>
              </div>
            </div>

            <div className="rounded-[1.4rem] bg-[rgba(243,237,228,0.86)] p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-[rgba(19,32,41,0.5)]">Intersection grouping</p>
              <p className="mt-2 text-sm leading-6 text-[rgba(19,32,41,0.74)]">
                Cameras at this location are grouped by their shared <strong>{selectedJunction.groupingSource === "junction_entity" ? "intersection" : "location name"}</strong>.
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                {selectedJunction.cameras.map((camera) => (
                  <Link key={camera.id} href={camera.dashboardHref} className={`rounded-full px-3 py-1 text-sm ${statusClass(camera.status)}`}>
                    {camera.code}
                  </Link>
                ))}
              </div>
            </div>

            {selectedHotspots.length > 0 ? (
              <div className="rounded-[1.4rem] bg-[rgba(243,237,228,0.86)] p-4">
                <p className="text-xs uppercase tracking-[0.18em] text-[rgba(19,32,41,0.5)]">Related hotspot summaries</p>
                <div className="mt-3 space-y-3">
                  {selectedHotspots.slice(0, 3).map((hotspot) => (
                    <div key={hotspot.id} className="rounded-[1.2rem] bg-[rgba(255,255,255,0.7)] p-3">
                      <div className="flex items-start justify-between gap-3">
                        <p className="font-semibold text-[var(--color-ink)]">{hotspot.title}</p>
                        <span className={`rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] ${severityClass(hotspot.severity)}`}>
                          {severityLabel(hotspot.severity)}
                        </span>
                      </div>
                      <p className="mt-2 text-sm leading-6 text-[rgba(19,32,41,0.72)]">{hotspot.description}</p>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            <div className="flex flex-wrap gap-3">
              <Link href={selectedJunction.dashboardHref} className={actionLinkClass}>
                Show on map
              </Link>
              <Link href={selectedJunction.eventFeedHref} className={actionLinkClass}>
                View incidents
              </Link>
            </div>
          </div>
        ) : (
          <p className="mt-4 text-sm text-[rgba(19,32,41,0.72)]">Select a camera or intersection on the map to see details, recent incidents, and related hotspots.</p>
        )}
      </div>

      <div className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.78)] p-5 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-[0.72rem] font-semibold uppercase tracking-[0.22em] text-[rgba(19,32,41,0.56)]">
              Hotspot Summaries
            </p>
            <h2 className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">Where operators should look first</h2>
          </div>
        </div>
        <div className="mt-5 space-y-3">
          {model.hotspots.map((hotspot) => (
            <div key={hotspot.id} className="rounded-[1.5rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(243,237,228,0.72)] p-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-semibold text-[var(--color-ink)]">{hotspot.title}</p>
                    <span className="rounded-full bg-[rgba(19,32,41,0.08)] px-3 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-[rgba(19,32,41,0.72)]">
                      {hotspot.source === "hotspot_analytics" ? "Monitored" : "Camera Health"}
                    </span>
                  </div>
                  <p className="mt-2 text-sm leading-6 text-[rgba(19,32,41,0.72)]">{hotspot.description}</p>
                  {hotspot.trendLabel ? (
                    <p className="mt-2 text-xs uppercase tracking-[0.16em] text-[rgba(19,32,41,0.54)]">{hotspot.trendLabel}</p>
                  ) : null}
                </div>
                <span className={`rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] ${severityClass(hotspot.severity)}`}>
                  {severityLabel(hotspot.severity)}
                </span>
              </div>
              <div className="mt-4 flex items-center justify-between text-sm">
                <span className="text-[rgba(19,32,41,0.56)]">{hotspot.metricLabel}</span>
                <span className="font-semibold text-[var(--color-ink)]">{hotspot.metricValue}</span>
              </div>
              <HotspotActions hotspot={hotspot} />
            </div>
          ))}
        </div>
      </div>
    </aside>
  );
}