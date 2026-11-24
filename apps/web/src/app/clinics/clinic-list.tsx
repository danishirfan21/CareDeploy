"use client";

import Link from "next/link";
import { api } from "@/lib/api/client";
import { useFetch } from "@/lib/use-fetch";
import { ButtonLink, Notice, PageHeader } from "@/components/ui";

export function ClinicList() {
  const { data, error, loading } = useFetch("clinics", () => api.listClinics());

  return (
    <>
      <PageHeader
        title="Clinics"
        subtitle="Each clinic has its own configuration and published versions."
        action={<ButtonLink href="/clinics/new">New clinic</ButtonLink>}
      />
      {loading && <p className="text-sm text-muted">Loading clinics…</p>}
      {error && <Notice tone="error">Could not load clinics: {error}</Notice>}
      {data && data.length === 0 && (
        <Notice tone="info">No clinics yet. Create one to get started.</Notice>
      )}
      {data && data.length > 0 && (
        <ul
          className="divide-y divide-line rounded-xl border border-line"
          aria-label="Clinics"
        >
          {data.map((c) => (
            <li key={c.id}>
              <Link
                href={`/clinics/${c.id}`}
                className="flex items-center justify-between gap-4 px-4 py-3.5 hover:bg-gray-50"
              >
                <div className="min-w-0">
                  <div className="truncate font-medium">{c.name}</div>
                  <div className="truncate text-sm text-muted">
                    {c.specialty} · {c.location}
                  </div>
                </div>
                <span
                  className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs ${
                    c.latest_version
                      ? "bg-accent-soft text-accent"
                      : "bg-gray-100 text-muted"
                  }`}
                >
                  {c.latest_version
                    ? `Published v${c.latest_version}`
                    : "Draft"}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
