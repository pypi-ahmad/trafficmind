import "server-only";

import { requestJson } from "@/features/shared/request-json";
import type { ApiResult } from "@/features/operations/types";
import type { CaseExportListResult, ExportListParams } from "@/features/reports/types";

export function fetchExports(options?: ExportListParams): Promise<ApiResult<CaseExportListResult>> {
  const params = new URLSearchParams();
  params.set("limit", String(options?.limit ?? 50));
  if (options?.offset) {
    params.set("offset", String(options.offset));
  }
  if (options?.subjectKind) {
    params.set("subject_kind", options.subjectKind);
  }
  if (options?.status) {
    params.set("status", options.status);
  }
  return requestJson<CaseExportListResult>(`/exports?${params.toString()}`);
}
