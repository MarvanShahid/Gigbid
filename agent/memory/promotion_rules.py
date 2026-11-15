"""Explicit promotion rules: the only code path that writes promoted memory (R7).

Style memory (from the user's edits to drafts)
  observe_edit() turns one edit into candidate observations:
    - "cut_first_sentence"   the user deleted the opening sentence
    - "avoid:<word>"         the user deleted a word/phrase the draft used (e.g. "passionate")
    - "shorter"              the user cut >= 25% of the words
    - "replace:<a>-><b>"     the user swapped one phrase for another
  RULE S: a candidate is promoted when it was seen in >= 2 distinct edits (different
  threads) and the user has not deleted that rule before.

Outcome memory (from marketplace outcomes)
  record_outcome() stores the outcome with proposal features (category, words,
  opening type, number of cited evidence items).
  RULE O: per category, once >= 3 outcomes exist, promote the reply rate and the
  feature contrast that separates replied from ignored proposals (only if the
  difference in reply rate is >= 0.25 and each side has >= 1 proposal).

Raw tool output never reaches these namespaces directly.
"""
from __future__ import annotations

import difflib
import re
import time
from collections import Counter

from agent.memory.store import store
from rag.text import sentences

STYLE_MIN_EDITS = 2
OUTCOME_MIN_N = 3
OUTCOME_MIN_GAP = 0.25
WATCH_WORDS = {"passionate", "hardworking", "perfect fit", "guarantee", "dear hiring manager", "expert", "ninja",
               "rockstar", "world-class", "cutting-edge", "synergy", "leverage", "delighted", "excited"}


def _words(t: str) -> list[str]:
    return re.findall(r"[a-z']+", t.lower())


def observe_edit(before: str, after: str) -> list[str]:
    obs = []
    sb, sa = sentences(before), sentences(after)
    if sb and (not sa or difflib.SequenceMatcher(None, sb[0], sa[0]).ratio() < 0.5) and sb[0] not in after:
        obs.append("cut_first_sentence")
    low_b, low_a = before.lower(), after.lower()
    for w in WATCH_WORDS:
        if w in low_b and w not in low_a:
            obs.append(f"avoid:{w}")
    wb, wa = len(_words(before)), len(_words(after))
    if wb and wa <= 0.75 * wb:
        obs.append("shorter")
    sm = difflib.SequenceMatcher(None, _words(before), _words(after))
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "replace" and 1 <= i2 - i1 <= 3 and 1 <= j2 - j1 <= 3:
            a, b = " ".join(_words(before)[i1:i2]), " ".join(_words(after)[j1:j2])
            obs.append(f"replace:{a}->{b}")
    return sorted(set(obs))


def describe(key: str) -> str:
    if key == "cut_first_sentence":
        return "Open directly with the client's problem; the user always cuts the first sentence."
    if key == "shorter":
        return "Keep drafts about a quarter shorter than the default length."
    if key.startswith("avoid:"):
        return f"Never use the word or phrase '{key[6:]}'."
    if key.startswith("replace:"):
        a, b = key[8:].split("->", 1)
        return f"Write '{b}' instead of '{a}'."
    return key


def promote_style(user: str, thread_id: str, before: str, after: str) -> list[str]:
    """Record an edit and apply RULE S. Returns keys promoted by this call."""
    st = store()
    promoted = []
    for key in observe_edit(before, after):
        if st.get(("style_blocked", user), key):
            continue
        cand = st.get(("style_candidates", user), key)
        threads = set(cand.value["threads"]) if cand else set()
        threads.add(thread_id)
        st.put(("style_candidates", user), key, {"threads": sorted(threads), "count": len(threads),
                                                 "rule": describe(key), "last_seen": time.time()})
        if len(threads) >= STYLE_MIN_EDITS and st.get(("style", user), key) is None:
            st.put(("style", user), key, {"rule": describe(key), "evidence_threads": sorted(threads),
                                          "promoted_by": "RULE S (>= 2 distinct edits)", "promoted_at": time.time()})
            promoted.append(key)
    return promoted


def style_rules(user: str) -> list[str]:
    return [it.value["rule"] for it in store().search(("style", user), limit=50)]


def apply_style(text: str, user: str) -> str:
    """Deterministic application of promoted rules (used by the rules profile and as a safety net)."""
    keys = [it.key for it in store().search(("style", user), limit=50)]
    out = text
    for k in keys:
        if k.startswith("avoid:"):
            out = re.sub(rf"(?i)\b{re.escape(k[6:])}\b\s*", "", out)
        elif k.startswith("replace:"):
            a, b = k[8:].split("->", 1)
            out = re.sub(rf"(?i)\b{re.escape(a)}\b", b, out)
    return re.sub(r"\s{2,}", " ", out).strip()


def proposal_features(text: str, citations: int) -> dict:
    first = (sentences(text) or [""])[0].lower()
    generic = bool(re.search(r"dear|hello|hi there|i am|i'm a|passionate|interested", first))
    n = len(text.split())
    return {"words_bucket": "short" if n <= 140 else "medium" if n <= 220 else "long",
            "opening": "generic" if generic else "specific", "citations_bucket": "0" if citations == 0 else
            "1-2" if citations <= 2 else "3+"}


def record_outcome(user: str, proposal_id: str, category: str, features: dict, outcome: str) -> list[str]:
    """Store one outcome (replied/hired/interview count as success) and apply RULE O."""
    st = store()
    st.put(("outcome_raw", user), proposal_id, {"category": category, "features": features, "outcome": outcome,
                                                "at": time.time()})
    rows = [it.value for it in st.search(("outcome_raw", user), limit=1000) if it.value["category"] == category]
    if len(rows) < OUTCOME_MIN_N:
        return []
    success = lambda r: r["outcome"] in ("replied", "interview", "hired")  # noqa: E731
    rate = sum(map(success, rows)) / len(rows)
    insights = []
    for feat in ("opening", "words_bucket", "citations_bucket"):
        by = Counter(r["features"][feat] for r in rows)
        rates = {v: sum(success(r) for r in rows if r["features"][feat] == v) / n for v, n in by.items() if n >= 1}
        if len(rates) >= 2:
            best, worst = max(rates, key=rates.get), min(rates, key=rates.get)
            if rates[best] - rates[worst] >= OUTCOME_MIN_GAP:
                insights.append(f"{feat}={best} got replies {rates[best]:.0%} vs {feat}={worst} {rates[worst]:.0%}")
    st.put(("outcome", user), category, {"category": category, "n": len(rows), "reply_rate": round(rate, 3),
                                         "insights": insights, "promoted_by": "RULE O (>= 3 outcomes)",
                                         "promoted_at": time.time()})
    return [category]


def outcome_notes(user: str, category: str) -> str:
    it = store().get(("outcome", user), category)
    if not it:
        return "no outcome history yet"
    v = it.value
    return f"{v['n']} past proposals, reply rate {v['reply_rate']:.0%}. " + "; ".join(v["insights"])
