"""`repo_identity`: every stored repo shape reduces to one `owner/repo` (#1129).

These names are what `GH_REPO` is built from. The routing that picks WHICH
installation's token `gh` gets used to live beside them, in the handler that
injected it as GITHUB_TOKEN; since #725 it lives in `setup_phase_secrets`,
which writes it to hosts.yml, and is tested there
(`test_725_gh_credential_and_ledger.py` in syn-adapters).
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    SourceCommit,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.repo_identity import (
    cloned_pins,
    repo_full_names,
    repo_identity_env,
)
from syn_shared.env_constants import ENV_GH_REPO


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
    assert repo_full_names([repo]) == ["syntropic137/syntropic137"]


@pytest.mark.unit
def test_repos_keep_their_order_so_the_primary_repo_is_asked_about_first() -> None:
    """A multi-repo workflow routes on its first repo, not on whichever answers."""
    assert repo_full_names(
        ["AgentParadise/agentic-primitives", "https://github.com/syntropic137/syntropic137"]
    ) == ["AgentParadise/agentic-primitives", "syntropic137/syntropic137"]


@pytest.mark.unit
def test_duplicates_are_collapsed_without_reordering() -> None:
    assert repo_full_names(
        [
            "syntropic137/syntropic137",
            "https://github.com/syntropic137/syntropic137.git",
            "syntropic137/event-sourcing-platform",
        ]
    ) == ["syntropic137/syntropic137", "syntropic137/event-sourcing-platform"]


@pytest.mark.unit
def test_unparseable_input_yields_no_repo_rather_than_a_wrong_one() -> None:
    """A half-parsed name would be looked up and 404, which is worse than not asking."""
    assert repo_full_names([]) == []
    assert repo_full_names(["", "not-a-repo", "https://github.com/"]) == []


@pytest.mark.unit
def test_gh_repo_names_the_primary_repo_only() -> None:
    """`gh` acts on `effective_repos[0]`, the same repo the prompt names (#1187)."""
    assert repo_identity_env(
        ["https://github.com/syntropic137/syntropic137.git", "syntropic137/event-sourcing-platform"]
    ) == {ENV_GH_REPO: "syntropic137/syntropic137"}


@pytest.mark.unit
def test_an_unparseable_primary_names_no_repo_rather_than_the_next_one() -> None:
    assert repo_identity_env(["not-a-repo", "syntropic137/syntropic137"]) == {}
    assert repo_identity_env([]) == {}


@pytest.mark.unit
def test_only_pinned_commits_of_cloned_repos_with_a_sha_are_kept() -> None:
    pins = [
        SourceCommit(repository="syntropic137/syntropic137", sha="a" * 40),
        SourceCommit(repository="syntropic137/event-sourcing-platform", sha="b" * 40),
        SourceCommit(repository="syntropic137/agentic-workspace", sha=None),
    ]
    cloned = ["https://github.com/syntropic137/syntropic137", "syntropic137/agentic-workspace"]
    assert cloned_pins(cloned, pins) == {"syntropic137/syntropic137": "a" * 40}
