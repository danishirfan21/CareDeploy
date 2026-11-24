import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import { api, expectStep, next, unique } from "./helpers";

// Calls are created through the real API and the worker channel (the e2e worker secret); no audio
// or provider is involved. Deployment tests use a fresh clinic each, so they do not depend on the
// order of other specs or on the shared sandbox clinic's state.
const WORKER = { "X-Voice-Worker-Secret": "e2e-worker-secret" };
const SANDBOX = "Sandbox Family Clinic";
const EMPTY_CLINIC = "Lakeside Dermatology";

interface Clinic {
  id: string;
  name: string;
}
type Json = Record<string, unknown>;

async function clinicByName(request: APIRequestContext, name: string) {
  const list = (await (await request.get(`${api}/clinics`)).json()) as Clinic[];
  const c = list.find((x) => x.name === name);
  if (!c) throw new Error(`${name} is not seeded`);
  return c.id;
}

let seq = 0;
async function worker(
  request: APIRequestContext,
  sid: string,
  events: { kind: string; payload: Json }[],
) {
  const r = await request.post(`${api}/voice/worker/sessions/${sid}/events`, {
    headers: WORKER,
    data: {
      events: events.map((e) => {
        seq += 1;
        return {
          event_id: `ops-${seq}-${Date.now()}`,
          seq,
          kind: e.kind,
          occurred_at: new Date().toISOString(),
          payload: e.payload,
        };
      }),
    },
  });
  expect(r.status()).toBe(200);
}

async function makeCall(
  request: APIRequestContext,
  clinic: string,
  opts: { summary?: string; abandon?: boolean },
) {
  const created = await request.post(`${api}/clinics/${clinic}/voice/sessions`);
  expect(created.status()).toBe(201);
  const s = (await created.json()) as {
    call_session_id: string;
    room_name: string;
  };
  const sid = s.call_session_id;
  if (opts.abandon) {
    await request.post(`${api}/voice/sessions/${sid}/end`, {
      data: { reason: "user_ended" },
    });
    return sid;
  }
  const claim = await request.post(
    `${api}/voice/worker/sessions/${sid}/claim`,
    { headers: WORKER, data: { room_name: s.room_name } },
  );
  expect(claim.status()).toBe(200);
  await worker(request, sid, [
    {
      kind: "transcript",
      payload: { speaker: "caller", text: "What are your hours?", final: true },
    },
    {
      kind: "transcript",
      payload: { speaker: "agent", text: "We open at eight.", final: true },
    },
    {
      kind: "tool",
      payload: { phase: "started", call_id: "t1", name: "find_slots" },
    },
    {
      kind: "tool",
      payload: {
        phase: "finished",
        call_id: "t1",
        name: "find_slots",
        status: "rejected",
        code: "slot_unavailable",
        message: "No openings that day.",
        latency_ms: 20,
      },
    },
  ]);
  const done = await request.post(
    `${api}/voice/worker/sessions/${sid}/complete`,
    {
      headers: WORKER,
      data: {
        status: "completed",
        outcome: "information_provided",
        summary: opts.summary ?? "Caller asked about opening hours.",
      },
    },
  );
  expect(done.status()).toBe(200);
  return sid;
}

async function openCalls(page: Page, clinic: string) {
  await page.goto("/activity");
  await page
    .getByLabel("Clinic", { exact: true })
    .selectOption({ label: clinic });
}

test("a clinic with no calls shows an honest empty state", async ({ page }) => {
  await openCalls(page, EMPTY_CLINIC);
  await expect(page.getByTestId("calls-empty")).toContainText("No calls yet");
});

