# Build stage
FROM python:3.12-slim AS build

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Dependencies layer (cached if unchanged)
COPY py/uv.lock py/pyproject.toml ./
RUN uv sync --no-install-project --no-dev

# Project code
COPY py/ .
# SSOT: departments.json lives at repo root, loader.py resolves via parents[5]
COPY departments.json /departments.json
RUN uv sync --frozen --no-dev

# Runtime stage (no uv binary)
FROM python:3.12-slim

RUN useradd -r -m crawler
WORKDIR /app
COPY --from=build --chown=crawler:crawler /app .
COPY --from=build --chown=crawler:crawler /departments.json /departments.json

ENV PATH="/app/.venv/bin:$PATH"
USER crawler

CMD ["python", "-m", "skkuverse_crawler", "start"]
