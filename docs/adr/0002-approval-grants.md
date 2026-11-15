# ADR 0002: approval grants bound to the exact payload
**Decision.** Write tools need a JWT minted by the API on approval: account, action, SHA-256 of the payload, one-time id.
**Why.** An `interrupt()` alone protects only the graph path. A grant protects the marketplace server itself,
so a direct tool call, a replayed request or an edit after approval cannot send.
**Consequence.** The API and the marketplace server share `APPROVAL_SECRET`. The grant is one-time; the idempotency key
makes retries safe.
