"""Who is allowed to reap the process that carried a phase's stream.

Its exit status is not bookkeeping. ``_detect_exit_code`` reports it as the
phase's own status, and ``AgentLaunchEvidence`` reads 126/127 as the wrapper
shell saying it never managed to exec the agent - so a status invented by the
cleanup path is a phase failure invented, or a launch retracted, out of
nothing (#1065).

The way it got invented was subtle. ``proc.returncode`` is filled in by
asyncio's child watcher thread, so there is a window after a process exits in
which it still reads None - and cleanup runs inside that window by
construction, because the stream ended when the process did. Signalling on
that reading routes through ``subprocess.Popen.send_signal``, which polls
first, and the poll reaps the child; the watcher's own ``waitpid`` then finds
nothing and asyncio substitutes 255. A failed exec is the fastest exit there
is, which made the status that reports one the likeliest of all to be lost.

The race cannot be provoked on demand, so what is asserted here is the
decision that closes it rather than the timing: a process that is ending is
waited for, not signalled.
"""

from __future__ import annotations

import asyncio
from typing import cast

import pytest

from syn_adapters.workspace_backends.agentic import stream_helpers
from syn_adapters.workspace_backends.agentic.stream_helpers import _cleanup_process

pytestmark = pytest.mark.unit


class _Process:
    """A process double that reports its status the way asyncio really does.

    ``returncode`` stays None until ``wait()`` has observed the exit, which is
    the whole point: a caller that reads the attribute and acts on it is acting
    on "not known yet", not on "still running".
    """

    def __init__(self, *, exits_after: int, status: int) -> None:
        self._waits_until_exit = exits_after
        self._status = status
        self.returncode: int | None = None
        self.signalled: list[str] = []

    async def wait(self) -> int:
        while self._waits_until_exit > 0:
            self._waits_until_exit -= 1
            await asyncio.sleep(0)
        self.returncode = self._status
        return self._status

    def terminate(self) -> None:
        self.signalled.append("terminate")

    def kill(self) -> None:
        self.signalled.append("kill")


def _as_process(double: _Process) -> asyncio.subprocess.Process:
    return cast("asyncio.subprocess.Process", double)


@pytest.mark.parametrize("status", [0, 126, 127, 3])
async def test_a_process_that_is_already_ending_is_waited_for_not_signalled(
    status: int,
) -> None:
    """The fix, stated as the rule it is.

    Every one of these statuses is load-bearing somewhere downstream, and all
    of them are reachable in the window where ``returncode`` still reads None.
    Signalling here is what let something other than the watcher reap the
    child and replace the status with 255.
    """
    proc = _Process(exits_after=2, status=status)

    exit_code = await _cleanup_process(_as_process(proc))

    assert exit_code == status
    assert proc.signalled == [], (
        "a process that was already on its way out must not be signalled - "
        "signalling it is what reaps it early and loses its real status"
    )


async def test_a_process_that_will_not_end_is_still_terminated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """And the rule does not cost the timeout path its teeth.

    A phase that hit its stream timeout leaves a process that is genuinely
    still running, and waiting for that one forever is how a workspace leaks.
    The grace period is bounded, and what follows it is the same escalation as
    before.
    """
    monkeypatch.setattr(
        "syn_adapters.workspace_backends.agentic.stream_helpers._SELF_EXIT_GRACE_SECONDS",
        0.01,
    )
    never_ends = 10**9
    proc = _Process(exits_after=never_ends, status=124)

    async def _stop_pretending_to_run() -> None:
        await asyncio.sleep(0.05)
        proc._waits_until_exit = 0

    async with asyncio.TaskGroup() as tasks:
        tasks.create_task(_stop_pretending_to_run())
        cleanup: asyncio.Task[int | None] = tasks.create_task(_cleanup_process(_as_process(proc)))

    assert cleanup.result() == 124
    assert proc.signalled == ["terminate"]


def test_the_grace_period_is_short_enough_to_be_invisible() -> None:
    """A guard on the one number, since nothing else here would notice it growing.

    It is paid on the timeout and cancellation paths, where a person is waiting
    for a phase to stop. Sub-second is the point; the process being waited for
    has already closed its stdout, so it needs milliseconds.
    """
    assert 0 < stream_helpers._SELF_EXIT_GRACE_SECONDS <= 1.0
