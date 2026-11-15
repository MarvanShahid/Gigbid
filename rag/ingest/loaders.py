"""Loaders and chunkers for a freelancer portfolio.

Every chunk carries metadata: owner, type, project, skills, date, client
industry and (for past proposals) outcome. Two chunk sets are produced:
`fixed` (naive 400-character windows, used by V0) and `structured`
(section-aware; one chunk per case-study section, README, code file,
review and proposal), used by every other variant.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pypdf import PdfReader

from rag.text import detect_skills


@dataclass
class Chunk:
    id: str
    owner: str
    type: str            # cv | case_study | readme | code | review | proposal | summary
    text: str
    source: str
    project: str | None = None
    skills: list[str] = field(default_factory=list)
    date: str | None = None
    industry: str | None = None
    outcome: str | None = None   # won | replied | ignored (proposals only)
    title: str | None = None
    chunkset: str = "structured"

    def to_dict(self) -> dict:
        return asdict(self)


def _cid(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


def _mk(owner, type_, text, source, chunkset="structured", **meta) -> Chunk:
    text = text.strip()
    return Chunk(id=_cid(owner, chunkset, source, text[:200], type_), owner=owner, type=type_, text=text,
                 source=source, skills=detect_skills(text), chunkset=chunkset, **meta)


def load_pdf_text(path: Path) -> str:
    return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)


def parse_case_study(owner: str, path: Path) -> list[Chunk]:
    md = path.read_text()
    title = (re.search(r"^#\s+(.+)$", md, re.M) or [None, path.stem])[1]
    year = re.search(r"\*\*Year:\*\*\s*(\d{4})", md)
    industry = re.search(r"\*\*Client industry:\*\*\s*([\w -]+?)\s*·", md)
    meta = dict(project=path.stem, date=year.group(1) if year else None,
                industry=industry.group(1).strip() if industry else None, title=title)
    out = []
    for sec in re.split(r"\n(?=## )", md):
        sec = sec.strip()
        if not sec or sec.startswith("# ") and "\n## " not in sec and len(sec) < 200:
            continue
        # every section keeps the title so it does not lose its meaning out of context
        text = sec if sec.startswith("# ") else f"{title}. {sec.lstrip('# ')}"
        out.append(_mk(owner, "case_study", text, str(path), **meta))
    return out


def parse_repo(owner: str, repo: Path) -> list[Chunk]:
    pid = repo.name
    out = []
    readme = repo / "README.md"
    if readme.exists():
        out.append(_mk(owner, "readme", readme.read_text(), str(readme), project=pid, title=f"repo {pid}"))
    for f in sorted((repo / "src").glob("*")) if (repo / "src").exists() else []:
        code = f.read_text(errors="ignore")
        out.append(_mk(owner, "code", f"File {f.name} in repo {pid}:\n{code}", str(f), project=pid, title=f"repo {pid}"))
    return out


def load_persona(persona_dir: Path, owner: str | None = None) -> list[Chunk]:
    """Load one persona/user portfolio folder into structured + fixed chunks."""
    owner = owner or persona_dir.name
    chunks: list[Chunk] = []
    cv_pdf, cv_md = persona_dir / "cv.pdf", persona_dir / "cv.md"
    cv_text = load_pdf_text(cv_pdf) if cv_pdf.exists() else (cv_md.read_text() if cv_md.exists() else "")
    if cv_text:
        for part in re.split(r"\n(?=#+ |Summary|Skills|Selected work)", cv_text):
            if part.strip():
                chunks.append(_mk(owner, "cv", part, str(cv_pdf if cv_pdf.exists() else cv_md), title="CV"))
    for cs in sorted((persona_dir / "case_studies").glob("*.md")):
        chunks += parse_case_study(owner, cs)
    for repo in sorted((persona_dir / "repos").glob("*")) if (persona_dir / "repos").exists() else []:
        if repo.is_dir():
            chunks += parse_repo(owner, repo)
    rev = persona_dir / "reviews.json"
    if rev.exists():
        for r in json.loads(rev.read_text()):
            chunks.append(_mk(owner, "review", f"Client review ({r['rating']}/5): {r['text']}", f"{rev}#{r['id']}",
                              project=r.get("project_id"), date=r.get("date"), industry=r.get("client_industry"),
                              title=f"review {r['id']}"))
    props = persona_dir / "proposals.json"
    if props.exists():
        for p in json.loads(props.read_text()):
            chunks.append(_mk(owner, "proposal", f"Past proposal for '{p['job_title']}': {p['text']}",
                              f"{props}#{p['id']}", project=p.get("project_id"), date=p.get("date"),
                              outcome=p.get("outcome"), title=p["id"]))
    chunks += fixed_chunks(owner, chunks)
    return chunks


def fixed_chunks(owner: str, structured: list[Chunk], size: int = 400, overlap: int = 80) -> list[Chunk]:
    """V0's naive chunking: concatenate each source document and cut fixed windows (no section awareness)."""
    by_source: dict[str, list[Chunk]] = {}
    for c in structured:
        if c.chunkset == "structured":
            by_source.setdefault(c.source.split("#")[0] if c.type != "proposal" and c.type != "review" else c.source,
                                 []).append(c)
    out = []
    for src, cs in by_source.items():
        text = "\n".join(c.text for c in cs)
        meta = dict(project=cs[0].project, date=cs[0].date, industry=cs[0].industry, outcome=cs[0].outcome,
                    title=cs[0].title)
        for i in range(0, max(1, len(text) - overlap), size - overlap):
            piece = text[i:i + size]
            if piece.strip():
                out.append(_mk(owner, cs[0].type, piece, src, chunkset="fixed", **meta))
    return out


def chunks_from_upload(owner: str, filename: str, content: bytes, kind: str | None = None) -> list[Chunk]:
    """Incremental ingestion of a single uploaded file from the UI."""
    name = filename.lower()
    if name.endswith(".pdf"):
        import io
        text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(content)).pages)
        type_ = kind or "cv"
    else:
        text = content.decode("utf-8", errors="ignore")
        type_ = kind or ("case_study" if name.endswith(".md") else "code")
    project = re.sub(r"\W+", "-", Path(filename).stem)[:40]
    secs = [s for s in re.split(r"\n(?=## )", text) if s.strip()] or [text]
    structured = [_mk(owner, type_, s, f"upload:{filename}", project=project, title=Path(filename).stem) for s in secs]
    return structured + fixed_chunks(owner, structured)
