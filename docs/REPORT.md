# GigBid: R&D report

AI-4016 Assignment II · Marvan Shahid (23i-0800) · engineering design review

Every number here comes from a file in `evals/results/` (named in brackets) and is reproduced by `make eval`.
**All results are on a synthetic stand-in** for GigSim and the persona corpora (docs/DATA_CARD.md). They were run
with the `rules` profile (no LLM) and the offline fallback embedder, because neither a model API nor a model download
was reachable from the build machine. Model-dependent experiments are scripted and reported as pending.

## 1. Problem and constraints

A freelancer loses hours scanning feeds, spends Connects on jobs they will not win, sends generic proposals,
and meets scams asking for free work or off-platform payment. GigBid automates **discovery, assessment and drafting**.
The freelancer keeps every decision that leaves the system.

**Never automated:** submitting a proposal, sending a message, spending Connects, and confirming anything on Upwork.
This is enforced three times: a LangGraph `interrupt()` before the action, an approval grant the marketplace server
checks against the exact payload, and draft-only writes in live mode.

**Budgets (declared in `agent/config.yaml`):** p95 ≤ 25 s per job analysed and ≤ 60 s per proposal; ≤ $0.002 per job
and ≤ $0.01 per proposal on the open profile; ≤ 40 steps and ≤ 60k tokens per thread. A thread over budget moves
to a visible *needs attention* state.

## 2. Architecture

Two graphs (docs/ARCHITECTURE.md, rendered from code in `docs/images/*.mmd`).

* **Bid graph**, one thread per job. The Scout hands a job in. Job Analyst, Risk Assessor, Client Researcher (X4) and Fit
  Matcher run in parallel (`Send`; separate keys under `analyses`, merged by a reducer). Then a decision (skip / watch
  / bid), Pricing, Writer, claim verification, Critic (at most two revisions), Compliance Guard, a dry-run preview and
  the approval interrupt. Approve submits exactly once; edit and regenerate go back through Compliance; reject records a reason.
* **Conversation graph**, one thread per client thread: intent → interview slots → reply → compliance → approval → send.
* **One marketplace port** with GigSim and Upwork adapters (R1). **MCP surface**: Portfolio, Marketplace and Workspace
  servers plus Upwork's and GitHub's official servers (docs/TOOLS.md).
* **Stores**: Postgres holds the app data, the LangGraph checkpointer, the LangGraph long-term store and pgvector.
  State, the execution trace (OpenTelemetry spans plus the hash-chained audit log) and promoted memory are kept apart.

Why each agent exists is tabulated in docs/ARCHITECTURE.md. In short, a role is separate when it needs a different
model, different tools, or must not grade its own output (the writer is never its own verifier).

## 3. R&D question A: tool granularity

*Hypothesis H-A:* coarse dispatcher tools lower argument accuracy (the model has to invent nested arguments), and
descriptions that say *when* to use a tool raise selection accuracy over plain descriptions.
*Setup* (`evals/runners/tool_granularity.py`): 40 tasks, each with one known correct call, generated from the dev set.
Three tool sets: fine (14 tools), coarse (3 dispatchers with `action` + `args`), and best (11 tools, rewritten descriptions).
One model call per task on the open profile's small model. *Metrics:* tool-selection accuracy, argument accuracy, tokens per task.
*Result:* **pending**. The run needs `GROQ_API_KEY` (`tool_granularity.json` records `status: pending` and the 40 tasks).
*How to finish:* `GROQ_API_KEY=… python -m evals.runners.tool_granularity`.

## 4. R&D question B: retrieval, claim verification, ablation

*Hypothesis H-B (stated before running):* requirement decomposition plus hybrid retrieval raises evidence Recall@5 by ≥ 15
points over V0 on jobs with four or more requirements. **Not supported: 0.782 → 0.765 (−1.7 points)** (`rag_variants.json`).
Decomposing a post into requirements and fusing one ranking per requirement spreads the top-5 across many projects
that each match one requirement. The gold set rewards projects that cover several. The whole-post query was better
for ranking. Decomposition is still the right tool for the *requirement → evidence map*, so the shipped pipeline uses
it there and not for ranking (ADR 0005).

