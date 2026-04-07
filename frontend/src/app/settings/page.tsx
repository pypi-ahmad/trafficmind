import Link from "next/link";

import { fetchAccessPolicy } from "@/features/evidence/api";
import type { AccessPolicyRead } from "@/features/evidence/types";
import { titleCase } from "@/features/shared/format-labels";

export const dynamic = "force-dynamic";

export default async function SettingsPage() {
  const policyResult = await fetchAccessPolicy("operator");
  const policy: AccessPolicyRead | null = policyResult.ok ? policyResult.data : null;

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-6xl flex-col gap-6 px-4 py-8 sm:px-6">
      {/* ── Hero ─────────────────────────────────────── */}
      <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[linear-gradient(135deg,rgba(244,238,224,0.94),rgba(231,242,244,0.92))] p-8 shadow-[0_24px_60px_rgba(18,32,41,0.08)]">
        <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Administration</p>
        <h1 className="mt-3 text-4xl font-semibold tracking-[-0.06em] text-[var(--color-ink)]">Settings</h1>
        <p className="mt-4 max-w-3xl text-base leading-7 text-[rgba(19,32,41,0.74)]">
          System configuration, access control policy, and administrative tools. Settings changes are managed by system administrators.
        </p>
      </section>

      {/* ── Access policy ───────────────────────────────── */}
      <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-6 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
        <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Access Control Policy</p>
        {policy ? (
          <>
            <p className="mt-3 text-sm text-[rgba(19,32,41,0.74)]">
              Policy: <span className="font-medium text-[var(--color-ink)]">{policy.policy_name}</span>
              {" · "}Current role: <span className="font-medium text-[var(--color-ink)]">{titleCase(policy.current_role)}</span>
            </p>

            {/* Role → permission matrix */}
            <div className="mt-5">
              <h3 className="text-sm font-semibold text-[var(--color-ink)]">Roles &amp; Permissions</h3>
              <div className="mt-3 space-y-3">
                {policy.roles.map((role) => (
                  <div key={role.role} className="rounded-[1.5rem] bg-[rgba(243,237,228,0.72)] p-4">
                    <div className="flex items-center justify-between">
                      <p className="font-semibold text-[var(--color-ink)]">{titleCase(role.role)}</p>
                      <span className="rounded-full bg-[rgba(19,32,41,0.08)] px-3 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-[rgba(19,32,41,0.72)]">
                        {role.permissions.length} permission{role.permissions.length === 1 ? "" : "s"}
                      </span>
                    </div>
                    {role.description ? (
                      <p className="mt-1 text-sm text-[rgba(19,32,41,0.68)]">{role.description}</p>
                    ) : null}
                    <div className="mt-3 flex flex-wrap gap-2">
                      {role.permissions.map((perm) => (
                        <span key={perm} className="rounded-full border border-[rgba(23,57,69,0.10)] bg-[rgba(255,255,255,0.64)] px-3 py-1 text-xs text-[rgba(19,32,41,0.72)]">
                          {titleCase(perm)}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Action requirements */}
            <div className="mt-6">
              <h3 className="text-sm font-semibold text-[var(--color-ink)]">Protected Actions</h3>
              <div className="mt-3 divide-y divide-[rgba(23,57,69,0.08)]">
                {policy.requirements.map((req) => (
                  <div key={req.action} className="py-3 first:pt-0 last:pb-0">
                    <p className="font-medium text-[var(--color-ink)]">{titleCase(req.action)}</p>
                    <p className="mt-1 text-xs text-[rgba(19,32,41,0.6)]">
                      Requires: {req.permissions.map((p) => titleCase(p)).join(", ")}
                    </p>
                    {req.note ? <p className="mt-0.5 text-xs text-[rgba(19,32,41,0.52)]">{req.note}</p> : null}
                  </div>
                ))}
              </div>
            </div>

            {policy.notes.length > 0 ? (
              <div className="mt-6 rounded-[1.5rem] border border-dashed border-[rgba(23,57,69,0.16)] p-4">
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[rgba(19,32,41,0.56)]">Policy Notes</p>
                <ul className="mt-2 space-y-1 text-sm leading-6 text-[rgba(19,32,41,0.72)]">
                  {policy.notes.map((note, i) => (
                    <li key={i}>- {note}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </>
        ) : (
          <div className="mt-3">
            <p className="text-sm text-[rgba(19,32,41,0.72)]">
              {policyResult.error ?? "Access policy could not be loaded. Try reloading the page."}
            </p>
          </div>
        )}
      </section>

      {/* ── Quick links ─────────────────────────────────── */}
      <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-6 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
        <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Admin Tools</p>
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <Link href="/evaluation" className="rounded-[1.5rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(243,237,228,0.72)] p-4 transition-colors hover:border-[rgba(23,57,69,0.24)]">
            <p className="font-semibold text-[var(--color-ink)]">Model Evaluation</p>
            <p className="mt-1 text-sm text-[rgba(19,32,41,0.68)]">Review benchmark test results for detection, tracking, OCR, and rule accuracy.</p>
          </Link>
          <Link href="/reports" className="rounded-[1.5rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(243,237,228,0.72)] p-4 transition-colors hover:border-[rgba(23,57,69,0.24)]">
            <p className="font-semibold text-[var(--color-ink)]">Case Exports</p>
            <p className="mt-1 text-sm text-[rgba(19,32,41,0.68)]">Browse and download audit-ready case export bundles.</p>
          </Link>
        </div>
      </section>
    </main>
  );
}
