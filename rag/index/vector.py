"""Vector stores: pgvector (production, docker compose) and an in-memory numpy store
(tests and machines without the extension). Both expose the same interface."""
from __future__ import annotations

import logging
import os

import numpy as np

from agent.settings import config

log = logging.getLogger(__name__)


class MemoryVectorStore:
    backend = "memory"

    def __init__(self) -> None:
        self.ids: list[str] = []
        self.vecs = np.zeros((0, 0), dtype=np.float32)
        self.meta: dict[str, dict] = {}

    def upsert(self, ids: list[str], vecs: np.ndarray, metas: list[dict]) -> None:
        existing = {cid: i for i, cid in enumerate(self.ids)}
        new_ids, new_vecs = [], []
        for cid, v, m in zip(ids, vecs, metas):
            self.meta[cid] = m
            if cid in existing:
                self.vecs[existing[cid]] = v
            else:
                new_ids.append(cid); new_vecs.append(v)
        if new_ids:
            nv = np.vstack(new_vecs).astype(np.float32)
            self.vecs = nv if self.vecs.size == 0 else np.vstack([self.vecs, nv])
            self.ids += new_ids

    def delete(self, ids: list[str]) -> None:
        keep = [i for i, cid in enumerate(self.ids) if cid not in set(ids)]
        self.ids = [self.ids[i] for i in keep]
        self.vecs = self.vecs[keep] if keep else np.zeros((0, self.vecs.shape[1] if self.vecs.ndim == 2 else 0))
        for cid in ids:
            self.meta.pop(cid, None)

    def search(self, q: np.ndarray, k: int, where: dict | None = None) -> list[tuple[str, float]]:
        if not self.ids:
            return []
        sims = self.vecs @ q
        order = np.argsort(-sims)
        out = []
        for i in order:
            cid = self.ids[i]
            m = self.meta[cid]
            if where and any(m.get(key) != val for key, val in where.items()):
                continue
            out.append((cid, float(sims[i])))
            if len(out) >= k:
                break
        return out


class PgVectorStore:
    """chunks(id, owner, chunkset, type, project, embedding vector(dim)) with an HNSW cosine index."""

    backend = "pgvector"

    def __init__(self, dsn: str, dim: int, table: str = "rag_chunks") -> None:
        import psycopg
        from pgvector.psycopg import register_vector
        self.conn = psycopg.connect(dsn, autocommit=True)
        self.conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        register_vector(self.conn)
        self.table = table
        self.dim = dim
        self.conn.execute(
            f"CREATE TABLE IF NOT EXISTS {table} (id text PRIMARY KEY, owner text, chunkset text, type text, "
            f"project text, embedding vector({dim}))")
        self.conn.execute(f"CREATE INDEX IF NOT EXISTS {table}_hnsw ON {table} USING hnsw (embedding vector_cosine_ops)")

    def upsert(self, ids, vecs, metas) -> None:
        with self.conn.cursor() as cur:
            for cid, v, m in zip(ids, vecs, metas):
                cur.execute(
                    f"INSERT INTO {self.table} (id, owner, chunkset, type, project, embedding) VALUES (%s,%s,%s,%s,%s,%s) "
                    f"ON CONFLICT (id) DO UPDATE SET embedding = EXCLUDED.embedding",
                    (cid, m.get("owner"), m.get("chunkset"), m.get("type"), m.get("project"), np.asarray(v)))

    def delete(self, ids) -> None:
        self.conn.execute(f"DELETE FROM {self.table} WHERE id = ANY(%s)", (list(ids),))

    def search(self, q, k, where=None):
        clauses, params = [], []
        for key, val in (where or {}).items():
            if key in ("owner", "chunkset", "type", "project"):
                clauses.append(f"{key} = %s"); params.append(val)
        sql = (f"SELECT id, 1 - (embedding <=> %s) AS sim FROM {self.table} "
               f"{'WHERE ' + ' AND '.join(clauses) if clauses else ''} ORDER BY embedding <=> %s LIMIT %s")
        rows = self.conn.execute(sql, [np.asarray(q), *params, np.asarray(q), k]).fetchall()
        return [(r[0], float(r[1])) for r in rows]


def make_store(dim: int):
    backend = os.getenv("VECTOR_BACKEND") or config()["vector_store"]["backend"]
    dsn = os.getenv("DATABASE_URL", "")
    if backend in ("pgvector", "auto") and dsn.startswith("postgres"):
        try:
            return PgVectorStore(dsn.replace("postgresql+psycopg", "postgresql"), dim)
        except Exception as e:  # noqa: BLE001
            if backend == "pgvector":
                raise
            log.warning("pgvector unavailable (%s); using in-memory vector store", e)
    return MemoryVectorStore()