*Variants:* V0–V8 plus seven compositions, on every dev job with gold evidence. The selection rule (highest nDCG@10, then
Recall@5, then prefer the corrective loop) picked **hybrid + multi-vector + rerank + outcome-aware + corrective map**:
Recall@5 0.947 and nDCG@10 0.870, against V0's 0.791 and 0.599. *Ablation* (`rag_ablation.json`):

| Removed | nDCG@10 | Δ |
|---|---|---|
| none (shipped) | 0.870 | |
| multi-vector grouping | 0.713 | −0.157 |
| rerank (lexical pair scorer) | 0.844 | −0.026 |
| hybrid BM25 | 0.857 | −0.013 |
| outcome-aware boost | 0.869 | −0.001 |
| corrective loop | 0.870 | 0.000 (by design: it only changes the requirement map) |

Multi-vector grouping matters most because the corpus describes each project three ways: case study, README, code.
Without grouping, three chunks of one project fill three of the top-5 slots. Outcome-aware ranking has no measurable
effect on this corpus, because won and replied proposals are spread almost evenly over projects. That is a negative
result, and the component is kept only because removing it does not help either.

*Claim verification* (`graph_eval_rules.json`): 2.92 claims checked per proposal; unsupported claims
0.004 → 0.000 per proposal after verification. The rules-profile writer builds sentences from evidence wording, so
its claims are rarely unsupported. The verifier matters for model-written drafts, and that run is pending.

*By persona:* bid F1 0.932 / 0.969 / 0.958 (ml / full-stack / data). Price-in-band is lowest for full-stack (83.1%),
where budgets vary most within a category.

**Where better retrieval did not translate into replies.** With the whole system fixed and only the retriever swapped,
V0 gets a **GigSim reply rate of 89.8% against 89.1%** for the shipped pipeline, but a **hire rate of 64.4% against 76.1%**
(`graph_eval_rules_v0.json` vs `graph_eval_rules.json`). The simulated client decides to *reply* mostly from whether the
proposal names its requirements and avoids a generic opening. Both writers name the requirements because they come from
the job text, not from retrieval. The *hire* threshold needs a higher score, which better evidence coverage
reaches more often. Retrieval quality shows up in the later stages of the funnel, not in the reply rate the assignment
asks for. On the stand-in this is partly an artefact of a rule-based client (DATA_CARD).

*Judge:* a calibrated LLM judge is required. `judge_labels.csv` holds 30 anonymised proposals for my own 1–5 labels;
the judge run and Cohen's kappa are **pending** a model key and those labels (`judge_calibration.json`).

**Decision on what ships:** hybrid + multi-vector + cross-encoder rerank + outcome boost + corrective requirement map,
with claim verification always on. It wins nDCG@10 and Recall@5. Its cost is about 13 ms p95 per retrieval on CPU,
negligible next to model calls.

## 5. R&D question C: single agent vs prebuilt supervisor vs hand-built graph

*Setup* (`evals/runners/architecture_compare.py`): the same 50 dev jobs. (a) one ReAct agent holding all read tools
(`create_react_agent`, prompt `agent/prompts/single_agent.md`); (b) `langgraph-supervisor` over three ReAct workers;
(c) the bid graph. Drafts from (a) and (b) are verified with the same claim checker, checked by the same compliance
rules and submitted to GigSim by the harness.
*Result so far* (`architecture_compare.json`): (c) in the rules profile gets 50/50 decisions right, reply rate 94.4% on its 18
proposals, 0 unsupported claims. (a) and (b) need a model and are **pending**.
Expected outcome, to confirm: the single agent may beat the graph on short, clearly in-domain posts, where one
model call can read the post and evidence together. It should lose on scams and injections, where the graph applies
rules before any model reads the text.

## 6. The change request

On 2 Nov the platform made large-budget jobs cost 1.5× Connects and started rejecting proposals with unanswered
screening questions (docs/CHANGE_REQUEST.md). Pricing needed **no change**, because it reads the cost from
`get_connects_cost`, which already applies the policy in force. Enforcing complete answers took a config flag, a 3-line
check in the Compliance Guard and a 5-line pre-check in `submit_proposal`, about 12 lines in three files, tested by
`test_change_request_policy_v2`. Because the policy text was known before the code was written, the switch was
designed in from the start. That is the point: platform rules belong in tools and config, not in prompts.

