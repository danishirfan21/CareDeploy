"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api/client";

type State = "checking" | "ok" | "error";

const dot: Record<State, string> = {
  checking: "bg-gray-300",
  ok: "bg-accent",
  error: "bg-red-500",
};

/** Small connectivity indicator (M0 health probes) shown at the bottom of the sidebar. */
export function ConnectivityStatus() {
  const [apiState, setApi] = useState<State>("checking");
  const [dbState, setDb] = useState<State>("checking");

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

  const row = (label: string, s: State, testid: string) => (
    <li className="flex items-center gap-2" data-testid={testid}>
      <span className={`h-1.5 w-1.5 rounded-full ${dot[s]}`} aria-hidden />
      {label}: {s}
    </li>
  );

  return (
    <ul
      className="space-y-1 px-2 text-xs text-muted"
      aria-label="System status"
    >
      {row("API", apiState, "api-status")}
      {row("Database", dbState, "db-status")}
    </ul>
  );
}
