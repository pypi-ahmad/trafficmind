import type {
  AccessPermission,
  AccessPolicyRead,
  EvidenceAccessResolution,
  EvidenceAccessRole,
  EvidenceAsset,
  EvidenceManifestRead,
} from "@/features/evidence/types";

/* -------------------------------------------------------------------------- */
/*  Privacy badge                                                              */
/* -------------------------------------------------------------------------- */

function viewBadge(view: "original" | "redacted") {
  const isRedacted = view === "redacted";
  return (
    <span
      className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${
        isRedacted
          ? "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300"
          : "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300"
      }`}
    >
      {isRedacted ? "Redacted" : "Original"}
    </span>
  );
}

/* -------------------------------------------------------------------------- */
/*  Access resolution panel                                                    */
/* -------------------------------------------------------------------------- */

function AccessResolutionPanel({ access }: { access: EvidenceAccessResolution }) {
  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 p-3 space-y-2 text-sm">
      <div className="flex items-center gap-2">
        <span className="font-medium text-gray-600 dark:text-gray-300">Active view:</span>
        {viewBadge(access.resolved_view)}
      </div>
      <div className="flex items-center gap-2">
        <span className="font-medium text-gray-600 dark:text-gray-300">Role:</span>
        <span className="text-gray-800 dark:text-gray-200">{access.requested_role}</span>
      </div>
      <div className="flex items-center gap-2">
        <span className="font-medium text-gray-600 dark:text-gray-300">Original access:</span>
        <span className={access.original_access_authorized ? "text-green-700 dark:text-green-400" : "text-amber-700 dark:text-amber-400"}>
          {access.original_access_authorized ? "Authorized" : "Restricted"}
        </span>
      </div>
      {access.resolution_notes.length > 0 && (
        <ul className="list-disc list-inside text-xs text-gray-500 dark:text-gray-400 space-y-0.5">
          {access.resolution_notes.map((note, i) => (
            <li key={i}>{note}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Redaction target pills                                                     */
/* -------------------------------------------------------------------------- */

function RedactionTargetPills({ targets }: { targets: string[] }) {
  if (targets.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1">
      {targets.map((target) => (
        <span
          key={target}
          className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300"
        >
          {target.replace(/_/g, " ")}
        </span>
      ))}
    </div>
  );
}

function formatAccessLabel(value: string) {
  return value.replace(/_/g, " ");
}

function permissionClass(permission: AccessPermission): string {
  switch (permission) {
    case "view_unredacted_evidence":
      return "bg-[rgba(216,87,75,0.12)] text-[var(--color-danger)]";
    case "manage_policy_settings":
    case "manage_watchlists":
      return "bg-[rgba(209,129,43,0.16)] text-[rgba(123,72,19,1)]";
    case "approve_reject_incidents":
    case "view_sensitive_audit_trail":
      return "bg-[rgba(77,151,177,0.14)] text-[rgba(29,91,112,1)]";
    case "export_evidence":
      return "bg-[rgba(56,183,118,0.14)] text-[var(--color-ok-ink)]";
    case "view_redacted_evidence":
    default:
      return "bg-[rgba(19,32,41,0.08)] text-[rgba(19,32,41,0.78)]";
  }
}

function PermissionPill({ permission }: { permission: AccessPermission }) {
  return (
    <span className={`rounded-full px-3 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.16em] ${permissionClass(permission)}`}>
      {formatAccessLabel(permission)}
    </span>
  );
}

/* -------------------------------------------------------------------------- */
/*  Asset list                                                                 */
/* -------------------------------------------------------------------------- */

function AssetList({ assets }: { assets: EvidenceAsset[] }) {
  if (assets.length === 0) {
    return <p className="text-xs text-gray-400">No visible assets.</p>;
  }
  return (
    <ul className="divide-y divide-gray-100 dark:divide-gray-700 text-xs">
      {assets.map((asset) => (
        <li key={asset.asset_key} className="py-1.5 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <span className="truncate font-mono text-gray-700 dark:text-gray-300">{asset.label}</span>
            {viewBadge(asset.asset_view)}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <span className="text-gray-400">{asset.redaction_status.replace(/_/g, " ")}</span>
            <RedactionTargetPills targets={asset.redaction_targets} />
          </div>
        </li>
      ))}
    </ul>
  );
}

/* -------------------------------------------------------------------------- */
/*  Main component                                                            */
/* -------------------------------------------------------------------------- */

export function EvidencePrivacyStatus({ manifest }: { manifest: EvidenceManifestRead }) {
  const plannedAssets = manifest.visible_assets.filter(
    (asset) => asset.redaction_status === "planned",
  ).length;

  return (
    <section className="space-y-3">
      <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-200">
        Privacy &amp; Redaction Status
      </h3>

      <AccessResolutionPanel access={manifest.access} />

      {manifest.has_restricted_original_assets && (
        <p className="text-xs text-amber-600 dark:text-amber-400">
          Original assets exist but are restricted under the current access policy.
        </p>
      )}

      {plannedAssets > 0 && (
        <p className="text-xs text-gray-500 dark:text-gray-400">
          {plannedAssets} visible asset{plannedAssets === 1 ? " is" : "s are"} still declared as planned redactions. The policy boundary is active, but the media pipeline has not materialized those redacted files yet.
        </p>
      )}

      <details className="text-sm">
        <summary className="cursor-pointer font-medium text-gray-600 dark:text-gray-300">
          Visible assets ({manifest.visible_assets.length})
        </summary>
        <div className="mt-1">
          <AssetList assets={manifest.visible_assets} />
        </div>
      </details>
    </section>
  );
}

export function EvidencePrivacyPolicyPreview({
  policy,
  selectedRole,
  error,
}: {
  policy: AccessPolicyRead | null;
  selectedRole: EvidenceAccessRole;
  error?: string | null;
}) {
  return (
    <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-6 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
      <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">
        Evidence privacy and access
      </p>
      <h2 className="mt-3 text-2xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">
        Request-declared roles now map to explicit sensitive-evidence permissions
      </h2>
      <p className="mt-3 text-sm leading-6 text-[rgba(19,32,41,0.74)]">
        Redacted evidence is still the default operator-facing view, but the backend now enforces separate permissions for original evidence, exports, incident review actions, watchlists, policy settings, and sensitive audit trails.
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        {viewBadge("redacted")}
        <span className="rounded-full bg-[rgba(19,32,41,0.08)] px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-[rgba(19,32,41,0.72)]">
          Original by request for privacy_officer / evidence_admin
        </span>
        <span className="rounded-full bg-[rgba(77,151,177,0.14)] px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-[rgba(29,91,112,1)]">
          Previewing {formatAccessLabel(selectedRole)}
        </span>
      </div>

      {policy ? (
        <>
          <div className="mt-6 grid gap-4 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
            <div className="rounded-[1.4rem] bg-[rgba(243,237,228,0.86)] p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-[rgba(19,32,41,0.5)]">Effective permissions</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {policy.current_permissions.map((permission) => (
                  <PermissionPill key={permission} permission={permission} />
                ))}
              </div>
              <p className="mt-3 text-sm leading-6 text-[rgba(19,32,41,0.72)]">
                The frontend preview mirrors the same backend policy returned by <span className="font-mono">GET /api/v1/access/policy</span>. It is descriptive only; the actual allow and deny decisions still happen server-side.
              </p>
            </div>

            <div className="rounded-[1.4rem] bg-[rgba(231,242,244,0.72)] p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-[rgba(19,32,41,0.5)]">Policy notes</p>
              <ul className="mt-3 space-y-2 text-sm leading-6 text-[rgba(19,32,41,0.72)]">
                {policy.notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </div>
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {policy.roles.map((rolePolicy) => {
              const isCurrent = rolePolicy.role === policy.current_role;
              return (
                <div
                  key={rolePolicy.role}
                  className={`rounded-[1.4rem] border p-4 ${
                    isCurrent
                      ? "border-[rgba(19,32,41,0.22)] bg-[rgba(255,255,255,0.92)]"
                      : "border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.7)]"
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-xs uppercase tracking-[0.18em] text-[rgba(19,32,41,0.5)]">Role</p>
                      <p className="mt-2 text-lg font-semibold tracking-[-0.03em] text-[var(--color-ink)]">
                        {formatAccessLabel(rolePolicy.role)}
                      </p>
                    </div>
                    {isCurrent ? (
                      <span className="rounded-full bg-[rgba(19,32,41,0.08)] px-3 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-[rgba(19,32,41,0.72)]">
                        current
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-3 text-sm leading-6 text-[rgba(19,32,41,0.72)]">{rolePolicy.description}</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {rolePolicy.permissions.map((permission) => (
                      <PermissionPill key={`${rolePolicy.role}-${permission}`} permission={permission} />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>

          <div className="mt-4 rounded-[1.4rem] bg-[rgba(243,237,228,0.86)] p-4">
            <p className="text-xs uppercase tracking-[0.18em] text-[rgba(19,32,41,0.5)]">Sensitive action requirements</p>
            <div className="mt-3 grid gap-3 lg:grid-cols-2">
              {policy.requirements.map((requirement) => (
                <div key={requirement.action} className="rounded-[1.2rem] bg-[rgba(255,255,255,0.72)] p-4">
                  <p className="font-semibold text-[var(--color-ink)]">{requirement.action}</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {requirement.permissions.map((permission) => (
                      <PermissionPill key={`${requirement.action}-${permission}`} permission={permission} />
                    ))}
                  </div>
                  {requirement.note ? (
                    <p className="mt-3 text-sm leading-6 text-[rgba(19,32,41,0.72)]">{requirement.note}</p>
                  ) : null}
                </div>
              ))}
            </div>
          </div>
        </>
      ) : (
        <div className="mt-6 rounded-[1.4rem] border border-[rgba(216,87,75,0.14)] bg-[rgba(255,244,241,0.92)] p-4">
          <p className="text-sm font-semibold text-[var(--color-danger)]">Access policy preview unavailable</p>
          <p className="mt-2 text-sm leading-6 text-[rgba(19,32,41,0.74)]">
            {error ?? "The frontend could not reach the access policy endpoint, so this page is falling back to the static privacy summary only."}
          </p>
        </div>
      )}

      <ul className="mt-4 space-y-2 text-sm leading-6 text-[rgba(19,32,41,0.74)]">
        <li>Original evidence requests are denied unless the role also has view unredacted evidence permission.</li>
        <li>Redacted assets keep provenance through <span className="font-mono">derived_from_asset_key</span>.</li>
        <li>Some redacted asset references remain planned until the masking pipeline materializes them.</li>
      </ul>
    </section>
  );
}
