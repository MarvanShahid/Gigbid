# GigBid Portfolio MCP server

A read-only MCP server over a freelancer's portfolio (CV, case studies, repos, client reviews, past proposals
with outcomes). Plug it into Claude Desktop, Cursor or any MCP host and ask things like
"which of my projects prove I can do RAG with pgvector?".

## Install and run

```bash
# from a clone of this repo
pip install .
gigbid-portfolio-mcp                                  # stdio
PORTFOLIO_ROOT=~/my_portfolio PORTFOLIO_OWNER=me gigbid-portfolio-mcp
gigbid-portfolio-mcp --http --port 8202               # streamable HTTP with bearer auth (MCP_TOKENS)

# without installing, via uv
uvx --from git+https://github.com/<your-account>/gigbid gigbid-portfolio-mcp
```

Claude Desktop (`claude_desktop_config.json`):

```json
{"mcpServers": {"portfolio": {"command": "uvx",
  "args": ["--from", "git+https://github.com/<your-account>/gigbid", "gigbid-portfolio-mcp"],
  "env": {"PORTFOLIO_ROOT": "/path/to/my_portfolio", "PORTFOLIO_OWNER": "me"}}}}
```

## Portfolio folder layout

```
my_portfolio/me/
  cv.pdf (or cv.md)
  case_studies/<project-id>.md      # "# Title", "**Client industry:** … · **Year:** …", "## Problem", "## What I built", "## Result"
  repos/<project-id>/README.md, src/*
  reviews.json                      # [{"id", "project_id", "rating", "text", "client_industry", "date"}]
  proposals.json                    # [{"id", "job_title", "category", "project_id", "text", "outcome": "won|replied|ignored", "date"}]
```

## Tools, resources and prompts

* `search_evidence(requirement, k, filters)`: evidence for one requirement, with type, source, date, outcome.
* `retrieve_for_job(job_text, requirements, k)`: the full pipeline for a job, plus a requirement → evidence map.
* `get_case_study(case_id)`, `list_skills()`.
* Resources: `portfolio://case/{id}`, `portfolio://proposal/{id}`, `portfolio://skills`.
* Prompts: *Answer a screening question from my portfolio*, *Write a cover-letter opening for a job*,
  *Show me which requirements I can prove*.

Embeddings are open models on CPU (`BAAI/bge-small-en-v1.5` via fastembed), with an offline hashed TF-IDF fallback.
