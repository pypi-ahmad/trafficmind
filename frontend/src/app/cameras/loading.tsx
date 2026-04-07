export default function CamerasLoading() {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-6xl flex-col gap-6 px-4 py-8 sm:px-6">
      {/* Hero skeleton */}
      <section className="animate-pulse rounded-[2rem] border border-[rgba(23,57,69,0.08)] bg-[rgba(255,255,255,0.5)] p-8">
        <div className="h-3 w-28 rounded bg-[rgba(19,32,41,0.08)]" />
        <div className="mt-5 h-9 w-48 rounded bg-[rgba(19,32,41,0.10)]" />
        <div className="mt-5 h-4 w-full max-w-lg rounded bg-[rgba(19,32,41,0.06)]" />
      </section>

      {/* Camera list skeleton */}
      <section className="animate-pulse rounded-[2rem] border border-[rgba(23,57,69,0.08)] bg-[rgba(255,255,255,0.5)] p-6">
        <div className="h-3 w-24 rounded bg-[rgba(19,32,41,0.08)]" />
        <div className="mt-5 divide-y divide-[rgba(23,57,69,0.06)]">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="flex items-center gap-4 py-4">
              <div className="min-w-0 flex-1 space-y-2">
                <div className="h-4 w-44 rounded bg-[rgba(19,32,41,0.07)]" />
                <div className="h-3 w-32 rounded bg-[rgba(19,32,41,0.05)]" />
              </div>
              <div className="h-6 w-16 rounded-full bg-[rgba(19,32,41,0.06)]" />
              <div className="h-3 w-20 rounded bg-[rgba(19,32,41,0.05)]" />
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
