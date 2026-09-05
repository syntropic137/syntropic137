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
    )

Model aliases are NOT here - they are not env var names. They live in
``syn_shared.agents.ModelAlias`` (issue #793).
"""

# ---------------------------------------------------------------------------
# Deployment identity
# APP_ENVIRONMENT is read in more places than any other name here, and it does
# not select one thing but three: the 1Password vault, the deployment identity
# stamped on every captured session, and the compose project and network names.
# A typo in any one of those literals fails silently as "development".
# ---------------------------------------------------------------------------

ENV_APP_ENVIRONMENT = "APP_ENVIRONMENT"

# ---------------------------------------------------------------------------
# Agent credential env vars
# Read from Settings (pydantic-settings); these are the raw env var name strings.
# ---------------------------------------------------------------------------

ENV_ANTHROPIC_API_KEY = "ANTHROPIC_API_KEY"
ENV_CLAUDE_CODE_OAUTH_TOKEN = "CLAUDE_CODE_OAUTH_TOKEN"
ENV_CODEX_AUTH_JSON = "CODEX_AUTH_JSON"
ENV_GITHUB_APP_TOKEN = "GITHUB_APP_TOKEN"
ENV_GITHUB_TOKEN = "GITHUB_TOKEN"

# ---------------------------------------------------------------------------
# Git identity env vars
# Set during workspace setup phase; git requires author and committer separately,
# even though in this codebase they're always the same (GitHub App bot identity).
# ---------------------------------------------------------------------------

ENV_GIT_AUTHOR_EMAIL = "GIT_AUTHOR_EMAIL"
ENV_GIT_AUTHOR_NAME = "GIT_AUTHOR_NAME"
ENV_GIT_COMMITTER_EMAIL = "GIT_COMMITTER_EMAIL"
ENV_GIT_COMMITTER_NAME = "GIT_COMMITTER_NAME"

# ---------------------------------------------------------------------------
# Agent execution env vars
# Injected into the workspace container environment at provision time.
# ---------------------------------------------------------------------------

ENV_CLAUDE_SESSION_ID = "CLAUDE_SESSION_ID"
ENV_ANTHROPIC_BASE_URL = "ANTHROPIC_BASE_URL"
ENV_CLAUDE_CODE_ENABLE_TELEMETRY = "CLAUDE_CODE_ENABLE_TELEMETRY"
ENV_OTEL_EXPORTER_OTLP_ENDPOINT = "OTEL_EXPORTER_OTLP_ENDPOINT"

#: WHICH repository `gh` acts on, in `owner/repo` form (#1187).
#:
#: Read by the `gh` CLI inside the workspace, not by anything here. `gh`
#: otherwise resolves the repository from the git remotes of the working tree
#: and fails BEFORE any API call when there is no tree, so a phase that
#: declares `clone_repos: false` has no way to answer the question. This
#: variable is that answer.
ENV_GH_REPO = "GH_REPO"

# ---------------------------------------------------------------------------
# Workspace infrastructure env vars
# Read by the workspace adapter at initialisation; not in pydantic Settings.
# ---------------------------------------------------------------------------

ENV_SYN_WORKSPACE_CONTAINER_DIR = "SYN_WORKSPACE_CONTAINER_DIR"
ENV_SYN_WORKSPACE_HOST_DIR = "SYN_WORKSPACE_HOST_DIR"
ENV_SYN_AGENT_NETWORK = "SYN_AGENT_NETWORK"

# ---------------------------------------------------------------------------
# Workspace image signature verification env vars
#
# Backed by ImageVerificationSettings (env_prefix SYN_IMAGE_VERIFY_). Named
# here because the verification code quotes them in operator-facing error
# messages, and those strings must not drift from the settings fields.
# ---------------------------------------------------------------------------

ENV_SYN_IMAGE_VERIFY_ENABLED = "SYN_IMAGE_VERIFY_ENABLED"
ENV_SYN_IMAGE_VERIFY_ALLOW_LOCAL_IMAGES = "SYN_IMAGE_VERIFY_ALLOW_LOCAL_IMAGES"
ENV_SYN_IMAGE_VERIFY_COSIGN_PATH = "SYN_IMAGE_VERIFY_COSIGN_PATH"

# ---------------------------------------------------------------------------
# Session store capability env vars (agentic-primitives workspace image)
#
# These are read INSIDE the workspace container by the session-store capability
# that ships in the agentic-primitives workspace image. Syn137 does not read
# them; it only writes them into the container environment at provision time.
#
# The capability is a complete no-op when AGENTIC_SESSION_STORE_PROVIDER is
# unset: no init, no doctor, no finalize. That is the self-hostability
# guarantee — an operator with no SeshMagic instance gets byte-identical
# behaviour because Syn137 omits the whole block rather than setting "none".
# ---------------------------------------------------------------------------

ENV_AGENTIC_SESSION_STORE_PROVIDER = "AGENTIC_SESSION_STORE_PROVIDER"
ENV_AGENTIC_SESSION_STORE_URL = "AGENTIC_SESSION_STORE_URL"
ENV_AGENTIC_SESSION_STORE_AUTH = "AGENTIC_SESSION_STORE_AUTH"
ENV_AGENTIC_SESSION_STORE_SPOOL = "AGENTIC_SESSION_STORE_SPOOL"

#: How many workflow executions the background TRIGGER dispatcher runs at once.
#: Bound to the settings field by `validation_alias`, so this name is what
#: pydantic actually reads rather than a second spelling kept in step by hand.
ENV_SYN_POLLING_MAX_CONCURRENT_DISPATCHES = "SYN_POLLING_MAX_CONCURRENT_DISPATCHES"
ENV_AGENTIC_SESSION_STORE_PARTITION = "AGENTIC_SESSION_STORE_PARTITION"
ENV_AGENTIC_SESSION_STORE_TAGS = "AGENTIC_SESSION_STORE_TAGS"

#: WHICH deployment produced a session (APS-V1-0004 ``origin.deployment``).
#:
#: Its own variable, and NOT a tag. The capability adapter maps this one onto
#: the exporter's SESSION_STORE_ORIGIN_DEPLOYMENT, which is what stamps
#: ``origin.deployment`` on the envelope. Tags are free-form metadata the
#: exporter does not read for origin, so a deployment sent as a tag arrives at
#: the store as ``origin.deployment: null`` while everything else looks healthy.
ENV_AGENTIC_SESSION_STORE_DEPLOYMENT = "AGENTIC_SESSION_STORE_DEPLOYMENT"

#: Every variable in the session-store contract. Used by the workspace adapter
#: to emit the block and by tests to assert the "not configured" path leaks none
#: of them. Keep in sync with the constants above.
SESSION_STORE_CONTRACT_ENV_VARS: frozenset[str] = frozenset(
    {
        ENV_AGENTIC_SESSION_STORE_PROVIDER,
        ENV_AGENTIC_SESSION_STORE_URL,
        ENV_AGENTIC_SESSION_STORE_AUTH,
        ENV_AGENTIC_SESSION_STORE_SPOOL,
        ENV_AGENTIC_SESSION_STORE_PARTITION,
        ENV_AGENTIC_SESSION_STORE_TAGS,
        ENV_AGENTIC_SESSION_STORE_DEPLOYMENT,
    }
)

__all__ = [
    "ENV_AGENTIC_SESSION_STORE_AUTH",
    "ENV_AGENTIC_SESSION_STORE_DEPLOYMENT",
    "ENV_AGENTIC_SESSION_STORE_PARTITION",
    "ENV_AGENTIC_SESSION_STORE_PROVIDER",
    "ENV_AGENTIC_SESSION_STORE_SPOOL",
    "ENV_AGENTIC_SESSION_STORE_TAGS",
    "ENV_AGENTIC_SESSION_STORE_URL",
    "ENV_ANTHROPIC_API_KEY",
    "ENV_ANTHROPIC_BASE_URL",
    "ENV_APP_ENVIRONMENT",
    "ENV_CLAUDE_CODE_ENABLE_TELEMETRY",
    "ENV_CLAUDE_CODE_OAUTH_TOKEN",
    "ENV_CLAUDE_SESSION_ID",
    "ENV_CODEX_AUTH_JSON",
    "ENV_GH_REPO",
    "ENV_GITHUB_APP_TOKEN",
    "ENV_GITHUB_TOKEN",
    "ENV_GIT_AUTHOR_EMAIL",
    "ENV_GIT_AUTHOR_NAME",
    "ENV_GIT_COMMITTER_EMAIL",
    "ENV_GIT_COMMITTER_NAME",
    "ENV_OTEL_EXPORTER_OTLP_ENDPOINT",
    "ENV_SYN_AGENT_NETWORK",
    "ENV_SYN_IMAGE_VERIFY_ALLOW_LOCAL_IMAGES",
    "ENV_SYN_IMAGE_VERIFY_COSIGN_PATH",
    "ENV_SYN_IMAGE_VERIFY_ENABLED",
    "ENV_SYN_POLLING_MAX_CONCURRENT_DISPATCHES",
    "ENV_SYN_WORKSPACE_CONTAINER_DIR",
    "ENV_SYN_WORKSPACE_HOST_DIR",
    "SESSION_STORE_CONTRACT_ENV_VARS",
]