test("calls are listed, filtered, searched and opened", async ({
  page,
  request,
}) => {
  const clinic = await clinicByName(request, SANDBOX);
  const info = await makeCall(request, clinic, {});
  const gone = await makeCall(request, clinic, { abandon: true });

  await openCalls(page, SANDBOX);
  const table = page.getByTestId("calls-table");
  await expect(table).toBeVisible();
  await expect(table).toContainText("Information request");
  await expect(table).toContainText("Abandoned");

  // Outcome filter.
  await page.getByLabel("Outcome").selectOption("abandoned");
  await expect(table).not.toContainText("Completed");
  await expect(table).toContainText("Abandoned");

  // Search by safe metadata (call id prefix).
  await page.getByLabel("Outcome").selectOption("");
  await page.getByLabel("Search calls").fill(info.slice(0, 8));
  await expect(page.getByTestId("call-link")).toHaveCount(1);

  // A date range that excludes every call empties the list.
  await page.getByLabel("Search calls").fill("");
  await page.getByLabel("From date").fill("2001-01-01");
  await page.getByLabel("To date").fill("2001-01-02");
  await expect(page.getByTestId("calls-empty")).toContainText(
    "No calls match these filters",
  );
  await page.getByLabel("From date").fill("");
  await page.getByLabel("To date").fill("");

  // Details.
  await page.getByLabel("Search calls").fill(info.slice(0, 8));
  await expect(page.getByTestId("call-link")).toHaveCount(1);
  await page.getByTestId("call-link").click();
  await expect(page.getByTestId("call-outcome")).toContainText("Completed");
  await expect(page.getByTestId("call-config")).toContainText("Version");
  await expect(page.getByTestId("transcript")).toContainText(
    "What are your hours?",
  );
  await expect(page.getByTestId("agent-actions")).toContainText(
    "Scheduling conflict",
  );
  await expect(page.getByTestId("call-evaluation")).toBeVisible();
  const technical = page.getByTestId("technical-details");
  await expect(technical).toBeVisible();
  expect(await technical.evaluate((e) => (e as HTMLDetailsElement).open)).toBe(
    false,
  );
  await technical.getByText("Technical details").click();
  await expect(technical).toContainText(
    "Cost unavailable: provider usage data was not recorded.",
  );

  // A call with no transcript says so rather than inventing one.
  await page.goto(`/activity/calls/${gone}?clinic=${clinic}`);
  await expect(page.getByTestId("no-transcript")).toBeVisible();
  await expect(page.getByTestId("call-outcome")).toContainText("Abandoned");
});

test("compact metrics expand into a secondary view", async ({
  page,
  request,
}) => {
  const clinic = await clinicByName(request, SANDBOX);
  await makeCall(request, clinic, {});
  await openCalls(page, SANDBOX);
  await expect(page.getByTestId("metric-completion")).toBeVisible();
  await expect(page.getByTestId("metric-escalation")).toBeVisible();
  await expect(page.getByTestId("metric-duration")).toBeVisible();
  await expect(page.getByTestId("metrics-details")).toHaveCount(0);
  await page.getByTestId("metrics-toggle").click();
  await expect(page.getByTestId("cost-line")).toContainText(
    "Cost unavailable: provider usage data was not recorded.",
  );
});

test("activity works on a phone without horizontal scrolling", async ({
  page,
  request,
}) => {
  const clinic = await clinicByName(request, SANDBOX);
  await makeCall(request, clinic, {});
  await page.setViewportSize({ width: 375, height: 812 });
  await openCalls(page, SANDBOX);
  await expect(page.getByTestId("calls-table")).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(overflow).toBe(false);
});

// ------------------------------------------------------------------------------ deployment ---
async function newClinic(request: APIRequestContext) {
  const sandbox = await clinicByName(request, SANDBOX);
  const cfg = (await (
    await request.get(`${api}/clinics/${sandbox}/config`)
  ).json()) as { config: { details: Json; agent: Json } & Json };
  const name = unique("Deploy Clinic");
  const details = { ...cfg.config.details, name };
  const created = await request.post(`${api}/clinics`, { data: details });
  expect(created.status()).toBe(201);
  const id = ((await created.json()) as Clinic).id;
  // Appointment-type ids belong to the clinic they were created in: send new types without ids.
  const types = ((cfg.config as Json).appointment_types as Json[]).map((t) =>
    Object.fromEntries(Object.entries(t).filter(([k]) => k !== "id")),
  );
  const config = { ...cfg.config, details, appointment_types: types };
  expect(
    (
      await request.put(`${api}/clinics/${id}/config`, { data: config })
    ).status(),
  ).toBe(200);
  const pub = await request.post(`${api}/clinics/${id}/config/publish`);
  expect([200, 201]).toContain(pub.status());
  return { id, name, config };
}

