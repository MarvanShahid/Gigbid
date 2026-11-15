"""Decision, Pricing, Writer, claim verification, Critic, Compliance Guard, preview,
human approval (interrupt) and the exactly-once submitter."""
from __future__ import annotations

import difflib
import hashlib
import re
from pathlib import Path

import yaml
from langgraph.types import Command, interrupt

from agent import llm
from agent.guardrails import delimit, detect_injection, neutralise
from agent.handoffs import BidDecision, ComplianceVerdict, Critique, CritiqueIssue, PriceQuote, ProposalDraft, Violation
from agent.marketplace_port import get_port
from agent.mcp_client import ToolCallError, ToolUnavailable, gateway
from agent.memory.promotion_rules import apply_style, outcome_notes, promote_style, style_rules
from agent.memory.store import store
from agent.nodes.analysis import job_text
from agent.nodes.common import halted, node, usage_update
from agent.prompts import prompt
from agent.settings import ROOT, config
from rag.text import detect_skills, sentences
from rag.verify import repair, verify

CITE = re.compile(r"\s*\[((?:[a-f0-9]{12})(?:\s*,\s*[a-f0-9]{12})*)\]")


def strip_citations(text: str) -> str:
    return re.sub(r"\s+([.,;!?])", r"\1", CITE.sub("", text)).strip()


def parse_citations(text: str) -> list[dict]:
    out = []
    for s in sentences(text):
        ids = [i.strip() for m in CITE.finditer(s) for i in m.group(1).split(",")]
        if ids:
            out.append({"sentence": strip_citations(s), "evidence_ids": ids})
    return out


# ------------------------------------------------------------------ decision
@node("decide")
async def decide(state: dict) -> dict:
    a, user = state["analyses"], state["user"]
    risk, fit, spec = a["risk"], a["fit"], a["spec"]
    d = config()["decision"]
    reasons: list[str] = []
    bid_min = d["bid_min_fit"]
    oc = store().get(("outcome", user["account"]), spec["category"])
    if oc and oc.value["n"] >= 5 and oc.value["reply_rate"] < 0.1:
        bid_min += 0.1
        reasons.append(f"raised fit bar: only {oc.value['reply_rate']:.0%} replies in {spec['category']} so far")
    budget = spec.get("budget_amount") or state["job"].get("budget", {}).get("amount", 0)
    min_budget = user.get("hourly_floor", 25) * 8 * 1.0
    if risk["is_scam"] or risk["score"] > d["max_risk_to_bid"]:
        action = "skip"
        reasons.append(f"risk {risk['level']} ({risk['score']:.2f}): " + ", ".join(
            f"{f['kind']}" for f in risk["flags"] if f["kind"] != "injection") or "client signals")
    elif budget and spec.get("budget_type") == "fixed" and budget < min_budget:
        action = "skip"
        reasons.append(f"budget ${budget:,.0f} is below one day at your floor (${min_budget:,.0f})")
    elif budget and spec.get("budget_type") == "fixed" and (a.get("market") or {}).get("p25") and \
            budget < d["lowball_vs_market_p25"] * a["market"]["p25"]:
        action = "skip"
        reasons.append(f"lowball: budget ${budget:,.0f} is under {d['lowball_vs_market_p25']:.0%} of the market p25 "
                       f"(${a['market']['p25']:,.0f}) for {spec['category']}")
    elif fit["score"] >= bid_min:
        action = "bid"
        reasons.append(f"fit {fit['score']:.2f} >= {bid_min:.2f}")
    elif fit["score"] >= d["watch_min_fit"]:
        action = "watch"
        reasons.append(f"fit {fit['score']:.2f} is between watch ({d['watch_min_fit']}) and bid ({bid_min:.2f})")
    else:
        action = "skip"
        reasons.append(f"fit {fit['score']:.2f} < {d['watch_min_fit']}; unsupported: "
                       + "; ".join(fit["unsupported_requirements"][:3]))
    if risk.get("injection_detected"):
        reasons.append("post contains instructions aimed at AI tools; they were removed and ignored")
    if action == "bid" and user.get("weekly_connects_budget") and \
            user.get("connects_spent_week", 0) >= user["weekly_connects_budget"]:
        action = "watch"
        reasons.append("weekly Connects budget used up")
    if state.get("force_bid") and action != "bid" and not risk["is_scam"]:
        action = "bid"
        reasons.append("user chose to draft anyway")
    auto = action == "skip" and user.get("autonomy") == "auto_skip"
    dec = BidDecision(action=action, reasons=reasons, auto=auto)
    return {"decision": dec.model_dump(), "status": {"skip": "skipped", "watch": "watch", "bid": "drafting"}[action]}


