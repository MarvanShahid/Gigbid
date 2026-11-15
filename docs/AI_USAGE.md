# AI usage

| Tool | Used for | Files |
|---|---|---|
| Claude (Anthropic), via claude.ai | Generated the first version of most of the code and docs from the assignment brief, then iterated with test runs | essentially all files; the student owns review, changes and every design decision defended in the viva |

**Things the assistant got wrong that were caught by tests or evaluation** (all fixed; see the commits):

1. **Shared embedder across portfolios.** The offline TF-IDF embedder was one cached instance. Building a second
   persona's index re-fitted its IDF, silently changing the first index's query vectors. The symptom was the same
   variant scoring 0.869, then 0.875 in a repeated run. Fixed by giving each index its own embedder
   (`rag/index/portfolio_index.py`).
2. **Evaluation leakage.** Evidence added only for the requirement map was being counted in ranking metrics, and V0's
   Recall@5 jumped from 0.79 to 0.93. Fixed with `Evidence.mapped_only`.
3. **Exactly-once ledger across simulator resets.** The ledger correctly replayed old idempotency keys, but in
   evaluation this meant proposals never reached the fresh simulator (reply rate 0.0). The eval now uses a fresh
   ledger per run; production keeps the persistent one.
4. **Injection metric blamed the attack for ordinary errors.** It counted wrong bids on injected posts as successful
   attacks. Replaced with a counterfactual: the same post without the injected line.
5. **Budget overrun did not stop parallel branches.** A `Command(goto=...)` plus static edges kept running nodes.
   Replaced with a sticky `needs_attention` status that every node and router respects.
6. A corrective-RAG subgraph inherited the parent's checkpointer and failed inside an async run
   (fixed with `checkpointer=False`).

Before the viva: read every file you will be asked about, rerun `make test` and `make eval`, and change one thing
yourself (for example a threshold in `agent/config.yaml`) so you can show the effect live.
