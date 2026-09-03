"""The injected GITHUB_TOKEN must belong to the repo under work (#1129).

The original bug: `_resolve_github_app_token` took `installations[0]`, which was
not the installation that owns this repo. Because `gh` prefers $GITHUB_TOKEN
over the repo-scoped credential `setup_phase_secrets.py` writes to hosts.yml,
injecting it REPLACED a working credential with one that could not reach the
repository:

    $ gh api /installation/repositories            # the injected token
    {"total_count": 2, "repos": ["AgentParadise/agentic-primitives", ...]}
    $ GH_TOKEN=<hosts.yml token> gh api /installation/repositories
    {"total_count": 6, "repos": ["syntropic137/syntropic137", ...]}

The first fix listed installations and matched account logins. Review found that
reintroduced the same class by another route: `list_installations` issues one
unpaginated request and GitHub pages that endpoint at 30, so an owner on page
two matched nothing. So the question is now asked of GitHub directly, per repo -
the same lookup the setup phase already uses, which is why the two credential
paths can no longer disagree.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
    _repo_full_names,
)


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
def test_every_repo_shape_the_platform_stores_yields_owner_slash_repo(repo: str) -> None:
    """The lookup is by full name, so every stored shape has to reduce to one."""
    assert _repo_full_names([repo]) == ["syntropic137/syntropic137"]


@pytest.mark.unit
def test_repos_keep_their_order_so_the_primary_repo_is_asked_about_first() -> None:
    """A multi-repo workflow routes on its first repo, not on whichever answers."""
    assert _repo_full_names(
        ["AgentParadise/agentic-primitives", "https://github.com/syntropic137/syntropic137"]
    ) == ["AgentParadise/agentic-primitives", "syntropic137/syntropic137"]


@pytest.mark.unit
def test_duplicates_are_collapsed_without_reordering() -> None:
    assert _repo_full_names(
        [
            "syntropic137/syntropic137",
            "https://github.com/syntropic137/syntropic137.git",
            "syntropic137/event-sourcing-platform",
        ]
    ) == ["syntropic137/syntropic137", "syntropic137/event-sourcing-platform"]


@pytest.mark.unit
def test_unparseable_input_yields_no_repo_rather_than_a_wrong_one() -> None:
    """A half-parsed name would be looked up and 404, which is worse than not asking."""
    assert _repo_full_names([]) == []
    assert _repo_full_names(["", "not-a-repo", "https://github.com/"]) == []
