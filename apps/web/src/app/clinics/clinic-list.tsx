"use client";

import Link from "next/link";
import { api } from "@/lib/api/client";
import { useFetch } from "@/lib/use-fetch";
import { Icon } from "@/components/icons";
import { ButtonLink, Notice, PageHeader } from "@/components/ui";
import { StatusIndicator } from "@/components/primitives";

export function ClinicList() {
  const { data, error, loading } = useFetch("clinics", () => api.listClinics());

  return (
    <>
      <PageHeader
        title="Your clinics"
        subtitle="Each clinic has its own configuration and published versions."
        action={
          <ButtonLink href="/clinics/new">
            <Icon name="plus" className="h-4 w-4" /> New clinic
          </ButtonLink>
        }
      />
      {loading && <p className="text-sm text-muted">Loading clinics…</p>}
      {error && <Notice tone="error">Could not load clinics: {error}</Notice>}
      {data && data.length === 0 && (
        <Notice tone="info">No clinics yet. Create one to get started.</Notice>
      )}
      {data && data.length > 0 && (
        <ul className="space-y-3" aria-label="Clinics">
          {data.map((c) => {
            const published = c.latest_version !== null;
            return (
              <li key={c.id}>
                <Link
                  href={`/clinics/${c.id}`}
                  className="flex items-center gap-4 rounded-2xl border border-line bg-surface p-4 shadow-[0_1px_2px_rgba(0,0,0,0.03)] hover:border-accent/50 md:p-5"
                >
                  <span
                    aria-hidden
                    className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${
                      published
                        ? "bg-accent-soft text-primary"
                        : "bg-surface-low text-muted"
                    }`}
                  >
                    <Icon name="building" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                      <span className="truncate text-lg font-medium">
                        {c.name}
                      </span>
                      <StatusIndicator tone={published ? "success" : "neutral"}>
                        {published ? `Published v${c.latest_version}` : "Draft"}
                      </StatusIndicator>
                    </span>
                    <span className="block truncate text-sm text-muted">
                      {c.specialty} · {c.location}
                    </span>
                  </span>
                  <span className="hidden shrink-0 items-center gap-1 rounded-lg bg-surface-high/70 px-3 py-2 text-sm sm:inline-flex">
                    {published ? "Open" : "Resume setup"}
                    <Icon name="arrowRight" className="h-4 w-4" />
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
