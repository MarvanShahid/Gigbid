import { expect, test } from "@playwright/test";

test("onboarding: register, choose a persona, set rates and budget, land in the inbox @mobile", async ({ page }) => {
  const email = `e2e-${Date.now()}@gigbid.dev`;
  await page.goto("/login");
  await page.getByRole("button", { name: "Create an account" }).click();
  await page.getByLabel("Name").fill("E2E User");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("password-e2e-1");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/onboarding/);
  await page.getByLabel(/Sana Tariq/).check();
  await page.getByLabel("Weekly Connects budget").fill("80");
  await page.getByRole("button", { name: "Save and open my inbox" }).click();
  await expect(page).toHaveURL(/\/inbox/);
  await expect(page.getByRole("heading", { name: "Job inbox" })).toBeVisible();
  await page.goto("/settings");
  await expect(page.getByLabel("Weekly Connects budget")).toHaveValue("80");
});
