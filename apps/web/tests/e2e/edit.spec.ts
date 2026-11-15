import { expect, test } from "@playwright/test";
import { draftFor, login } from "./helpers";

test("editing a draft re-checks it with Compliance and records a style observation", async ({ page, request }) => {
  await login(page);
  const job = await draftFor(page, request, 2);
  await page.goto(`/studio/${job.id}`);
  await page.getByTestId("edit").click();
  const box = page.getByLabel("Cover letter");
  const original = await box.inputValue();
  // the user deletes the opening sentence and sneaks in an email address
  const edited = original.split(/(?<=\.)\s/).slice(1).join(" ") + " Write to me at me@example.com for details.";
  await box.fill(edited);
  await page.getByTestId("save-edit").click();
  await expect(page.getByTestId("draft-view")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("draft-view")).not.toContainText("me@example.com");   // Compliance removed it
  await expect(page.locator("text=no_contact_details")).toBeVisible();
  await page.goto("/settings");
  await expect(page.getByTestId("memory")).toContainText("Open directly with the client's problem");
});
