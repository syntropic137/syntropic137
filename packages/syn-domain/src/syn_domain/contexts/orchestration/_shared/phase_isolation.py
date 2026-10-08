"""What a phase's workspace may see beyond the checkout it was given (#1725, ADR-073)."""

from __future__ import annotations

from enum import StrEnum


class PhaseIsolation(StrEnum):
    """How much of the repositories' history and of GitHub a phase can reach.

    STANDARD is every phase until ADR-073: a full clone with every branch and
    tag, and a GitHub credential that outlives setup so the agent can push.

    PINNED is for an evaluation, where any commit after the pin may be the
    answer. Every cloned repository must be pinned; each is sealed at its pin - no
    later commit, ref, tag or remote - and the workspace keeps no GitHub
    credential after setup. A pinned phase therefore cannot push, and
    declares ``delivers_repo_changes: false``.
    """

    STANDARD = "standard"
    PINNED = "pinned"


def require_satisfiable_isolation(
    isolation: PhaseIsolation, *, delivers_repo_changes: bool, phase_id: str
) -> None:
    """Refuse a pinned phase that would have to push, when it is written.

    A sealed workspace keeps no GitHub credential, so a phase that delivers
    repository changes could never push them: it would install cleanly and
    then fail the unpushed-work gate at run time, after it was paid for.

    Raises:
        ValueError: ``isolation`` is PINNED and the phase delivers repository
            changes.
    """
    if isolation is PhaseIsolation.PINNED and delivers_repo_changes:
        msg = (
            f"Phase '{phase_id}': isolation 'pinned' removes every GitHub credential"
            " after the clone, so the phase can never push and must declare"
            " 'delivers_repo_changes: false'"
        )
        raise ValueError(msg)
