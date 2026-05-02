"""Single source of truth for ports, URLs, and env var names.

All port numbers, default URLs, and environment variable name strings are
defined here. Everything else imports from this module - no magic strings.

See ADR-004: Environment Configuration with Pydantic Settings.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Ports (match docker-compose port mappings)
# ---------------------------------------------------------------------------

DEV_API_HOST_PORT = 9137
"""Host port for the dev stack API (container 8000 -> host 9137)."""

SELFHOST_GATEWAY_PORT = 8137
"""Host port for the selfhost nginx gateway."""

# ---------------------------------------------------------------------------
# Derived URLs
# ---------------------------------------------------------------------------

DEFAULT_DEV_API_URL = f"http://localhost:{DEV_API_HOST_PORT}"
"""Default API URL for dev tools (seed scripts, replay, E2E tests)."""

DEFAULT_SELFHOST_API_URL = f"http://localhost:{SELFHOST_GATEWAY_PORT}"
"""Default API URL for selfhost users (CLI, browser)."""

# ---------------------------------------------------------------------------
# Environment variable names
# ---------------------------------------------------------------------------

ENV_DEV_API_URL = "DEV__API_URL"
"""Env var for dev tooling API URL (DevToolingSettings)."""

ENV_SYN_API_URL = "SYN_API_URL"
"""Env var for selfhost API URL (used by CLI)."""

ENV_SYN_PUBLIC_HOSTNAME = "SYN_PUBLIC_HOSTNAME"
"""Env var for the public hostname (replaces deprecated SYN_DOMAIN)."""

ENV_SYN_GATEWAY_PORT = "SYN_GATEWAY_PORT"
"""Env var for the selfhost gateway port."""

ENV_ANTHROPIC_API_KEY = "ANTHROPIC_API_KEY"
"""Env var for the Anthropic API key."""

ENV_CLAUDE_CODE_OAUTH_TOKEN = "CLAUDE_CODE_OAUTH_TOKEN"
"""Env var for the Claude Code OAuth token."""
