import { expect, test } from "@playwright/test";
import { login, SIM } from "./helpers";

test("when the marketplace is down the UI says so, queues work, and recovers @mobile", async ({ page, request }) => {
  await login(page);
  await request.post(`${SIM}/admin/error_rate?rate=1`, { headers: { "x-admin-key": "sim-admin" } });
  try {
    await page.getByRole("button", { name: "Scout now" }).click();
    await expect(page.getByTestId("degraded-banner")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("degraded-banner")).toContainText("Marketplace unavailable");
  } finally {
    await request.post(`${SIM}/admin/error_rate?rate=0`, { headers: { "x-admin-key": "sim-admin" } });
  }
  await page.getByRole("button", { name: "Scout now" }).click();
  await expect(page.getByTestId("degraded-banner")).toBeHidden({ timeout: 30_000 });
});
