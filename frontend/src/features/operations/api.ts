import "server-only";

import { requestJson } from "@/features/shared/request-json";
import type {
  ApiResult,
  CameraDetailApi,
  CameraEventCountApi,
  CameraListResponse,
  CameraViolationCountApi,
  DetectionEventSearchResult,
  EventFeedParams,
  EventSummaryTotalsApi,
  HotspotAnalyticsRequestApi,
  HotspotAnalyticsResponseApi,
  ViolationFeedParams,
  ViolationSearchResult,
  ViolationSummaryTotalsApi,
} from "@/features/operations/types";

export function fetchCameraList(): Promise<ApiResult<CameraListResponse>> {
  return requestJson<CameraListResponse>("/cameras");
}

export function fetchCameraDetail(cameraId: string): Promise<ApiResult<CameraDetailApi>> {
  return requestJson<CameraDetailApi>(`/cameras/${cameraId}`);
}

export function fetchEventsFeed(options?: EventFeedParams): Promise<ApiResult<DetectionEventSearchResult>> {
  const params = new URLSearchParams();
  params.set("limit", String(options?.limit ?? 20));
  if (options?.offset) {
    params.set("offset", String(options.offset));
  }
  if (options?.cameraId) {
    params.set("camera_id", options.cameraId);
  }
  if (options?.eventType) {
    params.set("event_type", options.eventType);
  }
  if (options?.status) {
    params.set("status", options.status);
  }
  if (options?.objectClass) {
    params.set("object_class", options.objectClass);
  }
  if (options?.occurredAfter) {
    params.set("occurred_after", options.occurredAfter);
  }
  if (options?.occurredBefore) {
    params.set("occurred_before", options.occurredBefore);
  }
  if (options?.minConfidence != null) {
    params.set("min_confidence", String(options.minConfidence));
  }
  return requestJson<DetectionEventSearchResult>(`/events/?${params.toString()}`);
}

export function fetchViolationsFeed(options?: ViolationFeedParams): Promise<ApiResult<ViolationSearchResult>> {
  const params = new URLSearchParams();
  params.set("limit", String(options?.limit ?? 20));
  if (options?.offset) {
    params.set("offset", String(options.offset));
  }
  if (options?.cameraId) {
    params.set("camera_id", options.cameraId);
  }
  if (options?.violationType) {
    params.set("violation_type", options.violationType);
  }
  if (options?.status) {
    params.set("status", options.status);
  }
  if (options?.occurredAfter) {
    params.set("occurred_after", options.occurredAfter);
  }
  if (options?.occurredBefore) {
    params.set("occurred_before", options.occurredBefore);
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

export function fetchEventSummaryTotals(options?: {
  cameraId?: string | null;
  occurredAfter?: string;
  occurredBefore?: string;
}): Promise<ApiResult<EventSummaryTotalsApi>> {
  const params = new URLSearchParams();
  if (options?.cameraId) {
    params.set("camera_id", options.cameraId);
  }
  if (options?.occurredAfter) {
    params.set("occurred_after", options.occurredAfter);
  }
  if (options?.occurredBefore) {
    params.set("occurred_before", options.occurredBefore);
  }
  const qs = params.toString();
  return requestJson<EventSummaryTotalsApi>(`/events/summary/totals${qs ? `?${qs}` : ""}`);
}

export function fetchViolationSummaryTotals(options?: {
  cameraId?: string | null;
  occurredAfter?: string;
  occurredBefore?: string;
}): Promise<ApiResult<ViolationSummaryTotalsApi>> {
  const params = new URLSearchParams();
  if (options?.cameraId) {
    params.set("camera_id", options.cameraId);
  }
  if (options?.occurredAfter) {
    params.set("occurred_after", options.occurredAfter);
  }
  if (options?.occurredBefore) {
    params.set("occurred_before", options.occurredBefore);
  }
  const qs = params.toString();
  return requestJson<ViolationSummaryTotalsApi>(`/violations/summary/totals${qs ? `?${qs}` : ""}`);
}