import { defineConfig } from "@playwright/test";

// E2E runs against an isolated stack: its own database (caredeploy_e2e, recreated and seeded on
// each run), API on :8001 and web on :3101. The development database is never touched.
const python =
  process.platform === "win32"
    ? "..\\api\\.venv\\Scripts\\python"
    : "../api/.venv/bin/python";
const API_PORT = 8001;
const WEB_PORT = 3101;

export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  fullyParallel: false,
  use: { baseURL: `http://localhost:${WEB_PORT}` },
  webServer: [
    {
      command: `${python} -m app.testdb caredeploy_e2e --seed --sandbox --serve ${API_PORT}`,
      cwd: "../api",
      url: `http://localhost:${API_PORT}/api/health`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        CORS_ORIGINS: `http://localhost:${WEB_PORT}`,
        // Test values only: tokens are signed but no LiveKit server exists in e2e.
        LIVEKIT_URL: "wss://livekit.e2e.invalid",
        LIVEKIT_API_KEY: "APIe2ekey",
        LIVEKIT_API_SECRET: "e2e-livekit-secret-long-enough-for-hs256",
        VOICE_WORKER_SECRET: "e2e-worker-secret",
      },
    },
    {
      command: `npx next dev -p ${WEB_PORT}`,
      url: `http://localhost:${WEB_PORT}`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        NEXT_PUBLIC_API_URL: `http://localhost:${API_PORT}`,
        // Swaps the browser transport for the controlled test adapter (no audio).
        NEXT_PUBLIC_VOICE_TEST_TRANSPORT: "1",
      },
    },
  ],
});
