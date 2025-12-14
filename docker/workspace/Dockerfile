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

# Install GitHub CLI (gh) for PR creation
# Using official GitHub install script
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update \
    && apt-get install -y gh \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast Python package management
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && mv /root/.local/bin/uv /usr/local/bin/ \
    && mv /root/.local/bin/uvx /usr/local/bin/ \
    && rm -rf /root/.local

# Install anthropic SDK and claude-agent-sdk (required for agent runner)
RUN pip install --no-cache-dir anthropic>=0.40.0 claude-agent-sdk>=0.1.11

# Copy and install aef-agent-runner package
# This runs inside the container to execute the Claude agent
COPY packages/aef-agent-runner /tmp/aef-agent-runner
RUN pip install --no-cache-dir /tmp/aef-agent-runner \
    && rm -rf /tmp/aef-agent-runner

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
    WORKSPACE_DIR=/workspace \
    CLAUDE_PROJECT_DIR=/workspace \
    PATH="/workspace/.local/bin:/usr/local/bin:$PATH" \
    # Disable pip version warnings
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Use uv for Python package management
    UV_SYSTEM_PYTHON=1 \
    # GitHub CLI uses GH_TOKEN for authentication (set by workspace injection)
    # GH_TOKEN will be injected at runtime via env var
    GH_NO_UPDATE_NOTIFIER=1 \
    # Git configuration for commits
    GIT_AUTHOR_NAME="AEF Agent" \
    GIT_AUTHOR_EMAIL="agent@aef.local" \
    GIT_COMMITTER_NAME="AEF Agent" \
    GIT_COMMITTER_EMAIL="agent@aef.local" \
    # Proxy settings for sidecar (injected at runtime by orchestrator)
    # These will be set to http://sidecar:8081 when running with sidecar
    # The sidecar intercepts requests and injects API tokens
    HTTP_PROXY="" \
    HTTPS_PROXY="" \
    NO_PROXY="localhost,127.0.0.1"

# Create standard workspace directories
RUN mkdir -p /workspace/inputs /workspace/artifacts

# Configure git for commits and authentication
RUN git config --global user.name "AEF Agent" \
    && git config --global user.email "agent@aef.local" \
    && git config --global init.defaultBranch main \
    # Use GH_TOKEN for git authentication via credential helper
    && git config --global credential.helper '!f() { echo "username=x-access-token"; echo "password=${GH_TOKEN:-$GITHUB_TOKEN}"; }; f'

# Health check: verify workspace is accessible
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=2 \
    CMD [ "test", "-w", "/workspace" ]

# Default command: run agent runner (orchestrator writes task.json first)
# Can be overridden with "sleep infinity" for interactive debugging
CMD ["python", "-m", "aef_agent_runner"]
