"use client";

import Link from "next/link";
import { api } from "@/lib/api/client";
import { useFetch } from "@/lib/use-fetch";
import { formatDate } from "@/lib/format";
import { ConfigSummary } from "@/components/config-summary";
import { ButtonLink, Notice, PageHeader } from "@/components/ui";

export function ClinicDetail({ id }: { id: string }) {
  const { data, error, loading } = useFetch(`clinic:${id}`, async () => {
    const [clinic, cfg, versions] = await Promise.all([
      api.getClinic(id),
      api.getConfig(id),
      api.listVersions(id),
    ]);
    return { clinic, cfg, versions };
  });

  if (loading) return <p className="text-sm text-muted">Loading clinic…</p>;
  if (error || !data)
    return <Notice tone="error">Could not load clinic: {error}</Notice>;
  const { clinic, cfg, versions } = data;

  return (
    <>
      <p className="mb-4 text-sm">
        <Link
          href="/clinics"
          className="inline-flex min-h-11 items-center text-muted hover:text-foreground"
        >
          ← Clinics
        </Link>
      </p>
      <PageHeader
        title={clinic.name}
        subtitle={`${clinic.specialty} · ${clinic.location}`}
        action={
          <ButtonLink href={`/clinics/${id}/configure`}>
            Edit configuration
          </ButtonLink>
        }
      />

      <div className="mb-8">
        {cfg.latest_version === null ? (
          <Notice tone="info">
            Draft only. This configuration has never been published.
          </Notice>
        ) : cfg.has_unpublished_changes ? (
          <Notice tone="warning">
            The draft has changes that are not in published version v
            {cfg.latest_version}.
          </Notice>
        ) : (
          <Notice tone="success">
            The draft matches published version v{cfg.latest_version}.
          </Notice>
        )}
      </div>

      <h2 className="mb-3 text-xl font-medium">Published versions</h2>
      {versions.length === 0 ? (
        <p className="mb-2 text-sm text-muted">None yet.</p>
      ) : (
        <ul
          className="mb-2 divide-y divide-line rounded-2xl border border-line bg-surface"
          aria-label="Published versions"
        >
          {versions.map((v) => (
            <li
              key={v.version}
              className="flex justify-between px-4 py-2.5 text-sm"
            >
              <span className="font-medium">Version {v.version}</span>
              <span className="text-muted">{formatDate(v.published_at)}</span>
            </li>
          ))}
        </ul>
      )}
      <p className="mb-8 text-xs text-muted">
        Published versions are immutable snapshots. Voice deployment is not
        available yet.
      </p>

      <h2 className="mb-3 text-xl font-medium">Current draft</h2>
      <ConfigSummary config={cfg.config} />
    </>
  );
}
