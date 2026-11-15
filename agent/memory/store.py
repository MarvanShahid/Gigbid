"""LangGraph long-term store (R7, C2).

Namespaces (per user):
  ("style", user)              promoted style rules, learnt from the user's edits
  ("style_candidates", user)   observations waiting for promotion (never read by the writer)
  ("outcome", user)            promoted per-category outcome knowledge
  ("outcome_raw", user)        recorded outcomes waiting for promotion
Writer/Liaison read only the promoted namespaces.
"""
from __future__ import annotations

import os

from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore

from agent.settings import data_dir

_STORE: BaseStore | None = None


def _make() -> BaseStore:
    dsn = os.getenv("DATABASE_URL", "")
    if dsn.startswith("postgres"):
        from langgraph.store.postgres import PostgresStore
        from psycopg import Connection
        from psycopg.rows import dict_row
        conn = Connection.connect(dsn.replace("postgresql+psycopg", "postgresql"), autocommit=True,
                                  prepare_threshold=0, row_factory=dict_row)
        st = PostgresStore(conn)
        st.setup()
        return st
    if os.getenv("GIGBID_STORE", "sqlite") == "memory":
        return InMemoryStore()
    import sqlite3

    from langgraph.store.sqlite import SqliteStore
    conn = sqlite3.connect(str(data_dir() / "memory_store.db"), check_same_thread=False, isolation_level=None)
    st = SqliteStore(conn)
    st.setup()
    return st


def store() -> BaseStore:
    global _STORE
    if _STORE is None:
        _STORE = _make()
    return _STORE


def set_store(s: BaseStore | None) -> None:
    global _STORE
    _STORE = s


def list_memory(user: str) -> dict[str, list[dict]]:
    st = store()
    out = {}
    for ns in ("style", "outcome", "style_candidates"):
        out[ns] = [{"key": it.key, **it.value, "updated_at": str(it.updated_at)}
                   for it in st.search((ns, user), limit=200)]
    return out


def delete_memory(user: str, namespace: str, key: str) -> bool:
    if namespace not in ("style", "outcome", "style_candidates"):
        return False
    st = store()
    if st.get((namespace, user), key) is None:
        return False
    st.delete((namespace, user), key)
    if namespace == "style":   # a deleted rule must not be re-promoted from old candidates
        st.put(("style_blocked", user), key, {"blocked": True})
        if st.get(("style_candidates", user), key):
            st.delete(("style_candidates", user), key)
    return True

