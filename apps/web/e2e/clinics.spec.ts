import { expect, test } from "@playwright/test";
import { api, fillStep1 } from "./helpers";

test("lists both seeded clinics with distinct configuration", async ({
  page,
}) => {
  await page.goto("/clinics");
  const list = page.getByRole("list", { name: "Clinics" });
  await expect(list).toContainText("Northstar Family Medicine");
  await expect(list).toContainText("Lakeside Dermatology");

  await list.getByRole("link", { name: /Lakeside/ }).click();
  const summary = page.getByTestId("config-summary");
  await expect(summary).toContainText("America/Denver");
  await expect(summary).toContainText("Human escalation");
  await expect(summary).toContainText("10:00 AM – 6:00 PM");

  await page.goto("/clinics");
  await list.getByRole("link", { name: /Northstar/ }).click();
  await expect(page.getByTestId("config-summary")).toContainText(
    "America/Chicago",
  );
  await expect(page.getByTestId("config-summary")).not.toContainText(
    "Human escalation",
  );
});

test("wizard validates each step before continuing", async ({ page }) => {
  await page.goto("/clinics/new");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("Enter the clinic name.")).toBeVisible();
  await expect(page.getByTestId("step-indicator")).toContainText("Step 1 of 5");

  await fillStep1(page, "Validation Clinic");
  await page.getByLabel("Email").fill("not-an-email");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("Enter a valid email address.")).toBeVisible();
  await page.getByLabel("Email").fill("ok@example.com");
  await page.getByRole("button", { name: "Continue" }).click();

  await expect(page.getByTestId("step-indicator")).toContainText("Step 2 of 5");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(
    page.getByText("Select at least one operating day."),
  ).toBeVisible();
  await expect(
    page.getByText("Add at least one appointment type."),
  ).toBeVisible();
});

test("create a clinic, complete the wizard, save, reopen and publish", async ({
  page,
}) => {
  await page.goto("/clinics/new");
  await fillStep1(page, "Harbor Pediatrics");
  await page.getByRole("button", { name: "Continue" }).click();

  // Step 2
  await expect(page.getByTestId("step-indicator")).toContainText("Step 2 of 5");
  for (const d of ["Monday", "Tuesday", "Wednesday"]) {
    await page.getByLabel(d, { exact: true }).check();
  }
  await page.getByLabel("Monday opens").fill("08:00");
  await page.getByLabel("Monday closes").fill("16:00");
  await page.getByRole("button", { name: "+ Add appointment type" }).click();
  await page.getByLabel("Appointment type 1 name").fill("Well visit");
  await page.getByLabel("Appointment type 1 duration (minutes)").fill("20");
  await page.getByRole("button", { name: "Continue" }).click();

  // Step 3
  await expect(page.getByTestId("step-indicator")).toContainText("Step 3 of 5");
  await page.getByLabel("Minimum notice (hours)").fill("6");
  await page.getByLabel("Max reschedules").fill("1");
  await page.getByRole("button", { name: "Continue" }).click();

  // Step 4: Back keeps state
  await page.getByRole("button", { name: "Back" }).click();
  await expect(page.getByLabel("Minimum notice (hours)")).toHaveValue("6");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("Name the agent.")).toBeVisible();
  await page.getByLabel("Agent name").fill("Harbor");
  await page
    .getByLabel("Greeting")
    .fill("Thanks for calling Harbor Pediatrics.");
  await page.getByLabel("Intent: Book appointment").check();
  await page.getByLabel("Capability: Check availability").check();
  await page.getByRole("button", { name: "Continue" }).click();

  // Step 5: server validation reports the missing capability
  await expect(page.getByTestId("step-indicator")).toContainText("Step 5 of 5");
  await expect(page.getByTestId("validation-results")).toContainText(
    "needs the 'book_appointment' capability",
  );
  await expect(
    page.getByRole("button", { name: "Publish version" }),
  ).toBeDisabled();

  // Fix on step 4, re-validate, publish.
  await page.getByRole("button", { name: "Back" }).click();
  await page.getByLabel("Capability: Book appointment").check();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByTestId("validation-results")).toContainText(
    "No blocking issues",
  );
  await page.getByRole("button", { name: "Publish version" }).click();
  await expect(page.getByTestId("published-notice")).toContainText(
    "Version 1 published",
  );
  await expect(page.getByTestId("published-notice")).toContainText(
    "Evaluate it, then deploy it",
  );

  // Visible on the clinic page and the list.
  await page.getByRole("link", { name: "View clinic" }).click();
  await expect(
    page.getByRole("list", { name: "Published versions" }),
  ).toContainText("Version 1");
  await expect(page.getByTestId("config-summary")).toContainText(
    "Well visit · 20 min",
  );

  await page.goto("/clinics");
  const row = page.getByRole("link", { name: /Harbor Pediatrics/ });
  await expect(row).toContainText("Published v1");
  await expect(page.getByRole("link", { name: /Northstar/ })).toContainText(
    "Draft",
  );

  // Reopen the wizard: saved values persisted in the database.
  await row.click();
  await page.getByRole("link", { name: "Edit configuration" }).click();
  await expect(page.getByLabel("Clinic name")).toHaveValue("Harbor Pediatrics");
  await page.getByLabel("Location").fill("Salem, Oregon");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Draft saved.")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Location")).toHaveValue("Salem, Oregon");

  // Isolation: other clinics unchanged; published v1 keeps the old location.
  const clinics = await (await page.request.get(`${api}/clinics`)).json();
  const harbor = clinics.find(
    (c: { name: string }) => c.name === "Harbor Pediatrics",
  );
  const v1 = await (
    await page.request.get(`${api}/clinics/${harbor.id}/versions/1`)
  ).json();
  expect(v1.config.details.location).toBe("Portland, Oregon");
  const lake = clinics.find(
    (c: { name: string }) => c.name === "Lakeside Dermatology",
  );
  expect(lake.location).toBe("Denver, Colorado");
});
