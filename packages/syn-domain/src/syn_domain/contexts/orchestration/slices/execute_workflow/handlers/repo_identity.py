"""Which repositories a phase acts on, by `owner/repo` name (#1129, #1187).

Split from `WorkspaceProvisionHandler`: every stored repository shape reduced
to one name, and the two things provisioning derives from those names - the
`GH_REPO` that tells `gh` which repository it acts on, and the pinned commits
of the repositories a phase clones.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from syn_shared.env_constants import ENV_GH_REPO

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        SourceCommit,
    )

#: `owner` and `repo`: the two trailing path segments every accepted repo shape
#: ends with, whatever prefix it carries.
_OWNER_REPO_SEGMENTS: Final[int] = 2


def repo_full_names(repos: Sequence[str]) -> list[str]:
    """`owner/repo` for each entry, first occurrence first, unparseable ones dropped.

    Accepts the shapes the platform stores: a full URL with or without `.git`,
    an `owner/repo` shorthand, and `git@` / `ssh://` remotes.
    """
    names: list[str] = []
    for repo in repos:
        text = repo.strip().removesuffix(".git")
        if "github.com" in text:
            _, _, tail = text.partition("github.com")
            text = tail.lstrip(":/")
        parts = [part for part in text.split("/") if part]
        if len(parts) >= _OWNER_REPO_SEGMENTS:
            name = f"{parts[-2]}/{parts[-1]}"
            if name not in names:
                names.append(name)
    return names


def repo_identity_env(repos: Sequence[str]) -> dict[str, str]:
    """The environment that tells `gh` WHICH repository this phase acts on.

    Empty when the phase has no repository to name, so the caller adds it
    unconditionally rather than branching on the answer.

    WHY THIS IS PROVISIONED RATHER THAN INFERRED (#1187). `gh` resolves the
    repository a command targets from the git remotes of the surrounding
    working tree, and fails there - before it makes any API call - when there
    is no tree::

        $ gh pr list --limit 1
        failed to run git: fatal: not a git repository

    The clone used to supply that tree, so repository identity was never
    provisioned; it was a by-product of the checkout. A `clone_repos: false`
    phase still calls `gh pr create`, and after the checkout went there was
    nothing left to infer from. `GH_REPO` states the answer instead of leaving
    the agent to reconstruct it, which is why it is here and not in a prompt.

    KEYED ON THE PRIMARY REPO - the same `effective_repos[0]` that becomes
    `{{repo_url}}` in the prompt - so what the agent is told to work on and
    what `gh` acts on cannot disagree. An unparseable primary therefore yields
    no variable at all rather than falling through to the next repo's name:
    silently retargeting `gh pr create` at a different repository is a worse
    failure than the resolution error it would replace.
    """
    primary = repo_full_names(repos[:1])
    return {ENV_GH_REPO: primary[0]} if primary else {}


def cloned_pins(repos: Sequence[str], pinned_commits: Sequence[SourceCommit]) -> dict[str, str]:
    """``owner/name`` -> pinned commit, for the pinned repositories this phase clones."""
    cloned = set(repo_full_names(repos))
    return {
        c.repository: c.sha for c in pinned_commits if c.sha is not None and c.repository in cloned
    }
