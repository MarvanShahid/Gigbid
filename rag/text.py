"""Tokenisation and skill detection shared by indexing, retrieval and verification."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

_TOKEN = re.compile(r"[a-z0-9][a-z0-9+#./-]*[a-z0-9+#]|[a-z0-9]")
STOP = set("""a an the and or of to in on for with by at from as is are was were be been it its this that these those
i we you they he she my our your their me us them so if then than not no yes but into over under up down out about
can will would should could may might must have has had do does did done just very also more most such any all each
per via using use used""".split())


@lru_cache(maxsize=1)
def lexicon() -> dict[str, list[str]]:
    return yaml.safe_load((Path(__file__).parent / "skills_lexicon.yaml").read_text())


def tokens(text: str, keep_stop: bool = False) -> list[str]:
    toks = _TOKEN.findall(text.lower())
    out = []
    for t in toks:
        t = t.strip("./-")
        if not t or (not keep_stop and t in STOP):
            continue
        out.append(t)
        if "." in t or "-" in t or "/" in t:  # next.js -> nextjs and next, js
            out.append(re.sub(r"[./-]", "", t))
    return out


@lru_cache(maxsize=1)
def _alias_patterns() -> list[tuple[str, re.Pattern]]:
    pats = []
    for skill, aliases in lexicon().items():
        for a in sorted(set(aliases), key=len, reverse=True):
            pats.append((skill, re.compile(r"(?<![\w])" + re.escape(a.lower()) + r"(?![\w])")))
    return pats


def detect_skills(text: str) -> list[str]:
    """Skills named explicitly (canonical or alias) in text. Whole-word matching only."""
    low = text.lower()
    found = []
    for skill, pat in _alias_patterns():
        if skill not in found and pat.search(low):
            found.append(skill)
    # "node" alone is too ambiguous unless next to js-ish context
    if "nodejs" in found and not re.search(r"node\.?js", low):
        found.remove("nodejs")
    if "typescript" in found and not re.search(r"typescript", low):
        found.remove("typescript")
    return found


def skill_display(skill: str) -> str:
    aliases = lexicon().get(skill, [skill])
    return aliases[0].title() if aliases[0].islower() and len(aliases[0]) > 4 else aliases[0]


def sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text.strip())
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", text)
    return [p.strip() for p in parts if p.strip()]


def numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text))
