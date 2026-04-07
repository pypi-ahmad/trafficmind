"use client";

import { useActionState, useState } from "react";

import { reviewViolation } from "@/app/cases/actions";
import type { ReviewActionState } from "@/app/cases/actions";

const INITIAL: ReviewActionState = { ok: false, error: null, violationId: null };

const btnBase =
  "rounded-full px-3 py-1 text-xs font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed";
const confirmBtn = `${btnBase} border border-[rgba(56,183,118,0.30)] text-[var(--color-ok-ink)] hover:bg-[rgba(56,183,118,0.10)]`;
const dismissBtn = `${btnBase} border border-[rgba(240,90,79,0.20)] text-[var(--color-danger)] hover:bg-[rgba(240,90,79,0.06)]`;

export function ViolationActions({ violationId, currentStatus }: { violationId: string; currentStatus: string }) {
  const [expanded, setExpanded] = useState(false);
  const [selectedAction, setSelectedAction] = useState<"approve" | "reject" | null>(null);
  const [state, formAction, pending] = useActionState(reviewViolation, INITIAL);

  const justReviewed = state.ok && state.violationId === violationId;
  const failed = !state.ok && state.error && state.violationId === violationId;

  /* Already reviewed — show result instead of buttons */
  if (justReviewed) {
    return (
      <span className="rounded-full bg-[rgba(56,183,118,0.12)] px-3 py-1 text-xs font-medium text-[var(--color-ok-ink)]">
        ✓ {selectedAction === "approve" ? "Confirmed" : "Dismissed"}
      </span>
    );
  }

  /* Violation already in a terminal state */
  if (currentStatus === "confirmed" || currentStatus === "dismissed") {
    return null;
  }

  /* Collapsed: show action trigger buttons */
  if (!expanded) {
    return (
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => { setSelectedAction("approve"); setExpanded(true); }}
          className={confirmBtn}
        >
          Confirm
        </button>
        <button
          type="button"
          onClick={() => { setSelectedAction("reject"); setExpanded(true); }}
          className={dismissBtn}
        >
          Dismiss
        </button>
      </div>
    );
  }

  /* Expanded: show review form */
  return (
    <form action={formAction} className="mt-2 rounded-[1.25rem] border border-[rgba(23,57,69,0.10)] bg-[rgba(246,240,229,0.60)] p-3">
      <input type="hidden" name="violationId" value={violationId} />
      <input type="hidden" name="action" value={selectedAction ?? ""} />

      <div className="flex items-center gap-2 text-xs text-[rgba(19,32,41,0.68)]">
        <span className="font-semibold">
          {selectedAction === "approve" ? "Confirm this violation" : "Dismiss this violation"}
        </span>
        <button type="button" onClick={() => setExpanded(false)} className="ml-auto text-[rgba(19,32,41,0.44)] hover:text-[var(--color-ink)]">
          Cancel
        </button>
      </div>

      <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_2fr_auto]">
        <input
          name="actor"
          type="text"
          placeholder="Your name"
          required
          minLength={1}
          maxLength={120}
          className="rounded-lg border border-[rgba(23,57,69,0.14)] bg-white px-3 py-1.5 text-xs text-[var(--color-ink)] placeholder:text-[rgba(19,32,41,0.36)] focus:border-[rgba(23,57,69,0.32)] focus:outline-none"
        />
        <input
          name="note"
          type="text"
          placeholder="Optional note"
          maxLength={500}
          className="rounded-lg border border-[rgba(23,57,69,0.14)] bg-white px-3 py-1.5 text-xs text-[var(--color-ink)] placeholder:text-[rgba(19,32,41,0.36)] focus:border-[rgba(23,57,69,0.32)] focus:outline-none"
        />
        <button
          type="submit"
          disabled={pending}
          className={selectedAction === "approve" ? confirmBtn : dismissBtn}
        >
          {pending ? "Submitting…" : selectedAction === "approve" ? "Confirm" : "Dismiss"}
        </button>
      </div>

      {failed ? (
        <p className="mt-2 text-xs text-[var(--color-danger)]">{state.error}</p>
      ) : null}
    </form>
  );
}
