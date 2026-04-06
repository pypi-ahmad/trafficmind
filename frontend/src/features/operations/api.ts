import "server-only";

import { requestJson } from "@/features/shared/request-json";
import type {
  ApiResult,
  CameraDetailApi,
  CameraEventCountApi,
  CameraListResponse,
  CameraViolationCountApi,
  DetectionEventSearchResult,
  HotspotAnalyticsRequestApi,
  HotspotAnalyticsResponseApi,
  ViolationSearchResult,
} from "@/features/operations/types";

export function fetchCameraList(): Promise<ApiResult<CameraListResponse>> {
  return requestJson<CameraListResponse>("/cameras");
}

export function fetchCameraDetail(cameraId: string): Promise<ApiResult<CameraDetailApi>> {
  return requestJson<CameraDetailApi>(`/cameras/${cameraId}`);
}

export function fetchEventsFeed(options?: {
  limit?: number;
  cameraId?: string | null;
}): Promise<ApiResult<DetectionEventSearchResult>> {
  const params = new URLSearchParams();
  params.set("limit", String(options?.limit ?? 20));
  if (options?.cameraId) {
    params.set("camera_id", options.cameraId);
  }
  return requestJson<DetectionEventSearchResult>(`/events/?${params.toString()}`);
}

export function fetchViolationsFeed(options?: {
  limit?: number;
  cameraId?: string | null;
}): Promise<ApiResult<ViolationSearchResult>> {
  const params = new URLSearchParams();
  params.set("limit", String(options?.limit ?? 20));
  if (options?.cameraId) {
    params.set("camera_id", options.cameraId);
  }
  return requestJson<ViolationSearchResult>(`/violations/?${params.toString()}`);
}

export function fetchEventCountsByCamera(options?: {
  occurredAfter?: string;
  occurredBefore?: string;
  limit?: number;
}): Promise<ApiResult<CameraEventCountApi[]>> {
  const params = new URLSearchParams();
  if (options?.occurredAfter) {
    params.set("occurred_after", options.occurredAfter);
  }
  if (options?.occurredBefore) {
    params.set("occurred_before", options.occurredBefore);
  }
  if (options?.limit) {
    params.set("limit", String(options.limit));
  }
  const qs = params.toString();
  return requestJson<CameraEventCountApi[]>(`/events/summary/by-camera${qs ? `?${qs}` : ""}`);
}

export function fetchViolationCountsByCamera(options?: {
  occurredAfter?: string;
  occurredBefore?: string;
  limit?: number;
}): Promise<ApiResult<CameraViolationCountApi[]>> {
  const params = new URLSearchParams();
  if (options?.occurredAfter) {
    params.set("occurred_after", options.occurredAfter);
  }
  if (options?.occurredBefore) {
    params.set("occurred_before", options.occurredBefore);
  }
  if (options?.limit) {
    params.set("limit", String(options.limit));
  }
  const qs = params.toString();
  return requestJson<CameraViolationCountApi[]>(`/violations/summary/by-camera${qs ? `?${qs}` : ""}`);
}

export function fetchHotspotAnalytics(
  request: HotspotAnalyticsRequestApi,
): Promise<ApiResult<HotspotAnalyticsResponseApi>> {
  return requestJson<HotspotAnalyticsResponseApi>("/analytics/hotspots", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  });
}