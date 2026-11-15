"""Fixed GigSim reply-rate run: the same 30 labelled "bid" jobs per persona every time.

    python -m evals.runners.gigsim_outcomes
"""
import asyncio
import os
import time

from evals.runners.common import PERSONAS, dev_set, meta, setup_env, start_sim, write

FIXED_N = 30


def fixed_jobs(persona: str) -> list[dict]:
    return [j for j in dev_set(persona) if j["_gold"]["bid"] and "-dup" not in j["id"]][:FIXED_N]


def main() -> None:
    os.environ["SIM_START_CONNECTS"] = "1000000"
    setup_env()
    from evals.runners.graph_eval import run_persona
    sim = start_sim()
    out = {}
    for p in PERSONAS:
        t0 = time.time()
        rows = asyncio.run(run_persona(p, fixed_jobs(p), sim))
        sub = [r for r in rows if r["submitted"]]
        ok = [r for r in sub if r.get("outcome") in ("replied", "interview", "hired")]
        out[p] = {"jobs": len(rows), "submitted": len(sub), "replied": len(ok),
                  "reply_rate": round(len(ok) / len(sub), 4) if sub else None,
                  "hire_rate": round(sum(r.get("outcome") == "hired" for r in sub) / len(sub), 4) if sub else None,
                  "seconds": round(time.time() - t0, 1)}
    allsub = sum(v["submitted"] for v in out.values())
    write("gigsim_outcomes.json", {"meta": meta(fixed_set=f"first {FIXED_N} gold-bid jobs per persona"), "by_persona": out,
                                   "reply_rate": round(sum(v["replied"] for v in out.values()) / allsub, 4) if allsub else None})


if __name__ == "__main__":
    main()
