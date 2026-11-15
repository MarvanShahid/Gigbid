"""Configurable retrieval pipeline. Every variant (V0..V8, best) is a configuration of
this one class, which is what makes the ablation in evals/runners/ablation.py a
one-flag change per component."""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from rag.index.embed import get_reranker
from rag.index.portfolio_index import PortfolioIndex
from rag.text import detect_skills, lexicon, tokens

EVIDENCE_TYPES = {"cv", "case_study", "readme", "code", "review"}


@dataclass(frozen=True)
class PipelineConfig:
    name: str
    chunkset: str = "structured"
    decompose: bool = False
    hybrid: bool = False
    rerank: bool = False
    outcome: bool = False
    multivector: bool = False
    contextual: bool = False   # V6: prepend a generated context line (title/type/project) to the query side
    hyde: bool = False
    corrective: bool = False
    evidence_only: bool = True   # exclude past proposals from claim evidence
    candidates: int = 30


@dataclass
class Evidence:
    id: str
    item_id: str
    project: str | None
    type: str
    source: str
    text: str
    score: float
    requirement: str | None = None
    date: str | None = None
    outcome: str | None = None
    title: str | None = None
    related: list[str] = field(default_factory=list)
    mapped_only: bool = False   # added for the requirement map, not part of the ranking

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class RetrievalResult:
    evidence: list[Evidence]
    by_requirement: dict[str, list[str]]
    unsupported_requirements: list[str]
    queries: list[str]

    def ranked_projects(self) -> list[str]:
        seen, out = set(), []
        for e in self.evidence:
            if e.mapped_only:
                continue
            if e.project and e.project not in seen:
                seen.add(e.project); out.append(e.project)
        return out


def extract_requirements(job_text: str) -> list[str]:
    """Cheap requirement extraction: bullet lines, otherwise sentences naming a skill."""
    bullets = [re.sub(r"^[-*•]\s*", "", ln).strip() for ln in job_text.splitlines() if re.match(r"\s*[-*•]\s+", ln)]
    if bullets:
        return bullets[:8]
    sents = [s for s in re.split(r"(?<=[.!?])\s+", job_text) if detect_skills(s)]
    return sents[:8] or [job_text[:300]]


def rrf(lists: list[list[tuple[str, float]]], k: int = 60) -> list[tuple[str, float]]:
    agg: dict[str, float] = {}
    for lst in lists:
        for rank, (cid, _) in enumerate(lst):
            agg[cid] = agg.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return sorted(agg.items(), key=lambda x: -x[1])


