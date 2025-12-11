# AEF Isolated Workspace Image
# This image is used for running coding agents in isolation.
#
# Build:
#   docker build -t aef-workspace:latest -f docker/workspace/Dockerfile .
#
# Usage:
#   Used automatically by GVisorWorkspace and HardenedDockerWorkspace
#
# Security:
#   - Minimal base image (Debian slim)
#   - Non-root user by default
#   - Common development tools pre-installed
#   - No setuid binaries
#
# See ADR-021: Isolated Workspace Architecture

FROM python:3.12-slim-bookworm AS base

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Install essential development tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Version control
    git \
    # Build tools
    build-essential \
    gcc \
    g++ \
    make \
    # Common utilities
    curl \
    wget \
    jq \
    tree \
    vim-tiny \
    less \
    # Node.js (for JS/TS projects)
    nodejs \
    npm \
    # Network tools (useful for debugging, disabled at runtime)
    ca-certificates \
    # File utilities
    zip \
    unzip \
    # Process management
    procps \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Install uv for fast Python package management
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && mv /root/.local/bin/uv /usr/local/bin/ \
    && mv /root/.local/bin/uvx /usr/local/bin/ \
    && rm -rf /root/.local

# Create workspace user (non-root)
RUN groupadd --gid 1000 workspace \
    && useradd --uid 1000 --gid 1000 --shell /bin/bash --create-home workspace

# Create workspace directories
RUN mkdir -p /workspace /workspace/.context /workspace/output \
    && chown -R workspace:workspace /workspace

# Remove setuid/setgid binaries for security
RUN find / -perm /6000 -type f -exec chmod a-s {} \; 2>/dev/null || true

# Set working directory
WORKDIR /workspace

# Switch to non-root user
USER workspace

# Set environment variables
ENV HOME=/workspace \
    CLAUDE_PROJECT_DIR=/workspace \
    PATH="/workspace/.local/bin:/usr/local/bin:$PATH" \
    # Disable pip version warnings
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Use uv for Python package management
    UV_SYSTEM_PYTHON=1

# Health check: verify workspace is accessible
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=2 \
    CMD [ "test", "-w", "/workspace" ]

# Default command (keep container running)
CMD ["sleep", "infinity"]
