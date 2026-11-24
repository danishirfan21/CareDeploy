// Independent of spec order: it uses the pre-published sandbox clinic (seeded with --sandbox), so
// it never publishes or edits the seeded sample clinics other specs expect to be drafts.
import { expect, test } from "@playwright/test";
import { api } from "./helpers";

// Exercises the development-only scheduling console end to end against the isolated e2e API.

function futureTuesday(): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + 21);
  while (d.getUTCDay() !== 2) d.setUTCDate(d.getUTCDate() + 1);
  return d.toISOString().slice(0, 10);
}

test("verify a patient, book through proposal/confirm, then cancel", async ({
  page,
  request,
}) => {
  const clinics = (await (await request.get(`${api}/clinics`)).json()) as {
    id: string;
    name: string;
  }[];
  const north = clinics.find((c) => c.name === "Sandbox Family Clinic")!;

  await page.goto("/dev/scheduling");
  await expect(
    page.getByRole("heading", { name: "Scheduling test console" }),
  ).toBeVisible();
  await expect(page.getByText("Not a patient portal")).toBeVisible();

  await page.getByLabel("Clinic", { exact: true }).selectOption(north.id);
  await page.getByLabel("Patient name search").fill("Avery");
  await page.getByRole("button", { name: "Search" }).click();
  await page.getByRole("button", { name: "Avery Quinn" }).click();

  // Wrong credentials are rejected by the server.
  await page.getByLabel("Date of birth").fill("1985-04-12");
  await page.getByLabel("Phone last 4").fill("9999");
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByTestId("dev-error")).toContainText(
    "verification_failed",
  );

  await page.getByLabel("Phone last 4").fill("0101");
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByTestId("dev-status")).toContainText("Verified");

  await page.getByLabel("Date", { exact: true }).fill(futureTuesday());
  await page.getByRole("button", { name: "Show availability" }).click();
  await expect(page.getByLabel("Slot")).toBeVisible();
  await page.getByRole("button", { name: "Propose booking" }).click();
  await expect(page.getByTestId("proposal-summary")).toContainText(
    "Annual physical",
  );
  await page.getByRole("button", { name: "Confirm" }).click();
  await page.getByRole("button", { name: "Book appointment" }).click();
  await expect(page.getByTestId("dev-status")).toContainText("Booked");
  const row = page.getByTestId("appointment-row");
  await expect(row).toHaveCount(1);
  await expect(row).toContainText("scheduled");

  await row.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByTestId("dev-status")).toContainText("cancelled");
  await expect(page.getByTestId("appointment-row")).toHaveCount(0);
});
