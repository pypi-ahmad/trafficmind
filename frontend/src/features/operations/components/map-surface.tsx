import Link from "next/link";

import { MapLibreSurface } from "@/features/operations/components/maplibre-surface";
import type { CameraMapItem, MapProviderConfig, SpatialMapMarker } from "@/features/operations/types";

type MapSurfaceProps = {
  provider: MapProviderConfig;
  cameras: CameraMapItem[];
  markers: SpatialMapMarker[];
};

function markerToneClass(marker: SpatialMapMarker): string {
  if (marker.kind === "junction") {
    switch (marker.tone) {
      case "critical":
        return "border-[rgba(216,87,75,0.48)] bg-[rgba(216,87,75,0.18)] text-[var(--color-danger)]";
      case "watch":
        return "border-[rgba(226,176,71,0.48)] bg-[rgba(226,176,71,0.18)] text-[var(--color-warning-ink)]";
      case "inactive":
        return "border-[rgba(19,32,41,0.26)] bg-[rgba(19,32,41,0.08)] text-[rgba(19,32,41,0.72)]";
      case "ok":
      default:
        return "border-[rgba(56,183,118,0.42)] bg-[rgba(56,183,118,0.14)] text-[var(--color-ok-ink)]";
    }
  }

  switch (marker.tone) {
    case "critical":
      return "bg-[var(--color-danger)]";
    case "watch":
      return "bg-[var(--color-warning)]";
    case "inactive":
      return "bg-[rgba(19,32,41,0.42)]";
    case "ok":
    default:
      return "bg-[var(--color-ok)]";
  }
}

