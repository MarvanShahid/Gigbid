"""R&D question A: does tool granularity change agent behaviour?

    GROQ_API_KEY=... python -m evals.runners.tool_granularity [--profile open]

40 tasks with one known correct call each, three tool sets:
  fine    every MCP tool as-is (14 tools)
  coarse  three dispatcher tools: marketplace(action, args), portfolio(action, args), workspace(action, args)
  best    the fine set minus overlapping tools, with descriptions rewritten to say WHEN to use each tool
Metrics: tool-selection accuracy, argument accuracy (all required args equal after normalisation), tokens per task.
Hypothesis H-A: coarse tools lower argument accuracy (the model must invent the nested args), and rewritten
descriptions raise selection accuracy over the fine set.
"""
from __future__ import annotations

import argparse
import random

from evals.runners.common import PERSONAS, dev_set, meta, setup_env, write

FINE = {
    "search_evidence": ("Search the portfolio.", {"requirement": "string", "k": "integer"}),
    "retrieve_for_job": ("Retrieve evidence for a job.", {"job_text": "string"}),
    "get_case_study": ("Get a case study.", {"case_id": "string"}),
    "list_skills": ("List skills.", {}),
    "search_jobs": ("Search jobs.", {"query": "string"}),
    "get_job": ("Get a job.", {"job_id": "string"}),
    "get_client_history": ("Get client history.", {"client_id": "string"}),
    "get_connects_balance": ("Get Connects balance.", {}),
    "get_connects_cost": ("Get Connects cost.", {"job_id": "string"}),
    "market_stats": ("Get market stats.", {"category": "string"}),
    "list_messages": ("List messages.", {}),
    "list_proposals": ("List proposals.", {}),
    "free_slots": ("Get free slots.", {"days": "integer"}),
    "create_email_draft": ("Create an email draft.", {"to_label": "string", "subject": "string", "body": "string"}),
}
BEST_DESC = {
    "search_evidence": "Use when you need proof from MY portfolio for ONE skill or requirement. Pass that requirement as plain words.",
    "get_case_study": "Use when you already know a project id (like 'ml-p03') and need its full write-up.",
    "list_skills": "Use to see which skills my portfolio names explicitly. Takes no arguments.",
    "search_jobs": "Use to FIND open jobs by keywords. Not for a job whose id you already have.",
    "get_job": "Use when you have a job id and need its full post, screening questions or Connects cost field.",
    "get_client_history": "Use to judge a CLIENT (payment verified, hires, spend). Needs the client id from the job post.",
    "get_connects_balance": "Use to see how many Connects I have left. Takes no arguments.",
    "get_connects_cost": "Use to see how many Connects bidding on ONE job costs under today's policy. Needs the job id.",
    "market_stats": "Use for typical awarded prices in a job CATEGORY (p25/median/p75). Needs the category id.",
    "list_messages": "Use to read client message threads. Takes no arguments.",
    "free_slots": "Use to find free interview times in my calendar. Pass how many days ahead.",
}


def tasks() -> list[dict]:
    rng = random.Random(800)
    out = []
    jobs = [j for p in PERSONAS for j in dev_set(p)][:200]
    for i in range(40):
        j = rng.choice(jobs)
        kind = i % 10
        if kind == 0:
            out.append({"q": f"Do I have portfolio proof for {j['_gold']['requirements'][0].replace('_', ' ')}?",
                        "tool": "search_evidence", "args": {"requirement": j["_gold"]["requirements"][0].replace("_", " ")}})
        elif kind == 1:
            out.append({"q": f"Is the client behind job {j['id']} (client id {j['client_id']}) trustworthy?",
                        "tool": "get_client_history", "args": {"client_id": j["client_id"]}})
        elif kind == 2:
            out.append({"q": f"How many Connects would it cost me to bid on job {j['id']}?", "tool": "get_connects_cost",
                        "args": {"job_id": j["id"]}})
        elif kind == 3:
            out.append({"q": f"What do jobs in the {j['category']} category usually pay?", "tool": "market_stats",
                        "args": {"category": j["category"]}})
        elif kind == 4:
            out.append({"q": f"Show me the screening questions of job {j['id']}.", "tool": "get_job", "args": {"job_id": j["id"]}})
        elif kind == 5:
            out.append({"q": "How many Connects do I have left this week?", "tool": "get_connects_balance", "args": {}})
        elif kind == 6:
            proj = rng.choice(j["_gold"]["evidence"] or ["ml-p01"])
            out.append({"q": f"Open my case study {proj}.", "tool": "get_case_study", "args": {"case_id": proj}})
        elif kind == 7:
            out.append({"q": "When am I free for a client call in the next 3 days?", "tool": "free_slots", "args": {"days": 3}})
        elif kind == 8:
            out.append({"q": "Any new messages from clients?", "tool": "list_messages", "args": {}})
        else:
            kw = j["skills_tags"][0]
            out.append({"q": f"Find open jobs about {kw}.", "tool": "search_jobs", "args": {"query": kw}})
    return out


