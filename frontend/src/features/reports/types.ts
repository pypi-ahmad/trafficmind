/* ── Export/report types mirroring backend schemas ───────────────────── */

export type CaseExportStatus = "pending" | "completed" | "failed";
export type CaseSubjectKind = "violation_event" | "detection_event" | "watchlist_alert" | "operational_alert";
export type CaseExportFormat = "json" | "markdown" | "zip_manifest";

export interface CaseExportSummary {
  id: string;
  subject_kind: CaseSubjectKind;
  subject_id: string;
  export_format: CaseExportFormat;
  status: CaseExportStatus;
  requested_by: string | null;
  bundle_version: string;
  filename: string;
  completeness: Record<string, unknown>;
  error_message: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CaseExportListResult {
  items: CaseExportSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface ExportListParams {
  subjectKind?: CaseSubjectKind;
  status?: CaseExportStatus;
  limit?: number;
  offset?: number;
}
