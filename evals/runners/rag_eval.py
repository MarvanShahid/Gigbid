"""R&D question B, retrieval part: compare RAG variants on the dev set.

    python -m evals.runners.rag_eval [--per-persona 120]

Metrics against gold evidence (project level, since the persona corpora describe
the same project several ways):
  Recall@5  = |gold ∩ top-5 projects| / min(5, |gold|)
  MRR       = 1 / rank of the first gold project
  nDCG@10   = binary-relevance nDCG over the top-10 projects
Jobs with no gold evidence (scams, off-domain) are excluded from retrieval metrics.

Hypothesis H-B (stated before running): requirement decomposition plus hybrid
retrieval (V1+V2) raises Recall@5 by at least 15 points over V0 on jobs with four
or more requirements, because one whole-post query is dominated by one or two
skills and dense vectors blur exact tool names.
"""
from __future__ import annotations

import argparse
import math
import time

from evals.runners.common import PERSONAS, dev_set, meta, percentile, setup_env, write


def metrics(ranked: list[str], gold: set[str]) -> dict:
    top5 = ranked[:5]
    rec = len(gold & set(top5)) / min(5, len(gold))
    mrr = next((1 / (i + 1) for i, p in enumerate(ranked) if p in gold), 0.0)
    dcg = sum(1 / math.log2(i + 2) for i, p in enumerate(ranked[:10]) if p in gold)
    idcg = sum(1 / math.log2(i + 2) for i in range(min(10, len(gold))))
    return {"recall5": rec, "mrr": mrr, "ndcg10": dcg / idcg if idcg else 0.0}


def evaluate(variants: list[str], per_persona: int | None, ablate: dict | None = None) -> dict:
    import rag.retriever as R
    from rag.index.portfolio_index import get_index
    from rag.variants.base import extract_requirements
    build_variant = R.build_variant
    out: dict = {}
    for name in variants:
        pipe = build_variant(name.split("-")[0])
        if ablate and name in ablate:
            pipe = pipe.with_(**ablate[name])
        rows = []
        for persona in PERSONAS:
            idx = get_index(persona)
            for job in dev_set(persona, per_persona):
                gold = set(job["_gold"]["evidence"])
                if not gold:
                    continue
                reqs = extract_requirements(job["description"])
                t0 = time.perf_counter()
                res = pipe.retrieve(idx, job["description"], reqs, k=10)
                dt = time.perf_counter() - t0
                m = metrics(res.ranked_projects(), gold)
                rows.append({"persona": persona, "kind": job["_gold"]["kind"], "n_req": len(job["_gold"]["requirements"]),
                             "latency": dt, **m})
        agg = lambda rs: {k: round(sum(r[k] for r in rs) / len(rs), 4) for k in ("recall5", "mrr", "ndcg10")} if rs else {}  # noqa: E731
        by_persona = {p: agg([r for r in rows if r["persona"] == p]) for p in PERSONAS}
        by_kind = {k: agg([r for r in rows if r["kind"] == k]) for k in sorted({r["kind"] for r in rows})}
        out[name] = {**agg(rows), "n": len(rows), "p95_latency_s": round(percentile([r["latency"] for r in rows], .95), 4),
                     "by_persona": by_persona, "by_job_type": by_kind,
                     "four_plus_requirements": agg([r for r in rows if r["n_req"] >= 4])}
        print(f"{name:16s} R@5 {out[name]['recall5']:.3f}  MRR {out[name]['mrr']:.3f}  nDCG@10 {out[name]['ndcg10']:.3f}")
    return out


VARIANTS = ["v0_naive", "v1_decompose", "v2_hybrid", "v3_rerank", "v4_outcome", "v5_multivector", "v6_contextual",
            "v7_hyde", "v8_corrective", "v_best"]


# Candidate compositions for the shipped pipeline (each is a set of PipelineConfig flags).
CANDIDATES = {
    "c_hyb_mv": dict(hybrid=True, multivector=True),
    "c_hyb_mv_rr": dict(hybrid=True, multivector=True, rerank=True),
    "c_hyb_mv_rr_out": dict(hybrid=True, multivector=True, rerank=True, outcome=True),
    "c_hyb_mv_hyde": dict(hybrid=True, multivector=True, hyde=True),
    "c_hyb_mv_rr_corr": dict(hybrid=True, multivector=True, rerank=True, corrective=True),
    "c_dec_hyb_mv_rr": dict(decompose=True, hybrid=True, multivector=True, rerank=True),
    "c_hyb_mv_rr_out_corr": dict(hybrid=True, multivector=True, rerank=True, outcome=True, corrective=True),
}


def evaluate_candidates(per_persona: int | None) -> dict:
    import rag.retriever as R
    from rag.variants.base import PipelineConfig
    out = {}
    for name, flags in CANDIDATES.items():
        orig = R.build_variant
        from rag.variants.base import Pipeline
        R.build_variant = lambda n=None, _f=flags, _n=name: Pipeline(PipelineConfig(name=_n, **_f))  # noqa: E731
        try:
            out.update(evaluate([name], per_persona))
        finally:
            R.build_variant = orig
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-persona", type=int, default=None)
    ap.add_argument("--variants", nargs="*", default=VARIANTS)
    args = ap.parse_args()
    setup_env()
    res = evaluate(args.variants, args.per_persona)
    base, best4 = res.get("v0_naive", {}), {}
    if "v1_decompose" in res and "v2_hybrid" in res:
        # H-B arm: decomposition + hybrid together
        hb = evaluate(["v1_decompose-hybrid"], args.per_persona, {"v1_decompose-hybrid": {"hybrid": True}})
        res.update(hb)
        best4 = hb["v1_decompose-hybrid"]["four_plus_requirements"]
    cands = evaluate_candidates(args.per_persona)
    res.update(cands)
    pool = {k: v for k, v in res.items() if k.startswith("c_")}
    # ties (to 3 decimals) go to the composition with the corrective loop: same ranking, plus refusal to claim
    chosen = max(pool, key=lambda k: (round(pool[k]["ndcg10"], 3), round(pool[k]["recall5"], 3),
                                      CANDIDATES[k].get("corrective", False))) if pool else None
    b4 = base.get("four_plus_requirements", {})
    delta = round(100 * (best4.get("recall5", 0) - b4.get("recall5", 0)), 1) if b4 else None
    write("rag_variants.json", {"meta": meta(), "variants": res, "hypothesis": {
        "id": "H-B", "statement": "decomposition + hybrid raises Recall@5 by >= 15 points over V0 on jobs with >= 4 requirements",
        "v0_recall5_4plus": b4.get("recall5"), "decompose_hybrid_recall5_4plus": best4.get("recall5"),
        "delta_points": delta, "supported": delta is not None and delta >= 15},
        "candidates": CANDIDATES, "chosen": chosen, "chosen_flags": CANDIDATES.get(chosen),
        "selection_rule": "highest nDCG@10 among candidate compositions, then Recall@5, then prefer the corrective loop"})


if __name__ == "__main__":
    main()
