# Failure analysis

Failed dev jobs from the end-to-end run (`evals/results/failures_rules.json`), grouped into the report's taxonomy. Before/after counts compare the run before fix F-1 (`*_before_fix_F1.json`) with the final run.

| Category | Before F-1 | After F-1 | Cause | Fix tried | Worked? |
|---|---|---|---|---|---|
| Wrong bid | 33 | 8 | Lowball posts whose budget clears one day at the floor but sits far below the market. Remaining cases: partial-fit jobs where two weak matches lift fit just over 0.62. | F-1: lowball rule, skip fixed budgets under 40% of the category's market p25 (`decision.lowball_vs_market_p25`, uses the X4 researcher's market stats) | yes |
| Mispriced | 25 | 25 | The fair band depends on job complexity, which the post does not state; pricing anchors on the category median and the client budget, so small and very large jobs land outside the band. | F-3 (proposed): scale the target by the stated timeline (weeks), a proxy for complexity, before clamping to the budget. | not run |
| Wrong skip (missed evidence) | 15 | 15 | Requirements written only as paraphrases ('retrieval-augmented generation', 'a managed vector database'). The offline hashed TF-IDF embedder cannot connect them to named skills, so matches come out 'weak' and fit falls between watch and bid. | F-2 (proposed, not run here): use the real open embedder `BAAI/bge-small-en-v1.5`, which could not be downloaded on the build machine; expected to turn paraphrase matches from 'weak' into 'strong'. | not run |

Effect of F-1 on the whole run: bid/skip F1 0.906 → 0.953, precision 0.875 → 0.967, recall 0.939 → 0.939.

Not observed on this dev set: missed scams, unsupported claims after verification, successful injections, tool errors. That is partly because the stand-in's scam and injection patterns are a fixed family the rules were written against (see DATA_CARD).

## Ten examples from the final run

* **Wrong skip (missed evidence)**, `dev-ml-082` (ml_engineer, fit): decision `watch`, fit 0.588, price None vs band [1760, 2650]; requirements ['mlops', 'pytorch', 'docker', 'mlflow']. Reason given: “fit 0.59 is between watch (0.4) and bid (0.62)”
* **Wrong skip (missed evidence)**, `dev-ml-097` (ml_engineer, fit): decision `watch`, fit 0.5, price None vs band [1360, 2050]; requirements ['rag', 'pgvector']. Reason given: “fit 0.50 is between watch (0.4) and bid (0.62)”
* **Wrong skip (missed evidence)**, `dev-ml-113` (ml_engineer, fit): decision `watch`, fit 0.5, price None vs band [1360, 2050]; requirements ['rag', 'langchain']. Reason given: “fit 0.50 is between watch (0.4) and bid (0.62)”
* **Wrong skip (missed evidence)**, `dev-ml-122` (ml_engineer, fit): decision `watch`, fit 0.58, price None vs band [1360, 2050]; requirements ['fastapi', 'langgraph', 'pgvector', 'langchain', 'pinecone']. Reason given: “fit 0.58 is between watch (0.4) and bid (0.62)”
* **Mispriced**, `dev-ml-046` (ml_engineer, fit): decision `bid`, fit 1.0, price 2310.0 vs band [2370, 3560]; requirements ['transformers', 'langgraph', 'nlp']. Reason given: “fit 1.00 >= 0.62”
* **Mispriced**, `dev-ml-162` (ml_engineer, fit): decision `bid`, fit 0.725, price 2015.0 vs band [1290, 1930]; requirements ['docker', 'pytorch']. Reason given: “fit 0.72 >= 0.62”
* **Mispriced**, `dev-ml-196` (ml_engineer, fit): decision `bid`, fit 0.78, price 1910.0 vs band [1210, 1820]; requirements ['docker', 'computer_vision', 'fastapi', 'pytorch', 'mlops']. Reason given: “fit 0.78 >= 0.62”
* **Mispriced**, `dev-fu-011` (fullstack_dev, fit): decision `bid`, fit 0.817, price 1865.0 vs band [1980, 2970]; requirements ['nextjs', 'tailwind', 'typescript']. Reason given: “fit 0.82 >= 0.62”
* **Wrong bid**, `dev-ml-140` (ml_engineer, fit): decision `bid`, fit 0.69, price 2520.0 vs band [2370, 3560]; requirements ['pgvector', 'nlp', 'langchain', 'fastapi', 'rag']. Reason given: “fit 0.69 >= 0.62”
* **Wrong bid**, `dev-fu-083` (fullstack_dev, fit): decision `bid`, fit 0.725, price 1990.0 vs band [1290, 1930]; requirements ['auth', 'react_native', 'typescript', 'graphql']. Reason given: “fit 0.72 >= 0.62”
