FROM python:3.12-slim

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first (cached layer)
COPY pyproject.toml ./
RUN uv pip install --system --no-cache ".[postgres]"

# Copy source
COPY src/ ./src/

# Runtime data lives in a mounted volume — never baked into the image
VOLUME ["/app/data"]

EXPOSE 23

# Drop privileges: run as non-root
RUN useradd --system --no-create-home bbs
USER bbs

ENV DATABASE_URL=sqlite+aiosqlite:////app/data/bbs.db

ENTRYPOINT ["bbs"]
