import "server-only";

import { requestJson } from "@/features/shared/request-json";
import type { EvaluationSummaryResponseApi } from "@/features/evaluation/types";
import type { ApiResult } from "@/features/operations/types";

export function fetchEvaluationSummary(): Promise<ApiResult<EvaluationSummaryResponseApi>> {
  return requestJson<EvaluationSummaryResponseApi>("/analytics/evaluation");
}