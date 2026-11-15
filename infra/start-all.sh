#!/bin/sh
# One-container deployment (free hosts give one port): GigSim stand-in + API (in-process graph runs,
# in-memory MCP servers) + Next.js. Next.js listens on $PORT and proxies /api to the API.
set -e
cd "$(dirname "$0")/.."
export GIGBID_INLINE_RUNS=1 MCP_MODE=inmemory GIGSIM_URL=http://127.0.0.1:8100
export GIGBID_DATA_DIR="${GIGBID_DATA_DIR:-$(pwd)/data/processed}"
python -m uvicorn sim.app:app --host 127.0.0.1 --port 8100 &
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 &
for i in $(seq 1 60); do python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')" 2>/dev/null && break; sleep 1; done
cd "${WEB_DIR:-apps/web}"
if [ -f server.js ]; then exec env API_URL=http://127.0.0.1:8000 HOSTNAME=0.0.0.0 PORT="${PORT:-3000}" node server.js; fi
exec env API_URL=http://127.0.0.1:8000 npx next start -p "${PORT:-3000}"
