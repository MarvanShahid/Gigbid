"""V8 corrective RAG, written as a small LangGraph: grade the evidence for each
requirement, re-query with expanded wording when it is weak, and refuse to claim
the requirement when nothing supports it."""
from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from rag.text import detect_skills, lexicon

from .base import Pipeline, PipelineConfig, requirement_supported

CONFIG = PipelineConfig(name="v8_corrective", decompose=True, corrective=True)


class CState(TypedDict):
    reqs: list[str]
    by_req: dict[str, list[str]]
    weak: list[str]
    attempts: int
    extra: list[str]


def _expansions(req: str) -> list[str]:
    out = []
    for s in detect_skills(req):
        aliases = lexicon().get(s, [])
        out.append(f"project built with {' / '.join(aliases[:3])}")
        out.append(f"code using {aliases[0]}")
    return out or [f"past client work: {req}"]


def corrective_loop(pipe: Pipeline, idx, reqs: list[str], by_req: dict[str, list[str]]):
    base = pipe.with_(decompose=False, corrective=False, hyde=False)

    def grade(st: CState) -> CState:
        weak = []
        for r in st["reqs"]:
            ids = st["by_req"].get(r, [])
            if not any(requirement_supported(idx, r, cid) for cid in ids[:3]):
                weak.append(r)
        return {**st, "weak": weak}

    def requery(st: CState) -> CState:
        by_req, extra = dict(st["by_req"]), list(st["extra"])
        for r in st["weak"]:
            found = []
            for q in _expansions(r):
                for cid, _s in base._search(idx, q)[:8]:
                    if requirement_supported(idx, r, cid) and cid not in found:
                        found.append(cid)
            if found:
                by_req[r] = found[:3] + [c for c in by_req.get(r, []) if c not in found][:2]
                extra += found[:3]
        return {**st, "by_req": by_req, "extra": extra, "attempts": st["attempts"] + 1}

    def route(st: CState) -> str:
        return "requery" if st["weak"] and st["attempts"] < 1 else "done"

    g = StateGraph(CState)
    g.add_node("grade", grade)
    g.add_node("requery", requery)
    g.add_edge(START, "grade")
    g.add_conditional_edges("grade", route, {"requery": "requery", "done": END})
    g.add_edge("requery", "grade")
    out = g.compile(checkpointer=False).invoke({"reqs": reqs, "by_req": {r: by_req.get(r, []) for r in reqs}, "weak": [], "attempts": 0,
                              "extra": []})
    # refuse to claim: requirements still weak lose their evidence mapping
    final = {r: ([] if r in out["weak"] else ids) for r, ids in out["by_req"].items()}
    return final, list(out["weak"]), out["extra"]


def build() -> Pipeline:
    return Pipeline(CONFIG)
