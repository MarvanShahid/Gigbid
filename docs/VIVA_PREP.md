# Viva preparation: where each answer lives

You are graded on what you can explain and change live. For each question: the file, the function, and a command
to show it working.

| # | Examiner asks | Where | Show it |
|---|---|---|---|
| 1 | Kill the marketplace MCP server: what does the user see? | `agent/mcp_client.py::Gateway.call` (retries, then `health.mark(..., False)`, `ToolUnavailable`); `apps/api/services.py::run_bid` (job → `queued`); `apps/web/src/components/DegradedBanner.tsx` | `docker compose stop mcp-marketplace`, click *Scout now*, red banner; start it, banner goes. Test: `test_marketplace_down_degrades_and_recovers`, e2e `degraded.spec.ts` |
| 2 | Approve, crash the worker before submit: submitted exactly once? | `agent/nodes/proposal.py::submit` + `idem_key`; `mcp_servers/marketplace/approvals.py::GrantLedger` (idempotency table survives restarts); Celery `acks_late` | `tests/integration/test_durability.py` (both tests): restart while waiting, and crash after GigSim accepted |
| 3 | Show a claim and its evidence; delete the evidence and regenerate | Studio hover (`EvidenceHover.tsx`); evidence ids come from `rag/variants/base.py`; `rag/verify.py` grades claims | Delete the case study file (or `PortfolioIndex.remove_project`), re-analyse with *Draft anyway*: the claim is gone or marked unsupported and removed by `repair()` |
| 4 | A job GigBid wrongly skipped: which node got it wrong? | Run viewer `/runs/<id>` and `/api/runs/traces/<trace_id>` (per-node spans); `docs/FAILURES.md` | e.g. `dev-ml-097`: matcher marked "RAG" weak (paraphrase) → fit 0.50 → decide chose *watch* |
| 5 | Injected instruction: show the defence, and an attack that beats it | `agent/guardrails.py` (detect → neutralise → delimit); `agent/nodes/proposal.py::check_text` (output side) | Attack that beats input filtering: split the instruction over two harmless sentences; only the output check still blocks the payload |
| 6 | What did style memory learn from your last five edits? Promotion rule? Delete one | `agent/memory/promotion_rules.py` (RULE S: ≥2 distinct drafts); Settings → *What GigBid has learned* → Delete; `agent/memory/store.py::delete_memory` blocks re-promotion | Edit two drafts the same way (remove the first sentence) and watch it move from *Candidates* to *Style rules* |
| 7 | Switch GigSim → live mode: what changes? | `agent/config.yaml` `marketplace.mode`; `agent/marketplace_port.py::get_port`; `mcp_servers/marketplace/adapters/upwork_live.py` + `upwork_tools.yaml` | Nothing in `agent/graphs` or `agent/nodes` changes. Show `grep -r "gigsim" agent/graphs agent/nodes` is empty |
| 8 | Judge vs your labels: show two disagreements | `evals/runners/judge_calibration.py` → `judge_calibration.json` `large_disagreements` | **Do this first:** label the 30 items in `evals/datasets/judge_labels.csv`, then run with your Groq key |
| 9 | Where does the single agent beat the graph? Would you ship it? | `evals/runners/architecture_compare.py` → `architecture_compare.json` | **Run with your Groq key first**; the graph arm is already in the file |
| 10 | Lines changed for the change request | `docs/CHANGE_REQUEST.md` | Show `agent/config.yaml` `policy:` block, `compliance()` check and `submit_proposal` pre-check |

## Before the viva

1. `make test` (36 tests) and `make e2e` (7 Playwright runs) pass on your machine.
2. Put your Groq key in `.env`, run `make eval-llm`, `tool_granularity`, `architecture_compare` and `judge_calibration --score`,
   then `make tables`. Read every number that changes and update `docs/REPORT.md` sections 3, 5 and 9.
3. Change one threshold yourself (e.g. `decision.bid_min_fit` 0.62 → 0.55), rerun `python -m evals.runners.graph_eval`,
   and be able to say what moved and why.
4. Explain the parallel fan-out (`fan_out` → `Send`), the reducer `merge_dicts` in `agent/state.py`, and why the
   approval node has no timeout.
