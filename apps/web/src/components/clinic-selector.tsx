"use client";

import { api } from "@/lib/api/client";
import { useFetch } from "@/lib/use-fetch";
import { inputCls } from "@/components/ui";

/** Select a clinic from the API. Shows the latest published version, if any. */
export function ClinicSelector({
  value,
  onChange,
  label = "Clinic",
}: {
  value: string;
  onChange: (clinicId: string) => void;
  label?: string;
}) {
  const { data, error, loading } = useFetch("clinics", () => api.listClinics());
  const selected = data?.find((c) => c.id === value);
  return (
    <div>
      <label className="mb-1 block text-sm font-medium" htmlFor="clinic-select">
        {label}
      </label>
      <select
        id="clinic-select"
        className={inputCls}
        value={value}
        disabled={loading || !!error || !data?.length}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">
          {loading
            ? "Loading clinics…"
            : error
              ? "Clinics unavailable"
              : data?.length
                ? "Select a clinic"
                : "No clinics yet"}
        </option>
        {data?.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </select>
      {error && (
        <p role="alert" className="mt-1 text-xs text-danger">
          Could not load clinics: {error}
        </p>
      )}
      {selected && (
        <p className="mt-1 font-mono text-[11px] tracking-[0.04em] text-muted">
          {selected.latest_version
            ? `Published v${selected.latest_version}`
            : "Draft only, not published"}
        </p>
      )}
    </div>
  );
}
