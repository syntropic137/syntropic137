"""The injected GITHUB_TOKEN must belong to the repo under work (#1129).

The bug this guards: `_resolve_github_app_token` took `installations[0]`, with a
comment saying that was "sufficient for single-org dogfood deployments". The
deployment stopped being single-org. Index 0 was the wrong installation, and
because `gh` prefers $GITHUB_TOKEN over the repo-scoped credential the setup
phase writes to hosts.yml, injecting it REPLACED a working credential with one
that could not reach the repository:

    $ gh api /installation/repositories            # the injected token
    {"total_count": 2, "repos": ["AgentParadise/agentic-primitives", ...]}
    $ GH_TOKEN=<hosts.yml token> gh api /installation/repositories
    {"total_count": 6, "repos": ["syntropic137/syntropic137", ...]}

So a single-installation test proves nothing here. Every case below offers the
wrong installation FIRST, which is the arrangement that made the old code fail.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
    _installation_for_owners,
    _owners_of,
)

_WRONG = {"id": 111, "account": {"login": "AgentParadise"}}
_RIGHT = {"id": 222, "account": {"login": "syntropic137"}}
#: Wrong one first, always - index 0 is what the old code took.
_INSTALLATIONS = [_WRONG, _RIGHT]


@pytest.mark.unit
@pytest.mark.parametrize(
    "repo",
    [
        "https://github.com/syntropic137/syntropic137",
        "https://github.com/syntropic137/syntropic137.git",
        "syntropic137/syntropic137",
        "git@github.com:syntropic137/syntropic137.git",
        "ssh://git@github.com/syntropic137/syntropic137",
    ],
)
def test_the_owner_is_read_from_every_repo_shape_the_platform_stores(repo: str) -> None:
    assert _owners_of([repo]) == ["syntropic137"]


@pytest.mark.unit
def test_the_installation_that_owns_the_repo_wins_over_the_first_one() -> None:
    """The whole bug in one assertion."""
    match = _installation_for_owners(_INSTALLATIONS, _owners_of(["syntropic137/syntropic137"]))

    assert match is not None
    assert match["id"] == 222


@pytest.mark.unit
def test_no_owning_installation_means_no_token_rather_than_the_wrong_one() -> None:
    """A wrong token is worse than none: it displaces the working hosts.yml credential."""
    assert _installation_for_owners(_INSTALLATIONS, ["someone-else"]) is None


@pytest.mark.unit
def test_owner_matching_ignores_case() -> None:
    """GitHub logins are case-insensitive; a clone URL may not match the account's casing."""
    match = _installation_for_owners(_INSTALLATIONS, _owners_of(["SynTropic137/syntropic137"]))

    assert match is not None
    assert match["id"] == 222


@pytest.mark.unit
def test_repos_are_tried_in_order_so_the_primary_repo_decides() -> None:
    """A multi-repo workflow routes on its first repo, not on whichever matches."""
    owners = _owners_of(["AgentParadise/agentic-primitives", "syntropic137/syntropic137"])

    assert owners == ["agentparadise", "syntropic137"]
    match = _installation_for_owners(_INSTALLATIONS, owners)
    assert match is not None
    assert match["id"] == 111


@pytest.mark.unit
def test_unparseable_input_yields_no_owner_and_therefore_no_token() -> None:
    assert _owners_of([]) == []
    assert _owners_of(["", "not-a-repo", "https://github.com/"]) == []
