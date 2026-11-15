# Tools

All agent access goes through MCP (`agent/mcp_client.py`), with per-agent allowlists in `agent/config.yaml`
(`mcp.allowlists`). Schemas are snapshot-tested (`tests/contract/tool_schemas.snapshot.json`).

| Tool | Server | Read / write | Annotations (readOnly, destructive, idempotent) | Auth |
|---|---|---|---|---|
| search_evidence | portfolio | read | true, false, true | bearer (HTTP) / none (stdio) |
| retrieve_for_job | portfolio | read | true, false, true | bearer / none |
| get_case_study | portfolio | read | true, false, true | bearer / none |
| list_skills | portfolio | read | true, false, true | bearer / none |
| resources `portfolio://case/{id}`, `portfolio://proposal/{id}`, `portfolio://skills` | portfolio | read | — | bearer / none |
| prompts `answer_screening_question`, `cover_letter_opening`, `fit_check` | portfolio | — | — | bearer / none |
| search_jobs | marketplace | read | true, false, true | bearer; per-account rate limit; audited |
| get_job | marketplace | read | true, false, true | bearer; rate limit; audited |
| get_client_history | marketplace | read | true, false, true | bearer; rate limit; audited |
| get_connects_balance | marketplace | read | true, false, true | bearer; rate limit; audited |
| get_connects_cost | marketplace | read | true, false, true | bearer; rate limit; audited |
| get_policy | marketplace | read | true, false, true | bearer; rate limit; audited |
| market_stats | marketplace | read | true, false, true | bearer; rate limit; audited |
| list_messages | marketplace | read | true, false, true | bearer; rate limit; audited |
| list_proposals | marketplace | read | true, false, true | bearer; rate limit; audited |
| create_proposal_draft | marketplace | write (local draft only) | false, false, true | bearer; audited |
| submit_proposal | marketplace | write (spends Connects) | false, **true**, true | bearer + **approval grant** + idempotency key; `dry_run` default true; audited |
| send_message | marketplace | write | false, **true**, true | bearer + **approval grant** + idempotency key; `dry_run` default true; audited |
| free_slots | workspace | read | true, false, true | bearer; audited |
| create_interview_hold | workspace | write (tentative hold) | false, false, true | bearer + idempotency key; audited |
| create_email_draft | workspace | write (draft only) | false, false, true | bearer; audited |

Write tools carry an `idempotency_key` (a retried call returns the first result and never spends Connects twice; the
ledger survives restarts) and a `dry_run` flag. The approval screen shows the dry-run preview: the exact text, the
bid, the Connects cost and the balance after.

## Third-party servers (A5)

| Server | Used for | Trust rationale |
|---|---|---|
| Upwork official MCP (`https://mcp.upwork.com/mcp`) | live mode: job search, drafts, messages | First-party server of the marketplace. OAuth 2.1 with PKCE via the MCP SDK; tokens encrypted per user; every write is a draft the user confirms on Upwork. |
| GitHub official MCP (`https://api.githubcopilot.com/mcp/`) | ingesting repo READMEs and code into the portfolio (`rag/ingest/github.py`) | Maintained by GitHub, read-only use (`get_file_contents`), fine-grained read-only PAT, no cloning or scraping. |
