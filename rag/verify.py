"""Claim verification (B3, R5).

1. Split a draft into sentences and keep the ones that claim experience
   (past work, skills, numbers, results). Plans and questions are not claims.
2. Grade each claim against the evidence the writer was given:
   supported / partly supported / unsupported. A claim must (a) name only skills
   present in some evidence item, (b) use only numbers present in that item, and
   (c) overlap enough content words with it.
3. Repair: unsupported claims are removed; partly supported claims lose the
   specifics (numbers, skills) that the evidence does not back.
An optional LLM check (cheap model) can upgrade/downgrade "partial" verdicts.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from agent.settings import config
from rag.text import detect_skills, lexicon, numbers, sentences, tokens

CLAIM_HINT = re.compile(
    r"(?i)\b(i|i've|i have|my|we)\b.*\b(built|shipped|delivered|developed|designed|created|used|worked|led|"
    r"implemented|migrated|reduced|improved|raised|cut|saved|handled|deployed|trained|fine-tuned|automated|"
    r"experience|years|clients?|projects?)\b|\d+\s?(%|ms|k|x|weeks|years)")
NOT_CLAIM = re.compile(r"(?i)^(i would|i will|i'd|i can|i could|could we|would you|let's|happy to|looking forward|"
                       r"what|when|how|do you|are you|please|thanks|thank you)\b|\?$")
GENERIC = set("client clients project projects system solution work built build delivered used using similar "
              "experience end team years year shipped designed developed created worked help".split())


@dataclass
class ClaimVerdict:
    claim: str
    label: str              # supported | partial | unsupported
    score: float
    evidence_id: str | None
    missing_skills: list[str]
    missing_numbers: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def split_claims(text: str) -> list[str]:
    return [s for s in sentences(text) if CLAIM_HINT.search(s) and not NOT_CLAIM.search(s.strip())]


def _grade(claim: str, evidence: list[dict]) -> ClaimVerdict:
    cfg = config()["rag"]
    ct = {t for t in tokens(claim) if t not in GENERIC and not t.isdigit()}
    c_skills = set(detect_skills(claim))
    c_nums = {n for n in numbers(claim) if not re.fullmatch(r"20\d\d", n) or True}
    best = ClaimVerdict(claim, "unsupported", 0.0, None, sorted(c_skills), sorted(c_nums))
    for ev in evidence:
        etext = ev["text"] + " " + (ev.get("title") or "")
        et = set(tokens(etext))
        e_skills = set(detect_skills(etext))
        miss_sk = sorted(c_skills - e_skills)
        miss_num = sorted(c_nums - numbers(etext))
        cover = len(ct & et) / len(ct) if ct else (1.0 if c_skills and not miss_sk else 0.0)
        if c_skills:
            cover = 0.5 * cover + 0.5 * (1 - len(miss_sk) / len(c_skills))
        if miss_num:
            cover *= 0.5
        if cover >= cfg["claim_support_threshold"] and not miss_sk and not miss_num:
            label = "supported"
        elif cover >= cfg["partial_support_threshold"] and len(miss_sk) < max(1, len(c_skills)):
            label = "partial"
        else:
            label = "unsupported"
        rank = {"supported": 2, "partial": 1, "unsupported": 0}
        if (rank[label], cover) > (rank[best.label], best.score):
            best = ClaimVerdict(claim, label, round(cover, 3), ev["id"], miss_sk, miss_num)
    return best


def verify(text: str, evidence: list[dict], llm_check=None) -> list[ClaimVerdict]:
    verdicts = [_grade(c, evidence) for c in split_claims(text)]
    if llm_check:
        for v in verdicts:
            if v.label == "partial":
                ev = next((e for e in evidence if e["id"] == v.evidence_id), None)
                if ev is not None:
                    v.label = llm_check(v.claim, ev["text"]) or v.label
    return verdicts


def _strip_specifics(claim: str, v: ClaimVerdict) -> str:
    out = claim
    for n in v.missing_numbers:
        out = re.sub(rf"(?i)(by |from |to |about |over |under )?\$?{re.escape(n)}\s?(%|ms|k|x)?", "", out)
    for s in v.missing_skills:
        for a in lexicon().get(s, []):
            out = re.sub(rf"(?i)(,\s*|\s+and\s+)?\b{re.escape(a)}\b", "", out)
    out = re.sub(r"\s{2,}", " ", out).replace(" ,", ",").replace(" .", ".")
    return out.strip()


def repair(text: str, verdicts: list[ClaimVerdict]) -> tuple[str, list[dict]]:
    """Remove unsupported claims and soften partial ones. Returns new text and a change log."""
    changes = []
    out = text
    for v in verdicts:
        if v.label == "unsupported":
            out = out.replace(v.claim, "").strip()
            changes.append({"action": "removed", "claim": v.claim})
        elif v.label == "partial" and (v.missing_numbers or v.missing_skills):
            new = _strip_specifics(v.claim, v)
            if new != v.claim and len(new.split()) >= 5:
                out = out.replace(v.claim, new)
                changes.append({"action": "softened", "claim": v.claim, "new": new})
            elif len(new.split()) < 5:
                out = out.replace(v.claim, "").strip()
                changes.append({"action": "removed", "claim": v.claim})
    out = re.sub(r"\s{2,}", " ", out).replace(" \n", "\n").strip()
    return out, changes


def unsupported_rate(verdicts: list[ClaimVerdict]) -> float:
    return sum(v.label == "unsupported" for v in verdicts) / len(verdicts) if verdicts else 0.0
