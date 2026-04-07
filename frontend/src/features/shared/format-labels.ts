/**
 * Centralized label formatting utilities for converting raw
 * backend enum values and snake_case strings into user-friendly
 * display labels throughout the UI.
 */

/** Convert a snake_case string to Title Case (e.g. "red_light" → "Red Light"). */
export function titleCase(value: string): string {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

/** Human-friendly labels for violation type enums. */
export function violationTypeLabel(value: string): string {
  const overrides: Record<string, string> = {
    red_light: "Red Light",
    illegal_turn: "Illegal Turn",
    stop_line: "Stop Line",
    wrong_way: "Wrong Way",
    illegal_parking: "Illegal Parking",
    no_stopping: "No Stopping",
    pedestrian_conflict: "Pedestrian Conflict",
    bus_stop_violation: "Bus Stop Violation",
    stalled_vehicle: "Stalled Vehicle",
  };
  return overrides[value] ?? titleCase(value);
}

/** Human-friendly labels for violation status enums. */
export function violationStatusLabel(value: string): string {
  const overrides: Record<string, string> = {
    open: "Open",
    under_review: "Under Review",
    confirmed: "Confirmed",
    dismissed: "Dismissed",
  };
  return overrides[value] ?? titleCase(value);
}

/** Human-friendly labels for detection event status enums. */
export function eventStatusLabel(value: string): string {
  const overrides: Record<string, string> = {
    new: "New",
    enriched: "Processed",
    suppressed: "Filtered Out",
  };
  return overrides[value] ?? titleCase(value);
}

/** Human-friendly labels for detection event type enums. */
export function eventTypeLabel(value: string): string {
  const overrides: Record<string, string> = {
    detection: "Detection",
    zone_entry: "Zone Entry",
    zone_exit: "Zone Exit",
    line_crossing: "Line Crossing",
    light_state: "Light State",
  };
  return overrides[value] ?? titleCase(value);
}

/** Human-friendly labels for feed availability status. */
export function availabilityDisplayLabel(value: string): string {
  switch (value) {
    case "live":
      return "Live";
    case "pending_backend":
      return "Setting Up";
    case "unreachable":
      return "Offline";
    default:
      return titleCase(value);
  }
}

/** Human-friendly labels for camera status enums. */
export function cameraStatusLabel(value: string): string {
  const overrides: Record<string, string> = {
    active: "Active",
    provisioning: "Setting Up",
    maintenance: "Maintenance",
    disabled: "Disabled",
  };
  return overrides[value] ?? titleCase(value);
}

/** Human-friendly labels for stream kind. */
export function streamKindLabel(value: string): string {
  return titleCase(value);
}

/** Human-friendly labels for zone type. */
export function zoneTypeLabel(value: string): string {
  const overrides: Record<string, string> = {
    polygon: "Area",
    line: "Line",
    stop_line: "Stop Line",
    crosswalk: "Crosswalk",
    roi: "Region of Interest",
    lane: "Lane",
    restricted: "Restricted Area",
  };
  return overrides[value] ?? titleCase(value);
}

/** Human-friendly labels for violation severity. */
export function severityLabel(value: string): string {
  const overrides: Record<string, string> = {
    critical: "Critical",
    high: "High",
    medium: "Medium",
    low: "Low",
    watch: "Watch",
    stable: "Stable",
  };
  return overrides[value] ?? titleCase(value);
}

/** Human-friendly labels for evidence access roles. */
export function accessRoleLabel(value: string): string {
  return titleCase(value);
}

/**
 * Sanitize an error message for user-facing display.
 * Strips raw API paths, HTTP status codes, and technical jargon.
 */
export function userFriendlyError(rawError: string | null | undefined): string {
  if (!rawError) {
    return "Something went wrong. Please try again later.";
  }

  const lower = rawError.toLowerCase();

  // Network-level failures
  if (lower.includes("fetch failed") || lower.includes("econnrefused") || lower.includes("network")) {
    return "Unable to reach the server. Please check your connection and try again.";
  }

  // Timeout
  if (lower.includes("timeout") || lower.includes("timed out")) {
    return "The request took too long. Please try again.";
  }

  // If it looks like an API path or raw HTTP status, replace it
  if (/^(get|post|put|delete|patch)\s+\//i.test(rawError) || /^\d{3}\s/.test(rawError)) {
    return "Something went wrong. Please try again later.";
  }

  // If it contains explicit API path fragments, sanitize
  if (rawError.includes("/api/") || rawError.includes("endpoint")) {
    return "A service is temporarily unavailable. Please try again later.";
  }

  // Catch raw HTTP status text that backends sometimes return as detail
  if (/^internal server error$/i.test(rawError.trim()) || /^not found$/i.test(rawError.trim()) || /^service unavailable$/i.test(rawError.trim())) {
    return "Something went wrong. Please try again later.";
  }

  // Catch Python exception class names leaked by backend frameworks
  if (/\b(ValueError|TypeError|KeyError|AttributeError|RuntimeError|Exception|Traceback)\b/.test(rawError)) {
    return "Something went wrong. Please try again later.";
  }

  // Catch database / ORM / constraint errors that should never reach users
  if (
    /integrity|constraint|duplicate key|foreign key|column .* does not exist|relation .* does not exist|violates|unique violation/i.test(rawError)
  ) {
    return "Something went wrong while saving your data. Please try again or contact support.";
  }

  // Pass through messages that already look user-friendly (short, no jargon)
  if (rawError.length < 120 && !rawError.includes("traceback") && !rawError.includes("stack")) {
    return rawError;
  }

  return "Something went wrong. Please try again later.";
}
