"""Write apps/api/openapi.json (the web client is generated from it: `npm run gen:api` in apps/web)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.api.main import app  # noqa: E402

out = ROOT / "apps" / "api" / "openapi.json"
out.write_text(json.dumps(app.openapi(), indent=1))
print(f"wrote {out}")
