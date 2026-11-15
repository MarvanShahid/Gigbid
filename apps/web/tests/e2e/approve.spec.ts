import { expect, test } from "@playwright/test";
import { draftFor, login } from "./helpers";

test("approving a proposal shows evidence on hover, a dry-run preview, and submits it", async ({ page, request }) => {
  await login(page);
  const job = await draftFor(page, request, 0);
  await page.goto(`/studio/${job.id}`);
  const cite = page.locator(".cite").first();
  await expect(cite).toBeVisible();
  await cite.focus();                                  // keyboard users get the same evidence popover
  await expect(cite.locator(".pop")).toBeVisible();
  await expect(page.getByTestId("dry-run")).toContainText("Connects");
  await page.screenshot({ path: "../../docs/images/studio.png", fullPage: true });
  await page.getByTestId("approve").click();
  await expect(page.getByTestId("studio-result")).toContainText("submitted", { timeout: 30_000 });
  await page.goto("/inbox");
  await page.screenshot({ path: "../../docs/images/inbox.png" });
  await page.goto("/pipeline");
  await expect(page.getByRole("region", { name: "submitted" })).toContainText(job.title.slice(0, 20));
});
