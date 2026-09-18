"""A phase lost to a signal must SAY so, all the way out to the operator (#1295).

WHY THIS FILE IS SEPARATE from ``test_unpushed_work_guard``. That module tests
what the gate DECIDES, against real git. This one tests what it SAYS, and the
two failure modes are unrelated: a diagnostic can be captured perfectly and
still be dropped at the constructor one hop later, or carried faithfully and
never rendered, and the gate's verdict is identical in all three cases.

THE HOPS UNDER TEST. The capture is made by the backend at the moment it reaps
the process, because the workspace reap removes the container and there is
nothing to read afterwards. From there it has to survive:

    ExecutionResult -> FailedWorkspaceCommand -> the message a human reads

Each arrow is a constructor that can silently omit a field, and an assertion
made on either end of one passes while the field vanishes in the middle. So
every assertion below is made on the rendered STRING, and the fixture carries
a kernel line that could not have come from anywhere else - the ``cygrpc``
trace from #1138, which is the one piece of evidence this failure class has
ever produced and the thing an operator needs to see.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    FailedWorkspaceCommand,
    WorkspaceInspectionFailedError,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.unpushed_work_guard import (
    _checked,
)
from syn_shared.diagnostics import SignalDeath

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

#: The #1138 trace verbatim. A value that could not arise without this change:
#: nothing on the failing path had anywhere to put a kernel line before.
_CYGRPC_FAULT = (
    "event_engine[3868282]: segfault at 1f ip 0000784ca3b19c52 sp "
    "0000784c9d7fd950 error 4 in cygrpc.cpython-312-x86_64-linux-gnu.so"
    "[784ca3a00000+4a1000]"
)

#: The command that actually cost $12.40 when it died on a signal (#1295).
_THE_COMMAND = ["git", "-C", "/workspace/repos/syntropic137", "rev-parse", "--revs-only", "HEAD"]


class _DiedOnASignal:
    """A workspace whose every command comes back the way a segfault does.

    Exit ``-11``, no stdout, NO STDERR - the last of those is the detail that
    made this failure class opaque. A killed process never reached the code
    that would have written an explanation, so the old message had a bare
    integer and nothing else to offer.
    """

    def __init__(self, death: SignalDeath | None) -> None:
        self._death = death

    async def execute(self, command: list[str]) -> ExecutionResult:
        return ExecutionResult(
            exit_code=-11,
            success=False,
            duration_ms=8.0,
            stdout="",
            stderr="",
            signal_death=self._death,
        )


def _fault_captured() -> SignalDeath:
    return SignalDeath(
        exit_code=-11,
        signal_number=11,
        command=tuple(_THE_COMMAND),
        kernel_lines=(_CYGRPC_FAULT,),
    )


async def _message_for(death: SignalDeath | None) -> str:
    """Run the real gate chokepoint and return what an operator would read."""
    with pytest.raises(WorkspaceInspectionFailedError) as raised:
        await _checked(
            _DiedOnASignal(death),
            _THE_COMMAND,
            doing="checking for unpushed work in /workspace/repos/syntropic137",
        )
    return str(raised.value)


async def test_the_faulting_library_reaches_the_operator() -> None:
    """The whole point: the message names what faulted, not just that it died.

    If this line is present for a `git` death and a different library appears
    for the `find` or secret-injection deaths, #1295 is several bugs sharing an
    exit code. That comparison is what the platform could not make before, and
    it is made from this string.
    """
    message = await _message_for(_fault_captured())

    assert "cygrpc.cpython-312-x86_64-linux-gnu.so" in message
    assert "SIGSEGV" in message
    assert "git -C /workspace/repos/syntropic137 rev-parse --revs-only HEAD" in message


async def test_minus_eleven_is_never_reported_as_a_bare_integer() -> None:
    """``exited -11`` was the entire diagnostic, and it named nothing."""
    message = await _message_for(_fault_captured())

    assert "exited -11" not in message
    assert "was killed by SIGSEGV" in message


async def test_a_missing_trace_says_why_rather_than_saying_nothing() -> None:
    """Absence of a trace must not read as absence of a fault.

    The capture reports the REASON it has no kernel lines - no ``/dev/kmsg`` in
    the container, or no CAP_SYSLOG - because "nobody was permitted to look" is
    a one-line configuration fix and "the kernel logged nothing" is evidence
    about the bug. A message that flattened them to silence would send the next
    investigation looking for a fault the kernel never recorded.
    """
    message = await _message_for(
        SignalDeath(
            exit_code=-11,
            signal_number=11,
            command=tuple(_THE_COMMAND),
            unreadable_because="reading /dev/kmsg was denied. Needs CAP_SYSLOG.",
        )
    )

    assert "CAP_SYSLOG" in message
    assert "not evidence that the kernel logged none" in message


async def test_a_signal_death_is_still_named_when_no_backend_captured_one() -> None:
    """A backend with no capture at all still must not print ``exited -11``.

    ``signal_death`` is None for the in-memory adapter and for every test
    double, so the naming cannot be allowed to depend on the capture having
    run. The exit code alone is enough to say SIGSEGV, and it is said.
    """
    message = await _message_for(None)

    assert "was killed by SIGSEGV" in message
    assert "exited -11" not in message


def test_the_sentinel_minus_one_is_not_named_as_a_signal() -> None:
    """The regression that got the previous attempt reverted (``cc58c8fe``).

    ``-1`` means "no real status" repo-wide - a missing container, a timeout, a
    caught exception - and it collides with SIGHUP under the negative
    convention. Labelling those three "killed by SIGHUP" is what the revert
    was for: a wrong label on a failure costs more than no label.
    """
    message = str(
        WorkspaceInspectionFailedError(
            doing="listing repositories",
            failure=FailedWorkspaceCommand(
                command=("find", "/workspace/repos"), exit_code=-1, stderr=""
            ),
        )
    )

    assert "SIGHUP" not in message
    assert "no real status" in message


async def test_the_one_line_summary_names_the_signal_too() -> None:
    """``summary`` is a second consumer, on a path that never reads the full text.

    ``observe_branches`` and ``record_phase_starting_point`` both swallow this
    error and carry ``summary`` into ``ObservedBranches.unreadable`` - so a
    phase failing for some other reason reports the branch read's failure
    through this string and nothing else. It gets the signal name; it
    deliberately does NOT get the kernel dump, because it is one line inside a
    report about something else.
    """
    death = _fault_captured()
    with pytest.raises(WorkspaceInspectionFailedError) as raised:
        await _checked(_DiedOnASignal(death), _THE_COMMAND, doing="reading branches")
    summary = raised.value.summary

    assert "was killed by SIGSEGV" in summary
    assert "exited -11" not in summary
    assert "cygrpc" not in summary
    assert "\n" not in summary


async def test_secret_injection_killed_by_a_signal_says_so() -> None:
    """The occurrence with no agent, no tokens, and nothing to show for it.

    Secret injection has died on a signal BEFORE any agent ran (#1295), and
    the message it produced carried the exit code only when stderr happened to
    be empty - ``stderr or f"exit code {...}"``. A killed setup script that had
    written a single byte to stderr therefore reported that byte and dropped
    the status entirely. The status is now always said, and the diagnostic
    with it.
    """
    from unittest.mock import AsyncMock, MagicMock, patch

    from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
        WorkspaceProvisionHandler,
    )

    workspace = MagicMock()
    workspace.run_setup_phase = AsyncMock(
        return_value=ExecutionResult(
            exit_code=-11,
            success=False,
            duration_ms=3.0,
            # Non-empty on purpose: this is what made the old message drop the
            # status, and it is the reason this test exists at all.
            stderr="Cloning into '/workspace/repos/syntropic137'...",
            signal_death=_fault_captured(),
        )
    )
    handler = WorkspaceProvisionHandler.__new__(WorkspaceProvisionHandler)

    with (
        patch(
            "syn_adapters.workspace_backends.service.SetupPhaseSecrets.create",
            AsyncMock(return_value=MagicMock(codex_auth_json=None)),
        ),
        pytest.raises(RuntimeError) as raised,
    ):
        await handler._hydrate_workspace(
            workspace,
            ["syntropic137/syntropic137"],
            phase_name="premise",
            clone_repos=True,
            can_open_pr=False,
            include_codex_auth=False,
        )

    message = str(raised.value)
    assert "was killed by SIGSEGV" in message
    assert "cygrpc.cpython-312-x86_64-linux-gnu.so" in message
    # The stderr that used to displace the status is still reported, alongside it.
    assert "Cloning into" in message


async def test_secret_injection_names_the_status_even_with_no_diagnostic() -> None:
    """The ``stderr or <status>`` defect, isolated from the capture.

    The previous test cannot pin this on its own: the captured diagnostic also
    contains the words "killed by SIGSEGV", so it stays green while the status
    itself is displaced. With ``signal_death`` None - a backend that cannot
    capture, which is every non-Docker one - the status has nowhere else to
    come from, and a message carrying only stderr says nothing about how the
    script died.
    """
    from unittest.mock import AsyncMock, MagicMock, patch

    from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
        WorkspaceProvisionHandler,
    )

    workspace = MagicMock()
    workspace.run_setup_phase = AsyncMock(
        return_value=ExecutionResult(
            exit_code=-11,
            success=False,
            duration_ms=3.0,
            stderr="Cloning into '/workspace/repos/syntropic137'...",
            signal_death=None,
        )
    )
    handler = WorkspaceProvisionHandler.__new__(WorkspaceProvisionHandler)

    with (
        patch(
            "syn_adapters.workspace_backends.service.SetupPhaseSecrets.create",
            AsyncMock(return_value=MagicMock(codex_auth_json=None)),
        ),
        pytest.raises(RuntimeError) as raised,
    ):
        await handler._hydrate_workspace(
            workspace,
            ["syntropic137/syntropic137"],
            phase_name="premise",
            clone_repos=True,
            can_open_pr=False,
            include_codex_auth=False,
        )

    message = str(raised.value)
    assert "was killed by SIGSEGV" in message
    assert "Cloning into" in message