function CoordinateSurface({
  cameras,
  markers,
  note,
}: {
  cameras: CameraMapItem[];
  markers: SpatialMapMarker[];
  note: string;
}) {
  const mappedMarkers = markers.filter((marker) => marker.coordinates !== null);
  const missingCoordinates = cameras.filter((camera) => camera.coordinates === null);

  if (mappedMarkers.length === 0) {
    return (
      <div className="flex min-h-[28rem] flex-col items-center justify-center rounded-[2rem] border border-dashed border-[rgba(23,57,69,0.18)] bg-[rgba(255,255,255,0.72)] px-8 text-center text-sm text-[rgba(19,32,41,0.72)]">
        <p className="text-base font-semibold text-[var(--color-ink)]">No mapped cameras yet</p>
        <p className="mt-3 max-w-md">
          Camera coordinates already exist in the backend schema, but this environment has no camera rows with latitude and longitude populated.
        </p>
      </div>
    );
  }

  const latitudes = mappedMarkers.map((marker) => marker.coordinates.latitude);
  const longitudes = mappedMarkers.map((marker) => marker.coordinates.longitude);
  const minLatitude = Math.min(...latitudes);
  const maxLatitude = Math.max(...latitudes);
  const minLongitude = Math.min(...longitudes);
  const maxLongitude = Math.max(...longitudes);

  const toPosition = (marker: SpatialMapMarker) => {
    const coordinates = marker.coordinates;
    const longitudeRange = Math.max(maxLongitude - minLongitude, 0.001);
    const latitudeRange = Math.max(maxLatitude - minLatitude, 0.001);
    const left = ((coordinates.longitude - minLongitude) / longitudeRange) * 100;
    const top = 100 - ((coordinates.latitude - minLatitude) / latitudeRange) * 100;
    return {
      left: `${Math.min(Math.max(left, 4), 96)}%`,
      top: `${Math.min(Math.max(top, 6), 94)}%`,
    };
  };

  return (
    <div className="flex min-h-[28rem] flex-col gap-4">
      <div className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.74)] p-4 text-xs text-[rgba(19,32,41,0.74)]">
        {note}
      </div>
      <div className="relative min-h-[28rem] overflow-hidden rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[linear-gradient(135deg,rgba(21,51,63,0.92),rgba(14,34,43,0.98))]">
        <div className="absolute inset-0 opacity-30 [background-image:linear-gradient(rgba(255,255,255,0.15)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.15)_1px,transparent_1px)] [background-size:4.5rem_4.5rem]" />
        <div className="absolute inset-x-0 top-0 flex items-center justify-between px-6 py-5 text-[0.7rem] uppercase tracking-[0.28em] text-[rgba(246,240,229,0.62)]">
          <span>Coordinate Grid</span>
          <span>Lat / Long Fallback</span>
        </div>
        {mappedMarkers
          .filter((marker) => marker.kind === "junction")
          .map((marker) => {
            const position = toPosition(marker);
            return (
              <Link
                key={marker.id}
                href={marker.href}
                title={marker.detail}
                className="group absolute -translate-x-1/2 -translate-y-1/2"
                style={{ ...position, zIndex: marker.isSelected ? 18 : 10 }}
              >
                <span
                  className={`relative flex h-12 min-w-12 items-center justify-center rounded-full border px-3 text-[0.7rem] font-semibold tracking-[0.08em] shadow-[0_12px_26px_rgba(0,0,0,0.18)] transition-transform duration-150 group-hover:scale-[1.03] ${markerToneClass(marker)} ${marker.isSelected ? "ring-4 ring-[rgba(244,149,72,0.2)]" : ""}`}
                >
                  {marker.badge ?? "J"}
                </span>
                <span className="mt-2 block rounded-full bg-[rgba(8,21,28,0.8)] px-3 py-1 text-[0.65rem] font-medium tracking-[0.06em] text-[rgba(246,240,229,0.92)]">
                  {marker.label}
                </span>
              </Link>
            );
          })}
        {mappedMarkers
          .filter((marker) => marker.kind === "camera")
          .map((marker) => {
            const position = toPosition(marker);
            return (
              <Link
                key={marker.id}
                href={marker.href}
                title={marker.detail}
                className="group absolute -translate-x-1/2 -translate-y-1/2"
                style={{ ...position, zIndex: marker.isSelected ? 22 : 16 }}
              >
                <span
                  className={`relative block rounded-full border border-[rgba(246,240,229,0.88)] transition-transform duration-150 group-hover:scale-105 ${marker.isSelected ? "h-7 w-7 shadow-[0_0_0_8px_rgba(244,149,72,0.18)]" : "h-5 w-5"} ${markerToneClass(marker)}`}
                >
                  {marker.badge ? (
                    <span className="absolute -right-2 -top-2 flex h-5 min-w-5 items-center justify-center rounded-full bg-[var(--color-paper)] px-1 text-[0.55rem] font-bold text-[var(--color-ink)]">
                      {marker.badge}
                    </span>
                  ) : null}
                </span>
                <span className="mt-2 block rounded-full bg-[rgba(8,21,28,0.8)] px-3 py-1 text-[0.65rem] font-medium tracking-[0.06em] text-[rgba(246,240,229,0.92)]">
                  {marker.label}
                </span>
              </Link>
            );
          })}
      </div>
      {missingCoordinates.length > 0 ? (
        <div className="rounded-[1.6rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.74)] p-4">
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[rgba(19,32,41,0.56)]">
            Unmapped Cameras
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {missingCoordinates.map((camera) => (
              <Link
                key={camera.id}
                href={camera.dashboardHref}
                className="rounded-full border border-[rgba(23,57,69,0.12)] px-3 py-1 text-sm text-[var(--color-ink)] transition-colors hover:border-[rgba(23,57,69,0.28)]"
              >
                {camera.name}
              </Link>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function MapSurface({ provider, cameras, markers }: MapSurfaceProps) {
  const mappedMarkers = markers.filter((marker) => marker.coordinates !== null);

  if (provider.provider === "maplibre" && provider.styleUrl && mappedMarkers.length > 0) {
    return (
      <div className="overflow-hidden rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.74)]">
        <div className="flex items-center justify-between border-b border-[rgba(23,57,69,0.12)] px-5 py-4 text-xs uppercase tracking-[0.24em] text-[rgba(19,32,41,0.58)]">
          <span>Basemap</span>
          <span>MapLibre</span>
        </div>
        <MapLibreSurface markers={mappedMarkers} styleUrl={provider.styleUrl} />
      </div>
    );
  }

  return <CoordinateSurface cameras={cameras} markers={markers} note={provider.note} />;
}