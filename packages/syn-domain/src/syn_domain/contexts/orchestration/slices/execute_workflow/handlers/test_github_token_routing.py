"""`_repo_full_names`: every stored repo shape reduces to one `owner/repo` (#1129).

These names are what `GH_REPO` is built from. The routing that picks WHICH
installation's token `gh` gets used to live beside them, in the handler that
injected it as GITHUB_TOKEN; since #725 it lives in `setup_phase_secrets`,
which writes it to hosts.yml, and is tested there
(`test_725_gh_credential_and_ledger.py` in syn-adapters).
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
