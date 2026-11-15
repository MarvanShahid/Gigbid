"""Portfolio tool implementations (read-only). Kept separate from the MCP wiring so
they are unit-testable without a server."""
from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, Field

from rag.index.portfolio_index import PERSONA_ROOT, get_index
from rag.retriever import build_variant
from rag.text import lexicon


def default_owner() -> str:
    return os.getenv("PORTFOLIO_OWNER", "ml_engineer")


class EvidenceFilters(BaseModel):
    types: list[str] | None = Field(default=None, description="Restrict to item types: cv, case_study, readme, code, review")
    project: str | None = Field(default=None, description="Only items from this project id")
    since_year: int | None = Field(default=None, ge=2000, le=2100, description="Only items dated in or after this year")
    industry: str | None = Field(default=None, description="Client industry, e.g. fintech")


class EvidenceItem(BaseModel):
    id: str = Field(description="Chunk id; cite this in proposals")
    project: str | None
    type: str
    source: str
    date: str | None
    outcome: str | None = Field(description="For past proposals: won, replied or ignored")
    title: str | None
    text: str
    score: float
    requirement: str | None = None


def _to_item(e) -> EvidenceItem:
    return EvidenceItem(id=e.id, project=e.project, type=e.type, source=e.source, date=e.date, outcome=e.outcome,
                        title=e.title, text=e.text[:900], score=e.score, requirement=e.requirement)


def search_evidence(requirement: str, k: int = 5, filters: EvidenceFilters | None = None,
                    owner: str | None = None) -> list[EvidenceItem]:
    owner = owner or default_owner()
    idx = get_index(owner)
    pipe = build_variant()
    # one requirement -> a single (non-decomposed) query through the shipped pipeline
    res = pipe.with_(decompose=False, corrective=False).retrieve(idx, requirement, [requirement], k=max(k * 3, 10))
    out = []
    f = filters or EvidenceFilters()
    for e in res.evidence:
        ch = idx.get(e.id)
        if f.types and ch.type not in f.types:
            continue
        if f.project and ch.project != f.project:
            continue
        if f.since_year and (not ch.date or int(ch.date[:4]) < f.since_year):
            continue
        if f.industry and (ch.industry or "").lower() != f.industry.lower():
            continue
        out.append(_to_item(e))
        if len(out) >= k:
            break
    return out


class JobEvidence(BaseModel):
    evidence: list[EvidenceItem]
    by_requirement: dict[str, list[str]]
    unsupported_requirements: list[str]


def retrieve_for_job(job_text: str, requirements: list[str] | None = None, k: int = 6,
                     owner: str | None = None) -> JobEvidence:
    owner = owner or default_owner()
    res = build_variant().retrieve(get_index(owner), job_text, requirements, k)
    return JobEvidence(evidence=[_to_item(e) for e in res.evidence], by_requirement=res.by_requirement,
                       unsupported_requirements=res.unsupported_requirements)


def get_case_study(case_id: str, owner: str | None = None) -> dict:
    owner = owner or default_owner()
    idx = get_index(owner)
    parts = [c for c in idx.chunks.values() if c.project == case_id and c.chunkset == "structured"]
    if not parts:
        raise ValueError(f"no case study or project with id {case_id!r}")
    case = [c for c in parts if c.type == "case_study"]
    return {"id": case_id, "title": (case or parts)[0].title, "industry": parts[0].industry, "date": parts[0].date,
            "text": "\n\n".join(c.text for c in (case or parts)),
            "related": [{"id": c.id, "type": c.type, "source": c.source} for c in parts if c.type != "case_study"]}


def get_proposal(proposal_id: str, owner: str | None = None) -> dict:
    owner = owner or default_owner()
    idx = get_index(owner)
    for c in idx.chunks.values():
        if c.type == "proposal" and c.title == proposal_id and c.chunkset == "structured":
            return {"id": proposal_id, "outcome": c.outcome, "project": c.project, "date": c.date, "text": c.text}
    raise ValueError(f"no proposal {proposal_id!r}")


def list_skills(owner: str | None = None) -> list[dict]:
    owner = owner or default_owner()
    idx = get_index(owner)
    count: Counter = Counter()
    projects: dict[str, set] = {}
    for c in idx.chunks.values():
        if c.chunkset != "structured" or c.type == "proposal":
            continue
        for s in c.skills:
            count[s] += 1
            if c.project:
                projects.setdefault(s, set()).add(c.project)
    return [{"skill": s, "name": lexicon()[s][0], "mentions": n, "projects": sorted(projects.get(s, []))}
            for s, n in count.most_common()]


def list_owners() -> list[str]:
    root = Path(PERSONA_ROOT)
    return sorted(p.name for p in root.iterdir() if p.is_dir()) if root.exists() else []


def profile(owner: str | None = None) -> dict:
    owner = owner or default_owner()
    p = Path(PERSONA_ROOT) / owner / "profile.json"
    return json.loads(p.read_text()) if p.exists() else {"persona": owner}
