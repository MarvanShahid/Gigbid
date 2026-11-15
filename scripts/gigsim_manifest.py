"""Record sha256 of every file in gigsim/ so CI can prove the provided simulator was not modified."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1] / "gigsim"
files = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*"))
         if p.is_file() and p.name != "MANIFEST.sha256.json"}
(root / "MANIFEST.sha256.json").write_text(json.dumps(files, indent=1))
print(f"{len(files)} files hashed")
