# Build stage
FROM python:3.12-slim AS builder

# Install uv & git (needed for GitPython in tests)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Argument to control including dev dependencies
ARG INSTALL_DEV=false

# Install dependencies first (better layer caching)
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$INSTALL_DEV" = "true" ]; then \
        uv sync --frozen --all-extras --no-install-project; \
    else \
        uv sync --frozen --no-dev --no-install-project; \
    fi

# Copy application code
COPY . .

# Install the project
RUN if [ "$INSTALL_DEV" = "true" ]; then \
        uv sync --frozen --all-extras; \
    else \
        uv sync --frozen --no-dev; \
    fi

# Build CSS stage
FROM node:20-slim AS css-builder

WORKDIR /app

# Copy package files and templates for content scanning
COPY package.json tailwind.config.js ./
COPY app/static/input.css ./app/static/
COPY app/templates ./app/templates

# Install dependencies and build CSS with caching
RUN --mount=type=cache,target=/root/.npm \
    npm install && \
    npx tailwindcss -i ./app/static/input.css -o ./app/static/output.css --minify


# Runtime stage
FROM python:3.12-slim

# Install uv for script environments and git for git sync
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Create non-root user
RUN useradd --create-home --shell /bin/bash cronator

WORKDIR /app

# Copy virtual environment and application from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/app /app/app
COPY --from=builder /app/cronator_lib /app/cronator_lib
COPY --from=builder /app/pyproject.toml /app/
COPY --from=builder /app/alembic /app/alembic
COPY --from=builder /app/alembic.ini /app/

# Copy built CSS from css-builder
COPY --from=css-builder /app/app/static/output.css /app/app/static/output.css

# Create directories
RUN mkdir -p /app/scripts /app/envs /app/logs /app/data \
    && chown -R cronator:cronator /app

# Switch to non-root user
USER cronator

# Environment variables
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8080/health')" || exit 1
