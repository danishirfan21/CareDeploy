import { expect, test } from "@playwright/test";

test("home actions and sidebar navigation", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("link", { name: /Set up a clinic/ }),
  ).toBeVisible();
  await expect(page.getByText("Unavailable until M3")).toBeVisible();
  await expect(page.getByText("Unavailable until M4")).toBeVisible();

  const nav = page.getByRole("navigation", { name: "Primary" });
  await nav.getByRole("link", { name: "Playground" }).click();
  await expect(page.getByTestId("unavailable")).toContainText(
    "Not available yet",
  );
  await nav.getByRole("link", { name: "Activity" }).click();
  await expect(page.getByTestId("unavailable")).toContainText(
    "Not available yet",
  );
  await nav.getByRole("link", { name: "Clinics" }).click();
  await expect(page).toHaveURL(/\/clinics$/);

  await page.goto("/");
  await page.getByRole("link", { name: /Run evaluations/ }).click();
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
