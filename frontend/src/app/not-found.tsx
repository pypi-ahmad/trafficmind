import Link from "next/link";

export default function NotFound() {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-5xl flex-col items-center justify-center gap-6 px-4 py-16 sm:px-6">
      <section className="w-full rounded-[2rem] border border-[rgba(23,57,69,0.12)] bg-[rgba(255,255,255,0.82)] p-8 text-center shadow-[0_18px_40px_rgba(18,32,41,0.06)]">
        <p className="text-[0.75rem] font-semibold uppercase tracking-[0.24em] text-[rgba(19,32,41,0.56)]">
          Page Not Found
        </p>
        <h1 className="mt-3 text-4xl font-semibold tracking-[-0.06em] text-[var(--color-ink)]">
          404
        </h1>
        <p className="mx-auto mt-4 max-w-xl text-base leading-7 text-[rgba(19,32,41,0.74)]">
          The page you&apos;re looking for doesn&apos;t exist or may have been moved.
        </p>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          <Link
            href="/"
            className="rounded-full bg-[var(--color-ink)] px-5 py-2.5 text-sm font-medium text-[var(--color-paper)] transition-colors hover:bg-[rgba(19,32,41,0.85)]"
          >
            Go to Dashboard
          </Link>
          <Link
            href="/cases"
            className="rounded-full border border-[rgba(23,57,69,0.14)] px-5 py-2.5 text-sm font-medium text-[var(--color-ink)] transition-colors hover:border-[rgba(23,57,69,0.28)]"
          >
            View Cases
          </Link>
          <Link
            href="/help"
            className="rounded-full border border-[rgba(23,57,69,0.14)] px-5 py-2.5 text-sm font-medium text-[var(--color-ink)] transition-colors hover:border-[rgba(23,57,69,0.28)]"
          >
            Help
          </Link>
        </div>
      </section>
    </main>
  );
}
