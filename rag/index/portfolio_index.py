"""PortfolioIndex: chunks + dense vectors + BM25 for one owner (persona or user).

Embeddings are cached on disk by chunk id, so re-indexing after an upload only
embeds the new chunks (incremental re-indexing, B1)."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

from agent.settings import ROOT, data_dir
from rag.index.embed import get_embedder
from rag.index.vector import MemoryVectorStore, make_store
from rag.ingest.loaders import Chunk, chunks_from_upload, load_persona
from rag.text import tokens

PERSONA_ROOT = Path(os.getenv("PORTFOLIO_ROOT", ROOT / "data" / "personas"))


class PortfolioIndex:
    def __init__(self, owner: str, chunks: list[Chunk]) -> None:
        self.owner = owner
        shared = get_embedder()
        # a corpus-fitted embedder (hashed TF-IDF) must not be shared between portfolios: each index fits its own IDF
        self.embedder = type(shared)() if hasattr(shared, "idf") else shared
        self.chunks: dict[str, Chunk] = {}
        self.lock = threading.RLock()
        self._cache_path = data_dir() / "emb_cache" / f"{owner}__{self.embedder.name.replace('/', '_')}.npz"
        self._cache: dict[str, np.ndarray] = {}
        if self._cache_path.exists():
            z = np.load(self._cache_path)
            self._cache = {k: z[k] for k in z.files}
        if hasattr(self.embedder, "idf") and chunks:
            self.embedder.fit([c.text for c in chunks if c.chunkset == "structured"])
            self._cache = {}  # idf changed -> hashed vectors must be recomputed
        self.store = None
        self.add(chunks)

    # ------------------------------------------------------------------ build
    def add(self, chunks: list[Chunk]) -> int:
        with self.lock:
            new = [c for c in chunks if c.id not in self.chunks]
            for c in chunks:
                self.chunks[c.id] = c
            todo = [c for c in new if c.id not in self._cache]
            if todo:
                vecs = self.embedder.embed([c.text for c in todo])
                for c, v in zip(todo, vecs):
                    self._cache[c.id] = v
                if not hasattr(self.embedder, "idf"):
                    self._cache_path.parent.mkdir(parents=True, exist_ok=True)
                    np.savez(self._cache_path, **self._cache)
            if new:
                if self.store is None:
                    dim = len(next(iter(self._cache.values())))
                    self.store = make_store(dim) if os.getenv("VECTOR_BACKEND") == "pgvector" else MemoryVectorStore()
                self.store.upsert([c.id for c in new], np.vstack([self._cache[c.id] for c in new]),
                                  [{"owner": self.owner, "chunkset": c.chunkset, "type": c.type, "project": c.project}
                                   for c in new])
            self._rebuild_bm25()
            return len(new)

    def remove_project(self, project: str) -> int:
        with self.lock:
            ids = [cid for cid, c in self.chunks.items() if c.project == project]
            for cid in ids:
                del self.chunks[cid]
            if ids and self.store is not None:
                self.store.delete(ids)
            self._rebuild_bm25()
            return len(ids)

    def _rebuild_bm25(self) -> None:
        self.bm25 = {}
        for cs in ("structured", "fixed"):
            ids = [cid for cid, c in self.chunks.items() if c.chunkset == cs]
            if ids:
                self.bm25[cs] = (ids, BM25Okapi([tokens(self.chunks[i].text) or ["_"] for i in ids]))

    # ------------------------------------------------------------------ search
    def dense(self, query: str, k: int = 20, chunkset: str = "structured", types: set[str] | None = None
              ) -> list[tuple[str, float]]:
        if self.store is None:
            return []
        q = self.embedder.embed([query])[0]
        hits = self.store.search(q, k * 4 if types else k, {"chunkset": chunkset, "owner": self.owner})
        if types:
            hits = [h for h in hits if self.chunks.get(h[0]) and self.chunks[h[0]].type in types]
        return [h for h in hits if h[0] in self.chunks][:k]

    def lexical(self, query: str, k: int = 20, chunkset: str = "structured", types: set[str] | None = None
                ) -> list[tuple[str, float]]:
        if chunkset not in self.bm25:
            return []
        ids, bm = self.bm25[chunkset]
        qt = tokens(query)
        if not qt:
            return []
        scores = bm.get_scores(qt)
        order = np.argsort(-scores)
        out = []
        for i in order:
            if scores[i] <= 0:
                break
            if types and self.chunks[ids[i]].type not in types:
                continue
            out.append((ids[i], float(scores[i])))
            if len(out) >= k:
                break
        return out

    def get(self, cid: str) -> Chunk:
        return self.chunks[cid]

    def projects(self) -> dict[str, list[Chunk]]:
        out: dict[str, list[Chunk]] = {}
        for c in self.chunks.values():
            if c.project and c.chunkset == "structured":
                out.setdefault(c.project, []).append(c)
        return out

    def outcome_by_project(self) -> dict[str, dict[str, int]]:
        """won/replied/ignored counts of past proposals that cited each project."""
        out: dict[str, dict[str, int]] = {}
        for c in self.chunks.values():
            if c.type == "proposal" and c.project and c.chunkset == "structured":
                d = out.setdefault(c.project, {"won": 0, "replied": 0, "ignored": 0})
                d[c.outcome or "ignored"] = d.get(c.outcome or "ignored", 0) + 1
        return out


_INDEXES: dict[str, PortfolioIndex] = {}
_LOCK = threading.Lock()


def uploads_dir(owner: str) -> Path:
    d = data_dir() / "uploads" / owner
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_index(owner: str) -> PortfolioIndex:
    """owner is a persona folder name or a user id with uploaded material."""
    with _LOCK:
        if owner not in _INDEXES:
            chunks: list[Chunk] = []
            pdir = PERSONA_ROOT / owner
            if pdir.exists():
                chunks = load_persona(pdir, owner)
            manifest = uploads_dir(owner) / "manifest.json"
            if manifest.exists():
                for entry in json.loads(manifest.read_text()):
                    f = uploads_dir(owner) / entry["stored"]
                    if f.exists():
                        chunks += chunks_from_upload(owner, entry["filename"], f.read_bytes(), entry.get("kind"))
            _INDEXES[owner] = PortfolioIndex(owner, chunks)
        return _INDEXES[owner]


def add_upload(owner: str, filename: str, content: bytes, kind: str | None = None) -> int:
    """Store the file, then incrementally index only its chunks."""
    d = uploads_dir(owner)
    stored = f"{len(list(d.glob('*')))}_{Path(filename).name}"
    (d / stored).write_bytes(content)
    manifest = d / "manifest.json"
    entries = json.loads(manifest.read_text()) if manifest.exists() else []
    entries.append({"filename": filename, "stored": stored, "kind": kind})
    manifest.write_text(json.dumps(entries, indent=1))
    return get_index(owner).add(chunks_from_upload(owner, filename, content, kind))


def reset_indexes() -> None:
    with _LOCK:
        _INDEXES.clear()
