# ADR 0003: pgvector as the vector store
**Decision.** Dense vectors in Postgres (pgvector, HNSW cosine), BM25 in process, an in-memory numpy store for tests.
**Why.** One database for app data, checkpoints, the LangGraph store and vectors means one backup, one connection
string and one free managed instance when deploying. The corpus is small: thousands of chunks, not millions.
**Consequence.** No separate vector service in compose. Filtering by owner, chunk set and type is plain SQL.
