// Mirrors apps/api/app/schemas.py. Keep in sync when contracts change.
export interface HealthResponse {
  status: "ok";
  service: string;
  version: string;
}

export interface DbHealthResponse {
  status: "ok" | "unavailable";
  database: boolean;
}
