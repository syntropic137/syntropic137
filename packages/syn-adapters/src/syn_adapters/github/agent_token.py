"""The GitHub credential an agent phase is handed (#1197).

WHY THIS IS NOT IN A PROMPT. The `implement` phase opened its own pull
request, 4 minutes before it finished and 14 before the verifier started, on
an execution where `open_pr` never ran at all. Its prompt already said "Do not
open a PR - that is the last phase's job", in those words. Instructions are
not gates: the phase held a credential with `pull_requests: write`, so
publishing was one `gh pr create` away no matter what it had been told.

WHAT A PHASE IS ALLOWED TO DO IS THEREFORE A PROPERTY OF ITS TOKEN. A phase
that may not publish receives an installation token whose `pull_requests`
permission is `read`. `POST /repos/{o}/{r}/pulls` answers it 403 - through
`gh`, through `curl`, through the API directly, and on a codex phase, where a
tool allowlist would not have applied at all.

WHY THE SCOPE IS DERIVED, NOT ENUMERATED. GitHub rejects a token request whose
permissions exceed the installation's own grant, so a hand-written list of
"what a phase needs" would 422 on any deployment whose App is configured
differently from ours - and would silently drop a capability the App gained
later. Instead this asks the installation what it holds and downgrades the one
permission that decides publication. Everything else passes through unchanged,
which is what keeps `git push`, `gh pr checkout` and `gh issue view` working.

WHICH REPOSITORIES IT REACHES IS PART OF THE SAME ANSWER (#725). A phase is
provisioned for named repositories, and the token is minted for exactly those.
Before, it reached every repository the installation covers, so a credential
issued for `org/a` could push to `org/b` - and, because minting a new token
never revokes an old one, did so for its whole hour after the phase ended.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from syn_adapters.github.client_token import installation_token

if TYPE_CHECKING:
    from collections.abc import Collection

    from syn_adapters.github.client import GitHubAppClient, InstallationToken

logger = logging.getLogger(__name__)

PUBLICATION_PERMISSION = "pull_requests"
"""The permission `POST /repos/{owner}/{repo}/pulls` requires.

`read` keeps `gh pr view`, `gh pr diff` and `gh pr checkout` - which the
implement phase needs whenever it reworks an existing PR - and keeps
`git push`, which is `contents`.

BUT CREATION IS NOT THE ONLY THING IT TAKES. `pull_requests` is one
read/write switch over the whole pull request surface, so downgrading it also
removes submitting a review (`gh pr review`, `POST .../pulls/{n}/reviews`) and
the review-thread mutations `addPullRequestReviewThreadReply` and
`resolveReviewThread`. Commenting via the issues endpoint - which is what
`gh pr comment` and `acknowledgments.py` use - is governed by `issues` and is
untouched.

That gap is not expressible in a token: GitHub has no permission meaning "may
respond on a pull request but may not open one". A phase that must reply to
review threads therefore has to hold the same permission that lets it open a
PR. See the audit note on #1122 for the three trigger workflows this affects.
"""


async def _granted_permissions(client: GitHubAppClient, installation_id: str) -> dict[str, str]:
    """Ask GitHub what this installation actually holds.

    Deliberately uncached: it is one request per phase provisioned, against a
    setting an operator can change in the GitHub UI at any time. A cache would
    trade a negligible saving for a token scoped to a stale answer.
    """
    from syn_adapters.github.client_api import check_response

    jwt_token = client._generate_jwt()
    response = await client._http.get(
        f"/app/installations/{installation_id}",
        headers={"Authorization": f"Bearer {jwt_token}"},
    )
    check_response(response)
    permissions = response.json().get("permissions", {})
    return {str(name): str(level) for name, level in permissions.items()}


async def mint_agent_token(
    client: GitHubAppClient,
    installation_id: str,
    *,
    can_open_pr: bool,
    repositories: Collection[str] | None = None,
) -> InstallationToken:
    """Mint the installation token an agent phase will hold.

    Args:
        client: GitHubAppClient instance.
        installation_id: The installation the phase's repos resolve to.
        can_open_pr: Whether this phase is the one permitted to publish.
            False downgrades publication to read-only; the phase keeps every
            other permission the installation grants.
        repositories: Repository names (no owner) the token may reach. None
            only for a phase with no repository to scope to - a repo-less
            workflow - which then reaches whatever the installation covers.

    Returns:
        The installation token, with its expiry: the workspace records both,
        so it knows when to renew and what to revoke (#725).

    Raises:
        Whatever the installation lookup or the token request raises. A phase
        whose credential cannot be scoped gets no credential: an unscoped
        token handed out because a lookup failed is the defect this closes.
    """
    if can_open_pr:
        return await installation_token(client, installation_id, repositories=repositories)

    granted = await _granted_permissions(client, installation_id)
    scoped = {
        name: ("read" if name == PUBLICATION_PERMISSION else level)
        for name, level in granted.items()
    }
    logger.info(
        "Minting a non-publishing token for installation %s (%s: %s)",
        installation_id,
        PUBLICATION_PERMISSION,
        scoped.get(PUBLICATION_PERMISSION, "not granted to this installation"),
    )
    return await installation_token(
        client, installation_id, permissions=scoped, repositories=repositories
    )
