"""Parallel analysis branches: Job Analyst, Risk Assessor, Client Researcher (X4), Fit Matcher.
Each writes only its own key inside `analyses` (merged by the merge_dicts reducer)."""
from __future__ import annotations

import os
import re

from agent import llm
from agent.guardrails import delimit, detect_injection, neutralise
from agent.handoffs import ClientBrief, FitReport, JobSpec, Requirement, RequirementMatch, RiskFlag, RiskReport
from agent.marketplace_port import get_port
from agent.mcp_client import ToolCallError, ToolUnavailable, gateway
from agent.nodes.common import merge_usage, node, usage_update
from agent.prompts import prompt
from rag.text import detect_skills, lexicon
from rag.variants.base import extract_requirements


def job_text(job: dict) -> str:
    q = "\n".join(f"- {x}" for x in job.get("screening_questions", []))
    return (f"Title: {job.get('title', '')}\n{job.get('description', '')}\n"
            + (f"Screening questions:\n{q}\n" if q else ""))


# ------------------------------------------------------------------ Job Analyst
def analyse_rules(job: dict) -> JobSpec:
    clean, _ = neutralise(job.get("description", ""))
    reqs = []
    for r in extract_requirements(clean):
        if "[removed" in r:
            continue
        must = not re.search(r"(?i)nice to have|bonus|a plus|preferred", r)
        reqs.append(Requirement(text=re.sub(r"(?i)^(strong )?experience with\s+", "", r).strip(), skills=detect_skills(r),
                                must_have=must))
    text = clean.lower()
    hourly = bool(re.search(r"/\s?h(ou)?r|per hour|hourly", text))
    amt = re.search(r"\$\s?([\d,]+)", clean)
    weeks = re.search(r"(\d+(?:\.\d+)?)\s*weeks?", text)
    build = re.search(r"(?i)build an? ([\w\s-]{3,60}?)(?: for | to | that |\.|$)", clean, re.M)
    hidden = []
    if re.search(r"startup|mvp|launch", text):
        hidden.append("needs a fast first version; scope must stay small")
    if re.search(r"ongoing|long[- ]term|maintain", text):
        hidden.append("likely wants ongoing maintenance after delivery")
    if re.search(r"our (\w+ )?team", text):
        hidden.append("will hand over to or work alongside an in-house team")
    return JobSpec(job_id=job["id"], title=job.get("title", ""), category=job.get("category", "unknown"),
                   summary=f"Client wants {build.group(1).strip() if build else job.get('title', 'a project')}.",
                   deliverables=[build.group(1).strip()] if build else [], requirements=reqs,
                   budget_amount=float(amt.group(1).replace(",", "")) if amt else float(job.get("budget", {}).get("amount", 0)),
                   budget_type="hourly" if hourly else "fixed", timeline_weeks=float(weeks.group(1)) if weeks else None,
                   screening_questions=list(job.get("screening_questions", [])), hidden_needs=hidden[:3], source="rules")


@node("analyst")
async def analyst(state: dict) -> dict:
    job = state["job"]
    usage = None
    try:
        clean, _ = neutralise(job_text(job))
        spec, usage = llm.call("analyst", "Extract the JobSpec.", prompt(
            "analyst", skill_ids=", ".join(lexicon()), job_id=job["id"], category=job.get("category"),
            job=delimit("job_post", clean)), JobSpec)
        spec.job_id, spec.source = job["id"], "llm"
        spec.screening_questions = list(job.get("screening_questions", []))
        if not spec.budget_amount:
            spec.budget_amount = float(job.get("budget", {}).get("amount", 0))
        for r in spec.requirements:   # ground skill ids in the lexicon
            r.skills = [s for s in r.skills if s in lexicon()] or detect_skills(r.text)
    except llm.NoModel:
        spec = analyse_rules(job)
    except Exception as e:  # noqa: BLE001  model failure -> deterministic fallback, recorded
        spec = analyse_rules(job)
        spec.hidden_needs.append(f"(analyst fell back to rules: {type(e).__name__})")
    return {"analyses": {"spec": spec.model_dump()}, **usage_update(usage)}


# ------------------------------------------------------------------ Risk Assessor
RISK_RULES: list[tuple[str, str, float]] = [
    ("free_work", r"(?i)(complete|do|build) (a |the )?(full |free |unpaid )?(sample|test) (project|task|work)? ?(for free|before|unpaid|so we can)", 0.8),
    ("free_work", r"(?i)\bfor free\b|\bunpaid (test|trial)\b", 0.7),
    ("off_platform", r"(?i)\b(telegram|whatsapp|skype|signal|wechat)\b", 0.75),
    ("off_platform", r"(?i)(outside|off) (the |this )?platform|do not use this platform|avoid (platform )?fees", 0.8),
    ("off_platform", r"[\w.+-]+@[\w-]+\.[\w.]+", 0.5),
    ("scam", r"(?i)\b(usdt|bitcoin|crypto(currency)?|western union|gift cards?)\b", 0.8),
    ("scam", r"(?i)(buy|purchase|pay for) (our|the) (starter|training|kit|course|license)", 0.9),
    ("scam", r"(?i)\brefundable after\b|\bregistration fee\b", 0.85),
    ("scam", r"(?i)bank (details|account)|send your (id|passport|cnic)", 0.85),
]


