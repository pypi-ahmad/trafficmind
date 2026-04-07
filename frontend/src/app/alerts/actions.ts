"use server";

import { revalidatePath } from "next/cache";

import { getApiBaseUrl } from "@/features/operations/config";
import { userFriendlyError } from "@/features/shared/format-labels";

export type AlertActionKind = "acknowledge" | "resolve";

export interface AlertActionState {
  ok: boolean;
  error: string | null;
  alertId: string | null;
  action: AlertActionKind | null;
}

export const ALERT_ACTION_INITIAL: AlertActionState = {
  ok: false,
  error: null,
  alertId: null,
  action: null,
};

/**
 * Server action: POST /api/v1/alerts/{id}/{action}
 *
 * Expects form data with:
 *   - alertId (hidden)
 *   - action: "acknowledge" | "resolve"
 *   - actor: operator identifier (optional but encouraged)
 *   - note: optional note
 */
export async function performAlertAction(
  _prev: AlertActionState,
  formData: FormData,
): Promise<AlertActionState> {
  const alertId = formData.get("alertId");
  const action = formData.get("action");
  const actor = formData.get("actor");
  const note = formData.get("note");

  if (typeof alertId !== "string" || !alertId) {
    return { ...ALERT_ACTION_INITIAL, error: "Missing alert ID." };
  }
  if (action !== "acknowledge" && action !== "resolve") {
    return { ...ALERT_ACTION_INITIAL, error: "Invalid action." };
  }

  const body: Record<string, string> = {};
  if (typeof actor === "string" && actor.trim()) {
    body.actor = actor.trim();
  }
  if (typeof note === "string" && note.trim()) {
    body.note = note.trim();
  }

  try {
    const response = await fetch(
      `${getApiBaseUrl()}/alerts/${encodeURIComponent(alertId)}/${action}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(body),
        cache: "no-store",
      },
    );

    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      const detail =
        payload && typeof payload === "object" && "detail" in payload && typeof payload.detail === "string"
          ? payload.detail
          : `${response.status} ${response.statusText}`;
      return { ok: false, error: userFriendlyError(detail), alertId, action };
    }

    revalidatePath("/alerts");
    return { ok: true, error: null, alertId, action };
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Unknown network error";
    return { ok: false, error: userFriendlyError(msg), alertId, action };
  }
}
