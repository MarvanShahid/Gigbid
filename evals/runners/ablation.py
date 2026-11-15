"""Ablation of the shipped retrieval pipeline: remove one component at a time.

    python -m evals.runners.ablation
"""
from __future__ import annotations

from evals.runners.common import meta, setup_env, write
from evals.runners.rag_eval import evaluate


def main() -> None:
    setup_env()
    from agent.settings import config
    best = dict(config()["rag"]["best"])
    arms = {"shipped": {}}
    for comp in ("hybrid", "multivector", "rerank", "outcome", "corrective"):
        if best.get(comp):
            arms[f"-{comp}"] = {comp: False}
    res = evaluate([f"v_best-{k}" if k != "shipped" else "v_best" for k in arms], None,
                   {f"v_best-{k}": v for k, v in arms.items() if k != "shipped"})
    base = res["v_best"]
    table = []
    for k in arms:
        name = "v_best" if k == "shipped" else f"v_best-{k}"
        r = res[name]
        table.append({"removed": k if k != "shipped" else None, "recall5": r["recall5"], "mrr": r["mrr"],
                      "ndcg10": r["ndcg10"], "delta_ndcg10": round(r["ndcg10"] - base["ndcg10"], 4),
                      "by_persona": r["by_persona"], "by_job_type": r["by_job_type"]})
    write("rag_ablation.json", {"meta": meta(), "shipped_flags": best, "rows": table})


if __name__ == "__main__":
    main()
