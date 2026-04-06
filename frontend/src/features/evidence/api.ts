import "server-only";

import type { AccessPolicyRead, EvidenceAccessRole } from "@/features/evidence/types";
import type { ApiResult } from "@/features/operations/types";
import { requestJson } from "@/features/shared/request-json";

export function fetchAccessPolicy(accessRole: EvidenceAccessRole): Promise<ApiResult<AccessPolicyRead>> {
  const params = new URLSearchParams({ access_role: accessRole });
  return requestJson<AccessPolicyRead>(`/access/policy?${params.toString()}`);
}