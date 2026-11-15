# Signature extension: X4 Client research

**What it is.** Before deciding, a fourth parallel branch, the **Client Researcher** (`agent/nodes/analysis.py::researcher`),
builds a `ClientBrief` from the client's marketplace history and the category's market statistics, both through MCP
tools. It never scrapes. The brief contains:

* hard signals: payment verified, hire rate (hires / posts), average spend per hire, tenure, rating given;
* a tier (new / occasional / established / enterprise);
* where the job's budget sits against the market's p25–p75;
* up to three **talking points** the writer may use, for example "repeat hirer: give a clear milestone plan".
  With a model profile the points are written by the small model from the same facts only.

**Where it is used.**
1. Risk Assessor and Decision: client quality and budget position inform the decision and its explanation.
2. Pricing: if the client usually spends much more per hire than the market median, the price is not discounted.
3. Writer: the opening refers to the client's industry, and a milestone line is added for repeat hirers.
4. UI: the job detail page shows the brief next to the risk report.

**Public company information.** The assignment allows official APIs or search tools. The stand-in clients are
synthetic, so there is no real company to look up. The brief's `sources` field is where an official-search
tool's results would be cited.

**How it is measured** (`evals/runners/graph_eval.py`).
* Ablation: run with the researcher's talking points removed (`--tag no_x4` after setting
  `GIGBID_DISABLE_X4=1`) and compare the GigSim reply rate and the pricing-in-band rate.
* Safety: the brief must contain only facts from the tool results. A unit check compares every number in
  `signals` with the client record.

Status in this submission: the brief is implemented, used by four consumers and shown in the UI. The ablation run is
listed in the report's results as **pending**.
