"""Render both LangGraph graphs from code to Mermaid (docs/images/*.mmd); GitHub renders Mermaid in Markdown.
PNG export (draw_mermaid_png) needs network access to mermaid.ink, so it is optional."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.graphs import bid_graph, conversation_graph  # noqa: E402

out = ROOT / "docs" / "images"
out.mkdir(parents=True, exist_ok=True)
for name, g in (("bid_graph", bid_graph.build()), ("conversation_graph", conversation_graph.build())):
    mmd = g.get_graph().draw_mermaid()
    (out / f"{name}.mmd").write_text(mmd)
    print(f"wrote docs/images/{name}.mmd")
    if "--png" in sys.argv:
        (out / f"{name}.png").write_bytes(g.get_graph().draw_mermaid_png())
