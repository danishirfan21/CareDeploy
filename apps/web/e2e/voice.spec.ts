import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import { api } from "./helpers";

// These tests use the controlled browser transport (no audio, no LiveKit) and play the part of
// the voice worker by calling the worker channel of the real e2e API with the e2e secret. They
// prove the UI and the backend session/event pipeline; they do not prove audio or providers.
const WORKER = { "X-Voice-Worker-Secret": "e2e-worker-secret" };
const CLINIC = "Sandbox Family Clinic";

interface Started {
  id: string;
  room: string;
}

async function startCall(page: Page): Promise<Started> {
  await page.goto("/playground");
  await page.getByLabel("Clinic").selectOption({ label: CLINIC });
  const created = page.waitForResponse(
    (r) =>
      r.url().endsWith("/voice/sessions") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Start call" }).click();
  const body = (await (await created).json()) as {
    call_session_id: string;
    room_name: string;
  };
  return { id: body.call_session_id, room: body.room_name };
}

const base = (id: string) => `${api}/voice/worker/sessions/${id}`;

async function claim(request: APIRequestContext, s: Started) {
  const r = await request.post(`${base(s.id)}/claim`, {
    headers: WORKER,
    data: { room_name: s.room },
  });
  expect(r.status()).toBe(200);
}

let seq = 0;
async function emit(
  request: APIRequestContext,
  s: Started,
  kind: string,
  payload: Record<string, unknown>,
  eventId?: string,
) {
  seq += 1;
  const r = await request.post(`${base(s.id)}/events`, {
    headers: WORKER,
    data: {
      events: [
        {
          event_id: eventId ?? `e${seq}-${Date.now()}`,
          seq,
          kind,
          occurred_at: new Date().toISOString(),
          payload,
        },
      ],
    },
  });
  expect(r.status()).toBe(200);
}

async function setState(
  request: APIRequestContext,
  s: Started,
  state: Record<string, unknown>,
) {
  const r = await request.put(`${base(s.id)}/state`, {
    headers: WORKER,
    data: { state },
  });
  expect(r.status()).toBe(200);
}

test.beforeEach(() => {
  seq = 0;
});

test("a full call: connect, transcript, tools, confirmation, end and outcome", async ({
  page,
  request,
}) => {
  const s = await startCall(page);
  await expect(page.getByTestId("call-clinic")).toHaveText(CLINIC);
  await expect(page.getByTestId("agent-version")).toContainText("config v1");
  await expect(page.getByTestId("connecting")).toBeVisible();
  await expect(page.getByTestId("transport-status")).toHaveText("Connected");

  // The token handed to the browser is scoped and carries no API secret.
  const token = await page.evaluate(() => window.__voiceTest?.lastToken ?? "");
  expect(token.split(".")).toHaveLength(3);
  expect(token).not.toContain("e2e-livekit-secret");

  await claim(request, s);
  await setState(request, s, {
    transport: "connected",
    conversation: "listening",
  });
  await expect(page.getByTestId("call-stage")).toContainText("Listening");
  await expect(page.getByRole("button", { name: "End call" })).toBeEnabled();

  await emit(request, s, "transcript", {
    speaker: "agent",
    text: "Thanks for calling. How can I help?",
    final: true,
  });
  await emit(request, s, "transcript", {
    speaker: "caller",
    text: "I'd like to book a checkup.",
    final: true,
  });
  const transcript = page.getByTestId("transcript");
  await expect(transcript).toContainText("How can I help?");
  await expect(transcript).toContainText("book a checkup");

  // Interim speech is shown live but is not part of the transcript.
  await setState(request, s, {
    conversation: "listening",
    interim_user: "my name is Avery",
  });
  await expect(page.getByTestId("interim")).toContainText("my name is Avery");
  await expect(transcript).not.toContainText("my name is Avery");

  // Tool activity appears inline, running then finished.
  await emit(
    request,
    s,
    "tool",
    { call_id: "c1", name: "verify_patient", phase: "started", args: {} },
    "tool:c1:started",
  );
  await expect(page.getByLabel("Tool executions")).toContainText(
    "Verifying the caller",
  );
  await expect(page.getByLabel("Tool executions")).toContainText("running");
  await emit(
    request,
    s,
    "tool",
    {
      call_id: "c1",
      name: "verify_patient",
      phase: "finished",
      status: "ok",
      message: "Caller verified.",
    },
    "tool:c1:finished",
  );
  await expect(page.getByLabel("Tool executions")).toContainText(
    "Caller verified.",
  );
  await expect(page.getByLabel("Tool executions")).toContainText("succeeded");

  await setState(request, s, {
    conversation: "awaiting_confirmation",
    pending_confirmation: true,
    verified_patient: "Avery Quinn",
  });
  await expect(page.getByTestId("confirmation-pending")).toBeVisible();
  await expect(page.getByTestId("call-stage")).toContainText(
    "Waiting for the caller to confirm",
  );
  await expect(page.getByTestId("call-stage")).toContainText("Avery Quinn");

  // Caller hangs up; the worker then reports what it observed.
  await page.getByRole("button", { name: "End call" }).click();
  await expect(page.getByTestId("transport-status")).not.toHaveText(
    "Connected",
  );
  const done = await request.post(`${base(s.id)}/complete`, {
    headers: WORKER,
    data: {
      outcome: "appointment_booked",
      summary: "An appointment was booked.",
      operation_ids: ["op-e2e-1"],
    },
  });
  expect(done.status()).toBe(200);

  const outcome = page.getByTestId("call-outcome");
  await expect(outcome).toContainText("Appointment booked");
  await expect(outcome).toContainText("Duration");
  await outcome.getByRole("link", { name: "View call details" }).click();

  await expect(page).toHaveURL(new RegExp(`/activity/calls/${s.id}$`));
  await expect(page.getByTestId("call-meta")).toContainText(CLINIC);
  await expect(page.getByTestId("call-operations")).toContainText("op-e2e-1");
  await expect(page.getByRole("region", { name: "Transcript" })).toContainText(
    "book a checkup",
  );
  await expect(
    page.getByRole("region", { name: "Tool activity" }),
  ).toContainText("Caller verified.");
});

test("voice not configured shows the missing settings and starts nothing", async ({
  page,
}) => {
  await page.route("**/api/clinics/*/voice/sessions", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        detail: {
          code: "voice_not_configured",
          missing: ["LIVEKIT_URL", "LIVEKIT_API_SECRET"],
        },
      }),
    }),
  );
  await page.goto("/playground");
  await page.getByLabel("Clinic").selectOption({ label: CLINIC });
  await page.getByRole("button", { name: "Start call" }).click();
  const problem = page.getByTestId("call-problem");
  await expect(problem).toContainText("not configured");
  await expect(problem).toContainText("LIVEKIT_API_SECRET");
  await expect(page.getByTestId("transport-status")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Start call" })).toBeEnabled();
});

