"""Proposal studio helpers: regenerate one paragraph (sentence) from different evidence."""
from __future__ import annotations

import re

from agent import llm
from agent.nodes.proposal import CITE, evidence_claim, strip_citations
from rag.text import detect_skills, sentences


def regenerate_sentence(payload: dict, index: int) -> str:
    """Rewrite sentence `index` of the cover letter. With a model: ask the writer model for an alternative
    grounded in the same evidence. Without: rebuild it from the next-best evidence item, or drop it."""
    letter = payload["draft"]["cover_letter"]
    sents = sentences(letter)
    if index >= len(sents):
        return strip_citations(letter)
    target = sents[index]
    ids = [i.strip() for m in CITE.finditer(target) for i in m.group(1).split(",")]
    evidence = {e["id"]: e for e in payload.get("evidence", [])}
    new = None
    if llm.has_model("writer"):
        try:
            ev = "\n".join(f"{i}: {evidence[i]['text'][:400]}" for i in ids if i in evidence) or "(none)"
            new, _ = llm.call("writer", "Rewrite one sentence.", f"Rewrite this proposal sentence differently, using "
                              f"only facts in the evidence. Keep it to one sentence.\nSentence: {strip_citations(target)}"
                              f"\nEvidence:\n{ev}")
            new = str(new).strip().rstrip(".") + (f" [{', '.join(ids)}]." if ids else ".")
        except Exception:  # noqa: BLE001
            new = None
    if new is None:
        used = {i for s in sents for m in CITE.finditer(s) for i in m.group(1).split(",")}
        sk = detect_skills(target)
        for e in payload.get("evidence", []):
            if e["id"] in used:
                continue
            if not sk or set(sk) & set(detect_skills(e["text"])):
                c = evidence_claim(e, sk)
                if c:
                    new = f"{c.rstrip('.')} [{e['id']}]."
                    break
    sents[index] = new or ""
    return re.sub(r"\s{2,}", " ", " ".join(x for x in sents if x)).strip()   # citation markers are kept
