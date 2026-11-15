# ADR 0004: open-weight models through Groq, routed per node
**Decision.** `open` profile: gpt-oss-20b for cheap nodes (analyst, risk, researcher, verifier, intent), gpt-oss-120b
for writer, critic and liaison, Llama-3.1-8B as the fallback for cheap nodes. Second configuration `open_alt` (Llama 3.1 8B / 3.3 70B) is compared on the dev set.
A `rules` profile runs every node deterministically, with no model, for CI, tests and offline demos.
**Why.** Free hosts have no GPU, and Groq serves open-weight models fast enough for streaming. Every node's model is in config.
**Consequence.** Any node must still work if its model call fails: rules fallback for cheap nodes, retry for the writer.
