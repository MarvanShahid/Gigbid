"""Open embedding and reranking models (CPU), with honest fallbacks.

Primary: fastembed BAAI/bge-small-en-v1.5 (embeddings) and a fastembed cross-encoder
(reranker). If the model files cannot be downloaded (offline machine, blocked
network), we fall back to a hashed TF-IDF embedder and a lexical pair scorer and
record which one ran in every results file (`embedder_name`).
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
from collections import Counter
from functools import lru_cache

import numpy as np

from agent.settings import config
from rag.text import tokens

log = logging.getLogger(__name__)


class HashedTfidfEmbedder:
    """Unigram+bigram hashing embedder with IDF learnt from the indexed corpus."""

    name = "hashed-tfidf-1024"

    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim
        self.idf = np.ones(dim, dtype=np.float32)

    def _feats(self, text: str) -> Counter:
        t = tokens(text)
        feats = Counter(t)
        feats.update(f"{a}_{b}" for a, b in zip(t, t[1:]))
        return feats

    def _bucket(self, f: str) -> int:
        return int(hashlib.md5(f.encode()).hexdigest()[:8], 16) % self.dim

    def fit(self, texts: list[str]) -> None:
        df = np.zeros(self.dim, dtype=np.float32)
        for t in texts:
            for b in {self._bucket(f) for f in self._feats(t)}:
                df[b] += 1
        n = max(1, len(texts))
        self.idf = np.log((1 + n) / (1 + df)).astype(np.float32) + 1

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for f, c in self._feats(t).items():
                out[i, self._bucket(f)] += (1 + math.log(c))
            out[i] *= self.idf
            n = np.linalg.norm(out[i])
            if n:
                out[i] /= n
        return out


class FastEmbedder:
    def __init__(self, model: str) -> None:
        from fastembed import TextEmbedding
        self.model = TextEmbedding(model_name=model)
        self.name = model

    def fit(self, texts: list[str]) -> None:  # pretrained
        return None

    def embed(self, texts: list[str]) -> np.ndarray:
        arr = np.array(list(self.model.embed(texts)), dtype=np.float32)
        return arr / np.clip(np.linalg.norm(arr, axis=1, keepdims=True), 1e-9, None)


@lru_cache(maxsize=1)
def get_embedder():
    want = os.getenv("GIGBID_EMBEDDER") or config()["embeddings"]["model"]
    if want != "hashed-tfidf":
        try:
            return FastEmbedder(want)
        except Exception as e:  # noqa: BLE001 - offline / blocked download
            log.warning("embedding model %s unavailable (%s); using hashed-tfidf fallback", want, e)
    return HashedTfidfEmbedder()


class LexicalReranker:
    name = "lexical-pair"

    def score(self, query: str, docs: list[str]) -> list[float]:
        q = set(tokens(query))
        out = []
        for d in docs:
            dt = tokens(d)
            if not dt or not q:
                out.append(0.0); continue
            hit = sum(1 for t in dt if t in q)
            cover = len(q & set(dt)) / len(q)
            out.append(0.7 * cover + 0.3 * hit / (len(dt) ** 0.5 * 3))
        return out


class CrossEncoderReranker:
    def __init__(self, model: str) -> None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        self.model = TextCrossEncoder(model_name=model)
        self.name = model

    def score(self, query: str, docs: list[str]) -> list[float]:
        return [float(s) for s in self.model.rerank(query, docs)]


@lru_cache(maxsize=1)
def get_reranker():
    want = os.getenv("GIGBID_RERANKER") or config()["reranker"]["model"]
    if want != "lexical":
        try:
            return CrossEncoderReranker(want)
        except Exception as e:  # noqa: BLE001
            log.warning("reranker %s unavailable (%s); using lexical fallback", want, e)
    return LexicalReranker()