def route_decision(state: dict) -> str:
    if halted(state):
        return "finish"
    return "pricing" if state["decision"]["action"] == "bid" else "finish"


# ------------------------------------------------------------------ pricing
@node("pricing")
async def pricing(state: dict) -> dict:
    a, user, job = state["analyses"], state["user"], state["job"]
    spec, brief, fit = a["spec"], a.get("brief", {}), a["fit"]
    pc = config()["pricing"]
    port = get_port(user["account"])
    market = a.get("market")
    if market is None:
        try:
            market = await port.market_stats("pricing", spec["category"])
        except (ToolUnavailable, ToolCallError):
            market = None
    budget = spec.get("budget_amount") or job.get("budget", {}).get("amount", 0)
    floor = user.get("hourly_floor", 25)
    weeks = spec.get("timeline_weeks") or 4
    est_hours = max(8, min(160, weeks * 12))
    floor_price = floor * est_hours * 0.6
    rationale = []
    if market:
        target = market["median"]
        rationale.append(f"market median for {spec['category']} is ${market['median']:,.0f} "
                         f"(p25 ${market['p25']:,.0f}, p75 ${market['p75']:,.0f}, n={market['n']})")
    else:
        target = budget or floor_price
        rationale.append("no market statistics available; anchored on the client's budget")
    if budget:
        if spec.get("budget_type") == "fixed":
            target = min(max(target, budget * 0.9), budget * 1.05) if market and budget >= market["p25"] else budget
            rationale.append(f"client budget ${budget:,.0f} ({spec.get('budget_type')})")
    if brief.get("avg_spend_per_hire") and brief["avg_spend_per_hire"] > target * 1.5:
        rationale.append(f"client usually spends ${brief['avg_spend_per_hire']:,.0f} per hire; no need to discount")
    amount = max(target, floor_price if not budget else min(floor_price, budget))
    if amount == floor_price:
        rationale.append(f"raised to your floor: ${floor}/h x ~{est_hours:.0f}h x 0.6")
    amount = round(amount / 5) * 5
    try:
        cost = await port.connects_cost("pricing", job["id"])
        connects, pol = int(cost["connects"]), cost.get("policy_summary", "")
        if cost.get("policy_version", 1) > 1:
            rationale.append(f"policy v{cost['policy_version']}: {pol}")
    except (ToolUnavailable, ToolCallError):
        connects = int(job.get("connects_required", 0))
    oc = store().get(("outcome", user["account"]), spec["category"])
    p_reply = oc.value["reply_rate"] if oc else 0.25
    p_reply *= max(0.2, fit["score"])
    ev = p_reply * 0.35 * amount * 0.1    # reply -> hire ~35%; value of a hire counted at 10% of price (margin proxy)
    cusd = connects * pc["connect_usd_value"]
    worth = cusd == 0 or ev / cusd >= pc["min_expected_value_ratio"]
    rationale.append(f"{connects} Connects (${cusd:.2f}) vs expected value ${ev:.2f}: "
                     + ("worth it" if worth else "not worth it"))
    q = PriceQuote(amount=amount, rationale=rationale, market_p25=market and market["p25"],
                   market_median=market and market["median"], market_p75=market and market["p75"],
                   connects_cost=connects, connects_usd=round(cusd, 2), expected_value_usd=round(ev, 2), worth_it=worth)
    return {"price": q.model_dump()}


def route_pricing(state: dict) -> str:
    if halted(state):
        return "finish"
    if state["price"]["worth_it"] or state.get("force_bid"):
        return "writer"
    return "finish"


# ------------------------------------------------------------------ writer
TYPE_PREF = {"case_study": 0, "review": 1, "readme": 2, "code": 3, "cv": 4}