def toolset(name: str):
    from langchain_core.tools import StructuredTool

    def mk(tname, desc, props):
        schema = {"type": "object", "properties": {k: {"type": v} for k, v in props.items()}, "required": list(props)}
        return StructuredTool.from_function(func=lambda **kw: "ok", name=tname, description=desc, args_schema=schema)
    if name == "fine":
        return [mk(n, d, p) for n, (d, p) in FINE.items()]
    if name == "best":
        return [mk(n, BEST_DESC[n], FINE[n][1]) for n in BEST_DESC]
    groups = {"marketplace": ["search_jobs", "get_job", "get_client_history", "get_connects_balance", "get_connects_cost",
                              "market_stats", "list_messages", "list_proposals"],
              "portfolio": ["search_evidence", "retrieve_for_job", "get_case_study", "list_skills"],
              "workspace": ["free_slots", "create_email_draft"]}
    return [mk(g, f"{g} operations. action is one of: {', '.join(acts)}. args is an object with that action's arguments.",
               {"action": "string", "args": "object"}) for g, acts in groups.items()]


def norm(v):
    return str(v).strip().lower().replace("_", " ")


def score(task: dict, call: dict | None, coarse: bool) -> tuple[bool, bool]:
    if not call:
        return False, False
    name, args = call["name"], call.get("args", {})
    if coarse:
        name, args = args.get("action", ""), args.get("args", {}) or {}
    sel = name == task["tool"]
    argok = sel and all(norm(args.get(k)) == norm(v) for k, v in task["args"].items())
    return sel, argok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="open")
    args = ap.parse_args()
    setup_env(args.profile)
    from agent import llm
    from agent.settings import profile
    T = tasks()
    if not llm.has_model("intent"):
        write("tool_granularity.json", {"meta": meta(), "status": "pending",
                                         "reason": f"no model for profile '{args.profile}' (set {profile().get('api_key_env')})",
                                         "n_tasks": len(T), "tasks": T})
        return
    chat = llm._chat(llm.node_model("intent")["model"], 0)
    res = {}
    for name in ("fine", "coarse", "best"):
        bound = chat.bind_tools(toolset(name))
        sel = argok = toks = 0
        per = []
        for t in T:
            msg = bound.invoke([("system", "You are GigBid's assistant. Call exactly one tool to answer."), ("user", t["q"])])
            call = msg.tool_calls[0] if msg.tool_calls else None
            s, a = score(t, call, name == "coarse")
            sel += s; argok += a
            toks += (msg.usage_metadata or {}).get("total_tokens", 0)
            per.append({"q": t["q"], "expected": t["tool"], "got": call, "selection_ok": s, "args_ok": a})
        res[name] = {"selection_accuracy": sel / len(T), "argument_accuracy": argok / len(T),
                     "tokens_per_task": toks / len(T), "calls": per}
        print(name, res[name]["selection_accuracy"], res[name]["argument_accuracy"], res[name]["tokens_per_task"])
    write("tool_granularity.json", {"meta": meta(model=llm.node_model("intent")["model"]), "status": "done",
                                     "n_tasks": len(T), "results": res})


if __name__ == "__main__":
    main()
