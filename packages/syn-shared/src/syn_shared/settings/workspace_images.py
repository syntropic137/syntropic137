"""Workspace image registry — single source of truth for container image references.

All workspace image names, tags, and GHCR paths are defined here. No other module
should hardcode image strings. To add a new provider image, add an entry to
WorkspaceImageProvider.

See ADR-056: Workspace Tooling Architecture
"""

from __future__ import annotations

from enum import StrEnum

# ---------------------------------------------------------------------------
# Registry constants
# ---------------------------------------------------------------------------

GHCR_REGISTRY: str = "ghcr.io"
GHCR_OWNER: str = "agentparadise"
IMAGE_PREFIX: str = "agentic-workspace"

DEFAULT_TAG: str = "latest"


class WorkspaceImageProvider(StrEnum):
    """Available workspace image providers.

    Each provider corresponds to a Docker image built by agentic-primitives.
    """

    CLAUDE_CLI = "claude-cli"
    INTERACTIVE_TMUX = "interactive-tmux"
    OMNI_AGENT = "omni-agent"
    """Multi-harness image: claude AND codex on the shared ADR-040 runtime.

    The claude-cli image carries a codex binary too, so codex phases run there
    today. Omni is the image where hosting both harnesses is the contract
    rather than a side effect - its manifest treats one working harness as a
    broken image, not a degraded one.

    Published as ``omni-agent-workspace``, NOT ``agentic-workspace-omni-agent``
    - see IMAGE_NAME_OVERRIDES.
    """


# Most providers publish as ``<IMAGE_PREFIX>-<provider>``. omni-agent does not:
# agentic-primitives takes its repository name from ``image.tag`` in the
# provider manifest, which reads ``omni-agent-workspace``, and its build matrix
# publishes under exactly that. Deriving the name would silently produce
# ``agentic-workspace-omni-agent``, which does not exist - the workspace would
# fail to pull at provision time, far from this file.
IMAGE_NAME_OVERRIDES: dict[WorkspaceImageProvider, str] = {
    WorkspaceImageProvider.OMNI_AGENT: "omni-agent-workspace",
}


def workspace_image_name(provider: WorkspaceImageProvider) -> str:
    """Repository name (no registry, owner, or tag) for a provider image."""
    return IMAGE_NAME_OVERRIDES.get(provider, f"{IMAGE_PREFIX}-{provider.value}")


# ---------------------------------------------------------------------------
# Image reference builder
# ---------------------------------------------------------------------------


def workspace_image_ref(
    provider: WorkspaceImageProvider = WorkspaceImageProvider.CLAUDE_CLI,
    tag: str = DEFAULT_TAG,
    *,
    registry: str = GHCR_REGISTRY,
    owner: str = GHCR_OWNER,
) -> str:
    """Build a fully-qualified image reference for a workspace provider.

    Args:
        provider: Which provider image to reference.
        tag: Image tag (version or 'latest').
        registry: Container registry (default: ghcr.io).
        owner: Registry owner/org (default: agentparadise).

    Returns:
        Full image reference, e.g. 'ghcr.io/agentparadise/agentic-workspace-claude-cli:latest'
    """
    return f"{registry}/{owner}/{workspace_image_name(provider)}:{tag}"


# ---------------------------------------------------------------------------
# Convenience constants (the most common references)
# ---------------------------------------------------------------------------

DEFAULT_WORKSPACE_IMAGE: str = workspace_image_ref()
"""Default workspace image - Claude CLI provider, latest tag, from GHCR."""

INTERACTIVE_TMUX_WORKSPACE_IMAGE: str = (
    f"{IMAGE_PREFIX}-{WorkspaceImageProvider.INTERACTIVE_TMUX.value}:{DEFAULT_TAG}"
)
"""Default interactive-tmux workspace image - bare local tag, not yet published to GHCR.

Unlike DEFAULT_WORKSPACE_IMAGE, this is built and run locally by agentic-primitives
(EXP-05) and has not been published to a registry. Once it is published, switch this
to `workspace_image_ref(WorkspaceImageProvider.INTERACTIVE_TMUX)` to become
GHCR-qualified like the default image.
"""
