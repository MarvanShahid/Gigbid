# GigBid — make dev | test | eval | seed | demo | lint
PY ?= python
WEB = apps/web
export GIGBID_EMBEDDER ?=
export PYTHONPATH := $(CURDIR)

.PHONY: dev test eval seed demo lint tables openapi e2e smoke compose

seed:            ## build the synthetic stand-in corpus, dev set and GigSim seed
	$(PY) scripts/build_standin_data.py

dev:             ## single-process local stack: GigSim + API (in-process runs, in-memory MCP) + web
	$(PY) -m uvicorn sim.app:app --port 8100 & \
	GIGBID_INLINE_RUNS=1 MCP_MODE=inmemory $(PY) -m uvicorn apps.api.main:app --port 8000 --reload & \
	cd $(WEB) && npm run dev

compose:         ## everything in containers
	docker compose -f infra/docker-compose.yml --env-file .env up --build

test:            ## unit + integration + contract tests (offline, rules profile)
	$(PY) -m pytest

e2e:             ## Playwright (starts GigSim, API and web itself)
	cd $(WEB) && npx next build && PYTHON=$(PY) npx playwright test

eval:            ## retrieval, ablation, decisions, GigSim outcomes; writes evals/results/*.json
	$(PY) -m evals.runners.rag_eval
	$(PY) -m evals.runners.ablation
	$(PY) -m evals.runners.graph_eval
	$(PY) -m evals.runners.graph_eval --no-defences
	$(PY) -m evals.runners.decision_eval
	$(PY) -m evals.runners.gigsim_outcomes
	$(PY) -m evals.runners.tool_granularity
	$(PY) -m evals.runners.architecture_compare
	$(PY) -m evals.runners.judge_calibration --score
	$(MAKE) tables

eval-llm:        ## the same graph eval on the open (Groq) profile; needs GROQ_API_KEY
	GIGBID_PROFILE=open $(PY) -m evals.runners.graph_eval --profile open

smoke:           ## 30-job smoke eval with thresholds (CI gate)
	$(PY) -m evals.runners.smoke_eval

tables:          ## regenerate the README / RESULTS tables from evals/results
	$(PY) scripts/make_tables.py

openapi:         ## regenerate the typed TS client from FastAPI's schema
	$(PY) scripts/export_openapi.py && cd $(WEB) && npm run gen:api

demo:            ## scripted demo: one job inbox -> approved proposal, one scam, one injection, one client reply
	$(PY) scripts/demo.py

lint:
	ruff check agent rag mcp_servers apps/api worker evals sim scripts tests
	$(PY) scripts/check_repo_rules.py
	cd $(WEB) && npx tsc --noEmit
