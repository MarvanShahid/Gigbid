"""docs/FAILURES.md: failed dev jobs grouped into the report's taxonomy, with the fix tried and its measured effect.

    python scripts/make_failures.py
"""
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / "evals" / "results"

ANALYSIS = {
    "wrong_bid": ("Wrong bid", "Lowball posts whose budget clears one day at the floor but sits far below the market. "
                  "Remaining cases: partial-fit jobs where two weak matches lift fit just over 0.62."),
    "wrong_skip": ("Wrong skip (missed evidence)", "Requirements written only as paraphrases ('retrieval-augmented "
                   "generation', 'a managed vector database'). The offline hashed TF-IDF embedder cannot connect them to "
                   "named skills, so matches come out 'weak' and fit falls between watch and bid."),
    "mispriced": ("Mispriced", "The fair band depends on job complexity, which the post does not state; pricing anchors on "
                  "the category median and the client budget, so small and very large jobs land outside the band."),
    "missed_scam": ("Missed scam", "Scam wording outside the rule families."),
    "unsupported_claim": ("Unsupported claim", "A claim survived verification without support."),
    "injection": ("Injection", "Planted instruction changed the draft or the decision."),
    "tool_error": ("Tool error", "A tool call failed after retries."),
    "generic_opening": ("Generic opening", "Draft opened generically and got no reply."),
}
FIXES = {
    "wrong_bid": ("F-1: lowball rule, skip fixed budgets under 40% of the category's market p25 "
                  "(`decision.lowball_vs_market_p25`, uses the X4 researcher's market stats)"),
    "wrong_skip": ("F-2 (proposed, not run here): use the real open embedder `BAAI/bge-small-en-v1.5`, which could not be "
                   "downloaded on the build machine; expected to turn paraphrase matches from 'weak' into 'strong'."),
    "mispriced": ("F-3 (proposed): scale the target by the stated timeline (weeks), a proxy for complexity, before clamping "
                  "to the budget."),
}


def main() -> None:
    before = json.loads((R / "failures_rules_before_fix_F1.json").read_text())["failures"]
    after = json.loads((R / "failures_rules.json").read_text())["failures"]
    gb = json.loads((R / "graph_eval_rules_before_fix_F1.json").read_text())["overall"]
    ga = json.loads((R / "graph_eval_rules.json").read_text())["overall"]
    cb, ca = Counter(x["kind"] for x in before), Counter(x["kind"] for x in after)
    ex = defaultdict(list)
    for x in after:
        ex[x["kind"]].append(x)
    lines = ["# Failure analysis", "",
             "Failed dev jobs from the end-to-end run (`evals/results/failures_rules.json`), grouped into the report's taxonomy. "
             "Before/after counts compare the run before fix F-1 (`*_before_fix_F1.json`) with the final run.", "",
             "| Category | Before F-1 | After F-1 | Cause | Fix tried | Worked? |", "|---|---|---|---|---|---|"]
    for k in sorted(set(cb) | set(ca), key=lambda k: -cb.get(k, 0)):
        title, cause = ANALYSIS.get(k, (k, ""))
        fix = FIXES.get(k, "—")
        worked = ("yes" if ca.get(k, 0) < cb.get(k, 0) else "no") if k == "wrong_bid" else "not run"
        lines.append(f"| {title} | {cb.get(k, 0)} | {ca.get(k, 0)} | {cause} | {fix} | {worked} |")
    lines += ["", f"Effect of F-1 on the whole run: bid/skip F1 {gb['bid_skip']['f1']:.3f} → {ga['bid_skip']['f1']:.3f}, "
              f"precision {gb['bid_skip']['precision']:.3f} → {ga['bid_skip']['precision']:.3f}, "
              f"recall {gb['bid_skip']['recall']:.3f} → {ga['bid_skip']['recall']:.3f}.", "",
              "Not observed on this dev set: missed scams, unsupported claims after verification, successful injections, "
              "tool errors. That is partly because the stand-in's scam and injection patterns are a fixed family the rules "
              "were written against (see DATA_CARD).", "", "## Ten examples from the final run", ""]
    shown = 0
    for k in ("wrong_skip", "mispriced", "wrong_bid"):
        for x in ex.get(k, [])[:4]:
            if shown >= 10:
                break
            lines.append(f"* **{ANALYSIS[k][0]}**, `{x['job_id']}` ({x['persona']}, {x['job_kind']}): decision `{x['decision']}`, "
                         f"fit {x['fit']}, price {x['price']} vs band {x['fair_band']}; requirements {x['gold_requirements']}. "
                         f"Reason given: “{(x['reasons'] or [''])[0]}”")
            shown += 1
    (ROOT / "docs" / "FAILURES.md").write_text("\n".join(lines) + "\n")
    print("wrote docs/FAILURES.md")


if __name__ == "__main__":
    main()