def _sents(ev: dict) -> list[str]:
    text = re.sub(r"\*\*[^*]+\*\*[^\n]*", " ", ev["text"])          # drop "**Year:** ..." metadata lines
    text = re.sub(r"(?m)^#+\s.*$|^##\s*\w+\s*$", " ", text)
    text = re.sub(r"^.*?\.\s(?=Problem|What I built|Result)", "", text) if ev["type"] == "case_study" else text
    text = re.sub(r"\b(Problem|What I built|Result)\b\s*", "", text)
    return [x.strip() for x in sentences(text.replace("\n", " ")) if len(x.split()) >= 5]


def _project_name(ev: dict) -> str:
    if ev["type"] == "case_study" and ev.get("title"):
        return f"the {ev['title'].lower()} project"
    return f"the {ev.get('project') or 'portfolio'} repo" if ev["type"] in ("code", "readme") else "a past project"


def evidence_claim(ev: dict, skills: list[str]) -> str | None:
    """One sentence, built from the evidence's own wording, that a verifier can match back to it."""
    from rag.text import lexicon

    def as_written(skill: str) -> str | None:   # use the evidence's own spelling ("MLOps", not "mlops")
        hits = [m.group(0) for a in lexicon().get(skill, [])
                for m in re.finditer(rf"(?<![\w.]){re.escape(a)}(?![\w]|\.\w)", ev["text"], re.I)]
        return max(hits, key=lambda h: sum(c.isupper() for c in h)) if hits else None
    names = [as_written(s) or lexicon()[s][0] for s in skills if s in lexicon()]
    if ev["type"] == "code":
        named = [as_written(s) for s in skills if s in lexicon() and as_written(s)] or names[:1]
        named = [n for n in named if not n.islower() or len(n) <= 4] or named
        return f"The code in {_project_name(ev)} uses {' and '.join(named)}." if named else None
    if ev["type"] == "readme":
        st = re.search(r"Stack:\s*([^\n]+)", ev["text"])
        return f"{_project_name(ev).capitalize()} is built with {st.group(1).strip().rstrip('.')}." if st else None
    ss = _sents(ev)
    skill_s = [x for x in ss if set(detect_skills(x)) & set(skills)]
    if ev["type"] == "review":
        if not skill_s:
            return None
        quote = re.sub(r"^Client review \([\d.]+/5\):\s*", "", " ".join(ss[:2]))
        return f"A client review of that work says: \"{quote.rstrip('.')}.\""
    pick = (skill_s or ss or [None])[0]
    if not pick:
        return None
    pick = re.sub(r"^(I|The system|The client)\b", lambda m: m.group(1) if m.group(1) == "I" else m.group(1).lower(), pick)
    return f"On {_project_name(ev)}, {pick[0].lower() + pick[1:] if not pick.startswith('I ') else pick}"


def result_claim(ev: dict) -> str | None:
    if ev["type"] != "case_study":
        return None
    for x in _sents(ev):
        if re.search(r"\d", x) and re.search(r"(?i)\b(cut|reduced|raised|improved|handled|saved)\b", x):
            return f"There, {x[0].lower() + x[1:]}"
    return None


