"""30-job smoke eval with failure thresholds (run on every pull request).

    python -m evals.runners.smoke_eval        # exit code 1 if a threshold is crossed
"""
import asyncio
import os
import sys

import yaml

from evals.runners.common import PERSONAS, ROOT, dev_set, meta, setup_env, start_sim, write


def main() -> int:
    os.environ["SIM_START_CONNECTS"] = "1000000"
    setup_env("rules")
    from evals.runners.graph_eval import clean_twin, run_persona, summarise
    th = yaml.safe_load((ROOT / "evals" / "thresholds.yaml").read_text())
    sim = start_sim()
    rows = []
    for p in PERSONAS:
        jobs = [j for j in dev_set(p) if "-dup" not in j["id"]][: th["smoke_jobs_per_persona"]]
        rows += asyncio.run(run_persona(p, jobs + [clean_twin(j) for j in jobs if j["_gold"]["injected"]], sim))
    s = summarise(rows)
    checks = {
        "bid_skip_f1": (s["bid_skip"]["f1"], s["bid_skip"]["f1"] >= th["min_bid_skip_f1"]),
        "scam_recall": (s["scam_detection"]["recall"], s["scam_detection"]["recall"] >= th["min_scam_recall"]
                        or s["scam_detection"]["tp"] + s["scam_detection"]["fn"] == 0),
        "unsupported_per_proposal": (s["unsupported_per_proposal_after"],
                                     (s["unsupported_per_proposal_after"] or 0) <= th["max_unsupported_claims_per_proposal"]),
        "injection_attack_success": (s["injection"]["attack_success_rate"],
                                     (s["injection"]["attack_success_rate"] or 0) <= th["max_injection_attack_success_rate"]),
        "price_in_fair_band": (s["price_in_fair_band"], (s["price_in_fair_band"] or 1) >= th["min_price_in_fair_band"]),
    }
    write("smoke.json", {"meta": meta(), "summary": s, "checks": {k: {"value": v, "pass": ok} for k, (v, ok) in checks.items()}})
    failed = [k for k, (_, ok) in checks.items() if not ok]
    print("FAILED: " + ", ".join(failed) if failed else "all smoke thresholds pass")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
