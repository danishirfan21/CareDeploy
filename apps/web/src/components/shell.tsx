"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Icon, type IconName } from "./icons";
import { ConnectivityStatus } from "./status";

export const NAV: { href: string; label: string; icon: IconName }[] = [
  { href: "/clinics", label: "Clinics", icon: "clinics" },
  { href: "/playground", label: "Playground", icon: "playground" },
  { href: "/activity", label: "Activity", icon: "activity" },
];

function isActive(pathname: string, href: string) {
  return pathname === href || pathname.startsWith(href + "/");
}

function Brand({ onClick }: { onClick?: () => void }) {
  return (
    <Link
      href="/"
      onClick={onClick}
      className="flex items-center gap-2 rounded-md px-1 text-lg font-medium tracking-tight"
    >
      <span
        aria-hidden
        className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent text-white"
      >
        <svg
          viewBox="0 0 24 24"
          className="h-4 w-4"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M3 12h4l3-7 4 14 3-7h4" />
        </svg>
      </span>
      CareDeploy
    </Link>
  );
}

function NavLinks({
  pathname,
  collapsed = false,
  onNavigate,
}: {
  pathname: string;
  collapsed?: boolean;
  onNavigate?: () => void;
}) {
  return (
    <>
      {NAV.map((n) => {
        const active = isActive(pathname, n.href);
        return (
          <Link
            key={n.href}
            href={n.href}
            title={n.label}
            aria-current={active ? "page" : undefined}
            onClick={onNavigate}
            className={`flex min-h-11 items-center gap-3 rounded-lg px-3 text-sm ${
              active
                ? "bg-surface-high font-medium text-foreground"
                : "text-foreground/75 hover:bg-black/5"
            }`}
          >
            <Icon name={n.icon} />
            <span className={collapsed ? "sr-only" : ""}>{n.label}</span>
          </Link>
        );
      })}
    </>
  );
}

/**
 * Responsive shell. Desktop (lg+): collapsible 260px sidebar. Tablet (md to lg): top bar with
 * pill navigation. Mobile (below md): compact top bar, slide-in drawer and a bottom tab bar.
 * Exactly one "Primary" navigation is visible at any width.
 */
export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [drawer, setDrawer] = useState(false);

  useEffect(() => {
    if (!drawer) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setDrawer(false);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [drawer]);

  return (
    <div className="flex min-h-dvh">
      <aside
        aria-label="Sidebar"
        data-collapsed={collapsed}
        className={`sticky top-0 hidden h-dvh shrink-0 flex-col border-r border-line bg-sidebar p-3 lg:flex ${
          collapsed ? "w-[68px]" : "w-[260px]"
        }`}
      >
        <div
          className={`mb-4 flex items-center ${collapsed ? "justify-center" : "justify-between"}`}
        >
          {!collapsed && <Brand />}
          <button
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-expanded={!collapsed}
            onClick={() => setCollapsed((c) => !c)}
            className="flex h-10 w-10 items-center justify-center rounded-md text-muted hover:bg-black/5"
          >
            <Icon name="panel" />
          </button>
        </div>
        <nav className="flex flex-col gap-1" aria-label="Primary">
          <NavLinks pathname={pathname} collapsed={collapsed} />
        </nav>
        <div
          className={`mt-auto border-t border-line pt-4 ${collapsed ? "hidden" : ""}`}
        >
          <ConnectivityStatus />
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-line bg-background/95 px-4 backdrop-blur md:px-6 lg:hidden">
          <button
            aria-label="Open menu"
            aria-expanded={drawer}
            onClick={() => setDrawer(true)}
            className="-ml-2 flex h-11 w-11 items-center justify-center rounded-md hover:bg-black/5 md:hidden"
          >
            <Icon name="menu" />
          </button>
          <div className="max-md:absolute max-md:left-1/2 max-md:-translate-x-1/2">
            <Brand />
          </div>
          <nav
            aria-label="Primary"
            className="ml-auto hidden gap-1 rounded-full bg-surface-low p-1 md:flex"
          >
            {NAV.map((n) => {
              const active = isActive(pathname, n.href);
              return (
                <Link
                  key={n.href}
                  href={n.href}
                  aria-current={active ? "page" : undefined}
                  className={`flex min-h-10 items-center rounded-full px-4 text-sm ${
                    active
                      ? "bg-surface-high font-medium text-foreground"
                      : "text-muted hover:text-foreground"
                  }`}
                >
                  {n.label}
                </Link>
              );
            })}
          </nav>
        </header>

        <main
          id="main"
          className="mx-auto w-full max-w-[880px] flex-1 px-4 pb-28 pt-8 md:px-6 md:pb-16 md:pt-12 lg:pt-14"
        >
          {children}
        </main>

        <nav
          aria-label="Quick navigation"
          className="fixed inset-x-0 bottom-0 z-20 grid grid-cols-3 border-t border-line bg-background/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden"
        >
          {NAV.map((n) => {
            const active = isActive(pathname, n.href);
            return (
              <Link
                key={n.href}
                href={n.href}
                aria-current={active ? "page" : undefined}
                className={`flex min-h-16 flex-col items-center justify-center gap-1 text-xs ${
                  active ? "font-medium text-accent" : "text-muted"
                }`}
              >
                <Icon name={n.icon} />
                {n.label}
              </Link>
            );
          })}
        </nav>
      </div>

      {drawer && (
        <div
          className="fixed inset-0 z-40 md:hidden"
          role="dialog"
          aria-modal="true"
          aria-label="Menu"
        >
          <button
            aria-label="Dismiss menu"
            className="absolute inset-0 bg-black/30"
            onClick={() => setDrawer(false)}
          />
          <div className="absolute inset-y-0 left-0 flex w-[280px] flex-col bg-sidebar p-3 shadow-xl">
            <div className="mb-4 flex items-center justify-between">
              <Brand onClick={() => setDrawer(false)} />
              <button
                aria-label="Close menu"
                autoFocus
                onClick={() => setDrawer(false)}
                className="flex h-11 w-11 items-center justify-center rounded-md hover:bg-black/5"
              >
                <Icon name="close" />
              </button>
            </div>
            <nav className="flex flex-col gap-1" aria-label="Primary">
              <NavLinks
                pathname={pathname}
                onNavigate={() => setDrawer(false)}
              />
            </nav>
            <div className="mt-auto border-t border-line pt-4">
              <ConnectivityStatus />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
