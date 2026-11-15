# One image for every Python service (api, worker, mcp servers, gigsim); the command differs per service.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl && rm -rf /var/lib/apt/lists/*
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
RUN pip install .
RUN useradd -m gigbid && mkdir -p /app/data/processed && chown -R gigbid /app/data
USER gigbid
EXPOSE 8000
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