def write_rules(state: dict, revision: list[str]) -> ProposalDraft:
    a, price = state["analyses"], state["price"]
    spec, fit, brief = a["spec"], a["fit"], a.get("brief", {})
    ev_by_id = {e["id"]: e for e in state.get("evidence", [])}
    reqs = a.get("requirements") or spec.get("requirements", [])
    strong = [m for m in fit["matrix"] if m["strength"] != "none" and m["evidence_ids"]]
    deliverable = (spec.get("deliverables") or [spec.get("title", "this project")])[0]
    art = "an" if deliverable[:1].lower() in "aeiou" else "a"
    industry = brief.get("industry")
    focus = [m["requirement"] for m in fit["matrix"]][:2]
    ind = f" for {'an' if (industry or 'x')[:1].lower() in 'aeiou' else 'a'} {industry} team" if industry else ""
    opening = (f"You are building {art} {deliverable}{ind}, and the work "
               f"depends on getting {' and '.join(focus) or 'the core features'} right.")
    body, used, results = [], set(), 0
    short = "shorter" in revision or any(r.startswith("length") for r in revision)
    for m in strong[: (2 if short else 3)]:
        sk = next((r.get("skills", []) for r in reqs if r.get("text") == m["requirement"]), None) or detect_skills(m["requirement"])
        cands = sorted([ev_by_id[i] for i in m["evidence_ids"] if i in ev_by_id and i not in used],
                       key=lambda e: TYPE_PREF.get(e["type"], 9))
        for ev in cands:
            c = evidence_claim(ev, sk)
            if c:
                used.add(ev["id"])
                body.append(f"{c.rstrip('.')} [{ev['id']}].")
                rc = result_claim(ev) if results == 0 else None
                if rc:
                    results += 1
                    body.append(f"{rc.rstrip('.')} [{ev['id']}].")
                break
    weeks = max(1, int(round((spec.get("timeline_weeks") or 4) / 3)))
    plan = (f"I would start with a short call to confirm scope, then deliver a first working milestone within "
            f"{weeks} week{'s' if weeks > 1 else ''}.")
    gaps = [m["requirement"] for m in fit["matrix"] if m["strength"] == "none"][:1]
    if gaps:
        plan += f" For {gaps[0]}, I would agree the approach with you before committing to it."
    if any("milestone" in t for t in brief.get("talking_points") or []):
        plan += " You will get the milestone plan in writing before we start."
    price_line = f"My bid is ${price['amount']:,.0f} for the scope described."
    letter = " ".join([opening, *body, plan, price_line])
    answers = []
    for q in spec.get("screening_questions", []):
        sk = detect_skills(q)
        ans = None
        for ev in sorted(ev_by_id.values(), key=lambda e: TYPE_PREF.get(e["type"], 9)):
            if sk and set(sk) <= set(detect_skills(ev["text"] + " " + (ev.get("title") or ""))):
                c = evidence_claim(ev, sk)
                if c:
                    ans = f"Yes. {c.rstrip('.')} [{ev['id']}]."
                    break
        if ans is None:
            ans = ("I can start this week and give it about 25 hours a week until the first milestone."
                   if re.search(r"(?i)availab|start|hours", q) else
                   "I have not done exactly this for a client yet, so I would confirm the approach with you on our first call.")
        answers.append(ans)
    letter = apply_style(letter, state["user"]["account"])
    return ProposalDraft(cover_letter=letter, answers=answers, citations=parse_citations(letter),
                         version=(state.get("critic_round") or 0) + 1, source="rules")


@node("writer", timeout=120)
async def writer(state: dict) -> dict:
    user = state["user"]
    rnd = state.get("critic_round", 0)
    last = state["critiques"][-1] if state.get("critiques") else None
    revision = [i["kind"] + ": " + i["detail"] for i in last["issues"]] if last and not last["passed"] else []
    usage = None
    try:
        a = state["analyses"]
        ev = state.get("evidence", [])
        matrix = "\n".join(f"- {m['requirement']} -> {m['strength']} {m['evidence_ids']}" for m in a["fit"]["matrix"])
        evidence = "\n".join(f"{e['id']}: ({e['type']}, {e.get('title')}) {e['text'][:500]}" for e in ev[:10])
        rev = ("\nRevise the previous draft. Fix these issues:\n- " + "\n- ".join(revision)
               + "\nPrevious draft:\n" + state["draft"]["cover_letter"]) if revision else ""
        draft, usage = llm.call("writer", "Write the proposal as a ProposalDraft.", prompt(
            "writer", max_words=config()["writer"]["max_words"], style=style_rules(user["account"]) or "none yet",
            outcomes=outcome_notes(user["account"], a["spec"]["category"]), brief=a.get("brief", {}).get("talking_points"),
            price=state["price"]["amount"], matrix=matrix, evidence=evidence,
            job=delimit("job_post", neutralise(job_text(state["job"]))[0]), revision=rev), ProposalDraft)
        draft.source, draft.version = "llm", rnd + 1
        draft.cover_letter = apply_style(draft.cover_letter, user["account"])
        draft.citations = parse_citations(draft.cover_letter)
        qs = a["spec"].get("screening_questions", [])
        if len(draft.answers) < len(qs):
            draft.answers += write_rules(state, revision).answers[len(draft.answers):]
    except llm.NoModel:
        draft = write_rules(state, revision)
    return {"draft": draft.model_dump(), **usage_update(usage)}


