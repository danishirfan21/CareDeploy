import { expect, test } from "@playwright/test";
import {
  createClinicThroughWizard,
  expectStep,
  fillDetails,
  next,
  save,
  unique,
} from "./helpers";

test("step 1 validates required fields and email format", async ({ page }) => {
  await page.goto("/clinics/new");
  await next(page);
  await expectStep(page, 1);
  await expect(page.getByText("Enter the clinic name.")).toBeVisible();
  await expect(page.getByText("Enter the specialty.")).toBeVisible();
  await expect(page.getByText("Enter the location.")).toBeVisible();

  await fillDetails(page, unique("Validation Clinic"));
  await page.getByLabel("Email").fill("not-an-email");
  await next(page);
  await expect(page.getByText("Enter a valid email address.")).toBeVisible();
  await expectStep(page, 1);
});

test("step 2, 3 and 4 block continuing on invalid input", async ({ page }) => {
  await page.goto("/clinics/new");
  await fillDetails(page, unique("Validation Clinic"));
  await next(page);
  await expectStep(page, 2);

  await next(page);
  await expect(
    page.getByText("Select at least one operating day."),
  ).toBeVisible();
  await expect(
    page.getByText("Add at least one appointment type."),
  ).toBeVisible();

  await page.getByLabel("Monday", { exact: true }).check();
  await page.getByLabel("Monday opens").fill("17:00");
  await page.getByLabel("Monday closes").fill("09:00");
  await page.getByRole("button", { name: "+ Add appointment type" }).click();
  await next(page);
  await expect(
    page.getByText("Opening time must be before closing time."),
  ).toBeVisible();
  await expect(page.getByText("Enter a name.")).toBeVisible();

  await page.getByLabel("Monday opens").fill("09:00");
  await page.getByLabel("Monday closes").fill("17:00");
  await page.getByLabel("Appointment type 1 name").fill("Checkup");
  await page.getByLabel("Appointment type 1 duration (minutes)").fill("2");
  await next(page);
  await expect(page.getByText("Duration must be 5–480 minutes.")).toBeVisible();
  await page.getByLabel("Appointment type 1 duration (minutes)").fill("30");
  await next(page);
  await expectStep(page, 3);

  await page.getByLabel("Max reschedules").fill("99");
  await next(page);
  await expect(page.getByText("Enter 0–10.")).toBeVisible();
  await page.getByLabel("Max reschedules").fill("1");
  await next(page);
  await expectStep(page, 4);

  await next(page);
  await expect(page.getByText("Name the agent.")).toBeVisible();
  await expect(page.getByText("Select at least one intent.")).toBeVisible();
  await expect(page.getByText("Select at least one capability.")).toBeVisible();
});

test("back keeps entered data and only one step is visible at a time", async ({
  page,
}) => {
  await page.goto("/clinics/new");
  const name = unique("Back Clinic");
  await fillDetails(page, name);
  await next(page);
  await expectStep(page, 2);
  await expect(page.getByLabel("Clinic name")).toHaveCount(0);
  await page.getByRole("button", { name: "Back" }).click();
  await expectStep(page, 1);
  await expect(page.getByLabel("Clinic name")).toHaveValue(name);
  await expect(page.getByRole("button", { name: "Back" })).toBeDisabled();
});

