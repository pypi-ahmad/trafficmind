import "server-only";

import { getApiBaseUrl } from "@/features/operations/config";
import type { ApiResult } from "@/features/operations/types";

export async function requestJson<T>(path: string, init?: RequestInit): Promise<ApiResult<T>> {
  try {
    const headers = new Headers(init?.headers);
    if (!headers.has("Accept")) {
      headers.set("Accept", "application/json");
    }

    const response = await fetch(`${getApiBaseUrl()}${path}`, {
      ...init,
      headers,
      cache: "no-store",
    });

    const payload = (await response.json().catch(() => null)) as T | { detail?: string } | null;

    if (!response.ok) {
      const detail =
        payload && typeof payload === "object" && "detail" in payload && typeof payload.detail === "string"
          ? payload.detail
          : `${response.status} ${response.statusText}`;
      return {
        ok: false,
        status: response.status,
        data: null,
        error: detail,
      };
    }

    return {
      ok: true,
      status: response.status,
      data: payload as T,
      error: null,
    };
  } catch (error) {
    return {
      ok: false,
      status: null,
      data: null,
      error: error instanceof Error ? error.message : "Unknown network error",
    };
  }
}