"""Versioned prompts, one Markdown file per node (no inline prompts in code)."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).parent


@lru_cache(maxsize=None)
def _load(node: str) -> tuple[dict, str]:
    raw = (_DIR / f"{node}.md").read_text()
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
    meta = dict(line.split(": ", 1) for line in m.group(1).splitlines() if ": " in line)
    return meta, m.group(2).strip()


def prompt(node: str, **values) -> str:
    _, body = _load(node)
    return body.format(**values)


def version(node: str) -> str:
    return _load(node)[0].get("version", "0")
