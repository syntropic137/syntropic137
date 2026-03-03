# AEF Dashboard - Production Dockerfile
# Multi-stage build for minimal image size
#
# Build context: Repository root (not this directory)
# Build: docker build -f infra/docker/images/syn-dashboard/Dockerfile -t syn-dashboard .

# =============================================================================
# Build Stage
# =============================================================================
FROM python:3.12-slim AS builder

# Install uv for fast package management
COPY --from=ghcr.io/astral-sh/uv:0.10.6 /uv /usr/local/bin/uv

WORKDIR /app

# Copy root pyproject.toml and uv.lock for dependency resolution
COPY pyproject.toml uv.lock ./

# -----------------------------------------------------------------------------
# Copy local dependencies (order matters for layer caching)
# -----------------------------------------------------------------------------

# 1. Shared utilities (no deps on other local packages)
COPY packages/syn-shared/ ./packages/syn-shared/

# 2. Agentic primitives packages
COPY lib/agentic-primitives/lib/python/agentic_logging/ ./lib/agentic-primitives/lib/python/agentic_logging/
COPY lib/agentic-primitives/lib/python/agentic_events/ ./lib/agentic-primitives/lib/python/agentic_events/
COPY lib/agentic-primitives/lib/python/agentic_isolation/ ./lib/agentic-primitives/lib/python/agentic_isolation/

# 3. Event sourcing SDK
COPY lib/event-sourcing-platform/event-sourcing/python/ ./lib/event-sourcing-platform/event-sourcing/python/

# 4. Domain layer (depends on syn-shared)
COPY packages/syn-domain/ ./packages/syn-domain/

# 5. Token vending service
COPY packages/syn-tokens/ ./packages/syn-tokens/

# 6. Adapters layer (depends on domain, shared, agentic packages, tokens)
COPY packages/syn-adapters/ ./packages/syn-adapters/

# 7. API layer (depends on adapters, domain, shared)
COPY packages/syn-api/ ./packages/syn-api/

# 8. Dashboard application
COPY apps/syn-dashboard/ ./apps/syn-dashboard/

# -----------------------------------------------------------------------------
# Create virtual environment and install dependencies
# -----------------------------------------------------------------------------
RUN uv venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Install in dependency order
RUN uv pip install ./packages/syn-shared
RUN uv pip install ./lib/agentic-primitives/lib/python/agentic_logging
RUN uv pip install ./lib/agentic-primitives/lib/python/agentic_events
RUN uv pip install ./lib/agentic-primitives/lib/python/agentic_isolation
RUN uv pip install ./lib/event-sourcing-platform/event-sourcing/python
RUN uv pip install ./packages/syn-domain
RUN uv pip install ./packages/syn-tokens
RUN uv pip install "./packages/syn-adapters[all]"
RUN uv pip install ./packages/syn-api
RUN uv pip install ./apps/syn-dashboard

# =============================================================================
# Runtime Stage
# =============================================================================
FROM python:3.12-slim AS runtime

# Optional: Docker CLI for workspace container management (dev only)
ARG INCLUDE_DOCKER_CLI=0
# Optional: 1Password CLI for secret resolution at startup (op_resolver.py)
ARG INCLUDE_OP_CLI=0
RUN set -e; \
    NEEDS_CURL=0; \
    if [ "$INCLUDE_DOCKER_CLI" = "1" ] || [ "$INCLUDE_OP_CLI" = "1" ]; then NEEDS_CURL=1; fi; \
    if [ "$NEEDS_CURL" = "1" ]; then apt-get update && apt-get install -y --no-install-recommends curl; fi; \
    if [ "$INCLUDE_DOCKER_CLI" = "1" ]; then \
      curl -fsSL "https://download.docker.com/linux/static/stable/$(uname -m)/docker-29.2.1.tgz" | \
        tar xz --strip-components=1 -C /usr/local/bin docker/docker; \
    fi; \
    if [ "$INCLUDE_OP_CLI" = "1" ]; then \
      apt-get install -y --no-install-recommends unzip && \
      curl -fsSL "https://cache.agilebits.com/dist/1P/op2/pkg/v2.32.1/op_linux_$(dpkg --print-architecture)_v2.32.1.zip" \
        -o /tmp/op.zip && \
      unzip /tmp/op.zip -d /usr/local/bin op && rm /tmp/op.zip; \
    fi; \
    if [ "$NEEDS_CURL" = "1" ]; then apt-get purge -y curl unzip 2>/dev/null; apt-get autoremove -y; rm -rf /var/lib/apt/lists/*; fi

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy source directories that .pth files reference (for editable installs)
COPY --from=builder /app/packages /app/packages
COPY --from=builder /app/lib /app/lib
COPY --from=builder /app/apps /app/apps

# Set environment
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Default configuration
ENV DASHBOARD_HOST=0.0.0.0
ENV DASHBOARD_PORT=8000
ENV LOG_FORMAT=json
ENV LOG_LEVEL=INFO

# Create non-root user for security
# Install gosu for runtime privilege de-escalation (selfhost entrypoint)
RUN apt-get update && apt-get install -y --no-install-recommends gosu && \
    rm -rf /var/lib/apt/lists/* && \
    useradd -m -u 1000 aef && \
    mkdir -p /app/logs && \
    chown -R aef:aef /app

USER aef

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=5)" || exit 1

EXPOSE 8000

# Start the dashboard
# Use shell form to respect environment variables
CMD ["sh", "-c", "uvicorn syn_dashboard.main:app --host $DASHBOARD_HOST --port $DASHBOARD_PORT"]
