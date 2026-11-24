"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { ConnectivityStatus } from "./status";

const NAV = [
  {
    href: "/clinics",
    label: "Clinics",
    icon: "M4 21V8l8-5 8 5v13M9 21v-6h6v6",
  },
  {
    href: "/playground",
    label: "Playground",
    icon: "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM5 11a7 7 0 0 0 14 0M12 18v3",
  },
  { href: "/activity", label: "Activity", icon: "M3 12h4l3-8 4 16 3-8h4" },
];

function Icon({ d }: { d: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-5 w-5 shrink-0"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d={d} />
    </svg>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="flex min-h-screen">
      {mobileOpen && (
        <button
          aria-label="Close menu"
          className="fixed inset-0 z-20 bg-black/20 md:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}
      <aside
        aria-label="Sidebar"
        data-collapsed={collapsed}
        className={`fixed inset-y-0 left-0 z-30 flex w-60 flex-col border-r border-line bg-[#f9fafb] p-3 transition-transform md:sticky md:top-0 md:h-screen md:translate-x-0 ${
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        } ${collapsed ? "md:w-16" : "md:w-60"}`}
      >
        <div className="mb-4 flex items-center justify-between">
          <Link
            href="/"
            onClick={() => setMobileOpen(false)}
            className={`px-2 text-sm font-semibold tracking-tight ${collapsed ? "md:hidden" : ""}`}
          >
            Care<span className="text-accent">Deploy</span>
          </Link>
          <button
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            onClick={() => setCollapsed((c) => !c)}
            className="hidden rounded-md p-2 text-muted hover:bg-black/5 md:block"
          >
            <Icon d="M4 5h16v14H4zM9 5v14" />
          </button>
        </div>
        <nav className="flex flex-col gap-1" aria-label="Primary">
          {NAV.map((n) => {
            const active =
              pathname === n.href || pathname.startsWith(n.href + "/");
            return (
              <Link
                key={n.href}
                href={n.href}
                title={n.label}
                aria-current={active ? "page" : undefined}
                onClick={() => setMobileOpen(false)}
                className={`flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm ${
                  active
                    ? "bg-accent-soft font-medium text-accent"
                    : "text-foreground/80 hover:bg-black/5"
                }`}
              >
                <Icon d={n.icon} />
                <span className={collapsed ? "md:hidden" : ""}>{n.label}</span>
              </Link>
            );
          })}
        </nav>
        <div className={`mt-auto pt-4 ${collapsed ? "md:hidden" : ""}`}>
          <ConnectivityStatus />
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b border-line px-4 py-3 md:hidden">
          <button
            aria-label="Open menu"
            onClick={() => setMobileOpen(true)}
            className="rounded-md p-1.5 hover:bg-black/5"
          >
            <Icon d="M4 6h16M4 12h16M4 18h16" />
          </button>
          <span className="text-sm font-semibold">
            Care<span className="text-accent">Deploy</span>
          </span>
        </header>
        <main className="mx-auto w-full max-w-3xl flex-1 px-5 py-10 md:px-8 md:py-14">
          {children}
        </main>
      </div>
    </div>
  );
}
