# Single-container deployment for Render / Railway / Fly free tiers.
#   docker build -f infra/docker/allinone.Dockerfile -t gigbid . && docker run -p 3000:3000 --env-file .env gigbid
FROM node:22-slim AS web
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npx next build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 NODE_ENV=production
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
 && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml ./
COPY agent agent
COPY rag rag
COPY mcp_servers mcp_servers
COPY apps/__init__.py apps/__init__.py
COPY apps/api apps/api
COPY worker worker
COPY sim sim
COPY evals evals
COPY scripts scripts
COPY data/personas data/personas
COPY data/policy_pack data/policy_pack
COPY infra/start-all.sh infra/start-all.sh
RUN pip install .
COPY --from=web /web/.next/standalone /app/web
COPY --from=web /web/.next/static /app/web/.next/static
RUN mkdir -p /app/data/processed && chmod +x infra/start-all.sh
ENV WEB_DIR=/app/web PORT=3000
EXPOSE 3000
CMD ["sh", "infra/start-all.sh"]
