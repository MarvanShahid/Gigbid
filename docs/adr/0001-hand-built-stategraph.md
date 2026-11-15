# ADR 0001: hand-built StateGraph with parallel analysis
**Decision.** Nine roles in a hand-written LangGraph `StateGraph`. Job Analyst, Risk Assessor, Client Researcher
and Fit Matcher fan out with `Send` and merge through a reducer.
**Why.** The four analyses do not depend on each other, so running them in parallel cuts latency to the slowest one.
Separate keys plus `merge_dicts` make concurrent writes safe. A hand-built graph makes the approval interrupt,
the bounded critic loop and the exactly-once submit explicit. A prebuilt supervisor decides control flow with a model call per step.
**Consequence.** More code than `create_react_agent`. R&D question C measures whether it pays off.
