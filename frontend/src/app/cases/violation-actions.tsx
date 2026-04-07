"use client";

import { useActionState, useEffect, useRef, useState } from "react";

import { reviewViolation } from "@/app/cases/actions";
import type { ReviewActionState } from "@/app/cases/actions";

const INITIAL: ReviewActionState = { ok: false, error: null, violationId: null };
const STORAGE_KEY = "trafficmind:reviewer-name";

const btnBase =
  "rounded-full px-3 py-1 text-xs font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed";
const confirmBtn = `${btnBase} border border-[rgba(56,183,118,0.30)] text-[var(--color-ok-ink)] hover:bg-[rgba(56,183,118,0.10)]`;
const dismissBtn = `${btnBase} border border-[rgba(240,90,79,0.20)] text-[var(--color-danger)] hover:bg-[rgba(240,90,79,0.06)]`;

export function ViolationActions({ violationId, currentStatus }: { violationId: string; currentStatus: string }) {
  const [expanded, setExpanded] = useState(false);
  const [selectedAction, setSelectedAction] = useState<"approve" | "reject" | null>(null);
  const [confirmingDismiss, setConfirmingDismiss] = useState(false);
  const [state, formAction, pending] = useActionState(reviewViolation, INITIAL);
  const [savedName, setSavedName] = useState(() => {
    if (typeof window === "undefined") return "";
    try { return localStorage.getItem(STORAGE_KEY) ?? ""; } catch { return ""; }
  });
  const actorRef = useRef<HTMLInputElement>(null);
  const formRef = useRef<HTMLFormElement>(null);

  /* Persist reviewer name on successful review */
  useEffect(() => {
    if (state.ok && state.violationId === violationId && actorRef.current) {
      const name = actorRef.current.value.trim();
      if (name) {
        try { localStorage.setItem(STORAGE_KEY, name); } catch { /* ignore */ }
        setSavedName(name);
      }
    }
  }, [state.ok, state.violationId, violationId]);

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
    <form ref={formRef} action={formAction} className="mt-2 rounded-[1.25rem] border border-[rgba(23,57,69,0.10)] bg-[rgba(246,240,229,0.60)] p-3">
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
          ref={actorRef}
          name="actor"
          type="text"
          placeholder="Your name"
          required
          minLength={1}
          maxLength={120}
          defaultValue={savedName}
          className="rounded-lg border border-[rgba(23,57,69,0.14)] bg-white px-3 py-1.5 text-xs text-[var(--color-ink)] placeholder:text-[rgba(19,32,41,0.36)] focus:border-[rgba(23,57,69,0.32)] focus:outline-none"
        />
        <input
          name="note"
          type="text"
          placeholder="Optional note"
          maxLength={500}
          className="rounded-lg border border-[rgba(23,57,69,0.14)] bg-white px-3 py-1.5 text-xs text-[var(--color-ink)] placeholder:text-[rgba(19,32,41,0.36)] focus:border-[rgba(23,57,69,0.32)] focus:outline-none"
        />
        {selectedAction === "approve" ? (
          <button
            type="submit"
            disabled={pending}
            className={confirmBtn}
          >
            {pending ? "Submitting…" : "Confirm"}
          </button>
        ) : !confirmingDismiss ? (
          <button
            type="button"
            onClick={() => {
              if (formRef.current?.reportValidity()) setConfirmingDismiss(true);
            }}
            className={dismissBtn}
          >
            Dismiss
          </button>
        ) : (
          <button
            type="submit"
            disabled={pending}
            className={dismissBtn}
          >
            {pending ? "Submitting…" : "Yes, dismiss"}
          </button>
        )}
      </div>

      {confirmingDismiss && !pending ? (
        <p className="mt-2 flex items-center gap-2 text-xs text-[var(--color-danger)]">
          This will permanently dismiss this violation.
          <button
            type="button"
            onClick={() => setConfirmingDismiss(false)}
            className="font-medium text-[rgba(19,32,41,0.56)] hover:text-[var(--color-ink)]"
          >
            Cancel
          </button>
        </p>
      ) : null}

      {failed ? (
        <p className="mt-2 text-xs text-[var(--color-danger)]">{state.error}</p>
      ) : null}
    </form>
  );
}
