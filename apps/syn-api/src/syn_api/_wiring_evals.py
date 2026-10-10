"""Wiring for the eval routes (#967), kept out of ``_wiring.py`` (over its LOC cap)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.ports.RevisionResolverPort import (
        RevisionResolverPort,
    )


def get_revision_resolver() -> RevisionResolverPort:
    """Pins an eval's baseline refs to commit SHAs through the GitHub App."""
    from syn_adapters.github.client import get_github_client
    from syn_adapters.github.revision_resolver import GitHubRevisionResolver

    return GitHubRevisionResolver(get_github_client)
