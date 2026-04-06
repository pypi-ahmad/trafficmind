# Privacy Masking & Evidence Redaction

## Overview

TrafficMind includes a privacy masking and evidence redaction **foundation** plus a coarse sensitive-access control layer. The system defaults to redacted views for most users, preserves provenance between original and redacted asset references, and now gates sensitive evidence, export, review, watchlist, alert-policy, and audit-facing routes through explicit permissions.

> **Honest Note:** This is a policy and schema foundation. It declares _what_ to redact, _for whom_, and _where_, but a production pixel-level masking pipeline (face blurring, plate obscuration on actual media) needs to be built on top of this foundation.

## Architecture

### Evidence Privacy Policy

Every evidence manifest carries an `EvidencePrivacyPolicy` that declares:

| Setting | Default | Meaning |
|---|---|---|
| `default_asset_view` | `redacted` | API responses default to the redacted view |
| `default_export_view` | `redacted` | Export bundles default to the redacted view |
| `preserve_original_assets` | `true` | Original asset references are kept for authorized roles |
| `authorized_original_roles` | `privacy_officer`, `evidence_admin` | Only these roles can see original assets |
| `mask_by_default_roles` | `operator`, `reviewer`, `supervisor`, `export_service` | These roles always receive redacted views |
| `redaction_targets` | `face`, `license_plate`, `personally_identifying_detail` | What types of content are targeted for redaction |

### Access Roles

| Role | Original Access | Default View |
|---|---|---|
| `operator` | No | Redacted |
| `reviewer` | No | Redacted |
| `supervisor` | No | Redacted |
| `export_service` | No | Redacted |
| `privacy_officer` | Yes | Redacted (can request original) |
| `evidence_admin` | Yes | Redacted (can request original) |

### Sensitive Access Permissions

The backend now resolves each `EvidenceAccessRole` into a coarse permission set through `services/access_control/policy.py`.

| Role | Permissions |
|---|---|
| `operator` | `view_redacted_evidence` |
| `reviewer` | `view_redacted_evidence`, `approve_reject_incidents`, `view_sensitive_audit_trail` |
| `supervisor` | `view_redacted_evidence`, `export_evidence`, `approve_reject_incidents`, `manage_watchlists`, `view_sensitive_audit_trail` |
| `privacy_officer` | `view_redacted_evidence`, `view_unredacted_evidence`, `export_evidence`, `view_sensitive_audit_trail` |
| `evidence_admin` | `view_redacted_evidence`, `view_unredacted_evidence`, `export_evidence`, `approve_reject_incidents`, `manage_watchlists`, `manage_policy_settings`, `view_sensitive_audit_trail` |
| `export_service` | `view_redacted_evidence`, `export_evidence` |

### Sensitive Action Mapping

| Action | Required permission |
|---|---|
| View standard evidence manifests | `view_redacted_evidence` |
| Request original evidence | `view_unredacted_evidence` |
| Create, list, retrieve, or download case exports | `export_evidence` |
| Approve or reject incidents | `approve_reject_incidents` |
| Create, update, delete, list, or manually check watchlists | `manage_watchlists` |
| Manage alert routing targets and policies | `manage_policy_settings` |
| View sensitive review/workflow/audit details in exports | `view_sensitive_audit_trail` |

### Access Resolution

When an API request or export is made, the system resolves access in two stages:

1. The caller declares their `access_role` (defaults to `operator` for most API routes, `export_service` for export creation).
2. Sensitive routes resolve that role into a current permission set.
3. If the request asks for original evidence, the route requires `view_unredacted_evidence` up front and returns HTTP 403 when it is missing.
4. The privacy policy then resolves the final asset view and asset list for the authorized caller.
5. The `EvidenceAccessResolution` object accompanies evidence responses, making the final privacy boundary explicit.

### Redacted Assets

Each evidence manifest contains two asset lists:

- **Persisted `assets`** — original asset references with full provenance.
- **Persisted `redacted_assets`** — redacted variants with `storage_state: planned` and `derived_from_asset_key` linking back to the original.

When an API read is access-filtered:

- **`manifest.assets`** is rewritten to the caller's visible asset set.
- **`visible_assets`** mirrors that same access-filtered list as an explicit convenience field for UI code.
- **`has_restricted_original_assets`** is only `true` when original assets exist but are hidden from the current caller because of policy restrictions.

Redacted assets declare:
- `asset_view: redacted`
- `redaction_status: planned` (no pixel-level masking pipeline yet)
- `redaction_targets` — which categories of content need masking (face, license plate, PII)
- `derived_from_asset_key` — provenance link to the original asset

### Plate Text Masking

