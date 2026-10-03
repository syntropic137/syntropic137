"""A process killed by a signal must leave a diagnostic behind (#1295, #1138).

WHAT THESE TESTS ARE FOR. ``exit -11`` is the platform's most expensive
failure class and the whole of what it has ever told an operator is those four
characters. One kernel trace exists, gathered by hand, and cannot be obtained
again on demand - so the open question "do the faults from different contexts
name the SAME library or different ones" (one bug or several, #1138 vs #1295)
is unanswerable. These tests pin the capture that makes it answerable.

They are written against the CONSUMERS of the capture, not against
``SignalDeath``'s fields: a record constructed correctly and dropped one hop
later passes every assertion made on either end of the hop. So the assertions
below are made on the string an operator reads and on what the backend puts on
its ``ExecutionResult``, never on the object the capture returned.

THE KERNEL RECORD used throughout is the #1138 line verbatim, in ``/dev/kmsg``
wire format. Nothing in a test can write to the real ring buffer, so the
record walk is pointed at a file descriptor holding real records instead -
which is the part worth testing anyway, because the format (a
``priority,sequence,microseconds,flags;message`` header, one record per read,
EAGAIN at the end) is the part that can be got wrong.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from syn_adapters.diagnostics.signal_capture import (
    _RECENT_SECONDS,
    _fault_records,
    capture_signal_death,
)

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

#: The #1138 trace, verbatim, as the kernel wrote it. The fact this whole
#: feature exists to recover is the last field: `in cygrpc...so`.
_CYGRPC_FAULT = (
    "event_engine[3868282]: segfault at 1f ip 0000784ca3b19c52 sp "
    "0000784c9d7fd950 error 4 in cygrpc.cpython-312-x86_64-linux-gnu.so"
    "[784ca3a00000+4a1000]"
)

#: An unrelated fault from a different library, so a test can tell "found the
#: fault line" apart from "found any line at all" - and so the split-or-not
#: question these traces exist to answer has a shape in the tests.
_OTHER_FAULT = (
    "git[4001]: segfault at 0 ip 00007f0000000000 sp 00007ffd00000000 "
    "error 4 in libc.so.6[7f0000000000+1a000]"
)


def _kmsg_fd(*records: tuple[str, float]) -> int:
    """A file descriptor holding ``(message, seconds_since_boot)`` in wire format."""
    handle = tempfile.TemporaryFile()  # noqa: SIM115 - fd outlives the call
    for message, seconds in records:
        handle.write(f"6,1234,{int(seconds * 1_000_000)},-;{message}\n".encode())
    handle.flush()
    handle.seek(0)
    return os.dup(handle.fileno())


def test_the_faulting_library_is_read_out_of_the_ring_buffer() -> None:
    """The one fact worth having: which shared object the fault was in."""
    fd = _kmsg_fd(
        ("systemd[1]: Started something harmless.", 500.0),
        (_CYGRPC_FAULT, 990.0),
    )
    try:
        records = _fault_records(fd, uptime=1000.0)
    finally:
        os.close(fd)

    assert records == (_CYGRPC_FAULT,), records
    assert "cygrpc" in records[0]


def test_a_fault_from_a_different_library_is_reported_as_itself() -> None:
    """The split-or-not question needs the library NAMED, not classified.

    If the traces from different contexts name different libraries then #1295
    is several bugs sharing an exit code. A capture that normalised them, or
    that only recognised cygrpc, would destroy the very distinction it exists
    to expose.
    """
    fd = _kmsg_fd((_OTHER_FAULT, 990.0))
    try:
        records = _fault_records(fd, uptime=1000.0)
    finally:
        os.close(fd)

    assert records == (_OTHER_FAULT,)
    assert "libc.so.6" in records[0]
    assert "cygrpc" not in records[0]


def test_a_stale_fault_is_not_attributed_to_this_death() -> None:
    """An old segfault in the buffer is a different crash, not this one.

    Without the recency bound the capture would eventually hand an operator
    yesterday's fault as today's cause, which is the ``cc58c8fe`` lesson - a
    wrong label costs more than no label - applied to a timestamp.
    """
    uptime = 10_000.0
    fd = _kmsg_fd((_CYGRPC_FAULT, uptime - _RECENT_SECONDS - 60.0))
    try:
        assert _fault_records(fd, uptime=uptime) == ()
    finally:
        os.close(fd)


async def test_the_capture_cannot_fail_in_this_environment() -> None:
    """Whatever this machine's ring buffer permits, a diagnostic comes back.

    Deliberately NOT parametrised and deliberately not patched: it runs against
    the real ``/dev/kmsg``, whatever that is here, because the guarantee being
    pinned is the unconditional one. This runs on a path where a phase has
    already been lost, and a diagnostic that raised would convert one lost
    phase into an unreadable one.
    """
    death = await capture_signal_death(["git", "-C", "/workspace/repos/x", "rev-parse"], -11)

    assert death is not None
    assert death.signal_name == "SIGSEGV"
    assert death.command == ("git", "-C", "/workspace/repos/x", "rev-parse")
    described = death.describe()
    assert "SIGSEGV" in described
    assert "git -C /workspace/repos/x rev-parse" in described
    # Either a real trace, or a stated reason there is none. Never silence.
    assert bool(death.kernel_lines) != (death.unreadable_because is not None)


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("absent", "does not exist in this container"),
        ("denied", "CAP_SYSLOG"),
        ("no_fault", "held no fault report"),
    ],
)
async def test_every_reason_for_an_absent_trace_is_stated(
    state: str, expected: str, tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty trace must always say WHICH kind of empty it is.

    Three outcomes, three different findings, and conflating any two of them
    is how this failure class stayed unexplained. No device node and no
    capability are CONFIGURATION, fixable in one line by the operator reading
    the message. A readable buffer holding no fault report is EVIDENCE: the
    process was not killed by a memory fault at all, so the cygrpc theory
    (#1138) does not apply to it and #1295 may be several bugs.

    The path is patched rather than the outcome, so the real open-and-read
    code runs for all three. Every container in this stack is the first of
    them today, which is why the second and third would otherwise never be
    exercised anywhere.
    """
    from pathlib import Path

    from syn_adapters.diagnostics import signal_capture

    base = Path(str(tmp_path))
    if state == "absent":
        target = base / "no-such-kmsg"
    else:
        target = base / "kmsg"
        target.write_bytes(
            b"" if state == "denied" else b"6,1,1000000,-;systemd[1]: Reached target.\n"
        )
        if state == "denied":
            target.chmod(0o000)
    monkeypatch.setattr(signal_capture, "_KMSG", str(target))

    death = await capture_signal_death(["find", "/workspace/repos"], 139)

    assert death is not None
    assert death.kernel_lines == ()
    assert death.unreadable_because is not None
    assert expected in death.unreadable_because, death.unreadable_because
    # And the signal is named regardless of what the ring buffer could offer.
    assert "SIGSEGV" in death.describe()


