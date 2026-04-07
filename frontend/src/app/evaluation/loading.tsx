export default function EvaluationLoading() {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-6xl flex-col gap-6 px-4 py-8 sm:px-6">
      {/* Hero skeleton */}
      <section className="animate-pulse rounded-[2rem] border border-[rgba(23,57,69,0.08)] bg-[rgba(255,255,255,0.5)] p-8">
        <div className="h-3 w-36 rounded bg-[rgba(19,32,41,0.08)]" />
        <div className="mt-5 h-9 w-64 rounded bg-[rgba(19,32,41,0.10)]" />
        <div className="mt-5 h-4 w-full max-w-xl rounded bg-[rgba(19,32,41,0.06)]" />
      </section>

      {/* Metrics grid skeleton */}
      <section className="grid gap-6 sm:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className="animate-pulse rounded-[2rem] border border-[rgba(23,57,69,0.08)] bg-[rgba(255,255,255,0.5)] p-6"
          >
            <div className="h-3 w-28 rounded bg-[rgba(19,32,41,0.08)]" />
            <div className="mt-4 h-7 w-20 rounded bg-[rgba(19,32,41,0.10)]" />
            <div className="mt-3 h-3 w-36 rounded bg-[rgba(19,32,41,0.06)]" />
          </div>
        ))}
      </section>

      {/* Results table skeleton */}
      <section className="animate-pulse rounded-[2rem] border border-[rgba(23,57,69,0.08)] bg-[rgba(255,255,255,0.5)] p-6">
        <div className="h-3 w-32 rounded bg-[rgba(19,32,41,0.08)]" />
        <div className="mt-5 space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="flex gap-4">
              <div className="h-4 w-32 rounded bg-[rgba(19,32,41,0.07)]" />
              <div className="h-4 w-16 rounded bg-[rgba(19,32,41,0.05)]" />
              <div className="h-4 w-24 rounded bg-[rgba(19,32,41,0.05)]" />
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
