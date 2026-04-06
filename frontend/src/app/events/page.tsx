import Link from "next/link";

import { fetchAccessPolicy } from "@/features/evidence/api";
import { EvidencePrivacyPolicyPreview } from "@/features/evidence/components/evidence-privacy-status";
import { coerceEvidenceAccessRole, EVIDENCE_ACCESS_ROLES, type EvidenceAccessRole } from "@/features/evidence/types";
import { fetchCameraDetail, fetchEventsFeed, fetchViolationsFeed } from "@/features/operations/api";
import { buildDashboardHref, buildEventFeedHref, getSingleParam } from "@/features/operations/derive";
import type { DetectionEventReadApi, ViolationEventReadApi } from "@/features/operations/types";

export const dynamic = "force-dynamic";

type EventsPageProps = {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
};

export default async function EventsPage({ searchParams }: EventsPageProps) {
  const params = await searchParams;
  const cameraId = getSingleParam(params.cameraId);
  const junctionId = getSingleParam(params.junctionId);
  const accessRole = coerceEvidenceAccessRole(getSingleParam(params.accessRole));

  const [eventsResult, violationsResult, cameraResult, accessPolicyResult] = await Promise.all([
    fetchEventsFeed({ limit: 20, cameraId }),
    fetchViolationsFeed({ limit: 20, cameraId }),
    cameraId ? fetchCameraDetail(cameraId) : Promise.resolve(null),
    fetchAccessPolicy(accessRole),
  ]);

  const selectedCamera = cameraResult && cameraResult.ok ? cameraResult.data : null;
  const events: DetectionEventReadApi[] = eventsResult.ok && eventsResult.data ? eventsResult.data.items : [];
  const violations: ViolationEventReadApi[] = violationsResult.ok && violationsResult.data ? violationsResult.data.items : [];
  const eventsTotal = eventsResult.ok && eventsResult.data ? eventsResult.data.total : 0;
  const violationsTotal = violationsResult.ok && violationsResult.data ? violationsResult.data.total : 0;
  const eventsLive = eventsResult.ok && eventsResult.data !== null;
  const violationsLive = violationsResult.ok && violationsResult.data !== null;

  function buildPolicyPreviewHref(role: EvidenceAccessRole): string {
    const nextParams = new URLSearchParams();
    if (cameraId) {
      nextParams.set("cameraId", cameraId);
    }
    if (junctionId) {
      nextParams.set("junctionId", junctionId);
    }
    nextParams.set("accessRole", role);
    return `/events?${nextParams.toString()}`;
  }

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-6xl flex-col gap-6 px-4 py-8 sm:px-6">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <Link href={buildDashboardHref({ cameraId: cameraId ?? undefined, junctionId: junctionId ?? undefined })} className="rounded-full border border-[rgba(23,57,69,0.14)] px-4 py-2 font-medium text-[var(--color-ink)] transition-colors hover:border-[rgba(23,57,69,0.28)]">
          Back to map dashboard
        </Link>
        {selectedCamera ? (
          <Link href={`/cameras/${selectedCamera.id}`} className="rounded-full border border-[rgba(23,57,69,0.14)] px-4 py-2 font-medium text-[var(--color-ink)] transition-colors hover:border-[rgba(23,57,69,0.28)]">
            Open camera detail
          </Link>
        ) : null}
      </div>

      <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[linear-gradient(135deg,rgba(244,238,224,0.94),rgba(231,242,244,0.92))] p-8 shadow-[0_24px_60px_rgba(18,32,41,0.08)]">
        <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Event &amp; violation feed</p>
        <h1 className="mt-3 text-4xl font-semibold tracking-[-0.06em] text-[var(--color-ink)]">
          {eventsLive || violationsLive
            ? selectedCamera
              ? `Live incident feed for ${selectedCamera.name}`
              : "Live incident feed from backend"
            : "Incident feed is currently unavailable"}
        </h1>
        <p className="mt-4 max-w-3xl text-base leading-7 text-[rgba(19,32,41,0.74)]">
          {eventsLive || violationsLive
            ? selectedCamera
              ? `Events and violations are filtered to ${selectedCamera.name} at ${selectedCamera.location_name}. Clear the camera filter to see all incidents.`
              : "Events and violations are flowing from the backend. Select a camera from the map to filter."
            : "The backend event and violation endpoints could not be reached. Check that the API server is running."}
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          {cameraId ? (
            <Link href={buildEventFeedHref({ junctionId: junctionId ?? undefined })} className="rounded-full bg-[rgba(240,90,79,0.10)] px-4 py-2 text-sm font-medium text-[var(--color-danger)] transition-colors hover:bg-[rgba(240,90,79,0.18)]">
              Clear camera filter
            </Link>
          ) : null}
          {cameraId ? <span className="rounded-full bg-[rgba(255,255,255,0.72)] px-4 py-2 text-sm font-medium text-[var(--color-ink)]">Camera: {selectedCamera?.name ?? cameraId}</span> : null}
          {junctionId ? <span className="rounded-full bg-[rgba(255,255,255,0.72)] px-4 py-2 text-sm font-medium text-[var(--color-ink)]">Junction: {junctionId}</span> : null}
        </div>
      </section>

      <section className="grid gap-6 lg:grid-cols-2">
        <div className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-6 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
          <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Detection events</p>
          <p className="mt-3 text-2xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">
            {eventsLive ? `${eventsTotal} total` : (eventsResult.status ?? "offline")}
          </p>
          <p className="mt-3 text-sm leading-6 text-[rgba(19,32,41,0.74)]">
            {eventsLive
              ? `Showing ${events.length} most recent detection events from the backend.`
              : eventsResult.error ?? "The events feed could not be reached."}
          </p>
        </div>
        <div className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-6 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
          <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Violations</p>
          <p className="mt-3 text-2xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">
            {violationsLive ? `${violationsTotal} total` : (violationsResult.status ?? "offline")}
          </p>
          <p className="mt-3 text-sm leading-6 text-[rgba(19,32,41,0.74)]">
            {violationsLive
              ? `Showing ${violations.length} most recent violations from the backend.`
              : violationsResult.error ?? "The violations feed could not be reached."}
          </p>
        </div>
      </section>

      {violations.length > 0 ? (
        <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-6 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
          <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Recent violations</p>
          <div className="mt-4 divide-y divide-[rgba(23,57,69,0.08)]">
            {violations.map((v) => (
              <div key={v.id} className="flex items-start gap-4 py-4 first:pt-0 last:pb-0">
                <span className={`mt-1 inline-block rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] ${v.severity === "critical" ? "bg-[rgba(240,90,79,0.14)] text-[var(--color-danger)]" : v.severity === "high" ? "bg-[rgba(240,90,79,0.10)] text-[var(--color-danger)]" : v.severity === "medium" ? "bg-[rgba(226,176,71,0.16)] text-[var(--color-warning-ink)]" : "bg-[rgba(56,183,118,0.14)] text-[var(--color-ok-ink)]"}`}>
                  {v.severity}
                </span>
                <div className="flex-1">
                  <p className="font-semibold text-[var(--color-ink)]">{v.violation_type.replace(/_/g, " ")}</p>
                  <p className="mt-1 text-sm text-[rgba(19,32,41,0.72)]">{v.summary ?? "No summary available"}</p>
                  <p className="mt-1 text-xs text-[rgba(19,32,41,0.5)]">
                    {new Date(v.occurred_at).toLocaleString()} · Status: {v.status}
                    {v.assigned_to ? ` · Assigned: ${v.assigned_to}` : null}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {events.length > 0 ? (
        <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-6 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
          <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Recent detection events</p>
          <div className="mt-4 divide-y divide-[rgba(23,57,69,0.08)]">
            {events.map((e) => (
              <div key={e.id} className="flex items-start gap-4 py-4 first:pt-0 last:pb-0">
                <span className="mt-1 inline-block rounded-full bg-[rgba(56,183,118,0.14)] px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-[var(--color-ok-ink)]">
                  {e.object_class}
                </span>
                <div className="flex-1">
                  <p className="font-semibold text-[var(--color-ink)]">{e.event_type.replace(/_/g, " ")}</p>
                  <p className="mt-1 text-sm text-[rgba(19,32,41,0.72)]">
                    Confidence: {(e.confidence * 100).toFixed(0)}%
                    {e.track_id ? ` · Track: ${e.track_id}` : null}
                    {e.frame_index !== null ? ` · Frame: ${e.frame_index}` : null}
                  </p>
                  <p className="mt-1 text-xs text-[rgba(19,32,41,0.5)]">
                    {new Date(e.occurred_at).toLocaleString()} · Status: {e.status}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-6 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
        <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Policy preview role</p>
        <h2 className="mt-3 text-2xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">Inspect the live backend permission matrix by role</h2>
        <p className="mt-3 text-sm leading-6 text-[rgba(19,32,41,0.74)]">
          These links only change the preview role on this page. The actual backend checks use the same request-declared role field on sensitive evidence, export, review, watchlist, and alert policy routes.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          {EVIDENCE_ACCESS_ROLES.map((role) => {
            const isActive = role === accessRole;
            return (
              <Link
                key={role}
                href={buildPolicyPreviewHref(role)}
                className={`rounded-full px-4 py-2 text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-[var(--color-ink)] text-[var(--color-paper)]"
                    : "border border-[rgba(23,57,69,0.14)] text-[var(--color-ink)] hover:border-[rgba(23,57,69,0.28)]"
                }`}
              >
                {role.replace(/_/g, " ")}
              </Link>
            );
          })}
        </div>
      </section>

      <EvidencePrivacyPolicyPreview
        policy={accessPolicyResult.ok ? accessPolicyResult.data : null}
        selectedRole={accessRole}
        error={accessPolicyResult.error}
      />

      {selectedCamera ? (
        <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-6 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
          <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Selected camera context</p>
          <h2 className="mt-3 text-2xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">{selectedCamera.name}</h2>
          <p className="mt-3 text-sm leading-6 text-[rgba(19,32,41,0.74)]">
            Events and violations above are filtered to this camera. Use the links below to navigate to other views with context preserved.
          </p>
          <div className="mt-5 flex flex-wrap gap-3 text-sm">
            <Link href={buildEventFeedHref({ cameraId: selectedCamera.id, junctionId: junctionId ?? undefined })} className="rounded-full border border-[rgba(23,57,69,0.14)] px-4 py-2 font-medium text-[var(--color-ink)] transition-colors hover:border-[rgba(23,57,69,0.28)]">
              Keep current filters
            </Link>
            <Link href={`/cameras/${selectedCamera.id}`} className="rounded-full border border-[rgba(23,57,69,0.14)] px-4 py-2 font-medium text-[var(--color-ink)] transition-colors hover:border-[rgba(23,57,69,0.28)]">
              Open camera detail
            </Link>
          </div>
        </section>
      ) : null}
    </main>
  );
}