async function publishChange(
  request: APIRequestContext,
  id: string,
  config: { agent: Json } & Json,
  greeting: string,
) {
  const changed = { ...config, agent: { ...config.agent, greeting } };
  await request.put(`${api}/clinics/${id}/config`, { data: changed });
  const pub = await request.post(`${api}/clinics/${id}/config/publish`);
  expect([200, 201]).toContain(pub.status());
}

async function evaluate(
  request: APIRequestContext,
  id: string,
  version: number,
) {
  const started = await request.post(`${api}/clinics/${id}/evaluations/runs`, {
    data: { config_version: version },
  });
  expect(started.status()).toBe(202);
  await expect
    .poll(
      async () => {
        const runs = (await (
          await request.get(`${api}/clinics/${id}/evaluations/runs`)
        ).json()) as { status: string }[];
        return runs.some((r) => ["queued", "running"].includes(r.status));
      },
      { timeout: 180_000, intervals: [1000] },
    )
    .toBe(false);
}

async function stepFive(page: Page, id: string) {
  await page.goto(`/clinics/${id}/configure`);
  for (let n = 1; n < 5; n++) {
    await next(page);
    await expectStep(page, n + 1);
  }
  await expect(page.getByTestId("deployment-panel")).toBeVisible();
}

test("deployment is blocked, then promoted, then rolled back", async ({
  page,
  request,
}) => {
  test.setTimeout(480_000);
  const { id, config } = await newClinic(request);

  // Without an active deployment a call cannot start, and the error says how to proceed.
  const refused = await request.post(`${api}/clinics/${id}/voice/sessions`);
  expect(refused.status()).toBe(409);
  const detail = (
    (await refused.json()) as {
      detail: { code: string; message: string };
    }
  ).detail;
  expect(detail.code).toBe("no_active_deployment");
  expect(detail.message).toMatch(/evaluate/i);

  // Blocked: no evaluation evidence yet.
  await stepFive(page, id);
  await expect(page.getByTestId("deployment-active")).toContainText(
    "No version is active",
  );
  await expect(page.getByTestId("deployment-headline")).toContainText(
    "blocked",
  );
  await expect(page.getByTestId("deployment-missing")).toContainText(
    "workflow evaluation",
  );
  await expect(page.getByTestId("promote-button")).toBeDisabled();
  await expect(page.getByTestId("live-verification")).toContainText(
    "Real voice verification has not been completed",
  );

  // Evaluate version 1, then deploy it.
  await evaluate(request, id, 1);
  await stepFive(page, id);
  await expect(page.getByTestId("deployment-headline")).toContainText(
    "Eligible",
  );
  await page.getByTestId("promote-button").click();
  await expect(page.getByTestId("deployment-done")).toContainText("now active");
  await expect(page.getByTestId("deployment-active")).toContainText(
    "version 1",
  );
  const call = await request.post(`${api}/clinics/${id}/voice/sessions`);
  expect(call.status()).toBe(201);
  expect(
    ((await call.json()) as { config_version: number }).config_version,
  ).toBe(1);

  // Version 2 is published but is not used until it is evaluated and deployed.
  await publishChange(request, id, config, "A new greeting for version two.");
  const stillOne = await request.post(`${api}/clinics/${id}/voice/sessions`);
  expect(
    ((await stillOne.json()) as { config_version: number }).config_version,
  ).toBe(1);
  await evaluate(request, id, 2);
  await stepFive(page, id);
  await page.getByTestId("promote-button").click();
  await expect(page.getByTestId("deployment-active")).toContainText(
    "version 2",
  );

  // Rollback needs confirmation, restores version 1 and adds history.
  await page.getByLabel("Roll back to").selectOption("1");
  await expect(page.getByTestId("rollback-confirm-panel")).toContainText(
    "version 1",
  );
  await page.getByTestId("rollback-confirm").click();
  await expect(page.getByTestId("deployment-active")).toContainText(
    "version 1",
  );
  await page.getByRole("button", { name: /History/ }).click();
  const history = page.getByTestId("deployment-history");
  await expect(history).toContainText("restored through rollback");
  await expect(history).toContainText("promoted");
});

test("the clinic page states which version is active", async ({
  page,
  request,
}) => {
  const id = await clinicByName(request, SANDBOX);
  await page.goto(`/clinics/${id}`);
  await expect(page.getByTestId("deployment-summary")).toContainText(
    "is active in Simulated Live",
  );
});
