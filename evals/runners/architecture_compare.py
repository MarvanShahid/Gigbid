"""R&D question C: is the multi-agent design worth it?

    GROQ_API_KEY=... python -m evals.runners.architecture_compare [--n 50] [--profile open]

Arms on the same 50 dev jobs (ml_engineer persona, mixed kinds):
  (a) one ReAct agent holding all read tools (langgraph.prebuilt.create_react_agent), prompt agent/prompts/single_agent.md
  (b) prebuilt supervisor (langgraph-supervisor) over three ReAct workers: researcher, matcher, writer
  (c) GigBid's hand-built bid graph (any profile; with the `rules` profile it needs no key)
Measured: bid/skip accuracy, unsupported claims per proposal (rag.verify against retrieved evidence),
compliance violations caught before sending, GigSim reply rate (drafts submitted by the harness), tokens, latency.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import time

from evals.runners.common import dev_set, meta, percentile, setup_env, start_sim, write


def parse_final(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {"action": "skip", "reasons": ["no JSON in final answer"]}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"action": "skip", "reasons": ["unparsable final answer"]}


async def graph_arm(jobs, sim):
    from evals.runners.graph_eval import run_persona, summarise
    rows = await run_persona("ml_engineer", jobs, sim)
    s = summarise(rows)
    return {"accuracy": s["accuracy"], "bid_skip": s["bid_skip"], "unsupported_per_proposal": s["unsupported_per_proposal_after"],
            "compliance_caught": s["compliance"], "gigsim_reply_rate": s["gigsim_reply_rate"],
            "tokens_per_job": s["cost"]["tokens_per_job"], "p95_s": s["latency"]["p95_s_per_job"]}


async def agent_arm(kind: str, jobs, sim):
    import httpx
    from langgraph.prebuilt import create_react_agent

    from agent import llm
    from agent.mcp_client import Gateway
    from agent.nodes.proposal import check_text, strip_citations
    from agent.prompts import prompt
    from mcp_servers.marketplace.approvals import mint
    from rag.verify import verify
    gw = Gateway()
    gw.allow["single"] = {"get_job", "get_client_history", "market_stats", "get_connects_cost", "search_evidence",
                          "get_case_study", "list_skills"}
    account = f"arch-{kind}"
    tools = await gw.langchain_tools("single", account, "ml_engineer")
    model = llm._chat(llm.node_model("writer")["model"], 0)
    if kind == "react":
        agent = create_react_agent(model, tools)
    else:
        from langgraph_supervisor import create_supervisor
        by = {t.name: t for t in tools}
        research = create_react_agent(model, [by[n] for n in ("get_job", "get_client_history", "market_stats",
                                                              "get_connects_cost")], name="researcher",
                                      prompt="Research the job and client. Report scams and off-platform asks.")
        matcher = create_react_agent(model, [by[n] for n in ("search_evidence", "get_case_study", "list_skills")],
                                     name="matcher", prompt="Find portfolio evidence (ids) for each requirement.")
        writer = create_react_agent(model, [by["search_evidence"]], name="writer",
                                    prompt="Write the proposal; every experience claim cites evidence ids in [brackets].")
        agent = create_supervisor([research, matcher, writer], model=model,
                                  prompt="Coordinate researcher, matcher and writer, then give the final JSON.").compile()
    httpx.post(f"{sim}/admin/reset", headers={"x-admin-key": "sim-admin"}, params={"error_rate": 0})
    httpx.post(f"{sim}/admin/jobs", headers={"x-admin-key": "sim-admin"}, json=jobs)
    rows = []
    for j in jobs:
        t0 = time.perf_counter()
        q = prompt("single_agent", max_words=210, account=account, job=f"Job id {j['id']} (client {j['client_id']}):\n"
                   f"<job>\n{j['description']}\n</job>")
        try:
            out = await agent.ainvoke({"messages": [("user", q)]}, {"recursion_limit": 30})
            msgs = out["messages"]
            final = parse_final(msgs[-1].content)
            toks = sum((getattr(m, "usage_metadata", None) or {}).get("total_tokens", 0) for m in msgs)
        except Exception as e:  # noqa: BLE001
            final, toks = {"action": "skip", "reasons": [f"error {type(e).__name__}"]}, 0
        letter = final.get("cover_letter") or ""
        unsupported, caught, outcome = None, 0, None
        if final.get("action") == "bid" and letter:
            ev = await gw.call("system", "retrieve_for_job", {"job_text": j["description"], "owner": "ml_engineer"})
            v = verify(strip_citations(letter), ev["evidence"])
            unsupported = sum(x.label == "unsupported" for x in v)
            _, viols, _ = check_text(letter)
            caught = len(viols)
            body = {"account": account, "job_id": j["id"], "cover_letter": strip_citations(letter)[:4900] or "x" * 50,
                    "bid_amount": float(final.get("price") or j["budget"]["amount"]), "answers": ["Yes."] * len(j["screening_questions"])}
            d = await gw.call("system", "create_proposal_draft", body)
            grant = mint(account, "submit_proposal", {k: body[k] for k in ("job_id", "cover_letter", "bid_amount", "answers")},
                         f"arch-{kind}-{j['id']}")
            r = await gw.call("system", "submit_proposal", {"account": account, "draft_id": d["draft_id"],
                                                            "idempotency_key": f"arch-{kind}-{j['id']}", "approval_grant": grant,
                                                            "dry_run": False})
            outcome = r.get("proposal_id")
        rows.append({"bid": final.get("action") == "bid", "gold": j["_gold"]["bid"], "unsupported": unsupported,
                     "caught": caught, "proposal": outcome, "tokens": toks, "t": time.perf_counter() - t0})
    props = {p["id"]: p["status"] for p in httpx.get(f"{sim}/proposals", headers={"Authorization": f"Bearer gigsim-dev-{account}"}).json()["proposals"]}
    sub = [r for r in rows if r["proposal"]]
    up = [r["unsupported"] for r in rows if r["unsupported"] is not None]
    return {"accuracy": sum(r["bid"] == r["gold"] for r in rows) / len(rows),
            "unsupported_per_proposal": sum(up) / len(up) if up else None,
            "compliance_violations_in_drafts": sum(r["caught"] for r in rows),
            "gigsim_reply_rate": sum(props.get(r["proposal"]) in ("replied", "interview", "hired") for r in sub) / len(sub) if sub else None,
            "tokens_per_job": sum(r["tokens"] for r in rows) / len(rows), "p95_s": percentile([r["t"] for r in rows], .95)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--profile", default=None)
    args = ap.parse_args()
    import os
    os.environ["SIM_START_CONNECTS"] = "1000000"
    setup_env(args.profile)
    from agent import llm
    sim = start_sim()
    jobs = [j for j in dev_set("ml_engineer") if "-dup" not in j["id"]][: args.n]
    res = {"graph": asyncio.run(graph_arm(jobs, sim))}
    if llm.has_model("writer"):
        res["react_single_agent"] = asyncio.run(agent_arm("react", jobs, sim))
        res["prebuilt_supervisor"] = asyncio.run(agent_arm("supervisor", jobs, sim))
        status = "done"
    else:
        res["react_single_agent"] = res["prebuilt_supervisor"] = "pending: needs an LLM profile (GROQ_API_KEY)"
        status = "partial"
    write("architecture_compare.json", {"meta": meta(n_jobs=len(jobs)), "status": status, "results": res})


if __name__ == "__main__":
    main()
