"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const primaryItems = [
  { href: "/", label: "Dashboard", match: (p: string) => p === "/" },
  { href: "/cases", label: "Cases", match: (p: string) => p.startsWith("/cases") },
  { href: "/alerts", label: "Alerts", match: (p: string) => p.startsWith("/alerts") },
  { href: "/", label: "Cameras", match: (p: string) => p.startsWith("/cameras") },
] as const;

const secondaryItems = [
  { href: "/evaluation", label: "Evaluation", match: (p: string) => p.startsWith("/evaluation") },
  { href: "/reports", label: "Reports", match: (p: string) => p.startsWith("/reports") },
  { href: "/settings", label: "Settings", match: (p: string) => p.startsWith("/settings") },
  { href: "/help", label: "Help", match: (p: string) => p.startsWith("/help") },
] as const;

export function AppNav() {
  const pathname = usePathname();

  const activeLinkClass =
    "rounded-full bg-[var(--color-ink)] px-4 py-1.5 text-sm font-medium text-[var(--color-paper)]";
  const inactiveLinkClass =
    "rounded-full px-4 py-1.5 text-sm font-medium text-[rgba(19,32,41,0.72)] transition-colors hover:text-[var(--color-ink)]";
  const secondaryActiveLinkClass = activeLinkClass;
  const secondaryInactiveLinkClass =
    "rounded-full px-4 py-1.5 text-sm font-medium text-[rgba(19,32,41,0.50)] transition-colors hover:text-[rgba(19,32,41,0.72)]";

  /* Camera detail pages: show a breadcrumb trail below the nav */
  const isCameraDetail = /^\/cameras\/[^/]+$/.test(pathname);

  return (
    <header className="sticky top-0 z-40 border-b border-[rgba(23,57,69,0.10)] bg-[rgba(246,240,229,0.92)] backdrop-blur-sm">
      <nav className="mx-auto flex max-w-[1500px] items-center justify-between px-4 py-2.5 sm:px-6 lg:px-10">
        <div className="flex items-center gap-2">
          <Link
            href="/"
            className="mr-4 text-base font-semibold tracking-[-0.03em] text-[var(--color-ink)]"
          >
            TrafficMind
          </Link>
          <div className="flex items-center gap-1">
            {primaryItems.map((item) => (
              <Link
                key={item.label}
                href={item.href}
                className={item.match(pathname) ? activeLinkClass : inactiveLinkClass}
              >
                {item.label}
              </Link>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-1">
          {secondaryItems.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={item.match(pathname) ? secondaryActiveLinkClass : secondaryInactiveLinkClass}
            >
              {item.label}
            </Link>
          ))}
        </div>
      </nav>

      {isCameraDetail ? (
        <div className="mx-auto max-w-[1500px] border-t border-[rgba(23,57,69,0.06)] px-4 py-1.5 sm:px-6 lg:px-10">
          <ol className="flex items-center gap-1.5 text-xs text-[rgba(19,32,41,0.56)]">
            <li>
              <Link href="/" className="hover:text-[var(--color-ink)] transition-colors">Dashboard</Link>
            </li>
            <li aria-hidden="true">/</li>
            <li className="font-medium text-[var(--color-ink)]">Camera Detail</li>
          </ol>
        </div>
      ) : null}
    </header>
  );
}
