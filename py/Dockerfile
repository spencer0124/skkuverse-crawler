# syntax=docker/dockerfile:1
# Build stage
FROM python:3.12-slim AS build

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Dependencies layer (cached if unchanged)
COPY uv.lock pyproject.toml ./
RUN uv sync --no-install-project --no-dev

# Project code
COPY . .
RUN uv sync --frozen --no-dev

# Runtime stage (no uv binary)
FROM python:3.12-slim

RUN useradd -r -m crawler
WORKDIR /app
COPY --from=build --chown=crawler:crawler /app .

# SSOT config files from repo root (named build context)
COPY --from=repo-root departments.json /departments.json
COPY --from=repo-root categories.json /categories.json

ENV PATH="/app/.venv/bin:$PATH"
USER crawler

CMD ["python", "-m", "skkuverse_crawler", "start"]
