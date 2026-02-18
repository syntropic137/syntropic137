# AEF Dashboard API - Production Dockerfile
# Multi-stage build for minimal image size
# Build context: repo root (not apps/syn-dashboard)

# Build stage
FROM python:3.12-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy local dependencies first (for layer caching)
COPY packages/syn-shared/ ./packages/syn-shared/
COPY packages/syn-tokens/ ./packages/syn-tokens/
COPY packages/syn-domain/ ./packages/syn-domain/
COPY packages/syn-adapters/ ./packages/syn-adapters/
COPY packages/syn-api/ ./packages/syn-api/
COPY lib/event-sourcing-platform/event-sourcing/python/ ./lib/event-sourcing-platform/event-sourcing/python/
COPY lib/agentic-primitives/lib/python/agentic_logging/ ./lib/agentic-primitives/lib/python/agentic_logging/
COPY lib/agentic-primitives/lib/python/agentic_events/ ./lib/agentic-primitives/lib/python/agentic_events/
COPY lib/agentic-primitives/lib/python/agentic_workspace/ ./lib/agentic-primitives/lib/python/agentic_workspace/
COPY lib/agentic-primitives/lib/python/agentic_isolation/ ./lib/agentic-primitives/lib/python/agentic_isolation/

# Copy dashboard project files
COPY apps/syn-dashboard/pyproject.toml ./apps/syn-dashboard/
COPY apps/syn-dashboard/src/ ./apps/syn-dashboard/src/

# Create virtual environment and install dependencies
RUN uv venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Install local dependencies first (in dependency order)
RUN uv pip install ./lib/agentic-primitives/lib/python/agentic_logging
RUN uv pip install ./lib/agentic-primitives/lib/python/agentic_events
RUN uv pip install ./lib/agentic-primitives/lib/python/agentic_workspace
RUN uv pip install ./lib/agentic-primitives/lib/python/agentic_isolation
RUN uv pip install ./lib/event-sourcing-platform/event-sourcing/python
RUN uv pip install ./packages/syn-shared
RUN uv pip install ./packages/syn-tokens
RUN uv pip install ./packages/syn-domain
RUN uv pip install './packages/syn-adapters[all]'
RUN uv pip install ./packages/syn-api
RUN uv pip install ./apps/syn-dashboard

# Runtime stage
FROM python:3.12-slim AS runtime

# Install Docker CLI for workspace container management
# Copy from official docker image instead of apt install (more reliable)
COPY --from=docker:cli /usr/local/bin/docker /usr/local/bin/docker

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/apps/syn-dashboard/src /app/src

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Default environment variables
ENV DASHBOARD_PORT=8000
ENV DASHBOARD_HOST=0.0.0.0

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys, http.client, os; port = int(os.environ.get('DASHBOARD_PORT', 8000)); conn = http.client.HTTPConnection('localhost', port, timeout=5); conn.request('GET', '/health'); resp = conn.getresponse(); sys.exit(0 if resp.status == 200 else 1)"

# Expose dashboard port
EXPOSE 8000

# Default command - start dashboard service
CMD ["python", "-m", "uvicorn", "syn_dashboard.main:app", "--host", "0.0.0.0", "--port", "8000"]
