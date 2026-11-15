"""Decision metrics only (bid/skip F1, scam precision/recall, price in band), by persona and job type.
Thin entry point over graph_eval so `make eval` names every metric family explicitly.

    python -m evals.runners.decision_eval
"""
import json

from evals.runners.common import RESULTS, write


def main() -> None:
    from agent.settings import profile_name
    src = RESULTS / f"graph_eval_{profile_name()}.json"
    if not src.exists():
        from evals.runners import graph_eval
        graph_eval.main()
    d = json.loads(src.read_text())
    keep = ("n_jobs", "bid_skip", "accuracy", "scam_detection", "price_in_fair_band", "n_priced")
    pick = lambda s: {k: s[k] for k in keep}  # noqa: E731
    write("decisions.json", {"meta": d["meta"], "overall": pick(d["overall"]),
                             "by_persona": {k: pick(v) for k, v in d["by_persona"].items()},
                             "by_job_type": {k: pick(v) for k, v in d["by_job_type"].items()}})


if __name__ == "__main__":
    from evals.runners.common import setup_env
    setup_env()
    main()
