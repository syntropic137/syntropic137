"""What may count as proof that an agent process existed (#1047, #1065).

The fact these tests guard licenses one statement to a user: that a session
never started an agent, so its missing conversation log is not lost data. It
used to be taken from the stream advancing, which proves only that a `docker
exec` CLIENT started - and that client merges its own stderr into the agent's
stdout, so its failure diagnostics arrive looking exactly like agent output.

These drive the REAL adapter and the REAL observer against the two shapes a
`docker exec` failure actually takes, because a double cannot reproduce what
made this wrong. A mock raising ``RuntimeError`` from its first advance - the
previous guard - asserts a behaviour the real adapter does not have: it does
not raise when the client starts and the container is gone. It returns a line,
and exits non-zero long after the observer has fired.

The daemon is faked, not the transport: a ``docker`` on PATH reproduces the
observable behaviour of the real client, and everything from
``_build_exec_command`` inwards is production code.
"""

from __future__ import annotations

import os
import stat
from typing import TYPE_CHECKING, NamedTuple

import pytest

from syn_adapters.workspace_backends.agentic.stream_adapter import (
    AgenticEventStreamAdapter,
)
from syn_adapters.workspace_backends.agentic.stream_helpers import _build_exec_command
from syn_domain.contexts.orchestration import (
    AGENT_LAUNCH_MARKER as PUBLISHED_LAUNCH_MARKER,
)
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationHandle,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.agent_launch_observation import (
    AGENT_LAUNCH_MARKER,
    observing_launch,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from pathlib import Path

pytestmark = pytest.mark.unit

_CONTAINER = "agentic-ws-abc123"

#: Every fake client leaves this behind before doing anything else. Two of the
#: three cases are entirely silent, so without it a client that failed to run
#: at all would look identical to one that ran and refused the exec - and the
#: tests below would pass having exercised nothing. Deliberately NOT the
#: process exit code: a fast-exiting child is reported as 255 by asyncio's
#: child watcher often enough to make that control flaky.
_RECEIPT = 'open(sys.argv[0] + ".ran", "w").close()\n'

#: The daemon rejects the exec and the CLIENT reports it - on stderr, which the
#: adapter merges into stdout, and with an exit code that only exists once the
#: stream is over. Nothing ran inside the container.
_NO_SUCH_CONTAINER = (
    "import sys\n"
    + _RECEIPT
    + f'sys.stderr.write("Error response from daemon: No such container: {_CONTAINER}\\n")\n'
    + "sys.exit(1)\n"
)

#: The same failure without the courtesy of a diagnostic: the exec is refused
#: and the stream ends immediately, having yielded nothing.
_EXEC_REFUSED = "import sys\n" + _RECEIPT + "sys.exit(126)\n"

#: The daemon accepts the exec and creates a process from the container-side
#: argv, which is the only thing a real `docker exec` adds here. Skipping the
#: client's own flags and the container name leaves exactly what the daemon
#: would run - including the announce-then-exec wrapper under test.
_RUNS_THE_CONTAINER_ARGV = (
    "import os, sys\n"
    + _RECEIPT
    + """argv = sys.argv[1:]
assert argv[0] == "exec", argv
i = 1
while i < len(argv):
    if argv[i] in ("-i", "-t", "-d"):
        i += 1
    elif argv[i] in ("-w", "-e", "-u"):
        i += 2
    else:
        break
container_argv = argv[i + 1 :]
os.execvp(container_argv[0], container_argv)
"""
)


class _FakeDocker(NamedTuple):
    """A stream adapter wired to a ``docker`` that behaves a chosen way."""

    adapter: AgenticEventStreamAdapter
    receipt: Path

    @property
    def client_ran(self) -> bool:
        """Whether the fake client was really executed."""
        return self.receipt.exists()


@pytest.fixture
def fake_docker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[str], _FakeDocker]:
    """Put a ``docker`` behaving a given way on PATH, ahead of any real one."""

    def _install(behaviour: str) -> _FakeDocker:
        docker = tmp_path / "docker"
        docker.write_text(f"#!/usr/bin/env python3\n{behaviour}")
        docker.chmod(docker.stat().st_mode | stat.S_IEXEC)
        monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")

        adapter = AgenticEventStreamAdapter()
        adapter.set_provider(object())
        return _FakeDocker(adapter, tmp_path / "docker.ran")

    return _install


async def _launched_and_lines(
    adapter: AgenticEventStreamAdapter, command: list[str]
) -> tuple[bool, list[str]]:
    """Stream one phase through the real observer; report what it concluded."""
    launched = False

    async def observer() -> None:
        nonlocal launched
        launched = True

    handle = IsolationHandle(isolation_id="container-abc123", isolation_type="docker")
    stream = observing_launch(adapter.stream(handle, command), observer)
    lines = [line async for line in stream]
    return launched, lines


