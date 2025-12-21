# AEF Dashboard API - Production Dockerfile
# Multi-stage build for minimal image size
# Build context: repo root (not apps/aef-dashboard)

# Build stage
FROM python:3.12-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy local dependencies first (for layer caching)
COPY packages/aef-shared/ ./packages/aef-shared/
COPY packages/aef-tokens/ ./packages/aef-tokens/
COPY packages/aef-domain/ ./packages/aef-domain/
COPY packages/aef-adapters/ ./packages/aef-adapters/
COPY lib/event-sourcing-platform/event-sourcing/python/ ./lib/event-sourcing-platform/event-sourcing/python/
COPY lib/agentic-primitives/lib/python/agentic_logging/ ./lib/agentic-primitives/lib/python/agentic_logging/
COPY lib/agentic-primitives/lib/python/agentic_events/ ./lib/agentic-primitives/lib/python/agentic_events/
COPY lib/agentic-primitives/lib/python/agentic_workspace/ ./lib/agentic-primitives/lib/python/agentic_workspace/

# Copy dashboard project files
COPY apps/aef-dashboard/pyproject.toml ./apps/aef-dashboard/
COPY apps/aef-dashboard/src/ ./apps/aef-dashboard/src/

# Create virtual environment and install dependencies
RUN uv venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Install local dependencies first (in dependency order)
RUN uv pip install ./lib/agentic-primitives/lib/python/agentic_logging
RUN uv pip install ./lib/agentic-primitives/lib/python/agentic_events
RUN uv pip install ./lib/agentic-primitives/lib/python/agentic_workspace
RUN uv pip install ./lib/event-sourcing-platform/event-sourcing/python
RUN uv pip install ./packages/aef-shared
RUN uv pip install ./packages/aef-tokens
RUN uv pip install ./packages/aef-domain
RUN uv pip install ./packages/aef-adapters
RUN uv pip install ./apps/aef-dashboard

# Runtime stage
FROM python:3.12-slim AS runtime

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/apps/aef-dashboard/src /app/src

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
CMD ["python", "-m", "uvicorn", "aef_dashboard.main:app", "--host", "0.0.0.0", "--port", "8000"]