class Pipeline:
    def __init__(self, cfg: PipelineConfig, hyde_writer=None) -> None:
        self.cfg = cfg
        self.hyde_writer = hyde_writer

    def with_(self, **kw) -> "Pipeline":
        return Pipeline(replace(self.cfg, **kw), self.hyde_writer)

    # -------------------------------------------------------------- one query
    def _search(self, idx: PortfolioIndex, query: str) -> list[tuple[str, float]]:
        c = self.cfg
        types = EVIDENCE_TYPES if c.evidence_only and c.chunkset == "structured" else None
        if c.contextual:
            query = f"Portfolio evidence for a freelance job requirement: {query}"
        dense = idx.dense(query, c.candidates, c.chunkset, types)
        if c.hybrid:
            lex = idx.lexical(query, c.candidates, c.chunkset, types)
            hits = rrf([dense, lex])
        else:
            hits = dense
        if c.rerank and hits:
            top = hits[: c.candidates]
            scores = get_reranker().score(query, [idx.get(cid).text for cid, _ in top])
            hits = sorted(zip([cid for cid, _ in top], scores), key=lambda x: -x[1])
        return hits

    def _outcome_boost(self, idx: PortfolioIndex, hits: list[tuple[str, float]]) -> list[tuple[str, float]]:
        stats = idx.outcome_by_project()
        out = []
        for cid, s in hits:
            p = idx.get(cid).project
            st = stats.get(p or "", {})
            n = sum(st.values())
            if n:
                success = (st.get("won", 0) * 2 + st.get("replied", 0)) / (2 * n)
                s = s * (1 + 0.5 * success) if s > 0 else s + 0.05 * success
            out.append((cid, s))
        return sorted(out, key=lambda x: -x[1])

    def _group_projects(self, idx: PortfolioIndex, hits: list[tuple[str, float]]) -> list[tuple[str, float, list[str]]]:
        """V5 multi-vector: summary/README/code are separate vectors; return one item per project.
        The project score is its best chunk plus a bonus for each additional chunk type that matched."""
        groups: dict[str, dict] = {}
        loose = []
        for rank, (cid, s) in enumerate(hits):
            ch = idx.get(cid)
            if not ch.project:
                loose.append((cid, s, [cid])); continue
            g = groups.setdefault(ch.project, {"best": cid, "score": s, "types": set(), "ids": [], "rank": rank})
            g["ids"].append(cid)
            g["types"].add(ch.type)
        base = [(g["best"], g["score"] * (1 + 0.08 * (len(g["types"]) - 1)), g["ids"]) for g in groups.values()]
        return sorted(base + loose, key=lambda x: -x[1])

    # -------------------------------------------------------------- public
    def retrieve(self, idx: PortfolioIndex, job_text: str, requirements: list[str] | None = None, k: int = 6
                 ) -> RetrievalResult:
        c = self.cfg
        reqs = requirements or extract_requirements(job_text)
        if c.hyde:
            queries = [self.hyde_writer(job_text) if self.hyde_writer else hypothetical_proposal(job_text)]
            req_for_query = [None]
        elif c.decompose:
            queries, req_for_query = list(reqs), list(reqs)
        else:
            queries, req_for_query = [job_text], [None]

        per_query: list[list[tuple[str, float, list[str]]]] = []
        for q in queries:
            hits = self._search(idx, q)
            if c.outcome:
                hits = self._outcome_boost(idx, hits)
            grouped = self._group_projects(idx, hits) if c.multivector else [(cid, s, [cid]) for cid, s in hits]
            per_query.append(grouped)

        if len(per_query) == 1:
            merged = [(cid, s) for cid, s, _ in per_query[0]]
        else:
            # round-robin over requirements, so every requirement gets its best item early
            merged = rrf([[(cid, s) for cid, s, _ in lst] for lst in per_query])
        related = {cid: rel for lst in per_query for cid, _, rel in lst}

        by_req: dict[str, list[str]] = {}
        for _q, r, lst in zip(queries, req_for_query, per_query):
            if r is not None:
                by_req[r] = [cid for cid, _, _ in lst[:3]]
        if not by_req and reqs:
            # Ranking used one query, but the fit matrix and claim grounding still need evidence per
            # requirement: map each requirement with the same search settings (not used for ranking).
            for r in reqs:
                hits = self._search(idx, r)
                if c.outcome:
                    hits = self._outcome_boost(idx, hits)
                grouped = self._group_projects(idx, hits) if c.multivector else [(cid, s_, [cid]) for cid, s_ in hits]
                by_req[r] = [cid for cid, _, _ in grouped[:3]]
                for cid, _, rel in grouped[:3]:
                    related.setdefault(cid, rel)

        unsupported: list[str] = []
        if c.corrective:
            from rag.variants.v8_corrective import corrective_loop
            # re-queried items only feed the requirement map (appended below as mapped_only), never the ranking
            by_req, unsupported, _extra = corrective_loop(self, idx, reqs, by_req)

        evidence, seen_proj = [], set()
        req_of = {cid: r for r, ids in by_req.items() for cid in ids}
        for cid, s in merged:
            ch = idx.get(cid)
            key = ch.project if (c.multivector and ch.project) else cid
            if key in seen_proj:
                continue
            seen_proj.add(key)
            evidence.append(Evidence(id=cid, item_id=ch.project or cid, project=ch.project, type=ch.type,
                                     source=ch.source, text=ch.text, score=round(float(s), 4),
                                     requirement=req_of.get(cid), date=ch.date, outcome=ch.outcome, title=ch.title,
                                     related=related.get(cid, [cid])))
            if len(evidence) >= max(k, 10):
                break
        # every item the requirement map points at must be present, so callers can show it
        have = {e.id for e in evidence}
        for r, ids in by_req.items():
            for cid in ids:
                if cid not in have:
                    ch = idx.get(cid)
                    evidence.append(Evidence(id=cid, item_id=ch.project or cid, project=ch.project, type=ch.type,
                                             source=ch.source, text=ch.text, score=0.0, requirement=r, date=ch.date,
                                             outcome=ch.outcome, title=ch.title, related=related.get(cid, [cid]),
                                             mapped_only=True))
                    have.add(cid)
        return RetrievalResult(evidence=evidence, by_requirement=by_req, unsupported_requirements=unsupported,
                               queries=queries)


def hypothetical_proposal(job_text: str) -> str:
    """Template HyDE used when no LLM is configured: an 'ideal proposal' that restates the needs as experience."""
    reqs = extract_requirements(job_text)
    skills = [s for r in reqs for s in detect_skills(r)]
    names = ", ".join(lexicon()[s][0] for s in dict.fromkeys(skills)) or "the requested stack"
    return (f"I have built a similar system for a client using {names}. "
            + " ".join(f"I delivered {r.lower()}." for r in reqs[:5]))


def requirement_supported(idx: PortfolioIndex, requirement: str, cid: str, dense_score: float | None = None,
                          threshold: float = 0.35) -> bool:
    ch = idx.get(cid)
    want = set(detect_skills(requirement))
    if want:
        return bool(want & set(ch.skills))
    rt = set(tokens(requirement))
    return bool(rt) and len(rt & set(tokens(ch.text))) / len(rt) >= threshold
