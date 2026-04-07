import "server-only";

import { requestJson } from "@/features/shared/request-json";
import type { ApiResult } from "@/features/operations/types";
import type { AlertFeedParams, AlertListResult } from "@/features/alerts/types";

export function fetchAlerts(options?: AlertFeedParams): Promise<ApiResult<AlertListResult>> {
  const params = new URLSearchParams();
  params.set("limit", String(options?.limit ?? 50));
  if (options?.offset) {
    params.set("offset", String(options.offset));
  }
  if (options?.status) {
    params.set("status", options.status);
  }
  if (options?.severity) {
    params.set("severity", options.severity);
  }
  if (options?.sourceKind) {
    params.set("source_kind", options.sourceKind);
  }
  return requestJson<AlertListResult>(`/alerts/?${params.toString()}`);
}
