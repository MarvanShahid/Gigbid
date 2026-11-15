# ADR 0006: Celery for background work, Arize Phoenix for traces
**Decision.** Celery + beat on Redis; OpenTelemetry spans exported to self-hosted Phoenix and to local JSONL.
**Why.** Celery's `acks_late` plus task retries cover worker crashes during submit, and beat gives per-search schedules.
OTel keeps tracing vendor-neutral: the same trace id is set by the API middleware, carried into the worker and the graph,
sent to the MCP servers in `x-trace-id`, and written to the audit log.
**Consequence.** Without Redis (single-process mode) runs execute as background tasks in the API process.
