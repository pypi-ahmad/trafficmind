"use client";

import { useEffect, useMemo, useRef } from "react";
import maplibregl from "maplibre-gl";

import type { SpatialMapMarker } from "@/features/operations/types";

type MapLibreSurfaceProps = {
  markers: SpatialMapMarker[];
  styleUrl: string;
};

function getMarkerColor(marker: SpatialMapMarker): string {
  switch (marker.tone) {
    case "critical":
      return "#d8574b";
    case "watch":
      return "#e2b047";
    case "inactive":
      return "#5f6c72";
    case "ok":
    default:
      return "#38b776";
  }
}

export function MapLibreSurface({
  markers,
  styleUrl,
}: MapLibreSurfaceProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markerRefs = useRef<maplibregl.Marker[]>([]);

  const mappedMarkers = useMemo(
    () => markers.filter((marker) => marker.coordinates !== null),
    [markers],
  );

  useEffect(() => {
    if (!containerRef.current || mapRef.current || mappedMarkers.length === 0) {
      return;
    }

    const first = mappedMarkers[0]?.coordinates;
    if (!first) {
      return;
    }

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: styleUrl,
      center: [first.longitude, first.latitude],
      zoom: mappedMarkers.length > 1 ? 12 : 14,
      attributionControl: false,
    });

    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    mapRef.current = map;

    return () => {
      markerRefs.current.forEach((marker) => marker.remove());
      markerRefs.current = [];
      map.remove();
      mapRef.current = null;
    };
  }, [mappedMarkers, styleUrl]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) {
      return;
    }

    markerRefs.current.forEach((marker) => marker.remove());
    markerRefs.current = [];

    const bounds = new maplibregl.LngLatBounds();

    for (const spatialMarker of mappedMarkers) {
      const coordinates = spatialMarker.coordinates;

      const markerElement = document.createElement("a");
      markerElement.href = spatialMarker.href;
      markerElement.title = `${spatialMarker.label} · ${spatialMarker.detail}`;
      markerElement.setAttribute("aria-label", `Open ${spatialMarker.label} on the operations dashboard`);
      markerElement.style.display = "flex";
      markerElement.style.flexDirection = "column";
      markerElement.style.alignItems = "center";
      markerElement.style.gap = "8px";
      markerElement.style.transition = "transform 120ms ease";
      markerElement.onmouseenter = () => {
        markerElement.style.transform = "scale(1.08)";
      };
      markerElement.onmouseleave = () => {
        markerElement.style.transform = "scale(1)";
      };

      const core = document.createElement("span");
      core.style.display = "flex";
      core.style.alignItems = "center";
      core.style.justifyContent = "center";
      core.style.position = "relative";
      core.style.fontSize = "11px";
      core.style.fontWeight = "700";
      core.style.color = spatialMarker.kind === "junction" ? getMarkerColor(spatialMarker) : "#132029";
      core.style.boxShadow = spatialMarker.isSelected
        ? "0 0 0 6px rgba(244, 149, 72, 0.24)"
        : "0 8px 18px rgba(0, 0, 0, 0.18)";

      if (spatialMarker.kind === "junction") {
        core.style.minWidth = "42px";
        core.style.height = "42px";
        core.style.padding = "0 10px";
        core.style.borderRadius = "999px";
        core.style.border = `2px solid ${getMarkerColor(spatialMarker)}`;
        core.style.background = `${getMarkerColor(spatialMarker)}22`;
        core.textContent = spatialMarker.badge ?? "J";
      } else {
        core.style.width = spatialMarker.isSelected ? "26px" : "18px";
        core.style.height = spatialMarker.isSelected ? "26px" : "18px";
        core.style.borderRadius = "999px";
        core.style.border = spatialMarker.isSelected ? "3px solid #f6f0e5" : "2px solid #f6f0e5";
        core.style.background = getMarkerColor(spatialMarker);
        if (spatialMarker.badge) {
          const badge = document.createElement("span");
          badge.textContent = spatialMarker.badge;
          badge.style.position = "absolute";
          badge.style.top = "-8px";
          badge.style.right = "-8px";
          badge.style.minWidth = "18px";
          badge.style.height = "18px";
          badge.style.borderRadius = "999px";
          badge.style.background = "#f6f0e5";
          badge.style.color = "#132029";
          badge.style.display = "flex";
          badge.style.alignItems = "center";
          badge.style.justifyContent = "center";
          badge.style.fontSize = "10px";
          badge.style.padding = "0 4px";
          core.appendChild(badge);
        }
      }

      const label = document.createElement("span");
      label.textContent = spatialMarker.label;
      label.style.padding = "4px 10px";
      label.style.borderRadius = "999px";
      label.style.background = "rgba(8, 21, 28, 0.8)";
      label.style.color = "rgba(246, 240, 229, 0.92)";
      label.style.fontSize = "10px";
      label.style.fontWeight = "600";
      label.style.letterSpacing = "0.06em";

      markerElement.appendChild(core);
      markerElement.appendChild(label);

      const renderedMarker = new maplibregl.Marker({ element: markerElement, anchor: "center" })
        .setLngLat([coordinates.longitude, coordinates.latitude])
        .addTo(map);

      markerRefs.current.push(renderedMarker);
      bounds.extend([coordinates.longitude, coordinates.latitude]);
    }

    if (!bounds.isEmpty()) {
      map.fitBounds(bounds, {
        padding: 72,
        maxZoom: mappedMarkers.length > 1 ? 14 : 15,
        duration: 0,
      });
    }
  }, [mappedMarkers]);

  return <div ref={containerRef} className="h-full min-h-[28rem] w-full" />;
}