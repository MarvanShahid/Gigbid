# Runbook

## Run locally

| Mode | Command | What runs |
|---|---|---|
| Single process | `make dev` | GigSim stand-in :8100, API :8000 (runs graphs in-process, MCP servers in-memory), web :3000 |
| Full stack | `cp .env.example .env` (fill it) then `make compose` | web, api, worker+beat, 3 MCP servers, GigSim, Postgres+pgvector, Redis, Phoenix, Ollama |

Reviewer login: `REVIEWER_EMAIL` / `REVIEWER_PASSWORD` from `.env` (seeded at startup, preloaded with the ml_engineer persona).

## Scheduling (E1)

* Celery beat checks every 15 min which saved searches are due; each search has its own `every_hours` (default 4).
* **Live mode (Upwork) never polls more often than every 180 minutes** (`marketplace.live_poll_minutes`). Reason:
  a freelancer gains nothing from minute-level freshness (proposals are written and approved by a human, which takes
  hours), and Upwork's automation rules treat high-frequency polling as scraping. Three hours gives at most 8 reads a
  day per saved search, well inside "use bots properly".
* Pipeline sync every 30 min; queued jobs retried every 5 min once the marketplace is healthy.
* Idempotency: inbox rows are unique per (user, job); duplicates are detected by content hash; a thread already
  waiting for approval is never started twice; submits and messages carry idempotency keys stored in a
  restart-safe ledger.

## Degraded mode (viva Q1)

Kill the marketplace server: `docker compose stop mcp-marketplace`.
1. The next tool call times out or fails. `agent/mcp_client.py::Gateway.call` retries with backoff (3 tries), then
   marks the server down (`agent/health.py`, shared through Redis) and raises `ToolUnavailable`.
2. `apps/api/services.py::run_bid` catches it, sets the job to `queued` with the reason, and the run to `queued`.
3. The UI polls `/api/status`. `components/DegradedBanner.tsx` shows **"Marketplace unavailable … work is queued"**.
4. `docker compose start mcp-marketplace`: the beat task `retry_queued` (or the in-process requeue loop) re-runs queued
   jobs from their checkpoints, and the banner disappears after the first successful call.

## Crash while a proposal waits for approval (viva Q2)

`docker compose kill api worker` → `docker compose up -d api worker` → approve in the UI. The approval row is still
pending (Postgres), the graph thread resumes from the Postgres checkpoint, and `submit` uses an idempotency key, so the
proposal is submitted exactly once. If the worker dies after GigSim accepted but before the checkpoint was written,
the Celery task is redelivered (`acks_late`), `submit` re-runs, and the ledger returns the first result
(`idempotent_replay: true`).

## Switching to live mode (viva Q7)

Set `marketplace.mode: upwork_live` in `agent/config.yaml`, connect Upwork in onboarding (OAuth), then run
`python scripts/upwork_list_tools.py --user <id>` and check `upwork_tools.yaml` against the real tool names.
What changes: the port implementation, and the tool names in that YAML. What does not change: graphs, nodes, prompts,
approvals, the UI.

## Secrets

Only from environment variables (`.env`, never committed; CI scans for keys). OAuth tokens are Fernet-encrypted in
the `secrets` table and never logged: `agent/observability.mask_pii` masks bearer tokens, emails, phones, card and IBAN
numbers in every span and audit record.

## Deploy (public URL)

Free hosts have no GPU, so the deployment uses the **open** profile through Groq. One workable free setup:
API + worker + MCP servers on a single small VM or Render web service using `MCP_MODE=inmemory` and
`GIGBID_INLINE_RUNS=1` (one Python process), a managed Postgres with pgvector, and the web app on Vercel with
`API_URL` set. Keep the instance warm during the grading window.