test("create a clinic, complete all five steps, save, reopen and publish", async ({
  page,
}) => {
  const name = unique("Harbor Pediatrics");
  await createClinicThroughWizard(page, name);

  // Step 5: review + validation + summary reflect what was entered.
  await expect(page.getByTestId("validation-results")).toContainText(
    "No blocking issues",
  );
  const summary = page.getByTestId("config-summary");
  await expect(summary).toContainText(name);
  await expect(summary).toContainText("America/Los_Angeles");
  await expect(summary).toContainText("Well-child visit · 40 min");
  await expect(summary).toContainText("8:00 AM – 4:00 PM");
  await expect(summary).toContainText("6 hours");

  // The clinic exists in the list as a draft.
  await page.goto("/clinics");
  const row = page.getByRole("link", { name: new RegExp(name) });
  await expect(row).toContainText("Draft");

  // Reopen the saved configuration: data persisted through API + PostgreSQL.
  await row.click();
  await expect(
    page.getByText("Draft only. This configuration has never been published."),
  ).toBeVisible();
  await page.getByRole("link", { name: "Edit configuration" }).click();
  await expectStep(page, 1);
  await expect(page.getByLabel("Clinic name")).toHaveValue(name);
  await expect(page.getByLabel("Time zone")).toHaveValue("America/Los_Angeles");
  await expect(page.getByLabel("Email")).toHaveValue("hello@harbor.example");
  await next(page);
  await expect(page.getByLabel("Monday", { exact: true })).toBeChecked();
  await expect(page.getByLabel("Tuesday", { exact: true })).toBeChecked();
  await expect(page.getByLabel("Wednesday", { exact: true })).not.toBeChecked();
  await expect(page.getByLabel("Monday opens")).toHaveValue("08:00");
  await expect(page.getByLabel("Appointment type 1 name")).toHaveValue(
    "Well-child visit",
  );
  await next(page);
  await expect(page.getByLabel("Minimum notice (hours)")).toHaveValue("6");
  await expect(page.getByLabel("Max reschedules")).toHaveValue("3");

  // Edit and Save on step 3, reload the page, see the change persisted.
  await page.getByLabel("Max reschedules").fill("4");
  await save(page);
  await expect(page.getByText("Draft saved.")).toBeVisible();
  await page.reload();
  await next(page);
  await next(page);
  await expect(page.getByLabel("Max reschedules")).toHaveValue("4");
  await next(page);
  await next(page);
  await expectStep(page, 5);

  // Publish.
  await page.getByRole("button", { name: "Publish version" }).click();
  await expect(page.getByTestId("published-notice")).toContainText(
    "Version 1 published",
  );
  await expect(page.getByTestId("published-notice")).toContainText(
    "No live voice agent",
  );
  await page.getByRole("link", { name: "View clinic" }).click();

  await expect(
    page.getByRole("list", { name: "Published versions" }),
  ).toContainText("Version 1");
  await expect(
    page.getByText("The draft matches published version v1."),
  ).toBeVisible();

  await page.goto("/clinics");
  await expect(
    page.getByRole("link", { name: new RegExp(name) }),
  ).toContainText("Published v1");
  // Isolation: seeded clinics are unaffected.
  await expect(
    page.getByRole("link", { name: /Northstar Family Medicine/ }),
  ).toContainText("Draft");
  await expect(
    page.getByRole("link", { name: /Lakeside Dermatology/ }),
  ).toContainText("Draft");

  // Editing after publishing creates unpublished changes; the published version is unchanged.
  await page.getByRole("link", { name: new RegExp(name) }).click();
  await page.getByRole("link", { name: "Edit configuration" }).click();
  await next(page);
  await next(page);
  await page.getByLabel("Max reschedules").fill("2");
  await save(page);
  await page.goto(page.url().replace("/configure", ""));
  await expect(
    page.getByText(/changes that are not in published version v1/),
  ).toBeVisible();
  await expect(
    page.getByRole("list", { name: "Published versions" }),
  ).toContainText("Version 1");
});

test("publishing is blocked until validation passes", async ({ page }) => {
  const name = unique("Escalation Clinic");
  // One type needs human escalation but the agent has no escalation instructions.
  await createClinicThroughWizard(page, name, { escalation: true });

  const results = page.getByTestId("validation-results");
  await expect(results).toContainText("issue");
  await expect(results).toContainText("add escalation instructions");
  await expect(
    page.getByRole("button", { name: "Publish version" }),
  ).toBeDisabled();

  // Fix on step 4, continue, and publishing becomes available.
  await page.getByRole("button", { name: "Back" }).click();
  await page
    .getByLabel("Escalation instructions")
    .fill("Transfer developmental concerns to staff.");
  await next(page);
  await expectStep(page, 5);
  await expect(page.getByTestId("validation-results")).toContainText(
    "No blocking issues",
  );
  await page.getByRole("button", { name: "Publish version" }).click();
  await expect(page.getByTestId("published-notice")).toContainText(
    "Version 1 published",
  );
});

test("duplicate clinic names are rejected by the API and shown", async ({
  page,
}) => {
  await page.goto("/clinics/new");
  await fillDetails(page, "Northstar Family Medicine");
  await next(page);
  await expect(
    page.getByRole("alert").filter({ hasText: "already exists" }),
  ).toBeVisible();
  await expectStep(page, 1);
});
