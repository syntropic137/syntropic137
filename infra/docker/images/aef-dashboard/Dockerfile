# AEF Dashboard - Production Dockerfile
# Multi-stage build for minimal image size
#
# Build context: Repository root (not this directory)
# Build: docker build -f infra/docker/images/aef-dashboard/Dockerfile -t aef-dashboard .

# =============================================================================
# Build Stage
# =============================================================================
FROM python:3.12-slim AS builder

# Install uv for fast package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy root pyproject.toml and uv.lock for dependency resolution
COPY pyproject.toml uv.lock ./

# -----------------------------------------------------------------------------
# Copy local dependencies (order matters for layer caching)
# -----------------------------------------------------------------------------

# 1. Shared utilities (no deps on other local packages)
COPY packages/aef-shared/ ./packages/aef-shared/

# 2. Agentic primitives packages
COPY lib/agentic-primitives/lib/python/agentic_logging/ ./lib/agentic-primitives/lib/python/agentic_logging/
COPY lib/agentic-primitives/lib/python/agentic_hooks/ ./lib/agentic-primitives/lib/python/agentic_hooks/

# 3. Event sourcing SDK
COPY lib/event-sourcing-platform/event-sourcing/python/ ./lib/event-sourcing-platform/event-sourcing/python/

# 4. Domain layer (depends on aef-shared)
COPY packages/aef-domain/ ./packages/aef-domain/

# 5. Adapters layer (depends on domain, shared, agentic packages)
COPY packages/aef-adapters/ ./packages/aef-adapters/

# 6. Dashboard application
COPY apps/aef-dashboard/ ./apps/aef-dashboard/

# -----------------------------------------------------------------------------
# Create virtual environment and install dependencies
# -----------------------------------------------------------------------------
RUN uv venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Install in dependency order
RUN uv pip install ./packages/aef-shared
RUN uv pip install ./lib/agentic-primitives/lib/python/agentic_logging
RUN uv pip install ./lib/agentic-primitives/lib/python/agentic_hooks
RUN uv pip install ./lib/event-sourcing-platform/event-sourcing/python
RUN uv pip install ./packages/aef-domain
RUN uv pip install ./packages/aef-adapters
RUN uv pip install ./apps/aef-dashboard

# =============================================================================
# Runtime Stage
# =============================================================================
FROM python:3.12-slim AS runtime

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
RUN useradd -m -u 1000 aef && \
    mkdir -p /app/logs && \
    chown -R aef:aef /app

USER aef

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=5)" || exit 1

EXPOSE 8000

# Start the dashboard
# Use shell form to respect environment variables
CMD ["sh", "-c", "uvicorn aef_dashboard.main:app --host $DASHBOARD_HOST --port $DASHBOARD_PORT"]
