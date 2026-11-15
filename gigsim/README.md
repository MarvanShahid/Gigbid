# gigsim/ — provided simulator goes here

The assignment says this folder holds the instructor's GigSim, unmodified. It was **not in the starter kit
available to me**, so GigBid runs against a stand-in simulator in `sim/` (same responsibilities: jobs,
clients with hidden preferences, Connects, proposals, messages, rate limits, random 5xx errors and the
2 Nov policy update). See docs/DATA_CARD.md.

When the real GigSim is available:
1. copy it into this folder and run `python scripts/gigsim_manifest.py` to record its hashes (CI then fails if anything here changes);
2. point `GIGSIM_URL` at it — the marketplace adapter (`mcp_servers/marketplace/adapters/gigsim.py`) is the only code that talks to it,
   so only that file may need its paths adjusted.
