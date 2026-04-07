import Link from "next/link";

import { fetchCameraList } from "@/features/operations/api";
import { formatTimestamp } from "@/features/operations/components/dashboard-primitives";
import { cameraStatusLabel } from "@/features/shared/format-labels";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "Cameras | TrafficMind",
};

const STATUS_TONE: Record<string, string> = {
  active: "bg-[rgba(76,175,80,0.14)] text-[rgba(27,94,32,0.88)]",
  provisioning: "bg-[rgba(255,183,77,0.18)] text-[rgba(150,100,20,0.88)]",
  maintenance: "bg-[rgba(255,183,77,0.18)] text-[rgba(150,100,20,0.88)]",
  disabled: "bg-[rgba(19,32,41,0.08)] text-[rgba(19,32,41,0.56)]",
};

function statusClasses(status: string) {
  return STATUS_TONE[status] ?? "bg-[rgba(19,32,41,0.08)] text-[rgba(19,32,41,0.56)]";
}

export default async function CamerasPage() {
  const result = await fetchCameraList();

  const cameras = result.ok && result.data ? result.data.items : [];
  const total = result.ok && result.data ? result.data.total : 0;
  const live = result.ok && result.data !== null;

  const activeCameras = cameras.filter((c) => c.status === "active").length;

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-6xl flex-col gap-6 px-4 py-8 sm:px-6">
      {/* ── Hero ─────────────────────────────────────── */}
      <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[linear-gradient(135deg,rgba(244,238,224,0.94),rgba(231,242,244,0.92))] p-8 shadow-[0_24px_60px_rgba(18,32,41,0.08)]">
        <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">Camera Fleet</p>
        <h1 className="mt-3 text-4xl font-semibold tracking-[-0.06em] text-[var(--color-ink)]">
          {live
            ? total > 0
              ? `${total} Camera${total === 1 ? "" : "s"}`
              : "No Cameras"
            : "Cameras Unavailable"}
        </h1>
        <p className="mt-4 max-w-3xl text-base leading-7 text-[rgba(19,32,41,0.74)]">
          {live
            ? total === 0
              ? "No cameras have been registered yet. Once cameras are provisioned, they will appear here."
              : `${activeCameras} active across ${total} registered. Select a camera to view streams, zones, and configuration details.`
            : "The camera service could not be reached. Try reloading the page, or check that the system is running."}
        </p>
        {!live ? (
          <div className="mt-6 flex flex-wrap gap-3 text-sm">
            <Link href="/cameras" className="rounded-full bg-[rgba(23,57,69,0.08)] px-4 py-2 font-medium text-[var(--color-ink)] transition-colors hover:bg-[rgba(23,57,69,0.14)]">
              Try again
            </Link>
            <Link href="/" className="rounded-full bg-[rgba(23,57,69,0.08)] px-4 py-2 font-medium text-[var(--color-ink)] transition-colors hover:bg-[rgba(23,57,69,0.14)]">
              Return to dashboard
            </Link>
          </div>
        ) : null}
      </section>

      {/* ── Camera list ──────────────────────────────── */}
      {cameras.length > 0 ? (
        <section className="rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-6 shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
          <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">All Cameras</p>
          <ul className="mt-5 divide-y divide-[rgba(23,57,69,0.08)]">
            {cameras.map((camera) => (
              <li key={camera.id}>
                <Link
                  href={`/cameras/${camera.id}`}
                  className="flex items-center gap-4 px-2 py-4 transition-colors hover:bg-[rgba(23,57,69,0.03)] sm:px-4"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold text-[var(--color-ink)]">{camera.name}</p>
                    <p className="mt-0.5 truncate text-xs text-[rgba(19,32,41,0.56)]">{camera.location_name}</p>
                  </div>
                  <span className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-medium ${statusClasses(camera.status)}`}>
                    {cameraStatusLabel(camera.status)}
                  </span>
                  <span className="shrink-0 text-xs text-[rgba(19,32,41,0.50)]">
                    {camera.stream_count} stream{camera.stream_count === 1 ? "" : "s"}
                  </span>
                  {camera.calibration_updated_at ? (
                    <span className="hidden shrink-0 text-xs text-[rgba(19,32,41,0.40)] sm:inline">
                      {formatTimestamp(camera.calibration_updated_at)}
                    </span>
                  ) : null}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </main>
  );
}
