import Link from "next/link";

import { fetchAccessPolicy } from "@/features/evidence/api";
import { EvidencePrivacyPolicyPreview } from "@/features/evidence/components/evidence-privacy-status";
import { coerceEvidenceAccessRole, EVIDENCE_ACCESS_ROLES, type EvidenceAccessRole } from "@/features/evidence/types";
import { fetchCameraDetail, fetchEventsStatus, fetchViolationsStatus } from "@/features/operations/api";
import { buildDashboardHref, buildEventFeedHref, getSingleParam } from "@/features/operations/derive";

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
    fetchEventsStatus(),
    fetchViolationsStatus(),
    cameraId ? fetchCameraDetail(cameraId) : Promise.resolve(null),
    fetchAccessPolicy(accessRole),
  ]);

  const selectedCamera = cameraResult && cameraResult.ok ? cameraResult.data : null;

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
        <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Event feed foundation</p>
        <h1 className="mt-3 text-4xl font-semibold tracking-[-0.06em] text-[var(--color-ink)]">Spatial filters are wired even while the feed is still scaffolded</h1>
        <p className="mt-4 max-w-3xl text-base leading-7 text-[rgba(19,32,41,0.74)]">
          This page reflects the filters coming from the map selection layer so operators can move between the spatial dashboard, a selected camera, and the future incident feed without losing context.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          {cameraId ? <span className="rounded-full bg-[rgba(255,255,255,0.72)] px-4 py-2 text-sm font-medium text-[var(--color-ink)]">cameraId: {cameraId}</span> : null}
          {junctionId ? <span className="rounded-full bg-[rgba(255,255,255,0.72)] px-4 py-2 text-sm font-medium text-[var(--color-ink)]">junctionId: {junctionId}</span> : null}
        </div>
      </section>

      <section className="grid gap-6 lg:grid-cols-2">
        <div className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-6 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
          <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Events endpoint</p>
          <p className="mt-3 text-2xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">{eventsResult.status ?? "offline"}</p>
          <p className="mt-3 text-sm leading-6 text-[rgba(19,32,41,0.74)]">
            {eventsResult.ok
              ? eventsResult.data?.detail
              : eventsResult.error ?? "The events feed could not be reached."}
          </p>
        </div>
        <div className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-6 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
          <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Violations endpoint</p>
          <p className="mt-3 text-2xl font-semibold tracking-[-0.04em] text-[var(--color-ink)]">{violationsResult.status ?? "offline"}</p>
          <p className="mt-3 text-sm leading-6 text-[rgba(19,32,41,0.74)]">
            {violationsResult.ok
              ? violationsResult.data?.detail
              : violationsResult.error ?? "The violations feed could not be reached."}
          </p>
        </div>
      </section>

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
            The feed page already knows which camera the operator selected from the map. Once `/events` and `/violations` return real data, this route can hydrate lists, timelines, and review actions without changing the linking model.
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