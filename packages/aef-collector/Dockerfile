# AEF Event Collector - Production Dockerfile
# Multi-stage build for minimal image size

# Build stage
FROM python:3.12-slim as builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy project files
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Create virtual environment and install dependencies
RUN uv venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
RUN uv pip install -e .

# Runtime stage
FROM python:3.12-slim as runtime

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src

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
CMD ["python", "-m", "aef_collector.cli", "serve", "--port", "8080", "--host", "0.0.0.0"]
