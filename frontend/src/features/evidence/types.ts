export const EVIDENCE_ACCESS_ROLES = [
  "operator",
  "reviewer",
  "supervisor",
  "privacy_officer",
  "evidence_admin",
  "export_service",
] as const;

export type EvidenceAccessRole = (typeof EVIDENCE_ACCESS_ROLES)[number];

export type AccessPermission =
  | "view_redacted_evidence"
  | "view_unredacted_evidence"
  | "export_evidence"
  | "approve_reject_incidents"
  | "manage_watchlists"
  | "manage_policy_settings"
  | "view_sensitive_audit_trail";

export type EvidenceAssetView = "original" | "redacted";

export type EvidenceRedactionStatus = "not_required" | "planned" | "available";

export type EvidenceRedactionTarget =
  | "face"
  | "license_plate"
  | "personally_identifying_detail";

export interface EvidenceAccessResolution {
  requested_role: EvidenceAccessRole;
  requested_view: EvidenceAssetView | null;
  resolved_view: EvidenceAssetView;
  original_access_authorized: boolean;
  resolution_notes: string[];
}

export interface EvidencePrivacyPolicy {
  default_asset_view: EvidenceAssetView;
  default_export_view: EvidenceAssetView;
  preserve_original_assets: boolean;
  authorized_original_roles: EvidenceAccessRole[];
  mask_by_default_roles: EvidenceAccessRole[];
  redaction_targets: EvidenceRedactionTarget[];
  enforcement_notes: string;
  compliance_notes: string;
}

export interface EvidenceAsset {
  asset_kind: string;
  label: string;
  asset_key: string;
  asset_view: EvidenceAssetView;
  redaction_status: EvidenceRedactionStatus;
  redaction_targets: EvidenceRedactionTarget[];
}

export interface EvidenceManifestRead {
  id: string;
  subject_kind: string;
  subject_id: string;
  manifest_key: string;
  build_revision: number;
  camera_id: string;
  access: EvidenceAccessResolution;
  visible_assets: EvidenceAsset[];
  has_restricted_original_assets: boolean;
  created_at: string;
  updated_at: string;
}

export interface AccessRolePermissionRead {
  role: EvidenceAccessRole;
  permissions: AccessPermission[];
  description: string | null;
}

export interface AccessRequirementRead {
  action: string;
  permissions: AccessPermission[];
  note: string | null;
}

export interface AccessPolicyRead {
  policy_name: string;
  current_role: EvidenceAccessRole;
  current_permissions: AccessPermission[];
  roles: AccessRolePermissionRead[];
  requirements: AccessRequirementRead[];
  notes: string[];
}

export function coerceEvidenceAccessRole(value: string | null | undefined): EvidenceAccessRole {
  if (value && EVIDENCE_ACCESS_ROLES.includes(value as EvidenceAccessRole)) {
    return value as EvidenceAccessRole;
  }

  return "operator";
}