def assess_rules(job: dict, client: dict | None) -> RiskReport:
    text = job.get("description", "") + " " + job.get("title", "")
    flags: list[RiskFlag] = []
    for kind, pat, w in RISK_RULES:
        m = re.search(pat, text)
        if m and not any(f.kind == kind and f.evidence == m.group(0) for f in flags):
            flags.append(RiskFlag(kind=kind, evidence=m.group(0)[:120], weight=w))
    inj = detect_injection(text)
    if inj:
        flags.append(RiskFlag(kind="injection", evidence=inj[0][:120], weight=0.2))
    quality = 0.5
    if client:
        if not client.get("payment_verified"):
            flags.append(RiskFlag(kind="unverified_payment", evidence="payment method not verified", weight=0.35))
        hires, posted = client.get("hires", 0), client.get("jobs_posted", 0)
        if hires == 0 and posted >= 3:
            flags.append(RiskFlag(kind="no_hires", evidence=f"{posted} jobs posted, 0 hires", weight=0.3))
        rating = client.get("avg_rating_given") or 0
        quality = min(1.0, 0.25 * bool(client.get("payment_verified")) + 0.35 * min(1, hires / 10)
                      + 0.2 * min(1, client.get("total_spend", 0) / 20000) + 0.2 * (rating / 5 if rating else 0.5))
    score = 1.0
    for f in flags:
        score *= (1 - f.weight)
    score = round(1 - score, 3)
    hard = any(f.kind in ("scam", "free_work", "off_platform") and f.weight >= 0.7 for f in flags)
    is_scam = hard or score >= 0.75
    level = "high" if is_scam or score >= 0.6 else "medium" if score >= 0.3 else "low"
    return RiskReport(score=score, level=level, is_scam=is_scam, injection_detected=bool(inj),
                      client_quality=round(quality, 3), flags=flags)


@node("risk")
async def risk(state: dict) -> dict:
    job, user = state["job"], state["user"]
    port = get_port(user["account"])
    try:
        client = await port.get_client_history("risk", job["client_id"])
    except (ToolUnavailable, ToolCallError):
        client = None
    rep = assess_rules(job, client)
    usage = None
    if llm.has_model("risk"):
        try:
            extra, usage = llm.call("risk", "Return a RiskReport.", prompt(
                "risk", rule_flags=[f.model_dump() for f in rep.flags], client=client,
                job=delimit("job_post", neutralise(job_text(job))[0])), RiskReport)
            known = {(f.kind) for f in rep.flags}
            new = [f for f in extra.flags if f.kind not in known and f.kind != "injection"]
            if new:
                rep.flags += new
                p = 1 - rep.score
                for f in new:
                    p *= (1 - f.weight * 0.7)   # model-only flags count less than rule hits
                rep.score = round(1 - p, 3)
                rep.is_scam = rep.is_scam or extra.is_scam and rep.score >= 0.6
                rep.level = "high" if rep.is_scam or rep.score >= 0.6 else "medium" if rep.score >= 0.3 else "low"
        except Exception:  # noqa: BLE001  rules result stands
            pass
    return {"analyses": {"risk": rep.model_dump(), "client": client}, **usage_update(usage)}


# ------------------------------------------------------------------ Client Researcher (X4)
def brief_rules(client: dict | None, market: dict | None, job: dict) -> ClientBrief:
    if not client:
        return ClientBrief(client_id=job.get("client_id", "?"), signals=["client history unavailable"],
                           talking_points=[], sources=[])
    hires, posted = client.get("hires", 0), max(1, client.get("jobs_posted", 0))
    spend = client.get("total_spend", 0)
    since = client.get("member_since") or "2026"
    tenure = max(0.0, 2026 - int(str(since)[:4]))
    avg = spend / hires if hires else 0
    tier = "enterprise" if spend > 100000 else "established" if hires >= 10 else "occasional" if hires >= 1 else "new"
    signals = []
    signals.append("payment verified" if client.get("payment_verified") else "payment NOT verified")
    signals.append(f"hired on {hires}/{posted} posts ({hires / posted:.0%})")
    if avg:
        signals.append(f"average spend per hire ${avg:,.0f}")
    if client.get("avg_rating_given"):
        signals.append(f"rates freelancers {client['avg_rating_given']}/5 on average")
    budget = job.get("budget", {}).get("amount", 0)
    if market and budget:
        pos = "below" if budget < market["p25"] else "above" if budget > market["p75"] else "within"
        signals.append(f"budget ${budget:,.0f} is {pos} the market range ${market['p25']:,.0f}-${market['p75']:,.0f}")
    points = [f"Works in {client.get('industry')}; refer to their {client.get('industry')} context, not generic users."]
    if tier in ("established", "enterprise"):
        points.append("Repeat hirer: mention a clear milestone plan and handover, they have seen many proposals.")
    elif tier == "new":
        points.append("New to hiring: explain the first step and what they need to provide.")
    if avg and budget and budget < avg * 0.5:
        points.append("Budget is low for this client's usual spend: offer a smaller first milestone instead of discounting.")
    return ClientBrief(client_id=client["id"], name=client.get("name", ""), industry=client.get("industry", ""),
                       country=client.get("country", ""), payment_verified=bool(client.get("payment_verified")),
                       hire_rate=round(hires / posted, 3), avg_spend_per_hire=round(avg, 2), tenure_years=tenure,
                       tier=tier, signals=signals, talking_points=points[:3],
                       sources=["marketplace:get_client_history", "marketplace:market_stats"])


