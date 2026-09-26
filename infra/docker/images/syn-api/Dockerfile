# Syn137 API Server - Production Dockerfile
# Multi-stage build for minimal image size
#
# Build context: Repository root (not this directory)
# Build: docker build -f infra/docker/images/syn-api/Dockerfile -t syn-api .

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

# 7. API application (depends on adapters, domain, shared)
COPY apps/syn-api/ ./apps/syn-api/
COPY lib/ui-feedback/backend/ui-feedback-api/ ./lib/ui-feedback/backend/ui-feedback-api/

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
RUN uv pip install ./lib/ui-feedback/backend/ui-feedback-api
RUN uv pip install "./apps/syn-api[feedback]"

# =============================================================================
# Runtime Stage
# =============================================================================
FROM python:3.12-slim AS runtime

# NOT optional by default: the Docker CLI. syn_adapters' image_verification
# resolves every workspace image with shutil.which("docker") and raises
# ImageVerificationError when it is absent, so an image built without this
# answers /health, serves every read endpoint and fails EVERY execution at
# bootstrap having spent $0.00 (#1216). Defaulting it to 0 meant the only
# correct value had to be remembered by each caller, and one of them - the
# recipe named `release-local` - did not. Pass 0 deliberately to exclude the
# CLI from an image that provisions no workspaces.
ARG INCLUDE_DOCKER_CLI=1
# Optional: 1Password CLI for secret resolution at startup (op_resolver.py)
ARG INCLUDE_OP_CLI=0
# NOT optional: cosign. Workspace image signature verification defaults to ON
# (ImageVerificationSettings.enabled) and FAILS CLOSED - a missing cosign binary
# raises ImageVerificationError and no workspace is created. Without this the
# API image cannot provision a single workspace. syn_adapters'
# image_verification supports cosign v2 and v3; it needs at least v2 for
# --certificate-identity-regexp.
ARG COSIGN_VERSION=3.1.3
RUN set -e; \
    NEEDS_CURL=1; \
    apt-get update && apt-get install -y --no-install-recommends curl; \
    curl -fsSL "https://github.com/sigstore/cosign/releases/download/v${COSIGN_VERSION}/cosign-linux-$(dpkg --print-architecture)" \
      -o /usr/local/bin/cosign && chmod 755 /usr/local/bin/cosign; \
    /usr/local/bin/cosign version; \
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
# uvicorn runs on uvloop, which spawns every `docker exec` with a real fork().
# With grpc fork support on, a fork while grpc threads are busy leaves the child
# holding half-updated grpc state, and it segfaults in cygrpc before exec: the
# random exit -11 of #1046/#1295. Nothing here uses grpc in a forked child.
ENV GRPC_ENABLE_FORK_SUPPORT=false

# Default configuration
ENV SYN_API_HOST=0.0.0.0
ENV SYN_API_PORT=8000
ENV LOG_FORMAT=json
ENV LOG_LEVEL=INFO

# Create non-root user for security
# Install gosu for runtime privilege de-escalation (selfhost entrypoint)
RUN apt-get update && apt-get install -y --no-install-recommends gosu && \
    rm -rf /var/lib/apt/lists/* && \
    useradd -m -u 1000 syn && \
    mkdir -p /app/logs && \
    chown -R syn:syn /app

USER syn

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=5)" || exit 1

EXPOSE 8000

# Build identity (#1380). The release itself comes from the installed package
# metadata and needs no stamping; these two are facts only the build knows, so
# they are passed in as build args and read back by syn_api.build_info. Both
# default to empty and an empty stamp reports as null, so an image built
# without them is honest about not knowing rather than reporting a placeholder.
#
# LAST ON PURPOSE. Every layer after an ARG that changes per commit is rebuilt
# on every commit, so these sit below everything expensive.
#
# Nothing passes them yet: the workflow that builds this image is under
# .github/, which this change is not permitted to edit. Until the build-args
# block in release-containers.yaml supplies them, /health reports
# image_tag: null and commit: null and names the release from package
# metadata. See the PR body for the one-block change required.
ARG SYN_BUILD_IMAGE_TAG=""
ARG SYN_BUILD_COMMIT=""
ENV SYN_BUILD_IMAGE_TAG=${SYN_BUILD_IMAGE_TAG}
ENV SYN_BUILD_COMMIT=${SYN_BUILD_COMMIT}

# Start the API server
# Use shell form to respect environment variables
CMD ["sh", "-c", "uvicorn syn_api.main:app --host $SYN_API_HOST --port $SYN_API_PORT"]
