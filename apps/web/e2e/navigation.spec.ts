import { expect, test } from "@playwright/test";

test("home actions and sidebar navigation", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "What would you like to do?" }),
  ).toBeVisible();
  // No fake assistant: there is no free-text task input.
  await expect(page.getByRole("textbox")).toHaveCount(0);
  await expect(
    page.getByRole("link", { name: "Set up a clinic" }),
  ).toHaveAttribute("href", "/clinics/new");
  await expect(
    page.getByRole("link", { name: "Test a voice agent" }),
  ).toHaveAttribute("href", "/playground");
  await expect(
    page.getByRole("link", { name: "Run evaluations" }),
  ).toHaveAttribute("href", "/evaluations");

  const nav = page.getByRole("navigation", { name: "Primary" });
  await expect(nav.getByRole("link")).toHaveText([
    "Clinics",
    "Playground",
    "Activity",
  ]);
  await nav.getByRole("link", { name: "Playground" }).click();
  await expect(page.getByTestId("unavailable")).toContainText(
    "Live voice testing is not yet enabled",
  );
  await nav.getByRole("link", { name: "Activity" }).click();
  await expect(page.getByTestId("unavailable")).toContainText("No calls yet");
  await nav.getByRole("link", { name: "Clinics" }).click();
  await expect(page).toHaveURL(/\/clinics$/);

  await page.goto("/");
  await page.getByRole("link", { name: "Run evaluations" }).click();
  await expect(page).toHaveURL(/\/evaluations$/);
  await expect(page.getByTestId("unavailable")).toContainText("M4");
});

test("sidebar collapses", async ({ page }) => {
  await page.goto("/");
  const sidebar = page.getByRole("complementary", { name: "Sidebar" });
  await page.getByRole("button", { name: "Collapse sidebar" }).click();
  await expect(sidebar).toHaveAttribute("data-collapsed", "true");
  await page.getByRole("button", { name: "Expand sidebar" }).click();
  await expect(sidebar).toHaveAttribute("data-collapsed", "false");
});

test("playground shows no fake call or results", async ({ page }) => {
  await page.goto("/playground");
  await expect(page.getByTestId("unavailable")).toContainText("Not available");
  await expect(page.getByRole("button", { name: "Start call" })).toBeDisabled();
  await expect(page.getByTestId("transcript")).toHaveCount(0);
  await expect(page.getByTestId("call-outcome")).toHaveCount(0);
  await page
    .getByLabel("Clinic")
    .selectOption({ label: "Northstar Family Medicine" });
  await expect(page.getByText(/Draft only|Published v/)).toBeVisible();
});

test("evaluations shows no fabricated results", async ({ page }) => {
  await page.goto("/evaluations");
  await expect(
    page.getByRole("button", { name: "Run evaluation" }),
  ).toBeDisabled();
  await expect(page.getByTestId("unavailable")).toContainText(
    "No evaluation runs",
  );
  await expect(page.getByTestId("evaluation-summary")).toHaveCount(0);
  await expect(page.getByText(/scenarios passed/)).toHaveCount(0);
});

test("activity tabs are empty without records", async ({ page }) => {
  await page.goto("/activity");
  await expect(page.getByRole("tab", { name: /Calls/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(page.getByTestId("unavailable")).toContainText("No calls yet");
  await page.getByRole("tab", { name: /Evaluations/ }).click();
  await expect(page.getByTestId("unavailable")).toContainText(
    "No evaluation runs yet",
  );
  await expect(page.getByTestId("activity-detail")).toHaveCount(0);
});

test("component preview renders sample data (development page)", async ({
  page,
}) => {
  await page.goto("/dev/ui");
  await expect(page.getByText("none of it is real call")).toBeVisible();
  await expect(page.getByTestId("transcript").first()).toContainText(
    "Sample agent reply.",
  );
  const failing = page.getByText("Sample failing scenario");
  await expect(failing).toBeVisible();
  await expect(page.getByText("Sample expected behaviour.")).toBeVisible();
});
