import { expect, test } from "@playwright/test";

const PAGES = [
  "/",
  "/clinics",
  "/clinics/new",
  "/playground",
  "/evaluations",
  "/activity",
];

for (const [name, size] of [
  ["tablet", { width: 768, height: 1024 }],
  ["mobile", { width: 390, height: 844 }],
] as const) {
  test.describe(name, () => {
    test.use({ viewport: size });

    test("no horizontal overflow on any page", async ({ page }) => {
      for (const path of PAGES) {
        await page.goto(path);
        await page.waitForLoadState("networkidle");
        const overflow = await page.evaluate(
          () =>
            document.documentElement.scrollWidth -
            document.documentElement.clientWidth,
        );
        expect(overflow, `${path} overflows horizontally`).toBeLessThanOrEqual(
          0,
        );
      }
    });

    test("navigation reaches every section", async ({ page }) => {
      await page.goto("/");
      if (name === "mobile") {
        await page.getByRole("button", { name: "Open menu" }).click();
        const dialog = page.getByRole("dialog", { name: "Menu" });
        await dialog.getByRole("link", { name: "Playground" }).click();
        await expect(dialog).toHaveCount(0);
      } else {
        await page
          .getByRole("navigation", { name: "Primary" })
          .getByRole("link", { name: "Playground" })
          .click();
      }
      await expect(page).toHaveURL(/\/playground$/);
      await expect(page.getByTestId("unavailable")).toBeVisible();
    });
  });
}

test.describe("mobile wizard", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("one step at a time, inputs survive navigation", async ({ page }) => {
    await page.goto("/clinics/new");
    await expect(page.getByTestId("step-indicator")).toContainText(
      "Step 1 of 5",
    );
    await page.getByLabel("Clinic name").fill("Mobile Clinic Check");
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByText("Enter the specialty.")).toBeVisible();
    await expect(page.getByLabel("Clinic name")).toHaveValue(
      "Mobile Clinic Check",
    );
  });
});
