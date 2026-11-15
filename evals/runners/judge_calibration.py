"""Calibrate the LLM judge against Marvan's own labels (B4).

Step 1 (no key needed):  python -m evals.runners.judge_calibration --export
    writes evals/datasets/judge_labels.csv with 30 anonymised proposals and an empty `human_score` column.
Step 2 (human):           fill `human_score` (1-5) using the rubric in docs/RESULTS.md.
Step 3 (needs a model):   GROQ_API_KEY=... python -m evals.runners.judge_calibration --score
    asks the judge (critic model) for a 1-5 rubric score per proposal and reports Cohen's kappa (quadratic weights).
"""
from __future__ import annotations

import argparse
import csv
import json

from evals.runners.common import ROOT, meta, setup_env, write

LABELS = ROOT / "evals" / "datasets" / "judge_labels.csv"
RUBRIC = ("Score 1-5. 5 = specific to the client's problem in the first sentence, every experience claim is backed by "
          "the cited evidence, covers the must-have requirements, under 210 words, no fluff or guarantees. "
          "3 = adequate but generic in places or misses a requirement. 1 = generic, unsupported or non-compliant.")


def quadratic_kappa(a: list[int], b: list[int], k: int = 5) -> float:
    import numpy as np
    O = np.zeros((k, k))
    for x, y in zip(a, b):
        O[x - 1, y - 1] += 1
    W = np.array([[(i - j) ** 2 / (k - 1) ** 2 for j in range(k)] for i in range(k)])
    ha, hb = O.sum(1), O.sum(0)
    E = np.outer(ha, hb) / O.sum()
    return float(1 - (W * O).sum() / (W * E).sum()) if (W * E).sum() else 1.0


def export() -> None:
    import random
    rng = random.Random(800)
    src = ROOT / "evals" / "results" / "proposal_samples.json"
    samples = json.loads(src.read_text())["samples"] if src.exists() else []
    rng.shuffle(samples)
    with open(LABELS, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["item", "job_excerpt", "proposal", "human_score"])
        for i, s in enumerate(samples[:30]):
            w.writerow([f"p{i:02d}", s["job"][:400], s["proposal"], ""])
    print(f"wrote {LABELS} ({min(30, len(samples))} items); fill human_score 1-5")


def score() -> None:
    setup_env("open")
    from pydantic import BaseModel, Field

    from agent import llm

    class Judgement(BaseModel):
        score: int = Field(ge=1, le=5)
        reason: str
    rows = list(csv.DictReader(open(LABELS)))
    labelled = [r for r in rows if r["human_score"].strip()]
    if len(labelled) < 30 or not llm.has_model("critic"):
        write("judge_calibration.json", {"meta": meta(), "status": "pending",
                                          "reason": f"{len(labelled)}/30 human labels; model available: {llm.has_model('critic')}"})
        return
    human, judge = [], []
    for r in labelled:
        j, _ = llm.call("critic", "You are a strict proposal judge.", f"{RUBRIC}\n\nJob:\n{r['job_excerpt']}\n\nProposal:\n{r['proposal']}",
                        Judgement)
        human.append(int(r["human_score"]))
        judge.append(j.score)
    k = quadratic_kappa(human, judge)
    dis = [{"item": r["item"], "human": h, "judge": j} for r, h, j in zip(labelled, human, judge) if abs(h - j) >= 2]
    write("judge_calibration.json", {"meta": meta(), "status": "done", "n": len(human), "kappa_quadratic": round(k, 3),
                                      "pairs": list(zip(human, judge)), "large_disagreements": dis})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--score", action="store_true")
    a = ap.parse_args()
    export() if a.export else score()