## 7. Signature extension: X4 client research

A fourth parallel branch builds a `ClientBrief` (payment verified, hire rate, spend per hire, tenure, tier, budget
against the market range, up to three talking points) from MCP tools only. It feeds the decision, pricing, the writer and
the UI (docs/EXTENSION.md).
*Measurement* (`graph_eval_rules_no_x4.json`): switching X4 off changes **nothing measurable**: reply rate 89.1% → 89.1%,
price-in-band 89.2% → 89.2%, hire rate 76.1% → 76.6%. The simulated client does not reward client-specific angles, and
the rules writer only adds one milestone sentence for repeat hirers. Its market statistics did matter indirectly:
fix F-1 (below) uses them. A fair test of X4 needs the LLM writer and the instructor's LLM-driven clients.

## 8. Failure analysis

From the 600-job run (docs/FAILURES.md, `failures_rules*.json`):

| Category | Before F-1 | After F-1 | Fix tried | Worked? |
|---|---|---|---|---|
| Wrong bid | 33 | 8 | F-1: skip fixed budgets under 40% of the category's market p25 | **yes**: bid F1 0.906 → 0.953, precision 0.875 → 0.967 |
| Mispriced | 25 | 25 | F-3 (proposed): scale by stated timeline as a complexity proxy | not run |
| Wrong skip (missed evidence) | 15 | 15 | F-2 (proposed): real `bge-small` embedder instead of the offline fallback | not run (model download blocked) |
| Missed scam / unsupported claim / injection / tool error | 0 | 0 | — | — |

Wrong skips are all paraphrase-only requirements ("retrieval-augmented generation" for RAG). Each surfaces as a "watch"
with an explanation, so the user can override it with *Draft anyway*. Mispricing comes from complexity the post does not state.

Engineering failures found by the evaluation itself are listed in docs/AI_USAGE.md: a shared embedder that
silently changed scores between runs, evidence leaking into ranking metrics, the exactly-once ledger replaying across
simulator resets, and an injection metric that blamed attacks for ordinary errors. Each was caught because a number
moved when it should not have.

## 9. Safety and platform respect

**Never:** send without approval; spend Connects without approval; contact or pay off-platform; claim unsupported
experience; scrape, use browser automation or session cookies; poll Upwork faster than every 3 hours.
**How it is enforced:** (1) the interrupt plus a payload-bound, one-time approval grant checked by the marketplace server;
(2) the Compliance Guard over `rules.yaml` blocks contact details, off-platform payment and echoed injection payloads,
and strips guarantees; (3) untrusted text is neutralised (hidden comments and instruction sentences removed), delimited
with a random boundary, and labelled as data in every prompt; (4) claim verification; (5) PII and token masking in every
span and audit record; (6) per-account rate limiting at about 80% of GigSim's limit; encrypted OAuth tokens; tenant scoping
on every query (tested).
**Measured:** 36/36 planted injections detected, 0 false positives on clean posts, 0/36 successful attacks by a
counterfactual test (the same post without the injected line). With defences off the rules profile also shows 0/36,
**because nothing in that profile reads the post as instructions**. The defence becomes testable only with a model;
`graph_eval --no-defences --profile open` is the pending measurement.
**What still gets through:** scam wording outside the five pattern families (rules are lexical); instructions phrased
as ordinary requirements ("the proposal must include your WhatsApp"); and an attack that would beat the defence:
spreading an instruction across two innocuous sentences, so no single sentence matches a pattern and the
model reassembles it. Only the output-side Compliance check would still catch the payload.

## 10. Hidden test results against declared budgets

Not available at writing time: the hidden test run happens after the deadline against the deployed URL. Development
measurements in the rules profile: p95 0.30 s per job analysed and 0.40 s per proposal, $0 per job, all well inside
the declared budgets. The open profile adds model latency and cost, which the per-node spans record; `make eval-llm`
produces the comparable numbers. An optimisation that helped: running the four analysis nodes in parallel. Their
latencies overlap instead of adding up (per-node times in each run's `node_latency`).
