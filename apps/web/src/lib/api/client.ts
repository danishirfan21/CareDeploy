import type {
  Clinic,
  ClinicConfig,
  ClinicDetails,
  ConfigResponse,
  ConfigVersion,
  ConfigVersionSummary,
  DbHealthResponse,
  HealthResponse,
  ValidationResult,
} from "./types";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public body?: unknown,
  ) {
    super(message);
  }
}

/** Turn FastAPI's `detail` (string | validation list | object) into a readable message. */
function describe(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) =>
        [d.loc?.slice(1).join("."), d.msg].filter(Boolean).join(": "),
      )
      .join("; ");
  }
  return `Request failed (${status})`;
}

/** All backend calls go through here; routes are served under /api. */
export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`${API_BASE_URL}/api${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
    cache: "no-store",
  });
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, describe(res.status, body), body);
  return body as T;
}

const json = (method: string, data?: unknown): RequestInit => ({
  method,
  body: data === undefined ? undefined : JSON.stringify(data),
});

export const api = {
  health: () => apiFetch<HealthResponse>("/health"),
  healthDb: () => apiFetch<DbHealthResponse>("/health/db"),

  listClinics: () => apiFetch<Clinic[]>("/clinics"),
  createClinic: (d: ClinicDetails) =>
    apiFetch<Clinic>("/clinics", json("POST", d)),
  getClinic: (id: string) => apiFetch<Clinic>(`/clinics/${id}`),
  updateClinic: (id: string, d: Partial<ClinicDetails>) =>
    apiFetch<Clinic>(`/clinics/${id}`, json("PATCH", d)),

  getConfig: (id: string) => apiFetch<ConfigResponse>(`/clinics/${id}/config`),
  saveConfig: (id: string, c: ClinicConfig) =>
    apiFetch<ConfigResponse>(`/clinics/${id}/config`, json("PUT", c)),
  validateConfig: (id: string) =>
    apiFetch<ValidationResult>(`/clinics/${id}/config/validate`, json("POST")),
  publishConfig: (id: string) =>
    apiFetch<ConfigVersion>(`/clinics/${id}/config/publish`, json("POST")),
  listVersions: (id: string) =>
    apiFetch<ConfigVersionSummary[]>(`/clinics/${id}/versions`),
};