@node("researcher")
async def researcher(state: dict) -> dict:
    job, user = state["job"], state["user"]
    port = get_port(user["account"])
    client = market = None
    try:
        client = await port.get_client_history("researcher", job["client_id"])
    except (ToolUnavailable, ToolCallError):
        pass
    try:
        market = await port.market_stats("researcher", job.get("category", ""))
    except (ToolUnavailable, ToolCallError):
        pass
    brief = brief_rules(client, market, job)
    usage = None
    if os.getenv("GIGBID_DISABLE_X4") == "1":   # ablation switch for the X4 measurement
        brief = ClientBrief(client_id=job.get("client_id", "?"), signals=["X4 disabled"], sources=[])
        return {"analyses": {"brief": brief.model_dump(), "market": market}}
    if client and llm.has_model("researcher"):
        try:
            b2, usage = llm.call("researcher", "Return a ClientBrief.", prompt(
                "researcher", client=client, market=market, summary=job.get("title")), ClientBrief)
            brief.talking_points = (b2.talking_points or brief.talking_points)[:3]
        except Exception:  # noqa: BLE001
            pass
    return {"analyses": {"brief": brief.model_dump(), "market": market}, **usage_update(usage)}


# ------------------------------------------------------------------ Fit Matcher
STRENGTH = {"strong": 1.0, "weak": 0.45, "none": 0.0}


def fit_from_evidence(reqs: list[Requirement], ev: list[dict], by_req: dict[str, list[str]],
                      unsupported: list[str]) -> FitReport:
    by_id = {e["id"]: e for e in ev}
    rows, total, weight = [], 0.0, 0.0
    for r in reqs:
        ids = [i for i in by_req.get(r.text, by_req.get(_find_key(by_req, r.text), [])) if i in by_id]
        want = set(r.skills)
        strong = [i for i in ids if want and want <= set(detect_skills(by_id[i]["text"] + " " + (by_id[i].get("title") or "")))]
        if r.text in unsupported or not ids:
            strength = "none"
        elif strong or (not want and ids):
            strength = "strong"
        else:
            strength = "weak" if any(set(detect_skills(by_id[i]["text"])) & want for i in ids) else "none"
        if not want and strength == "strong":
            strength = "weak"   # nothing to check against: be conservative
        keep = strong or ids
        rows.append(RequirementMatch(requirement=r.text, evidence_ids=keep[:3] if strength != "none" else [],
                                     projects=sorted({by_id[i]["project"] for i in keep[:3] if by_id[i].get("project")}),
                                     strength=strength))
        w = 1.0 if r.must_have else 0.5
        total += w * STRENGTH[strength]
        weight += w
    score = round(total / weight, 3) if weight else 0.0
    reasons = [f"{m.strength}: {m.requirement}" for m in rows]
    return FitReport(score=score, matrix=rows, reasons=reasons,
                     unsupported_requirements=[m.requirement for m in rows if m.strength == "none"])


def _find_key(d: dict, text: str) -> str:
    for k in d:
        if text.lower() in k.lower() or k.lower() in text.lower():
            return k
    return text


@node("matcher", timeout=300)
async def matcher(state: dict) -> dict:
    job, user = state["job"], state["user"]
    clean, _ = neutralise(job.get("description", ""))
    spec = analyse_rules(job)   # the matcher runs in parallel with the analyst, so it extracts requirements itself
    reqs = spec.requirements or [Requirement(text=job.get("title", ""), skills=detect_skills(job.get("title", "")))]
    res = await gateway().call("matcher", "retrieve_for_job", {
        "job_text": clean, "requirements": [r.text for r in reqs], "k": 8, "owner": user["owner"]})
    # the pipeline is keyed by the requirement strings we sent
    fit = fit_from_evidence(reqs, res["evidence"], res["by_requirement"], res["unsupported_requirements"])
    return {"analyses": {"fit": fit.model_dump(), "requirements": [r.model_dump() for r in reqs]},
            "evidence": res["evidence"], **merge_usage()}
