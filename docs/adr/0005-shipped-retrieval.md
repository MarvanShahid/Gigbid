# ADR 0005: shipped retrieval = hybrid + multi-vector + rerank + outcome + corrective map
**Decision.** Chosen by `evals/runners/rag_eval.py` among candidate compositions (highest nDCG@10, then Recall@5, then
prefer the corrective loop). Requirement decomposition is **not** used for ranking. It is used only to build the
requirement → evidence map.
**Why.** On the dev set, decomposition lowered ranking quality (H-B not supported), while multi-vector project
grouping gave the largest gain in the ablation. The corrective loop does not change ranking but refuses to claim
requirements nothing supports.
**Consequence.** Two kinds of evidence in a result: ranked items, and `mapped_only` items added for the matrix.