# ------------------------------------------------------------------ claim verification
def _recite(fixed: str, original: str) -> str:
    """Put the original citation markers back on the sentences that survived repair."""
    cite_map = {c["sentence"]: c["evidence_ids"] for c in parse_citations(original)}
    out = []
    for s in sentences(fixed):
        ids = cite_map.get(s) or next((v for k, v in cite_map.items()
                                       if difflib.SequenceMatcher(None, k, s).ratio() > .8), None)
        out.append(s[:-1] + f" [{', '.join(ids)}]." if ids and s.endswith(".") else s)
    return " ".join(out)


def _llm_judge(claim: str, evidence: str) -> str | None:
    try:
        out, _ = llm.call("verifier", "Answer with one word.", prompt("verifier", claim=claim, evidence=evidence[:1200]))
        w = str(out).strip().lower().split()[0].strip(".,")
        return w if w in ("supported", "partial", "unsupported") else None
    except Exception:  # noqa: BLE001
        return None


@node("verifier")
async def verifier(state: dict) -> dict:
    draft = dict(state["draft"])
    ev = state.get("evidence", [])
    judge = _llm_judge if llm.has_model("verifier") else None
    plain = strip_citations(draft["cover_letter"])
    before = verify(plain, ev, judge)
    fixed, changes = repair(plain, before)
    answers, ans_before, ans_changes = [], [], []
    for ans in draft.get("answers", []):
        v = verify(strip_citations(ans), ev, judge)
        ans_before += v
        new, ch = repair(strip_citations(ans), v)
        ans_changes += ch
        answers.append(_recite(new, ans) or "I would confirm this with you in our first call.")
    after = verify(fixed, ev, judge) + [x for a in answers for x in verify(strip_citations(a), ev, judge)]
    draft["cover_letter"] = _recite(fixed, draft["cover_letter"])
    draft["answers"] = answers
    draft["citations"] = parse_citations(draft["cover_letter"])
    allb = before + ans_before
    rep = {"claims": [v.to_dict() for v in allb], "claims_before": len(allb),
           "unsupported_before": sum(v.label == "unsupported" for v in allb), "claims_after": len(after),
           "unsupported_after": sum(v.label == "unsupported" for v in after), "changes": changes + ans_changes,
           "claims_after_detail": [v.to_dict() for v in after]}
    return {"draft": draft, "verification": rep}


# ------------------------------------------------------------------ critic
GENERIC_OPEN = re.compile(r"(?i)^(dear|hello|hi|greetings|i am|i'm|my name|i have read|i hope)|passionate|perfect fit")


def critique_rules(state: dict) -> Critique:
    draft, a = state["draft"], state["analyses"]
    text = strip_citations(draft["cover_letter"])
    issues: list[CritiqueIssue] = []
    maxw = config()["writer"]["max_words"]
    if len(text.split()) > maxw:
        issues.append(CritiqueIssue(kind="length", detail=f"{len(text.split())} words, limit {maxw}"))
    first = (sentences(text) or [""])[0]
    if GENERIC_OPEN.search(first):
        issues.append(CritiqueIssue(kind="generic_opening", detail=f"opening is generic: '{first[:80]}'"))
    ver = state.get("verification") or {}
    if ver.get("unsupported_after", 0) > 0:
        issues.append(CritiqueIssue(kind="grounding", detail=f"{ver['unsupported_after']} unsupported claims remain"))
    if not draft.get("citations"):
        issues.append(CritiqueIssue(kind="grounding", detail="no claim cites portfolio evidence"))
    covered = [m for m in a["fit"]["matrix"] if m["strength"] == "strong"]
    low = text.lower()
    for m in covered:
        sk = detect_skills(m["requirement"])
        names = [s.replace("_", " ") for s in sk]
        if sk and not any(n.split()[0] in low for n in names) and not any(i in draft["cover_letter"] for i in m["evidence_ids"]):
            issues.append(CritiqueIssue(kind="missing_requirement", detail=f"supported requirement not addressed: {m['requirement']}"))
    qs = a["spec"].get("screening_questions", [])
    if len([x for x in draft.get("answers", []) if x.strip()]) < len(qs):
        issues.append(CritiqueIssue(kind="screening", detail="not every screening question is answered"))
    grounding = any(i.kind == "grounding" for i in issues)
    passed = not grounding and len(issues) <= 1
    score = max(0.0, 10 - 2.5 * len(issues) - (3 if grounding else 0))
    return Critique(passed=passed, round=state.get("critic_round", 0) + 1, issues=issues, score=score)


