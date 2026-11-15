"""Graph runtime: checkpointer (Postgres in compose, SQLite locally), store, thread helpers."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from agent.graphs import bid_graph, conversation_graph
from agent.memory.store import store
from agent.settings import data_dir


@asynccontextmanager
async def checkpointer():
    dsn = os.getenv("DATABASE_URL", "")
    if dsn.startswith("postgres"):
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        async with AsyncPostgresSaver.from_conn_string(dsn.replace("postgresql+psycopg", "postgresql")) as cp:
            await cp.setup()
            yield cp
    else:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        path = os.getenv("CHECKPOINT_DB", str(data_dir() / "checkpoints.db"))
        async with AsyncSqliteSaver.from_conn_string(path) as cp:
            yield cp


@asynccontextmanager
async def graphs():
    async with checkpointer() as cp:
        yield {"bid": bid_graph.build(cp, store()), "conversation": conversation_graph.build(cp, store())}


def thread_config(kind: str, user: str, ident: str) -> dict:
    return {"configurable": {"thread_id": f"{kind}:{user}:{ident}"}, "recursion_limit": 60}


def pending_interrupt(snapshot) -> dict | None:
    for t in snapshot.tasks or []:
        for it in getattr(t, "interrupts", ()) or ():
            return it.value
    return None
