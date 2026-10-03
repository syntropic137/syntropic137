"""The GitHub credential an agent phase is handed.

EVERY PHASE HOLDS THE INSTALLATION'S OWN PERMISSIONS (#1477). #1197 minted
non-publishing phases a token with `pull_requests: read`, on the belief that
`gh pr comment` still worked through `issues: write`. It does not: GitHub
requires `pull_requests: write` to comment on a pull request through GraphQL
`addComment` AND through `POST /repos/{o}/{r}/issues/{n}/comments`, measured
2026-10-01 against one installation with both tokens. GitHub has no permission
meaning "may comment but may not open a PR", so the downgrade silently refused
every review phase's comment and read as a flaky App permission. Phases are
ephemeral and must be able to open their own PRs, so the downgrade is gone.

WHICH REPOSITORIES IT REACHES IS STILL SCOPED (#725). A phase is provisioned
for named repositories, and the token is minted for exactly those. Without
that, a credential issued for `org/a` could push to `org/b` for its whole hour,
because minting a new token never revokes an old one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_adapters.github.client_token import installation_token

if TYPE_CHECKING:
    from collections.abc import Collection

    from syn_adapters.github.client import GitHubAppClient, InstallationToken


async def mint_agent_token(
    client: GitHubAppClient,
    installation_id: str,
    *,
    repositories: Collection[str] | None = None,
) -> InstallationToken:
    """Mint the installation token an agent phase will hold.

    Args:
        client: GitHubAppClient instance.
        installation_id: The installation the phase's repos resolve to.
        repositories: Repository names (no owner) the token may reach. None
            only for a phase with no repository to scope to - a repo-less
            workflow - which then reaches whatever the installation covers.

    Returns:
        The installation token, with its expiry: the workspace records both,
        so it knows when to renew and what to revoke (#725).
    """
    return await installation_token(client, installation_id, repositories=repositories)
