import type {
  Clinic,
  ClinicConfig,
  ClinicDetails,
  ConfigResponse,
  ConfigVersion,
  ConfigVersionSummary,
  CallDetail,
  CallEvent,
  CallList,
  CallMetrics,
  DeploymentAssessment,
  DeploymentEvent,
  DeploymentRead,
  DeploymentState,
  DbHealthResponse,
  EvalCatalog,
  EvalMode,
  EvalReadiness,
  EvalResultDetail,
  EvalRunDetail,
  EvalRunSummary,
  EvalSelection,
  HealthResponse,
  ValidationResult,
  VoiceSession,
  VoiceSessionCreated,
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
  if (
    detail &&
    typeof detail === "object" &&
    typeof (detail as { message?: unknown }).message === "string"
  ) {
    return (detail as { message: string }).message;
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

  startVoiceSession: (clinicId: string) =>
    apiFetch<VoiceSessionCreated>(
      `/clinics/${clinicId}/voice/sessions`,
      json("POST"),
    ),
  getVoiceSession: (id: string) =>
    apiFetch<VoiceSession>(`/voice/sessions/${id}`),
  getVoiceEvents: (id: string, afterSeq?: number) =>
    apiFetch<{ events: CallEvent[] }>(
      `/voice/sessions/${id}/events${afterSeq === undefined ? "" : `?after_seq=${afterSeq}`}`,
    ),
  endVoiceSession: (
    id: string,
    reason:
      "user_ended" | "connection_failed" | "page_closed" | "microphone_denied",
  ) =>
    apiFetch<VoiceSession>(
      `/voice/sessions/${id}/end`,
      json("POST", { reason }),
    ),

  // Evaluations (M4)
  evalCatalog: () => apiFetch<EvalCatalog>("/evaluations/scenarios"),
  listEvalRuns: (clinicId: string, limit = 25) =>
    apiFetch<EvalRunSummary[]>(
      `/clinics/${clinicId}/evaluations/runs?limit=${limit}`,
    ),
  startEvalRun: (
    clinicId: string,
    body: {
      mode: EvalMode;
      config_version?: number;
      selection: EvalSelection;
    },
  ) =>
    apiFetch<EvalRunSummary>(
      `/clinics/${clinicId}/evaluations/runs`,
      json("POST", body),
    ),
  getEvalRun: (clinicId: string, runId: string) =>
    apiFetch<EvalRunDetail>(`/clinics/${clinicId}/evaluations/runs/${runId}`),
  getEvalResult: (clinicId: string, runId: string, scenarioId: string) =>
    apiFetch<EvalResultDetail>(
      `/clinics/${clinicId}/evaluations/runs/${runId}/results/${scenarioId}`,
    ),
  cancelEvalRun: (clinicId: string, runId: string) =>
    apiFetch<EvalRunSummary>(
      `/clinics/${clinicId}/evaluations/runs/${runId}/cancel`,
      json("POST"),
    ),
  rerunEvalScenario: (clinicId: string, runId: string, scenarioId: string) =>
    apiFetch<EvalRunSummary>(
      `/clinics/${clinicId}/evaluations/runs/${runId}/rerun`,
      json("POST", { scenario_id: scenarioId }),
    ),
  evalReadiness: (clinicId: string, version?: number) =>
    apiFetch<EvalReadiness>(
      `/clinics/${clinicId}/evaluations/readiness${version ? `?config_version=${version}` : ""}`,
    ),

  // Call operations (M5)
  listCalls: (
    clinicId: string,
    q: {
      outcome?: string;
      date_from?: string;
      date_to?: string;
      q?: string;
      limit?: number;
      offset?: number;
    },
  ) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(q))
      if (v !== undefined && v !== "") p.set(k, String(v));
    return apiFetch<CallList>(`/clinics/${clinicId}/calls?${p.toString()}`);
  },
  getCall: (clinicId: string, callId: string) =>
    apiFetch<CallDetail>(`/clinics/${clinicId}/calls/${callId}`),
  callMetrics: (clinicId: string, from?: string, to?: string) => {
    const p = new URLSearchParams();
    if (from) p.set("date_from", from);
    if (to) p.set("date_to", to);
    return apiFetch<CallMetrics>(
      `/clinics/${clinicId}/call-metrics?${p.toString()}`,
    );
  },

  // Deployments (M5)
  getDeployment: (clinicId: string) =>
    apiFetch<DeploymentState>(`/clinics/${clinicId}/deployment`),
  deploymentHistory: (clinicId: string) =>
    apiFetch<DeploymentEvent[]>(`/clinics/${clinicId}/deployment/history`),
  deploymentReadiness: (
    clinicId: string,
    version: number,
    action: "promote" | "rollback" = "promote",
  ) =>
    apiFetch<DeploymentAssessment>(
      `/clinics/${clinicId}/deployment/readiness?config_version=${version}&action=${action}`,
    ),
  promote: (
    clinicId: string,
    version: number,
    expectedActive: number | null,
    key: string,
  ) =>
    apiFetch<DeploymentRead>(
      `/clinics/${clinicId}/deployment/promote`,
      json("POST", {
        config_version: version,
        expected_active_version: expectedActive,
        idempotency_key: key,
      }),
    ),
  rollback: (
    clinicId: string,
    version: number,
    expectedActive: number | null,
    key: string,
  ) =>
    apiFetch<DeploymentRead>(
      `/clinics/${clinicId}/deployment/rollback`,
      json("POST", {
        target_version: version,
        expected_active_version: expectedActive,
        idempotency_key: key,
      }),
    ),
};
