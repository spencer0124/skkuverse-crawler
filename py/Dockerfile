# syntax=docker/dockerfile:1
# Build stage
FROM python:3.12-slim AS build

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Production runs every plugin, so every runtime extra must be installed
# here. Without them the image builds and boots with no Mongo driver and no
# scheduler — the failure the extras themselves introduce (plan 위험 ⑤).
# The flag set is pinned against pyproject by test_packaging.py.
#
# --frozen on both: a stale lock must fail the build loudly rather than
# silently re-resolve into a non-reproducible image.

# Dependencies layer (cached if unchanged)
COPY uv.lock pyproject.toml ./
RUN uv sync --frozen --no-install-project --no-dev \
    --extra mongo --extra sched --extra discord --extra ai

# Project code
COPY . .
RUN uv sync --frozen --no-dev \
    --extra mongo --extra sched --extra discord --extra ai

# Runtime stage (no uv binary)
FROM python:3.12-slim

RUN useradd -r -m crawler
WORKDIR /app
COPY --from=build --chown=crawler:crawler /app .

# SSOT config files from repo root (named build context)
COPY --from=repo-root sources.json /sources.json
COPY --from=repo-root categories.json /categories.json

ENV PATH="/app/.venv/bin:$PATH"
USER crawler

CMD ["python", "-m", "skkuverse_crawler", "start"]
