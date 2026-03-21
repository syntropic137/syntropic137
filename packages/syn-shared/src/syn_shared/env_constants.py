"""Typed string constants for environment variable names used across Syntropic137.

Centralizes all env var name literals so that:
- Typos are caught at import time (NameError) rather than at runtime
- Renaming an env var is a one-line change
- IDEs can trace every usage via the constant name

Pattern mirrors workspace_paths.py — plain module-level constants, no classes.

Usage:
    from syn_shared.env_constants import (
        ENV_CLAUDE_CODE_OAUTH_TOKEN,
        ENV_ANTHROPIC_API_KEY,
        ENV_CLAUDE_SESSION_ID,
        MODEL_SONNET,
    )
"""

# ---------------------------------------------------------------------------
# Agent credential env vars
# Read from Settings (pydantic-settings); these are the raw env var name strings.
# ---------------------------------------------------------------------------

ENV_CLAUDE_CODE_OAUTH_TOKEN = "CLAUDE_CODE_OAUTH_TOKEN"
ENV_ANTHROPIC_API_KEY = "ANTHROPIC_API_KEY"

# ---------------------------------------------------------------------------
# Agent execution env vars
# Injected into the workspace container environment at provision time.
# ---------------------------------------------------------------------------

ENV_CLAUDE_SESSION_ID = "CLAUDE_SESSION_ID"
ENV_ANTHROPIC_BASE_URL = "ANTHROPIC_BASE_URL"

# ---------------------------------------------------------------------------
# Workspace infrastructure env vars
# Read by the workspace adapter at initialisation; not in pydantic Settings.
# ---------------------------------------------------------------------------

ENV_SYN_WORKSPACE_CONTAINER_DIR = "SYN_WORKSPACE_CONTAINER_DIR"
ENV_SYN_WORKSPACE_HOST_DIR = "SYN_WORKSPACE_HOST_DIR"
ENV_SYN_AGENT_NETWORK = "SYN_AGENT_NETWORK"

# ---------------------------------------------------------------------------
# Model alias constants
# Short names recognised by ModelRegistry (resolved to full API names via YAML).
# ---------------------------------------------------------------------------

MODEL_HAIKU = "haiku"
MODEL_SONNET = "sonnet"
MODEL_OPUS = "opus"

__all__ = [
    "ENV_ANTHROPIC_API_KEY",
    "ENV_ANTHROPIC_BASE_URL",
    "ENV_CLAUDE_CODE_OAUTH_TOKEN",
    "ENV_CLAUDE_SESSION_ID",
    "ENV_SYN_AGENT_NETWORK",
    "ENV_SYN_WORKSPACE_CONTAINER_DIR",
    "ENV_SYN_WORKSPACE_HOST_DIR",
    "MODEL_HAIKU",
    "MODEL_OPUS",
    "MODEL_SONNET",
]