async def test_a_client_diagnostic_is_not_evidence_that_an_agent_ran(
    fake_docker: Callable[[str], _FakeDocker],
) -> None:
    """The break, in its exact production shape.

    The container is gone, so the client says so and quits. The stream carries
    a line and then ends cleanly - the two things the launch signal used to be
    taken from - and no process was ever created inside the container. The
    diagnostic is asserted on deliberately: without it this would pass against
    an empty stream and prove nothing.
    """
    docker = fake_docker(_NO_SUCH_CONTAINER)

    launched, lines = await _launched_and_lines(docker.adapter, ["claude", "-p", "hello"])

    assert lines == [f"Error response from daemon: No such container: {_CONTAINER}"], (
        "the fake client must really emit its diagnostic, or this test cannot fail"
    )
    assert launched is False


async def test_a_refused_exec_is_not_evidence_that_an_agent_ran(
    fake_docker: Callable[[str], _FakeDocker],
) -> None:
    """The silent form of the same failure.

    Nothing is written and the stream ends at once. Read as "the process ran
    and printed nothing" that becomes a launch; it is a client that never got
    inside the container.
    """
    docker = fake_docker(_EXEC_REFUSED)

    launched, lines = await _launched_and_lines(docker.adapter, ["claude", "-p", "hello"])

    assert docker.client_ran, "the fake client must really run, or this test cannot fail"
    assert lines == []
    assert launched is False


async def test_a_process_in_the_container_is_evidence_and_its_output_is_untouched(
    fake_docker: Callable[[str], _FakeDocker],
) -> None:
    """The positive case, through the real wrapper.

    Drop the announce-then-exec wrapper from ``_build_exec_command`` and this
    fails: nothing else in the stream can attest a launch. The marker must also
    stay out of the stream - a processor parsing JSONL would choke on it.
    """
    docker = fake_docker(_RUNS_THE_CONTAINER_ARGV)

    launched, lines = await _launched_and_lines(
        docker.adapter, ["python3", "-c", 'print("{\\"type\\":\\"result\\"}")']
    )

    assert launched is True
    assert lines == ['{"type":"result"}']
    assert AGENT_LAUNCH_MARKER not in lines


async def test_an_agent_that_dies_before_printing_anything_still_counts(
    fake_docker: Callable[[str], _FakeDocker],
) -> None:
    """The mirror-image error, which counting agent output would commit.

    A process that exits before its first line is silent in the same way a
    refused exec is, and calling that never-started would be the same false
    statement pointing the other way. It has already announced itself by the
    time it dies.
    """
    docker = fake_docker(_RUNS_THE_CONTAINER_ARGV)

    launched, lines = await _launched_and_lines(
        docker.adapter, ["python3", "-c", "raise SystemExit(3)"]
    )

    assert launched is True
    assert lines == []


def _announced_marker(exec_argv: list[str]) -> str:
    """The marker the adapter really put on the wire, read back out of the argv.

    Taken positionally, from what a container would be handed, rather than by
    importing the constant a third time - an assertion that re-imports the
    value it is checking cannot see the two halves disagree.
    """
    return exec_argv[exec_argv.index("syn-launch") + 1]


async def _observed(lines: list[str]) -> tuple[bool, list[str]]:
    """Put lines through the real observer; report what it concluded."""
    launched = False

    async def observer() -> None:
        nonlocal launched
        launched = True

    async def stream() -> AsyncIterator[str]:
        for line in lines:
            yield line

    survived = [line async for line in observing_launch(stream(), observer)]
    return launched, survived


async def test_the_marker_the_adapter_announces_is_the_one_the_domain_counts() -> None:
    """The hop between the two halves of the launch contract (#1065).

    ``_build_exec_command`` bakes the marker into a container-side argv and
    reaches it through the orchestration context's public API;
    ``observing_launch`` decides what counts as evidence and defines it. Both
    ends are exercised above, but only against each other - so a public export
    that drifted from the constant it re-exports would leave the adapter
    announcing a string the observer ignores, every session would report
    never-started, and every other test here would still pass.
    """
    argv = _build_exec_command(_CONTAINER, ["claude", "-p", "hello"], None, None)
    announced = _announced_marker(argv)

    launched, survived = await _observed([announced, '{"type":"result"}'])

    assert launched is True, (
        f"the observer does not count {announced!r}, the line the adapter really prints"
    )
    assert survived == ['{"type":"result"}'], "the marker is consumed, not forwarded"
    assert announced == PUBLISHED_LAUNCH_MARKER, (
        "the context publishes this constant as the wire contract; the adapter "
        "must be announcing exactly what it publishes"
    )
