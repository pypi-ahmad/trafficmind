import "server-only";

import { requestJson } from "@/features/shared/request-json";
import type {
  ApiResult,
  CameraDetailApi,
  CameraListResponse,
  HotspotAnalyticsRequestApi,
  HotspotAnalyticsResponseApi,
  PlaceholderApiResponse,
} from "@/features/operations/types";

export function fetchCameraList(): Promise<ApiResult<CameraListResponse>> {
  return requestJson<CameraListResponse>("/cameras");
}

export function fetchCameraDetail(cameraId: string): Promise<ApiResult<CameraDetailApi>> {
  return requestJson<CameraDetailApi>(`/cameras/${cameraId}`);
}

export function fetchEventsStatus(): Promise<ApiResult<PlaceholderApiResponse>> {
  return requestJson<PlaceholderApiResponse>("/events/");
}

export function fetchViolationsStatus(): Promise<ApiResult<PlaceholderApiResponse>> {
  return requestJson<PlaceholderApiResponse>("/violations/");
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