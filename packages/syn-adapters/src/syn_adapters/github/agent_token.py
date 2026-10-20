"""The GitHub credential an agent phase is handed.

A PHASE HOLDS THE INSTALLATION'S OWN PERMISSIONS, WITH ONE CEILING. #1197
minted non-publishing phases a token with `pull_requests: read`, on the belief
that `gh pr comment` still worked through `issues: write`. It does not: GitHub
requires `pull_requests: write` to comment on a pull request through GraphQL
`addComment` AND through `POST /repos/{o}/{r}/issues/{n}/comments`, measured
2026-10-01 against one installation with both tokens. So #1477 removed that
downgrade, and nothing here touches `pull_requests` or any other level an agent
legitimately uses.

`actions` is the one exception, and it is capped at `read`. The platform, not
the agent, dispatches evidence workflows (docs/plans/20261015_platform-
dispatched-evidence.md, A.10), so the App will be granted `actions: write`. An
agent that held it could re-run or dispatch the very workflow that judges its
own change. No phase needs it: prompts already expect `gh run rerun` to answer
403. The cap is a no-op while the App holds `Actions: Read-only`, and MUST be
deployed before the App's grant is raised.

WHY THE MAP IS DERIVED, NOT WRITTEN DOWN. A token minted with `permissions`
gets exactly that map, and GitHub rejects a map that exceeds the installation's
grant. So the map is the installation's live grant, read on every mint, with
`actions` lowered when present. A permission the App gains later reaches every
phase without an edit here; one it lacks is never asked for.

WHICH REPOSITORIES IT REACHES IS STILL SCOPED (#725). A phase is provisioned
for named repositories, and the token is minted for exactly those. Without
that, a credential issued for `org/a` could push to `org/b` for its whole hour,
because minting a new token never revokes an old one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from syn_adapters.github.client_token import installation_token

if TYPE_CHECKING:
    from collections.abc import Collection

    from syn_adapters.github.client import GitHubAppClient, InstallationToken

CAPPED_PERMISSION = "actions"
"""The permission no agent token may hold above `CAPPED_LEVEL`."""

CAPPED_LEVEL = "read"


class _Installation(BaseModel):
    """The part of ``GET /app/installations/{id}`` a phase token is derived from."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    permissions: dict[str, str]


def _phase_permissions(granted: dict[str, str]) -> dict[str, str]:
    """The installation's grant with `actions` lowered to `read`, and nothing else changed.

    `actions` is never added: an installation without it gets a map without
    it, because GitHub refuses a token that asks for more than the grant.
    """
    return {
        name: (CAPPED_LEVEL if name == CAPPED_PERMISSION else level)
        for name, level in granted.items()
    }


async def _granted_permissions(client: GitHubAppClient, installation_id: str) -> dict[str, str]:
    """Ask GitHub what this installation actually holds.

    Deliberately uncached: it is one request per token minted, against a
    setting an operator can change in the GitHub UI at any time. A cache would
    trade a negligible saving for a token scoped to a stale answer.
    """
    from syn_adapters.github.client_api import check_response

    response = await client._http.get(
        f"/app/installations/{installation_id}",
        headers={"Authorization": f"Bearer {client._generate_jwt()}"},
    )
    check_response(response)
    return _Installation.model_validate(response.json()).permissions


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

    Raises:
        Whatever the installation lookup or the token request raises. A phase
        whose credential cannot be capped gets no credential: an uncapped
        token handed out because a lookup failed is the defect this closes.
    """
    granted = await _granted_permissions(client, installation_id)
    return await installation_token(
        client,
        installation_id,
        permissions=_phase_permissions(granted),
        repositories=repositories,
    )
