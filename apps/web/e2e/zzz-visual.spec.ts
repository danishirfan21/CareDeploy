import { test } from "@playwright/test";
import { mkdirSync } from "node:fs";

// Captures rendered screens at the Stitch export viewports for manual comparison with
// design-reference/*/screen.png. Output goes to test-output/screens (git-ignored).
const OUT = "test-output/screens";
const VIEWPORTS = {
  desktop: { width: 1440, height: 900 },
  tablet: { width: 768, height: 1024 },
  mobile: { width: 390, height: 844 },
} as const;

for (const [name, viewport] of Object.entries(VIEWPORTS)) {
  test(`capture ${name}`, async ({ page }) => {
    mkdirSync(OUT, { recursive: true });
    await page.setViewportSize(viewport);
    const shot = async (file: string) => {
      await page.waitForLoadState("networkidle");
      await page.screenshot({
        path: `${OUT}/${name}-${file}.png`,
        fullPage: true,
      });
    };
    for (const [path, file] of [
      ["/", "home"],
      ["/clinics", "clinics"],
      ["/playground", "playground"],
      ["/evaluations", "evaluations"],
      ["/activity", "activity"],
      ["/dev/ui", "components"],
    ] as const) {
      await page.goto(path);
      await shot(file);
    }
    await page.goto("/clinics");
    await page.getByRole("link", { name: /Lakeside/ }).click();
    await page.getByRole("link", { name: "Edit configuration" }).click();
    await page.getByRole("button", { name: "Continue" }).click();
    await shot("wizard-step2");
  });
}
