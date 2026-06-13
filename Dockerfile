FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Create non-root user early so the home dir exists before we need it
RUN useradd --system --create-home --home-dir /home/bbs --shell /bin/false bbs

# ── Dependency layer (cached unless pyproject.toml or uv.lock changes) ────────
COPY pyproject.toml uv.lock ./
# Install deps only (no project yet) so this layer is reused on source-only changes
RUN uv sync --frozen --no-install-project --no-dev --extra postgres

# ── Application layer ─────────────────────────────────────────────────────────
COPY src/ ./src/
# Install the project itself (fast — deps are already in the layer above)
RUN uv sync --frozen --no-dev --extra postgres

# Runtime data lives in a mounted volume — never baked into the image
VOLUME ["/app/data"]

EXPOSE 23

# Default env — override via .env / environment: in docker-compose
ENV DATABASE_URL=sqlite+aiosqlite:////app/data/bbs.db \
    FILES_DIR=/app/data/files \
    BBS_PORT=23

USER bbs

# `bbs` is the entry point defined in pyproject.toml [project.scripts]
ENTRYPOINT ["uv", "run", "bbs"]
