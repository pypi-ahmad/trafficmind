import type { MapProviderConfig, SpatialAnalyticsConfig } from "@/features/operations/types";

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000/api/v1";
const DEFAULT_SPATIAL_LOOKBACK_DAYS = 7;
const DEFAULT_SPATIAL_TOP_N = 48;

function parsePositiveInteger(value: string | undefined, fallback: number): number {
  if (!value) {
    return fallback;
  }

  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return fallback;
  }

  return parsed;
}

function normalizeBaseUrl(value: string | undefined, fallback: string): string {
  if (!value) {
    return fallback;
  }

  try {
    return new URL(value).toString().replace(/\/$/, "");
  } catch {
    return fallback;
  }
}

export function getApiBaseUrl(): string {
  return normalizeBaseUrl(
    process.env.TRAFFICMIND_API_BASE_URL ??
    process.env.NEXT_PUBLIC_TRAFFICMIND_API_BASE_URL ??
    process.env.NEXT_PUBLIC_API_BASE_URL,
    DEFAULT_API_BASE_URL,
  );
}

export function getMapProviderConfig(): MapProviderConfig {
  const requestedProvider = process.env.NEXT_PUBLIC_MAP_PROVIDER ?? "coordinate-grid";
  const styleUrl = process.env.NEXT_PUBLIC_MAP_STYLE_URL ?? null;
  const token = process.env.NEXT_PUBLIC_MAP_ACCESS_TOKEN ?? null;

  if (requestedProvider === "maplibre" && styleUrl) {
    return {
      provider: "maplibre",
      displayName: "Interactive Map",
      requestedProvider,
      styleUrl,
      token,
      note: "Interactive map is active.",
    };
  }

  if (requestedProvider === "maplibre" && !styleUrl) {
    return {
      provider: "coordinate-grid",
      displayName: "Basic Map View",
      requestedProvider,
      styleUrl: null,
      token,
      note: "Interactive map is not fully configured yet. Using a simple coordinate view.",
    };
  }

  return {
    provider: "coordinate-grid",
    displayName: "Basic Map View",
    requestedProvider,
    styleUrl: null,
    token,
    note: "Using a simple coordinate view. Configure a map provider for a richer map.",
  };
}

export function getSpatialAnalyticsConfig(): SpatialAnalyticsConfig {
  const lookbackDays = parsePositiveInteger(
    process.env.TRAFFICMIND_SPATIAL_LOOKBACK_DAYS ??
      process.env.NEXT_PUBLIC_TRAFFICMIND_SPATIAL_LOOKBACK_DAYS,
    DEFAULT_SPATIAL_LOOKBACK_DAYS,
  );

  const topN = parsePositiveInteger(
    process.env.TRAFFICMIND_SPATIAL_TOP_N ?? process.env.NEXT_PUBLIC_TRAFFICMIND_SPATIAL_TOP_N,
    DEFAULT_SPATIAL_TOP_N,
  );

  return {
    lookbackDays,
    topN,
  };
}