Plate text is masked in redacted views:
- First 2 and last 2 alphanumeric characters are preserved.
- Middle characters are replaced with `*`.
- Non-alphanumeric characters (hyphens, spaces) are preserved.

Example: `ABC1234` → `AB***34`

## API Endpoints

All evidence endpoints accept privacy query parameters:

```
GET /events/{event_id}/evidence?access_role=operator&requested_view=redacted
POST /events/{event_id}/evidence?access_role=operator&requested_view=redacted
GET /violations/{violation_id}/evidence?access_role=operator
POST /violations/{violation_id}/evidence?access_role=operator
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `access_role` | `EvidenceAccessRole` | `operator` | Caller's role for privacy resolution |
| `requested_view` | `EvidenceAssetView` | `null` (policy default) | Preferred view; policy may downgrade |

### Response Structure

The `EvidenceManifestRead` response includes:

```json
{
  "access": {
    "requested_role": "operator",
    "requested_view": null,
    "resolved_view": "redacted",
    "original_access_authorized": false,
    "resolution_notes": [
      "Redacted evidence is the default response for operator-facing and export-facing access paths."
    ]
  },
  "visible_assets": [...],
  "has_restricted_original_assets": true,
  "manifest": {
    "active_asset_view": "redacted",
    "privacy_policy": {...}
  }
}
```

For redacted responses, original media URIs are suppressed from export bundles and auxiliary payloads such as incident media references, detection media references, and plate-read media references.

Additional sensitive endpoints now use the same request-declared role model:

```
GET /access/policy?access_role=reviewer
POST /violations/{violation_id}/review?access_role=reviewer
GET /exports/{export_id}?access_role=supervisor
POST /exports/{export_id}/downloads?access_role=evidence_admin
POST /watchlist/?access_role=supervisor
POST /alerts/policies?access_role=evidence_admin
```

`GET /access/policy` returns the effective permissions for the supplied role, the full role-to-permission matrix, and the sensitive-action requirements used by the backend.

## Export Integration

Case exports use both `EvidencePrivacyPolicy` and the new access-control layer:

- The export `CaseExportCreateRequest` accepts `access_role` and `requested_view`.
- Export creation, listing, retrieval, and download require `export_evidence`.
- If `requested_view` is omitted, exports follow `default_export_view` rather than the API default.
- Plate text is masked in redacted export bundles.
- Evidence manifests are sanitized per the resolved access view.
- Original media URIs are omitted from redacted exports. Legacy manifests that only store `frames` / `clips` / `plates` arrays have those original references suppressed and replaced with an explicit `privacy_redaction_notice`.
- The export bundle includes a `privacy` section documenting the applied policy and the current permission set.
- Roles without `view_sensitive_audit_trail` receive restricted review, workflow, and audit sections even when they can access the export itself.

## Frontend

The `EvidencePrivacyStatus` component displays:

- The active view (original or redacted badge).
- The caller's role and authorization state.
- Resolution notes explaining any access downgrades.
- Restricted original asset warnings.
- Visible asset list with redaction status and targets.

The events route now surfaces a live access-policy preview that calls `GET /api/v1/access/policy`, lets the user inspect each current role, and renders the same role-to-permission matrix and action requirements enforced by the backend.

## What This Foundation Does NOT Do

1. **No pixel-level masking** — faces are not blurred, plates are not obscured in actual image/video files. Redacted assets use `storage_state: planned`.
2. **No authentication layer** — roles are still declared per-request. A full authentication/session system needs to be integrated before these permissions become identity-backed.
3. **No jurisdiction-specific compliance** — the foundation is privacy-aware but does not claim GDPR, CCPA, or other regulatory compliance on its own.
4. **No durable access audit store** — sensitive allow and deny decisions are emitted through the `trafficmind.access.audit` logger, but they are not yet written to a dedicated audit table.

## Testing

Privacy tests live in `tests/api/test_evidence_privacy.py` and cover:

- Role authorization checks (all 6 roles)
- Access resolution (default, upgrade, downgrade scenarios)
- Visible asset selection (original vs redacted)
- Manifest sanitization (asset replacement, audit marking)
- Plate text masking (standard, short, edge cases)
- Policy defaults (views, roles, targets, honest notes)
- Legacy manifest normalization
- Full integration flows (operator and privacy officer end-to-end)

Access-control regression coverage also lives in:

- `tests/api/test_evidence.py` for original-evidence denials, review action permissions, and access-policy endpoint coverage.
- `tests/api/test_case_export.py` for export audit-visibility sanitization.
- `tests/api/test_anpr.py` for watchlist management denials.
- `tests/api/test_alert_routing.py` for alert policy management denials.
