# Technical write-up: outline (write it in your own words, 1,200–1,800 words)

The assignment asks for an article on LinkedIn, Medium or a blog about **the most surprising thing your experiments
showed**, not a tutorial. These are the candidates the results support. Pick one, rerun with the open profile first, and
write it yourself.

1. **Better retrieval didn't raise the reply rate, but it raised the hire rate.** Swapping the naive retriever for the
   shipped pipeline moved nDCG@10 from 0.599 to 0.870, yet GigSim's reply rate stayed at about 89% (89.8% vs 89.1%). The hire
   rate went from 64.4% to 76.1%. The first gate (reply) rewards naming the client's needs, and both writers do that from
   the job text. The second gate rewards evidence coverage. Lesson: measure the whole funnel, not the first metric you are given.
   (`graph_eval_rules.json`, `graph_eval_rules_v0.json`)
2. **The fanciest retrieval idea made ranking worse.** Requirement decomposition is the textbook fix for multi-skill job
   posts, and it lowered Recall@5 on exactly those posts (−1.7 points). It is still the right tool for mapping each
   requirement to evidence. (`rag_variants.json`)
3. **One config rule beat a model.** A lowball check against the market's 25th percentile raised bid/skip precision from
   0.875 to 0.967. (`failures_rules_before_fix_F1.json` vs `failures_rules.json`)
4. **Your evaluation lies to you before your model does.** Four numbers moved for the wrong reasons during development:
   a shared embedder, ranking leakage, an exactly-once ledger replaying across resets, and an injection metric blaming
   attacks for ordinary errors (docs/AI_USAGE.md).

Structure: the claim → the setup in two paragraphs → the number → why → what you changed → what you would test next
(the LLM run, real GigSim).

## Résumé bullet (numbers from your own results files; update after the open-profile run)

* Built GigBid, a LangGraph multi-agent freelancer copilot over 5 MCP servers (3 custom). Hybrid + multi-vector
  retrieval raised evidence nDCG@10 from 0.60 to 0.87, and claim verification held unsupported claims at 0 per proposal
  across 239 simulated proposals.
* Shipped human-in-the-loop approvals with exactly-once submission (crash-tested), bid/skip F1 0.95 on 600 labelled
  jobs, and 36/36 prompt-injection attempts detected, behind a CI eval gate.
