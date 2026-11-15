import { APIRequestContext, expect, Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const DEV = JSON.parse(fs.readFileSync(path.join(__dirname, "../../../../evals/datasets/dev_ml_engineer.json"), "utf8"));
export const SIM = "http://127.0.0.1:8100";
export const API = "http://127.0.0.1:8000";

export function bidJobs(): { id: string; title: string }[] {
  return DEV.filter((j: any) => j._gold.bid && !j._gold.injected); // eslint-disable-line @typescript-eslint/no-explicit-any
}

export async function loadJob(request: APIRequestContext, job: unknown) {
  await request.post(`${SIM}/admin/jobs`, { headers: { "x-admin-key": "sim-admin" }, data: [job] });
}

export async function login(page: Page, email = "reviewer@gigbid.dev", password = "reviewer-pass-0800") {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/inbox/);
  return page.evaluate(() => localStorage.getItem("gigbid_token"));
}

/** Put a known bid job into GigSim and let GigBid analyse it until a proposal waits for approval. */
export async function draftFor(page: Page, request: APIRequestContext, index: number) {
  const job = DEV.filter((j: any) => j._gold.bid && !j._gold.injected)[index]; // eslint-disable-line @typescript-eslint/no-explicit-any
  await loadJob(request, job);
  const token = await page.evaluate(() => localStorage.getItem("gigbid_token"));
  await request.post(`${API}/api/jobs/${job.id}/analyse`, { headers: { Authorization: `Bearer ${token}` } });
  await expect.poll(async () => {
    const r = await request.get(`${API}/api/jobs/${job.id}`, { headers: { Authorization: `Bearer ${token}` } });
    return r.ok() ? (await r.json()).status : "pending";
  }, { timeout: 60_000 }).toBe("awaiting_approval");
  return job;
}
