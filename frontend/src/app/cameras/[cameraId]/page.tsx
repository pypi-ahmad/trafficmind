import Link from "next/link";
import { notFound } from "next/navigation";

import { fetchCameraDetail } from "@/features/operations/api";
import { buildDashboardHref, buildEventFeedHref } from "@/features/operations/derive";

export const dynamic = "force-dynamic";

type CameraDetailPageProps = {
  params: Promise<{
    cameraId: string;
  }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
};

function formatTimestamp(value: string | null): string {
  if (!value) {
    return "Not available";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function getSingleValue(value: string | string[] | undefined): string | null {
  if (Array.isArray(value)) {
    return value[0] ?? null;
  }
  return value ?? null;
}

export default async function CameraDetailPage({ params, searchParams }: CameraDetailPageProps) {
  const { cameraId } = await params;
  const query = await searchParams;
  const junctionId = getSingleValue(query.junctionId);
  const result = await fetchCameraDetail(cameraId);

  if (result.status === 404) {
    notFound();
  }

  if (!result.ok || !result.data) {
    return (
      <main className="mx-auto flex min-h-screen w-full max-w-5xl flex-col gap-6 px-4 py-8 sm:px-6">
        <Link href="/" className="text-sm font-medium text-[var(--color-ink)] underline underline-offset-4">
          Back to operations view
        </Link>
        <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-8 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
          <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Camera detail unavailable</p>
          <h1 className="mt-3 text-4xl font-semibold tracking-[-0.06em] text-[var(--color-ink)]">Camera detail could not be loaded</h1>
          <p className="mt-4 max-w-2xl text-base leading-7 text-[rgba(19,32,41,0.74)]">
            {result.error ?? "The camera detail endpoint is not reachable from the frontend at the moment."}
          </p>
        </section>
      </main>
    );
  }

  const camera = result.data;

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-6xl flex-col gap-6 px-4 py-8 sm:px-6">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <Link href={buildDashboardHref({ cameraId: camera.id, junctionId: junctionId ?? undefined })} className="rounded-full border border-[rgba(23,57,69,0.14)] px-4 py-2 font-medium text-[var(--color-ink)] transition-colors hover:border-[rgba(23,57,69,0.28)]">
          Back to map selection
        </Link>
        <Link href={buildEventFeedHref({ cameraId: camera.id, junctionId: junctionId ?? undefined })} className="rounded-full border border-[rgba(23,57,69,0.14)] px-4 py-2 font-medium text-[var(--color-ink)] transition-colors hover:border-[rgba(23,57,69,0.28)]">
          Open event feed filters
        </Link>
        {junctionId ? (
          <Link href={buildDashboardHref({ junctionId })} className="rounded-full border border-[rgba(23,57,69,0.14)] px-4 py-2 font-medium text-[var(--color-ink)] transition-colors hover:border-[rgba(23,57,69,0.28)]">
            View parent junction
          </Link>
        ) : null}
      </div>

      <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[linear-gradient(135deg,rgba(244,238,224,0.94),rgba(231,242,244,0.92))] p-8 shadow-[0_24px_60px_rgba(18,32,41,0.08)]">
        <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Camera Detail</p>
        <h1 className="mt-3 text-4xl font-semibold tracking-[-0.06em] text-[var(--color-ink)]">{camera.name}</h1>
        <p className="mt-3 text-lg text-[rgba(19,32,41,0.74)]">{camera.location_name}</p>
        <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-[1.4rem] bg-[rgba(255,255,255,0.72)] p-4">
            <p className="text-xs uppercase tracking-[0.16em] text-[rgba(19,32,41,0.5)]">Status</p>
            <p className="mt-2 text-xl font-semibold text-[var(--color-ink)]">{camera.status}</p>
          </div>
          <div className="rounded-[1.4rem] bg-[rgba(255,255,255,0.72)] p-4">
            <p className="text-xs uppercase tracking-[0.16em] text-[rgba(19,32,41,0.5)]">Coordinates</p>
            <p className="mt-2 text-xl font-semibold text-[var(--color-ink)]">
              {camera.latitude !== null && camera.longitude !== null
                ? `${camera.latitude.toFixed(5)}, ${camera.longitude.toFixed(5)}`
                : "Not geocoded"}
            </p>
          </div>
          <div className="rounded-[1.4rem] bg-[rgba(255,255,255,0.72)] p-4">
            <p className="text-xs uppercase tracking-[0.16em] text-[rgba(19,32,41,0.5)]">Streams</p>
            <p className="mt-2 text-xl font-semibold text-[var(--color-ink)]">{camera.streams.length}</p>
          </div>
          <div className="rounded-[1.4rem] bg-[rgba(255,255,255,0.72)] p-4">
            <p className="text-xs uppercase tracking-[0.16em] text-[rgba(19,32,41,0.5)]">Zones</p>
            <p className="mt-2 text-xl font-semibold text-[var(--color-ink)]">{camera.zones.length}</p>
          </div>
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <div className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-6 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
          <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Metadata</p>
          <dl className="mt-5 grid gap-4 text-sm text-[rgba(19,32,41,0.74)]">
            <div>
              <dt className="uppercase tracking-[0.14em] text-[rgba(19,32,41,0.5)]">Camera code</dt>
              <dd className="mt-2 text-base font-medium text-[var(--color-ink)]">{camera.camera_code}</dd>
            </div>
            <div>
              <dt className="uppercase tracking-[0.14em] text-[rgba(19,32,41,0.5)]">Approach</dt>
              <dd className="mt-2 text-base font-medium text-[var(--color-ink)]">{camera.approach ?? "Unassigned"}</dd>
            </div>
            <div>
              <dt className="uppercase tracking-[0.14em] text-[rgba(19,32,41,0.5)]">Timezone</dt>
              <dd className="mt-2 text-base font-medium text-[var(--color-ink)]">{camera.timezone}</dd>
            </div>
            <div>
              <dt className="uppercase tracking-[0.14em] text-[rgba(19,32,41,0.5)]">Calibration updated</dt>
              <dd className="mt-2 text-base font-medium text-[var(--color-ink)]">{formatTimestamp(camera.calibration_updated_at)}</dd>
            </div>
            <div>
              <dt className="uppercase tracking-[0.14em] text-[rgba(19,32,41,0.5)]">Notes</dt>
              <dd className="mt-2 text-base leading-7 text-[rgba(19,32,41,0.78)]">{camera.notes ?? "No notes recorded."}</dd>
            </div>
          </dl>
        </div>

        <div className="grid gap-6">
          <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-6 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
            <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Streams</p>
            <div className="mt-5 space-y-3">
              {camera.streams.length > 0 ? camera.streams.map((stream) => (
                <div key={stream.id} className="rounded-[1.4rem] bg-[rgba(243,237,228,0.72)] p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p className="font-semibold text-[var(--color-ink)]">{stream.name}</p>
                    <span className="rounded-full bg-[rgba(19,32,41,0.08)] px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-[rgba(19,32,41,0.72)]">
                      {stream.status}
                    </span>
                  </div>
                  <p className="mt-2 text-sm text-[rgba(19,32,41,0.72)]">{stream.source_type} · {stream.stream_kind}</p>
                </div>
              )) : (
                <p className="text-sm text-[rgba(19,32,41,0.72)]">No streams are attached yet.</p>
              )}
            </div>
          </section>

          <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-6 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
            <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Spatial zones</p>
            <div className="mt-5 flex flex-wrap gap-3">
              {camera.zones.length > 0 ? camera.zones.map((zone) => (
                <div key={zone.id} className="rounded-full bg-[rgba(243,237,228,0.86)] px-4 py-2 text-sm font-medium text-[var(--color-ink)]">
                  {zone.name} · {zone.zone_type}
                </div>
              )) : (
                <p className="text-sm text-[rgba(19,32,41,0.72)]">No zones are configured for this camera yet.</p>
              )}
            </div>
          </section>
        </div>
      </section>
    </main>
  );
}