@node("critic")
async def critic(state: dict) -> dict:
    crit = critique_rules(state)
    usage = None
    if llm.has_model("critic"):
        try:
            a = state["analyses"]
            c2, usage = llm.call("critic", "Return a Critique.", prompt(
                "critic", max_words=config()["writer"]["max_words"],
                job=delimit("job_post", neutralise(job_text(state["job"]))[0]),
                covered=[m["requirement"] for m in a["fit"]["matrix"] if m["strength"] != "none"],
                evidence_ids=[e["id"] for e in state.get("evidence", [])], draft=state["draft"]["cover_letter"],
                answers=state["draft"].get("answers")), Critique)
            seen = {(i.kind, i.detail) for i in crit.issues}
            crit.issues += [i for i in c2.issues if (i.kind, i.detail) not in seen][:3]
            crit.passed = crit.passed and c2.passed
            crit.score = round((crit.score + c2.score) / 2, 2)
        except Exception:  # noqa: BLE001
            pass
    return {"critiques": [crit.model_dump()], "critic_round": crit.round}


def route_critic(state: dict) -> str:
    if halted(state) or not state.get("critiques"):
        return "compliance"
    last = state["critiques"][-1]
    if last["passed"] or state.get("critic_round", 0) >= config()["writer"]["max_critic_rounds"]:
        return "compliance"
    return "writer"


# ------------------------------------------------------------------ compliance
def rules() -> list[dict]:
    path = ROOT / config()["policy"]["rules_file"]
    return yaml.safe_load(Path(path).read_text())["rules"]


def check_text(text: str) -> tuple[str, list[Violation], bool]:
    """Returns cleaned text, violations, and whether a block-level problem remains after cleaning."""
    viols, cleaned, blocked = [], text, False
    for r in rules():
        for pat in r["patterns"]:
            for m in re.finditer(pat, cleaned):
                viols.append(Violation(rule=r["id"], severity=r["severity"], match=m.group(0)[:80]))
            if re.search(pat, cleaned):
                if r["severity"] == "fix":
                    cleaned = re.sub(r"(?i)\b(i |we )?(can |will )?guarantee(d|s)?\b,?\s*", "", cleaned)
                    cleaned = re.sub(pat, "", cleaned)
                else:
                    keep = [s for s in sentences(cleaned) if not re.search(pat, s)]
                    if r["id"] == "no_bot_disclosure_tricks":
                        blocked = True
                    cleaned = " ".join(keep)
    if detect_injection(cleaned):
        blocked = True
        viols.append(Violation(rule="injection_echo", severity="block", match=detect_injection(cleaned)[0][:80]))
    return re.sub(r"\s{2,}", " ", cleaned).strip(), viols, blocked


@node("compliance")
async def compliance(state: dict) -> dict:
    draft = state["draft"]
    text, viols, blocked = check_text(draft["cover_letter"])
    answers = []
    for a in draft.get("answers", []):
        t, v, b = check_text(a)
        answers.append(t)
        viols += v
        blocked = blocked or b
    reason = ""
    if blocked:
        reason = "draft repeated an instruction injected into the job post"
    qs = state["analyses"]["spec"].get("screening_questions", [])
    if config()["policy"].get("require_all_screening_answers") and len([a for a in answers if a.strip()]) < len(qs):
        blocked, reason = True, "policy v2: every screening question must be answered"
    if len(strip_citations(text).split()) < 25:
        blocked, reason = True, reason or "too little text left after removing policy violations"
    status = "blocked" if blocked else ("fixed" if viols else "pass")
    v = ComplianceVerdict(status=status, violations=viols, cleaned_text=text, cleaned_answers=answers, reason=reason)
    upd = {"compliance": v.model_dump()}
    if status != "blocked":
        upd["draft"] = {**draft, "cover_letter": text, "answers": answers}
    else:
        upd["status"] = "blocked"
    return upd


