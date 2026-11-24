"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api/client";

type State = "loading" | "ok" | "error";

// Temporary M0 connectivity probe; replaced by the real workspace in M1.
export function ConnectivityStatus() {
  const [api_, setApi] = useState<State>("loading");
  const [db, setDb] = useState<State>("loading");

  useEffect(() => {
    api.health().then(
      () => setApi("ok"),
      () => setApi("error"),
    );
    api.healthDb().then(
      () => setDb("ok"),
      () => setDb("error"),
    );
  }, []);

  return (
    <ul className="space-y-1 text-sm">
      <li data-testid="api-status">API: {api_}</li>
      <li data-testid="db-status">Database: {db}</li>
    </ul>
  );
}
