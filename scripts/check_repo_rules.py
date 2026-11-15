"""Repository rules enforced in CI:
1. no secrets committed (API keys, private keys, .env)
2. nothing under gigsim/ changed (hash manifest)
3. every prompt lives in agent/prompts/ (no long inline prompt strings in agent/ code)
4. every number in README.md's results block comes from evals/results (block must equal scripts/make_tables.py output)
"""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
errors = []

SECRET = re.compile(r"(gsk_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)")
try:
    tracked = subprocess.check_output(["git", "ls-files"], cwd=ROOT).decode().split()
except Exception:  # noqa: BLE001  (not a git checkout: scan the tree)
    tracked = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file() and "node_modules" not in p.parts
               and ".next" not in p.parts and "processed" not in p.parts and ".git" not in p.parts]
for f in tracked:
    if f == ".env" or f.endswith("/.env"):
        errors.append(f"{f}: .env must not be committed")
    p = ROOT / f
    if p.suffix in {".png", ".pdf", ".zip", ".db", ".npz", ".gif", ".mp4"} or not p.is_file():
        continue
    try:
        if SECRET.search(p.read_text(errors="ignore")):
            errors.append(f"{f}: looks like a secret")
    except OSError:
        pass

manifest = ROOT / "gigsim" / "MANIFEST.sha256.json"
if manifest.exists():
    want = json.loads(manifest.read_text())
    for rel, h in want.items():
        p = ROOT / "gigsim" / rel
        if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != h:
            errors.append(f"gigsim/{rel} was modified (provided code must stay untouched)")

for p in (ROOT / "agent").rglob("*.py"):
    src = p.read_text()
    for m in re.finditer(r'(""".*?"""|\'\'\'.*?\'\'\')', src, re.S):
        s = m.group(0)
        if len(s) > 400 and re.search(r"(?i)\byou are (the|an?|gigbid)\b", s):
            errors.append(f"{p.relative_to(ROOT)}: inline prompt found; move it to agent/prompts/")

readme = ROOT / "README.md"
if readme.exists() and "<!-- RESULTS:START -->" in readme.read_text():
    sys.path.insert(0, str(ROOT))
    from scripts.make_tables import results_block
    cur = readme.read_text().split("<!-- RESULTS:START -->")[1].split("<!-- RESULTS:END -->")[0].strip()
    if cur != results_block().strip():
        errors.append("README results block differs from evals/results; run `make tables`")

if errors:
    print("\n".join(errors))
    sys.exit(1)
print("repo rules OK")
