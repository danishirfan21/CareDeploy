import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import { api, unique } from "./helpers";

// These run the real evaluation worker against the e2e database. Workflow simulation is the only
// mode that can run here (no model credentials, no audio), and the tests assert exactly that.
// The seeded sample clinics stay drafts for other specs, so evaluations use the pre-published
// sandbox clinic (seeded with --sandbox) and never publish or edit anything other specs rely on.
const NORTHSTAR = "Sandbox Family Clinic";
const LAKESIDE = NORTHSTAR;

interface Clinic {
  id: string;
  name: string;
}
interface Run {
  id: string;
  status: string;
}

async function clinicId(request: APIRequestContext, name: string) {
  const list = (await (await request.get(`${api}/clinics`)).json()) as Clinic[];
  const found = list.find((c) => c.name === name);
  if (!found) throw new Error(`clinic ${name} is not seeded`);
  return found.id;
}

async function runs(request: APIRequestContext, id: string) {
  return (await (
    await request.get(`${api}/clinics/${id}/evaluations/runs`)
  ).json()) as Run[];
}

/** Tests share a database; wait until the clinic has no queued or running evaluation. */
async function waitIdle(request: APIRequestContext, id: string) {
  await expect
    .poll(
      async () =>
        (await runs(request, id)).some((r) =>
          ["queued", "running"].includes(r.status),
        ),
      { timeout: 120_000 },
    )
    .toBe(false);
}

async function choose(page: Page, clinic: string) {
  await page.goto("/evaluations");
  await page
    .getByLabel("Clinic", { exact: true })
    .selectOption({ label: clinic });
}

test("a clinic with no runs shows the first-run prompt and a disabled Run", async ({
  page,
  request,
}) => {
  const name = unique("Evaluation Empty Clinic");
  const created = await request.post(`${api}/clinics`, {
    data: {
      name,
      specialty: "Family medicine",
      location: "Portland, Oregon",
      timezone: "America/Los_Angeles",
      phone: "(503) 555-0100",
      email: "front-desk@example.com",
    },
  });
  expect(created.ok()).toBeTruthy();
  await choose(page, name);
  await expect(
    page.getByText("Publish a configuration before running"),
  ).toBeVisible();
  await expect(page.getByTestId("evaluations-empty")).toContainText(
    "Run your first evaluation to check this agent's scheduling behavior.",
  );
  await expect(
    page.getByRole("button", { name: "Run evaluation" }),
  ).toBeDisabled();
});

test("unavailable modes are labelled Not run and cannot be started", async ({
  page,
}) => {
  await choose(page, NORTHSTAR);
  const mode = page.getByLabel("Evaluation mode");
  await expect(mode.locator("option")).toHaveText([
    "Workflow simulation",
    "LLM conversation (not run)",
    "Real audio (not run)",
  ]);
  await mode.selectOption({ label: "LLM conversation (not run)" });
  await expect(page.getByTestId("mode-unavailable")).toContainText("Not run");
  await expect(
    page.getByRole("button", { name: "Run evaluation" }),
  ).toBeDisabled();
});

test("run a category, inspect a result, and rerun one scenario", async ({
  page,
  request,
}) => {
  test.setTimeout(240_000);
  const id = await clinicId(request, NORTHSTAR);
  await waitIdle(request, id);
  await choose(page, NORTHSTAR);
  await page
    .getByLabel("Scenarios")
    .selectOption({ label: "Appointment workflows" });
  await page.getByRole("button", { name: "Run evaluation" }).click();

  const group = page.getByTestId("group-appointment_workflows");
  await expect(group).toBeVisible({ timeout: 120_000 });
  await expect(group.getByTestId("group-counts")).toHaveText("4 passed");
  await expect(page.getByTestId("run-summary")).toContainText("Completed");
  await expect(page.getByTestId("run-counts")).toHaveText("4 passed");

  // Honest readiness: a partial run establishes nothing, and modes stay separate.
  await expect(page.getByTestId("readiness")).toHaveAttribute(
    "data-level",
    "not_evaluated",
  );
  await expect(page.getByTestId("mode-workflow")).toContainText(
    "Partial run only",
  );
  await expect(page.getByTestId("mode-llm")).toContainText("Not run");
  await expect(page.getByTestId("mode-real_audio")).toContainText("Not run");
  await expect(page.getByText(/\d+\s*%/)).toHaveCount(0);

  await page.getByTestId("result-EVAL-001").click();
  await expect(page.getByTestId("result-inspector")).toHaveAttribute(
    "data-scenario",
    "EVAL-001",
  );
  await expect(page.getByTestId("inspector-expected")).not.toBeEmpty();
  await expect(page.getByTestId("tool-events")).toBeVisible();
  await expect(page.getByTestId("raw-json")).not.toHaveAttribute("open", "");
  await expect(page.getByTestId("trace")).not.toHaveAttribute("open", "");

  await page.getByRole("button", { name: "Rerun scenario" }).click();
  await expect(page.getByTestId("run-counts")).toHaveText("1 passed", {
    timeout: 120_000,
  });
});

test("a running evaluation shows progress and can be cancelled", async ({
  page,
  request,
}) => {
  test.setTimeout(240_000);
  const id = await clinicId(request, LAKESIDE);
  await waitIdle(request, id);
  await choose(page, LAKESIDE);
  await page.getByRole("button", { name: "Run evaluation" }).click();

  const progress = page.getByTestId("run-progress");
  await expect(progress).toBeVisible({ timeout: 30_000 });
  await expect(progress.getByRole("progressbar")).toBeVisible();
  // Duplicate submission is prevented while the run is active.
  await expect(
    page.getByRole("button", { name: "Run evaluation" }),
  ).toBeDisabled();
  const duplicate = await request.post(
    `${api}/clinics/${id}/evaluations/runs`,
    { data: {} },
  );
  expect(duplicate.status()).toBe(409);

  await page.getByRole("button", { name: "Cancel run" }).click();
  await expect(page.getByTestId("run-summary")).toContainText("Cancelled", {
    timeout: 120_000,
  });
  // A queued run is cancelled with nothing run; a started one records the rest as not run.
  // Either way nothing is ever reported as passed.
  await expect(page.getByTestId("run-counts")).not.toContainText("passed");
  await waitIdle(request, id);
});

test("activity lists persisted evaluation runs", async ({ page, request }) => {
  const id = await clinicId(request, NORTHSTAR);
  await waitIdle(request, id);
  const started = await request.post(`${api}/clinics/${id}/evaluations/runs`, {
    data: { selection: { kind: "scenario", value: "EVAL-002" } },
  });
  expect(started.status()).toBe(202);
  await waitIdle(request, id);

  await page.goto("/activity");
  await page.getByRole("tab", { name: /Evaluations/ }).click();
  await page
    .getByLabel("Clinic", { exact: true })
    .selectOption({ label: NORTHSTAR });
  const history = page.getByTestId("run-history");
  await expect(history).toBeVisible();
  await history.getByRole("button").first().click();
  await expect(page.getByTestId("activity-detail")).toContainText("Completed");
  // The Calls tab is unaffected.
  await page.getByRole("tab", { name: /Calls/ }).click();
  await expect(page.getByRole("tab", { name: /Calls/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
});

test.describe("mobile", () => {
  test.use({ viewport: { width: 390, height: 844 } });
  test("results do not overflow the viewport", async ({ page, request }) => {
    const id = await clinicId(request, NORTHSTAR);
    await waitIdle(request, id);
    await choose(page, NORTHSTAR);
    await expect(page.getByTestId("run-history")).toBeVisible();
    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });
});
