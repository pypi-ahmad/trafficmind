/* ── Alert types mirroring backend schemas ──────────────────────────────── */

export type AlertSeverity = "info" | "low" | "medium" | "high" | "critical";
export type AlertStatus = "new" | "acknowledged" | "escalated" | "resolved" | "suppressed";
export type AlertSourceKind =
  | "violation_event"
  | "watchlist_alert"
  | "camera_health"
  | "stream_health"
  | "workflow_backlog"
  | "manual";

export interface OperationalAlertSummary {
  id: string;
  policy_id: string | null;
  camera_id: string | null;
  source_kind: AlertSourceKind;
  condition_key: string;
  severity: AlertSeverity;
  status: AlertStatus;
  title: string;
  summary: string | null;
  occurred_at: string;
  first_seen_at: string;
  last_seen_at: string;
  occurrence_count: number;
  escalation_level: number;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  resolved_at: string | null;
  resolved_by: string | null;
  created_at: string;
}

export interface AlertListResult {
  items: OperationalAlertSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface AlertFeedParams {
  status?: AlertStatus;
  severity?: AlertSeverity;
  sourceKind?: AlertSourceKind;
  limit?: number;
  offset?: number;
}
