"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

const primaryItems = [
  { href: "/", label: "Dashboard", match: (p: string) => p === "/" },
  { href: "/cases", label: "Cases", match: (p: string) => p.startsWith("/cases") },
  { href: "/alerts", label: "Alerts", match: (p: string) => p.startsWith("/alerts") },
  { href: "/cameras", label: "Cameras", match: (p: string) => p.startsWith("/cameras") },
] as const;

const secondaryItems = [
  { href: "/evaluation", label: "Evaluation", match: (p: string) => p.startsWith("/evaluation") },
  { href: "/reports", label: "Reports", match: (p: string) => p.startsWith("/reports") },
  { href: "/settings", label: "Settings", match: (p: string) => p.startsWith("/settings") },
  { href: "/help", label: "Help", match: (p: string) => p.startsWith("/help") },
] as const;

export function AppNav() {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);

  /* Close drawer on route change */
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  /* Close drawer on Escape key */
  useEffect(() => {
    if (!mobileOpen) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setMobileOpen(false);
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [mobileOpen]);

  /* Prevent body scroll when drawer is open */
  useEffect(() => {
    if (mobileOpen) {
      document.body.style.overflow = "hidden";
      return () => { document.body.style.overflow = ""; };
    }
  }, [mobileOpen]);

  const activeLinkClass =
    "rounded-full bg-[var(--color-ink)] px-4 py-1.5 text-sm font-medium text-[var(--color-paper)]";
  const inactiveLinkClass =
    "rounded-full px-4 py-1.5 text-sm font-medium text-[rgba(19,32,41,0.72)] transition-colors hover:text-[var(--color-ink)]";
  const secondaryActiveLinkClass = activeLinkClass;
  const secondaryInactiveLinkClass =
    "rounded-full px-4 py-1.5 text-sm font-medium text-[rgba(19,32,41,0.50)] transition-colors hover:text-[rgba(19,32,41,0.72)]";

  const mobileActiveLinkClass =
    "block rounded-[1.4rem] bg-[var(--color-ink)] px-4 py-2.5 text-sm font-medium text-[var(--color-paper)]";
  const mobileInactiveLinkClass =
    "block rounded-[1.4rem] px-4 py-2.5 text-sm font-medium text-[rgba(19,32,41,0.72)] transition-colors hover:bg-[rgba(23,57,69,0.06)]";
  const mobileSecondaryInactiveLinkClass =
    "block rounded-[1.4rem] px-4 py-2.5 text-sm font-medium text-[rgba(19,32,41,0.50)] transition-colors hover:bg-[rgba(23,57,69,0.06)]";


  return (
    <header className="sticky top-0 z-40 border-b border-[rgba(23,57,69,0.10)] bg-[rgba(246,240,229,0.92)] backdrop-blur-sm">
      <nav className="mx-auto flex max-w-[1500px] items-center justify-between px-4 py-2.5 sm:px-6 lg:px-10">
        {/* Logo + desktop primary links */}
        <div className="flex items-center gap-2">
          <Link
            href="/"
            className="mr-4 text-base font-semibold tracking-[-0.03em] text-[var(--color-ink)]"
          >
            TrafficMind
          </Link>
          <div className="hidden items-center gap-1 md:flex">
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

        {/* Desktop secondary links */}
        <div className="hidden items-center gap-1 md:flex">
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

        {/* Mobile hamburger button */}
        <button
          type="button"
          onClick={() => setMobileOpen(!mobileOpen)}
          className="flex items-center justify-center rounded-[1.4rem] p-2 text-[var(--color-ink)] transition-colors hover:bg-[rgba(23,57,69,0.08)] md:hidden"
          aria-label={mobileOpen ? "Close menu" : "Open menu"}
          aria-expanded={mobileOpen}
        >
          {mobileOpen ? (
            /* X icon */
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="4" y1="4" x2="16" y2="16" />
              <line x1="16" y1="4" x2="4" y2="16" />
            </svg>
          ) : (
            /* Hamburger icon */
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="3" y1="5" x2="17" y2="5" />
              <line x1="3" y1="10" x2="17" y2="10" />
              <line x1="3" y1="15" x2="17" y2="15" />
            </svg>
          )}
        </button>
      </nav>

      {/* Mobile drawer */}
      {mobileOpen && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 top-[49px] z-30 bg-[rgba(19,32,41,0.3)] md:hidden"
            onClick={() => setMobileOpen(false)}
            aria-hidden="true"
          />
          {/* Drawer panel */}
          <div className="fixed inset-x-0 top-[49px] z-40 max-h-[calc(100dvh-49px)] overflow-y-auto border-b border-[rgba(23,57,69,0.10)] bg-[rgba(246,240,229,0.98)] px-4 pb-4 pt-2 md:hidden">
            <div className="flex flex-col gap-0.5">
              <p className="px-4 pb-1 pt-2 text-xs font-medium uppercase tracking-wider text-[rgba(19,32,41,0.40)]">
                Navigation
              </p>
              {primaryItems.map((item) => (
                <Link
                  key={item.label}
                  href={item.href}
                  className={item.match(pathname) ? mobileActiveLinkClass : mobileInactiveLinkClass}
                >
                  {item.label}
                </Link>
              ))}

              <div className="my-2 border-t border-[rgba(23,57,69,0.08)]" />

              <p className="px-4 pb-1 pt-2 text-xs font-medium uppercase tracking-wider text-[rgba(19,32,41,0.40)]">
                Tools
              </p>
              {secondaryItems.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className={item.match(pathname) ? mobileActiveLinkClass : mobileSecondaryInactiveLinkClass}
                >
                  {item.label}
                </Link>
              ))}
            </div>
          </div>
        </>
      )}


    </header>
  );
}
