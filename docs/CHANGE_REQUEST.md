# Change request: 2 Nov 2026 platform policy update

**What changed** (stand-in GigSim, `POST /admin/policy/2`):
1. Jobs with a budget of $2,000 or more cost **1.5×** the Connects.
2. A proposal that leaves any screening question unanswered is **rejected** by the platform.

**What I had to edit**

| File | Change | Lines (approx.) |
|---|---|---|
| `agent/config.yaml` | `policy.require_all_screening_answers`, `large_budget_threshold`, `large_budget_connects_multiplier` | 4 |
| `agent/nodes/proposal.py::compliance` | block a draft whose answers do not cover every question (reads the config flag) | 3 |
| `mcp_servers/marketplace/server.py::submit_proposal` | refuse before spending Connects when policy v2 requires answers | 5 |

Pricing needed **no change**. The Connects cost always comes from the marketplace tool `get_connects_cost`, which reads
the policy in force, and the price rationale shows "policy v2: …" automatically. The Writer already answered every
screening question; the new rule only turns a soft Critic issue into a hard block.

Test: `tests/integration/test_conversation_and_degraded.py::test_change_request_policy_v2`.

**What it says about the design:** rules and costs that come from the platform belong behind a tool, and the rules we
enforce ourselves belong in config. The only code change was a new kind of check, not a new number.
