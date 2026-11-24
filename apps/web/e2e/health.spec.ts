import { expect, test } from "@playwright/test";

// Requires the API running on :8000 (see README). DB line requires Postgres.
test("frontend reaches backend health endpoint", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("api-status")).toHaveText("API: ok");
});

test("backend reports database connectivity", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("db-status")).toHaveText("Database: ok");
});
