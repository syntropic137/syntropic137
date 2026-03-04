# Syn137 Event Collector - Production Dockerfile
# Multi-stage build for minimal image size
# Build context: repo root (not packages/syn-collector)

# Build stage
FROM python:3.12-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

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

# 7. Collector (depends on syn-adapters[postgres], syn-shared)
COPY packages/syn-collector/ ./packages/syn-collector/

# Create virtual environment and install
RUN uv venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

RUN uv pip install "./packages/syn-collector[dev]"

# Runtime stage
FROM python:3.12-slim AS runtime

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy source directories that .pth files reference (for editable installs)
COPY --from=builder /app/packages /app/packages
COPY --from=builder /app/lib /app/lib

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Default environment variables
ENV EVENT_COLLECTOR_PORT=8080
ENV EVENT_BATCH_SIZE=100
ENV EVENT_BATCH_INTERVAL_MS=1000

# Health check (using Python since curl is not available in slim image)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys, http.client, os; port = int(os.environ.get('EVENT_COLLECTOR_PORT', 8080)); conn = http.client.HTTPConnection('localhost', port, timeout=5); conn.request('GET', '/health'); resp = conn.getresponse(); sys.exit(0 if resp.status == 200 else 1)"

# Expose collector port
EXPOSE 8080

# Default command - start collector service
CMD ["python", "-m", "syn_collector.cli", "serve", "--port", "8080", "--host", "0.0.0.0"]
