import type { CameraMapItem, FeedAvailability, HotspotSeverity } from "@/features/operations/types";

export function formatTimestamp(value: string | null | undefined): string {
  if (!value) {
    return "Not available";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

export function formatWindowLabel(start: string | null, end: string | null): string {
  if (!start || !end) {
    return "Current configured window";
  }

  const startDate = new Date(start);
  const endDate = new Date(end);
  if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) {
    return "Current configured window";
  }

  const formatter = new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
  });

  return `${formatter.format(startDate)} - ${formatter.format(endDate)}`;
}

export function severityClass(severity: HotspotSeverity): string {
  switch (severity) {
    case "critical":
      return "bg-[rgba(240,90,79,0.14)] text-[var(--color-danger)]";
    case "watch":
      return "bg-[rgba(226,176,71,0.16)] text-[var(--color-warning-ink)]";
    case "stable":
    default:
      return "bg-[rgba(56,183,118,0.14)] text-[var(--color-ok-ink)]";
  }
}

export function statusClass(status: CameraMapItem["status"]): string {
  switch (status) {
    case "active":
      return "bg-[rgba(56,183,118,0.14)] text-[var(--color-ok-ink)]";
    case "maintenance":
      return "bg-[rgba(255,155,61,0.16)] text-[var(--color-warning-ink)]";
    case "disabled":
      return "bg-[rgba(240,90,79,0.16)] text-[var(--color-danger)]";
    case "provisioning":
    default:
      return "bg-[rgba(226,176,71,0.18)] text-[var(--color-warning-ink)]";
  }
}

export function availabilityClass(availability: FeedAvailability): string {
  switch (availability) {
    case "live":
      return "bg-[rgba(56,183,118,0.14)] text-[var(--color-ok-ink)]";
    case "pending_backend":
      return "bg-[rgba(226,176,71,0.16)] text-[var(--color-warning-ink)]";
    case "unreachable":
    default:
      return "bg-[rgba(240,90,79,0.14)] text-[var(--color-danger)]";
  }
}

export function availabilityLabel(availability: FeedAvailability): string {
  return availability.replace(/_/g, " ");
}

export function StatCard({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="rounded-[1.7rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.72)] p-5 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
      <p className="text-[0.72rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">
        {label}
      </p>
      <p className="mt-4 text-3xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">{value}</p>
      <p className="mt-2 text-sm leading-6 text-[rgba(19,32,41,0.72)]">{note}</p>
    </div>
  );
}