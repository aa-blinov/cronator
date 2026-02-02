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

# Install dependencies for Oracle client, uv, git, gosu, and nodejs
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    gosu \
    curl \
    wget \
    unzip \
    libnsl2 \
    gcc \
    g++ \
    make \
    libssl-dev \
    python3-dev \
    build-essential \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Oracle Instant Client Basic Lite
RUN mkdir -p /usr/lib/instantclient && \
    cd /tmp && \
    curl -o instantclient-basiclite.zip https://download.oracle.com/otn_software/linux/instantclient/instantclient-basiclite-linuxx64.zip -SL && \
    unzip instantclient-basiclite.zip && \
    mv instantclient*/* /usr/lib/instantclient/ && \
    rm -rf /tmp/* && \
    ln -s /usr/lib/instantclient/libclntsh.so.19.1 /usr/lib/libclntsh.so || true && \
    ln -s /usr/lib/instantclient/libocci.so.19.1 /usr/lib/libocci.so || true && \
    ln -s /usr/lib/instantclient/libociicus.so /usr/lib/libociicus.so || true && \
    ln -s /usr/lib/instantclient/libnnz19.so /usr/lib/libnnz19.so || true && \
    ln -s /lib/x86_64-linux-gnu/libnsl.so.2 /usr/lib/libnsl.so.1 || true && \
    ln -s /lib/x86_64-linux-gnu/libc.so.6 /usr/lib/libresolv.so.2 || true && \
    ln -s /lib64/ld-linux-x86-64.so.2 /usr/lib/ld-linux-x86-64.so.2 || true

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

# Copy built CSS from css-builder (fallback if build fails at runtime)
COPY --from=css-builder /app/app/static/output.css /app/app/static/output.css

# Copy package files for CSS building at runtime
COPY package.json tailwind.config.js ./
COPY app/static/input.css ./app/static/

# Copy entrypoint script
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Create directories
RUN mkdir -p /app/scripts /app/envs /app/logs /app/data /app/data/artifacts \
    && chown -R cronator:cronator /app

# Set entrypoint (runs as root to fix permissions, then switches to cronator user)
# Note: We don't set USER cronator here because entrypoint needs to run as root
# The entrypoint script will switch to cronator user before executing the command
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

# Environment variables
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    ORACLE_BASE=/usr/lib/instantclient \
    LD_LIBRARY_PATH=/usr/lib/instantclient \
    TNS_ADMIN=/usr/lib/instantclient \
    ORACLE_HOME=/usr/lib/instantclient

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD sh -c "python -c \"import os,httpx; httpx.get('http://localhost:' + os.getenv('PORT','8080') + '/health')\"" || exit 1

CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