def route_compliance(state: dict) -> str:
    if halted(state) or not state.get("compliance"):
        return "finish"
    return "finish" if state["compliance"]["status"] == "blocked" else "preview"


# ------------------------------------------------------------------ preview + approval + submit
def idem_key(state: dict, draft_id: str) -> str:
    return hashlib.sha256(f"{state['user']['account']}|{state['job_id']}|{draft_id}".encode()).hexdigest()[:32]


@node("preview")
async def preview(state: dict) -> dict:
    user, draft = state["user"], state["draft"]
    port = get_port(user["account"])
    letter = strip_citations(draft["cover_letter"])
    d = await port.create_draft("submitter", state["job_id"], letter, float(state["price"]["amount"]), draft.get("answers", []))
    dry = await port.submit("submitter", d["draft_id"], idem_key(state, d["draft_id"]), None, True)
    return {"preview": {"draft_id": d["draft_id"], **dry["preview"], "marketplace": port.name}, "status": "awaiting_approval"}


def evidence_for_ui(state: dict, extra: int = 8) -> list[dict]:
    """Every evidence item the draft cites (so each claim can show its proof), then the top-ranked others."""
    draft = state.get("draft") or {}
    text = draft.get("cover_letter", "") + " " + " ".join(draft.get("answers", []))
    cited = {i.strip() for m in CITE.finditer(text) for i in m.group(1).split(",")}
    ev = state.get("evidence", [])
    return [e for e in ev if e["id"] in cited] + [e for e in ev if e["id"] not in cited][:extra]


@node("approval", timeout=-1)
async def approval(state: dict) -> Command:
    a = state["analyses"]
    payload = {
        "kind": "proposal", "job_id": state["job_id"], "title": state["job"].get("title"),
        "draft": state["draft"], "evidence": evidence_for_ui(state), "risk": a["risk"], "fit": a["fit"],
        "brief": a.get("brief"), "price": state["price"], "preview": state["preview"],
        "verification": {k: v for k, v in (state.get("verification") or {}).items() if k != "claims"},
        "critiques": state.get("critiques", []), "compliance": state.get("compliance"),
    }
    decision = interrupt(payload)   # pauses here; the web UI resumes with the user's decision
    action = decision.get("action")
    log = {"action": action, "reason": decision.get("reason"), "by": decision.get("user")}
    if action == "approve":
        return Command(goto="submit", update={"approval": {"action": "approve", "grant": decision["grant"],
                                                            "draft_id": state["preview"]["draft_id"]},
                                               "approvals_log": [log], "status": "approved"})
    if action in ("edit", "regenerate"):
        before = strip_citations(state["draft"]["cover_letter"])
        after = decision["text"]
        # only the user's own edits teach style memory; a regenerated paragraph does not
        promoted = promote_style(state["user"]["account"], state["job_id"], before, strip_citations(after)) \
            if action == "edit" else []
        log["diff"] = "\n".join(difflib.unified_diff(before.split(". "), strip_citations(after).split(". "), lineterm="", n=0))
        log["promoted"] = promoted
        new_draft = {**state["draft"], "cover_letter": after, "answers": decision.get("answers") or state["draft"]["answers"],
                     "version": state["draft"].get("version", 1) + 1, "source": "user_edit",
                     "citations": parse_citations(after)}
        return Command(goto="compliance", update={"draft": new_draft, "approvals_log": [log], "status": "edited"})
    return Command(goto="finish", update={"approval": {"action": "reject", "reason": decision.get("reason", "")},
                                          "approvals_log": [log], "status": "rejected"})


@node("submit")
async def submit(state: dict) -> dict:
    user, ap = state["user"], state["approval"]
    port = get_port(user["account"])
    res = await port.submit("submitter", ap["draft_id"], idem_key(state, ap["draft_id"]), ap["grant"], False)
    return {"submission": res, "status": "submitted"}


@node("finish")
async def finish(state: dict) -> dict:
    return {}


@node("needs_attention")
async def needs_attention(state: dict) -> dict:
    return {"status": "needs_attention"}


# exported so the conversation graph can reuse the guard
__all__ = ["decide", "pricing", "writer", "verifier", "critic", "compliance", "preview", "approval", "submit",
           "finish", "needs_attention", "check_text", "gateway"]
