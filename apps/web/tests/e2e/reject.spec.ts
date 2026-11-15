import { expect, test } from "@playwright/test";
import { draftFor, login } from "./helpers";

test("rejecting with a reason sends nothing and records the reason", async ({ page, request }) => {
  await login(page);
  const job = await draftFor(page, request, 1);
  await page.goto(`/studio/${job.id}`);
  await expect(page.getByTestId("reject")).toBeDisabled();   // a reason is required
  await page.getByLabel("Reason for rejecting").fill("Budget too low for the scope");
  await page.getByTestId("reject").click();
  await expect(page.getByTestId("studio-result")).toContainText("rejected", { timeout: 30_000 });
  await expect(page.getByTestId("studio-result")).toContainText("Nothing was sent");
  await page.goto("/analytics");
  await expect(page.getByText("Budget too low for the scope")).toBeVisible();
});
