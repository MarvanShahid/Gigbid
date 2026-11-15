import { defineConfig } from "@playwright/test";

const ROOT = "../..";
const PY = process.env.PYTHON || "python";
const env = `GIGBID_PROFILE=rules GIGBID_EMBEDDER=hashed-tfidf GIGBID_RERANKER=lexical MCP_MODE=inmemory GIGBID_INLINE_RUNS=1 ` +
  `GIGBID_DATA_DIR=${process.env.E2E_DATA_DIR || "/tmp/gigbid-e2e"} GIGSIM_URL=http://127.0.0.1:8100 SIM_ERROR_RATE=0 ` +
  `SIM_RATE_LIMIT_PER_MIN=100000 MARKETPLACE_RATE_PER_MIN=100000`;

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 90_000,
  workers: 1,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  use: { baseURL: "http://localhost:3000", channel: process.env.PW_CHANNEL || "chrome", trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { viewport: { width: 1280, height: 800 } } },
    { name: "phone", use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true }, grep: /@mobile/ },
  ],
  webServer: [
    { command: `cd ${ROOT} && ${env} ${PY} -m uvicorn sim.app:app --port 8100`, url: "http://127.0.0.1:8100/health", reuseExistingServer: true },
    { command: `cd ${ROOT} && ${env} ${PY} -m uvicorn apps.api.main:app --port 8000`, url: "http://127.0.0.1:8000/api/health", reuseExistingServer: true, timeout: 120_000 },
    { command: "npx next start -p 3000", url: "http://localhost:3000/login", reuseExistingServer: true, env: { API_URL: "http://127.0.0.1:8000" } },
  ],
});
