"use client";

import { useActionState, useEffect, useRef, useState } from "react";

import { performAlertAction, ALERT_ACTION_INITIAL } from "@/app/alerts/actions";
import type { AlertActionKind } from "@/app/alerts/actions";

const STORAGE_KEY = "trafficmind:reviewer-name";

const btnBase =
  "rounded-full px-3 py-1 text-xs font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed";
const ackBtn = `${btnBase} border border-[rgba(23,57,69,0.18)] text-[var(--color-ink)] hover:bg-[rgba(23,57,69,0.06)]`;
const resolveBtn = `${btnBase} border border-[rgba(56,183,118,0.30)] text-[var(--color-ok-ink)] hover:bg-[rgba(56,183,118,0.10)]`;

export function AlertActions({ alertId, currentStatus }: { alertId: string; currentStatus: string }) {
  const [expanded, setExpanded] = useState(false);
  const [selectedAction, setSelectedAction] = useState<AlertActionKind | null>(null);
  const [state, formAction, pending] = useActionState(performAlertAction, ALERT_ACTION_INITIAL);
  const [savedName, setSavedName] = useState(() => {
    if (typeof window === "undefined") return "";
    try { return localStorage.getItem(STORAGE_KEY) ?? ""; } catch { return ""; }
  });
  const actorRef = useRef<HTMLInputElement>(null);

  /* Persist reviewer name on successful action */
  useEffect(() => {
    if (state.ok && state.alertId === alertId && actorRef.current) {
      const name = actorRef.current.value.trim();
      if (name) {
        try { localStorage.setItem(STORAGE_KEY, name); } catch { /* ignore */ }
        setSavedName(name);
      }
    }
  }, [state.ok, state.alertId, alertId]);

  const justActed = state.ok && state.alertId === alertId;
  const failed = !state.ok && state.error && state.alertId === alertId;

  /* Already acted — show result */
  if (justActed) {
    return (
      <span className="rounded-full bg-[rgba(56,183,118,0.12)] px-3 py-1 text-xs font-medium text-[var(--color-ok-ink)]">
        ✓ {state.action === "acknowledge" ? "Acknowledged" : "Resolved"}
      </span>
    );
  }

  /* Terminal states — no actions available */
  if (currentStatus === "resolved" || currentStatus === "suppressed") {
    return null;
  }

  /* Determine which actions are available based on current status */
  const canAcknowledge = currentStatus === "new" || currentStatus === "escalated";
  const canResolve = currentStatus === "new" || currentStatus === "acknowledged" || currentStatus === "escalated";

  if (!canAcknowledge && !canResolve) {
    return null;
  }

  /* Collapsed: show action trigger buttons */
  if (!expanded) {
    return (
      <div className="flex items-center gap-2">
        {canAcknowledge ? (
          <button
            type="button"
            onClick={() => { setSelectedAction("acknowledge"); setExpanded(true); }}
            className={ackBtn}
          >
            Acknowledge
          </button>
        ) : null}
        {canResolve ? (
          <button
            type="button"
            onClick={() => { setSelectedAction("resolve"); setExpanded(true); }}
            className={resolveBtn}
          >
            Resolve
          </button>
        ) : null}
      </div>
    );
  }

  /* Expanded: show inline form */
  return (
    <form action={formAction} className="mt-2 rounded-[1.25rem] border border-[rgba(23,57,69,0.10)] bg-[rgba(246,240,229,0.60)] p-3">
      <input type="hidden" name="alertId" value={alertId} />
      <input type="hidden" name="action" value={selectedAction ?? ""} />

      <div className="flex items-center gap-2 text-xs text-[rgba(19,32,41,0.68)]">
        <span className="font-semibold">
          {selectedAction === "acknowledge" ? "Acknowledge this alert" : "Resolve this alert"}
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
          placeholder="Your name (optional)"
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
        <button
          type="submit"
          disabled={pending}
          className={selectedAction === "acknowledge" ? ackBtn : resolveBtn}
        >
          {pending ? "Submitting…" : selectedAction === "acknowledge" ? "Acknowledge" : "Resolve"}
        </button>
      </div>

      {failed ? (
        <p className="mt-2 text-xs text-[var(--color-danger)]">{state.error}</p>
      ) : null}
    </form>
  );
}
