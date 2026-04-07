"use server";

import { revalidatePath } from "next/cache";

import { getApiBaseUrl } from "@/features/operations/config";
import { userFriendlyError } from "@/features/shared/format-labels";

export interface ReviewActionState {
  ok: boolean;
  error: string | null;
  violationId: string | null;
}

const INITIAL_STATE: ReviewActionState = { ok: false, error: null, violationId: null };

/**
 * Server action: POST /api/v1/violations/{id}/review
 *
 * Expects form data with:
 *   - violationId (hidden)
 *   - action: "approve" | "reject"
 *   - actor: operator identifier
 *   - note: optional review note
 */
export async function reviewViolation(
  _prev: ReviewActionState,
  formData: FormData,
): Promise<ReviewActionState> {
  const violationId = formData.get("violationId");
  const action = formData.get("action");
  const actor = formData.get("actor");
  const note = formData.get("note");

  if (typeof violationId !== "string" || !violationId) {
    return { ...INITIAL_STATE, error: "Missing violation ID." };
  }
  if (action !== "approve" && action !== "reject") {
    return { ...INITIAL_STATE, error: "Invalid action." };
  }
  if (typeof actor !== "string" || !actor.trim()) {
    return { ...INITIAL_STATE, error: "Please enter your name before submitting." };
  }

  const body: Record<string, string> = {
    actor: actor.trim(),
    action,
  };
  if (typeof note === "string" && note.trim()) {
    body.note = note.trim();
  }

  try {
    const response = await fetch(
      `${getApiBaseUrl()}/violations/${encodeURIComponent(violationId)}/review?access_role=reviewer`,
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
      return { ok: false, error: userFriendlyError(detail), violationId };
    }

    revalidatePath("/cases");
    return { ok: true, error: null, violationId };
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Unknown network error";
    return { ok: false, error: userFriendlyError(msg), violationId };
  }
}
