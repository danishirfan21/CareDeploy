import { expect, type Page } from "@playwright/test";

export const api = "http://localhost:8001/api";

let counter = 0;
export function unique(base: string) {
  counter += 1;
  return `${base} ${Date.now().toString(36)}${counter}`;
}

export async function next(page: Page) {
  await page.getByRole("button", { name: "Continue" }).click();
}

export async function save(page: Page) {
  await page.getByRole("button", { name: "Save", exact: true }).click();
}

export async function expectStep(page: Page, n: number) {
  await expect(page.getByTestId("step-indicator")).toContainText(
    `Step ${n} of 5`,
  );
}

export async function fillDetails(page: Page, name: string) {
  await page.getByLabel("Clinic name").fill(name);
  await page.getByLabel("Specialty").fill("Pediatrics");
  await page.getByLabel("Location").fill("Portland, Oregon");
  await page.getByLabel("Time zone").selectOption("America/Los_Angeles");
  await page.getByLabel("Phone").fill("(503) 555-0100");
  await page.getByLabel("Email").fill("hello@harbor.example");
}

export const fillStep1 = fillDetails;

/** Completes steps 1-4 through the UI and lands on step 5 with validation shown. */
export async function createClinicThroughWizard(
  page: Page,
  name: string,
  opts: { escalation?: boolean } = {},
) {
  await page.goto("/clinics/new");
  await fillDetails(page, name);
  await next(page);

  await expectStep(page, 2);
  await page.getByLabel("Monday", { exact: true }).check();
  await page.getByLabel("Tuesday", { exact: true }).check();
  await page.getByLabel("Monday opens").fill("08:00");
  await page.getByLabel("Monday closes").fill("16:00");
  await page.getByRole("button", { name: "+ Add appointment type" }).click();
  await page.getByLabel("Appointment type 1 name").fill("Well-child visit");
  await page.getByLabel("Appointment type 1 duration (minutes)").fill("40");
  if (opts.escalation) {
    await page
      .getByLabel("Appointment type 1 requires human escalation")
      .check();
  }
  await next(page);

  await expectStep(page, 3);
  await page.getByLabel("Minimum notice (hours)").fill("6");
  await page.getByLabel("Max reschedules").fill("3");
  await next(page);

  await expectStep(page, 4);
  await page.getByLabel("Agent name").fill("Harbor");
  await page
    .getByLabel("Greeting")
    .fill("Thanks for calling Harbor Pediatrics.");
  await page.getByLabel("Intent: Book appointment").check();
  await page.getByLabel("Capability: Check availability").check();
  await page.getByLabel("Capability: Book appointment").check();
  if (opts.escalation) {
    await page.getByLabel("Capability: Escalate to human").check();
  }
  await next(page);
  await expectStep(page, 5);
  await expect(page.getByTestId("validation-results")).toBeVisible();
}
