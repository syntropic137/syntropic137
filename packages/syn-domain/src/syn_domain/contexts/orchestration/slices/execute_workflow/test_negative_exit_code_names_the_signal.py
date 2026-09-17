"""A negative exit code must reach the operator with its signal named (#1295).

Exit ``-11`` is SIGSEGV. Three runs died to it in one day and the records said
only ``-11``, so every reader had to know CPython's ``Popen.returncode``
convention (``-N`` means killed by signal ``N``) and POSIX signal numbering
before they could tell a segfault from a exit status. One of those runs lost
its diagnostic report to the same number: the branch-state inspection on
``exec-76a6d3b22b23`` reported the ``find`` below as ``exited -11``.

These tests read the strings an operator actually reads - the error text, the
stored ``error_message`` - not the formatter that builds them. That is the hop
that matters: a value named correctly at the formatter and dropped at the
constructor or the record would pass a test of either end.

WHAT IS DELIBERATELY NOT CLAIMED: naming the signal does not fix the
segfault. The failing process is the orchestrator's own ``docker`` client
(a contained process killed by a signal comes back as a POSITIVE ``128+N``),
and why THAT segfaults needs host-level evidence no test here can reach.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration._shared.skill_errors import SkillInstallFailed
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    FailedWorkspaceCommand,
    WorkspaceInspectionFailedError,
)

pytestmark = [pytest.mark.unit]

#: The command that came back ``-11`` on exec-76a6d3b22b23, verbatim.
THE_FIND = (
    "find",
    "/workspace/repos",
    "-mindepth",
    "2",
    "-maxdepth",
    "2",
    "-name",
    ".git",
)


def _inspection_failure(
    exit_code: int, *, timed_out: bool = False
) -> WorkspaceInspectionFailedError:
    return WorkspaceInspectionFailedError(
        doing="listing the repositories in the workspace",
        failure=FailedWorkspaceCommand(
            command=THE_FIND,
            exit_code=exit_code,
            stderr="",
            timed_out=timed_out,
        ),
    )


def test_the_segfault_that_lost_the_report_is_named_not_numbered() -> None:
    """The #1295 case: the operator is told SIGSEGV, not left to decode -11."""
    error = _inspection_failure(-11)

    for text in (str(error), error.summary):
        # The number stays - it is what logs get grepped by - but it never
        # travels alone.
        assert "exited -11 (SIGSEGV: Segmentation fault)" in text
        # The command that died is still named, so the report says WHAT
        # segfaulted and not merely that something did.
        assert "find /workspace/repos" in text


def test_the_sentinel_is_not_dressed_up_as_a_signal() -> None:
    """``-1`` means "no status was ever collected", and SIGHUP never happened.

    Every isolation provider writes ``exit_code=-1`` for a missing container, a
    timeout, or a raised exception. Decoding negatives by arithmetic alone
    would report all three as SIGHUP - a cause that did not occur, invented on
    the one path an operator turns to when something has already gone wrong.
    Naming a real signal and inventing one are the same change if nobody
    checks this.
    """
    text = str(_inspection_failure(-1))

    assert "SIGHUP" not in text
    assert "Hangup" not in text
    assert "no exit status" in text


def test_an_ordinary_failure_still_reads_as_a_plain_number() -> None:
    """Positive codes are exit statuses and must not grow signal decoration."""
    text = str(_inspection_failure(3))

    assert "exited 3" in text
    assert "SIG" not in text


def test_a_timeout_still_says_it_timed_out() -> None:
    """The timeout wording outranks the code, exactly as before."""
    text = str(_inspection_failure(-1, timed_out=True))

    assert "timed out, so it did not finish" in text
    assert "SIG" not in text


def test_a_signal_killed_skill_install_names_the_signal() -> None:
    """The same defect on the skill path, where the code is passed one hop."""
    text = str(SkillInstallFailed("review", "claude", -9, "  "))

    assert "SIGKILL" in text
    assert "-9" in text