test("microphone denied ends the call with a clear message", async ({
  page,
  request,
}) => {
  await page.addInitScript(() => {
    window.__voiceTest = { denyMic: true };
  });
  const s = await startCall(page);
  await expect(page.getByTestId("call-problem")).toContainText(
    "Microphone access is blocked",
  );
  await expect(page.getByRole("button", { name: "Start call" })).toBeEnabled();
  await expect
    .poll(async () => {
      const r = await request.get(`${api}/voice/sessions/${s.id}`);
      const j = await r.json();
      return `${j.status}:${j.error}`;
    })
    .toBe("abandoned:microphone_denied");
});

test("connection failure is reported and the session is closed", async ({
  page,
  request,
}) => {
  await page.addInitScript(() => {
    window.__voiceTest = { failNextConnect: true };
  });
  const s = await startCall(page);
  await expect(page.getByTestId("call-problem")).toContainText(
    "Could not connect",
  );
  await expect
    .poll(async () => {
      const r = await request.get(`${api}/voice/sessions/${s.id}`);
      const j = await r.json();
      return `${j.status}:${j.error}`;
    })
    .toBe("failed:connection_failed");
});

test("losing the connection mid-call ends it and says so", async ({
  page,
  request,
}) => {
  const s = await startCall(page);
  await claim(request, s);
  await setState(request, s, { conversation: "listening" });
  await expect(page.getByTestId("call-stage")).toBeVisible();
  await page.evaluate(() =>
    window.__voiceTest?.emit?.({ type: "disconnected", reason: "network" }),
  );
  await expect(page.getByTestId("call-problem")).toContainText(
    "Connection lost",
  );
  await expect(page.getByRole("button", { name: "End call" })).toBeVisible();
});

test("mute toggles the microphone and is keyboard operable", async ({
  page,
  request,
}) => {
  const s = await startCall(page);
  await claim(request, s);
  await setState(request, s, { conversation: "listening" });
  const mute = page.getByRole("button", { name: "Mute microphone" });
  await expect(mute).toBeEnabled();
  await mute.focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("button", { name: "Unmute microphone" }),
  ).toHaveAttribute("aria-pressed", "true");
  expect(await page.evaluate(() => window.__voiceTest?.micEnabled)).toBe(false);
  await page.getByRole("button", { name: "End call" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("transport-status")).toContainText(
    /ended|Disconnected|Connected/,
  );
});

test("mobile layout has no horizontal overflow during a call", async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const s = await startCall(page);
  await claim(request, s);
  await setState(request, s, { conversation: "listening" });
  await emit(request, s, "transcript", {
    speaker: "agent",
    text: "A fairly long sentence that should wrap inside the bubble rather than overflow the narrow screen.",
    final: true,
  });
  await expect(page.getByTestId("transcript")).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(overflow).toBe(false);
  await expect(page.getByRole("button", { name: "End call" })).toBeVisible();
});