@pytest.mark.parametrize("exit_code", [0, 1, 124, -1, None])
async def test_nothing_is_captured_for_a_command_that_was_not_killed(
    exit_code: int | None,
) -> None:
    """Including -1, which is this repo's 'no real status' sentinel.

    ``-1`` collides with SIGHUP under the negative convention and labelling it
    a signal death is precisely what got the previous attempt at this feature
    reverted (``cc58c8fe``): it put "killed by SIGHUP" on a missing container,
    a timeout and a caught exception.
    """
    assert await capture_signal_death(["git", "status"], exit_code) is None


async def test_the_backend_carries_the_diagnostic_out_on_its_result() -> None:
    """THE FIRST HOP, and the one that makes every later hop reachable.

    ``AgenticIsolationAdapter.execute`` is the single chokepoint every short
    command the platform runs in a workspace passes through - the
    unpushed-work gate's ``git rev-parse``, the ``find`` over
    ``/workspace/repos``, the secret-injection setup script - and all three
    have been lost to a bare ``-11`` (#1295). Capturing here and failing to
    ATTACH it would leave every one of them exactly as undiagnosable as
    before, with a passing test on the capture itself.

    The provider is a double because the fact under test is what the adapter
    does with a signal status, and no container can be made to segfault on
    demand - which is the whole problem this change exists to solve.
    """
    from unittest.mock import AsyncMock, MagicMock, patch

    from agentic_isolation.providers.base import ExecuteResult

    from syn_adapters.workspace_backends.agentic.adapter import AgenticIsolationAdapter
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationHandle,
    )

    adapter = AgenticIsolationAdapter()
    handle = IsolationHandle(
        isolation_id="ws-1f482c3ed9e8",
        isolation_type="docker",
        proxy_url=None,
        workspace_path="/workspace",
        host_workspace_path="/tmp/ws",
    )
    provider = MagicMock()
    provider.execute = AsyncMock(
        return_value=ExecuteResult(exit_code=-11, stdout="", stderr="", duration_ms=12.0)
    )
    with (
        patch.object(adapter, "_provider", provider),
        patch.dict(adapter._workspaces, {handle.isolation_id: MagicMock()}),
    ):
        result = await adapter.execute(handle, ["git", "-C", "/workspace/repos/x", "rev-parse"])

    assert result.exit_code == -11
    assert result.signal_death is not None
    assert result.signal_death.signal_name == "SIGSEGV"
    assert result.signal_death.command == ("git", "-C", "/workspace/repos/x", "rev-parse")
