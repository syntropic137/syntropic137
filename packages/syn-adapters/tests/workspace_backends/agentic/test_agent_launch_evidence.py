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

The marker alone is not the answer either, and the failures below are why. It
is printed immediately BEFORE the ``exec`` that would make its announcer into
the agent, so at the moment it arrives it is a prediction; when the exec then
fails, a shell has attested a launch that never happened (#1065). So each case
here is run to the end and settled against the status the adapter really
reported - a real one, produced by a real ``sh`` failing a real ``exec``, not
a number chosen by the test.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from typing import TYPE_CHECKING, NamedTuple

import pytest

from syn_adapters.workspace_backends.agentic.stream_adapter import (
    AgenticEventStreamAdapter,
)
from syn_adapters.workspace_backends.agentic.stream_helpers import _build_exec_command
from syn_domain.contexts.orchestration import (
    AGENT_LAUNCH_MARKER as PUBLISHED_LAUNCH_MARKER,
)
from syn_domain.contexts.orchestration import announce_as
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationHandle,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.agent_launch_observation import (
    AGENT_LAUNCH_MARKER,
    AgentLaunchEvidence,
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
#: process exit code, which says whether the WRAPPER ran, not the client: the
#: two are different questions and each case below asks both.
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


async def _launches_and_lines(
    adapter: AgenticEventStreamAdapter, command: list[str]
) -> tuple[int, list[str]]:
    """Stream one phase through the real observer; report how often it recorded a launch.

    Settled with the status the adapter really reported for this stream, which
    is what turns the marker's "about to exec" into a fact or discards it.

    Settled TWICE on purpose. The handler settles from a ``finally``, so a
    second call is reachable in production, and counting rather than flagging
    means no test here can be satisfied by a launch recorded once per call.
    """
    launches = 0

    async def observer() -> None:
        nonlocal launches
        launches += 1

    handle = IsolationHandle(isolation_id="container-abc123", isolation_type="docker")
    evidence = AgentLaunchEvidence(observer)
    lines = [
        line
        async for line in evidence.observing(
            adapter.stream(handle, command, wrapper_name=evidence.wrapper_name),
        )
    ]
    await evidence.settle(adapter.last_exit_code)
    await evidence.settle(adapter.last_exit_code)
    return launches, lines


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

    launches, lines = await _launches_and_lines(docker.adapter, ["claude", "-p", "hello"])

    assert lines == [f"Error response from daemon: No such container: {_CONTAINER}"], (
        "the fake client must really emit its diagnostic, or this test cannot fail"
    )
    assert launches == 0


async def test_a_refused_exec_is_not_evidence_that_an_agent_ran(
    fake_docker: Callable[[str], _FakeDocker],
) -> None:
    """The silent form of the same failure.

    Nothing is written and the stream ends at once. Read as "the process ran
    and printed nothing" that becomes a launch; it is a client that never got
    inside the container.
    """
    docker = fake_docker(_EXEC_REFUSED)

    launches, lines = await _launches_and_lines(docker.adapter, ["claude", "-p", "hello"])

    assert docker.client_ran, "the fake client must really run, or this test cannot fail"
    assert lines == []
    assert launches == 0


async def test_a_process_in_the_container_is_evidence_and_its_output_is_untouched(
    fake_docker: Callable[[str], _FakeDocker],
) -> None:
    """The positive case, through the real wrapper.

    Drop the announce-then-exec wrapper from ``_build_exec_command`` and this
    fails: nothing else in the stream can attest a launch. The marker must also
    stay out of the stream - a processor parsing JSONL would choke on it.

    The agent then exits 0, which is the ordinary end of every successful
    phase. Settling reads that status, so this is also where a retraction rule
    that keyed on the stream ENDING rather than on how it ended would show
    itself: the launch has to survive the process finishing.
    """
    docker = fake_docker(_RUNS_THE_CONTAINER_ARGV)

    launches, lines = await _launches_and_lines(
        docker.adapter, ["python3", "-c", 'print("{\\"type\\":\\"result\\"}")']
    )

    assert launches == 1, "recorded once, and not once per settle"
    assert docker.adapter.last_exit_code == 0, "the agent must really have exited normally"
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

    launches, lines = await _launches_and_lines(
        docker.adapter, ["python3", "-c", "raise SystemExit(3)"]
    )

    assert launches == 1
    assert lines == []
    assert docker.adapter.last_exit_code == 3, (
        "an agent choosing its own non-zero status is not a shell reporting a failed exec"
    )


async def test_a_missing_agent_binary_is_not_evidence_that_an_agent_ran(
    fake_docker: Callable[[str], _FakeDocker],
) -> None:
    """The failure the announcement itself used to manufacture (#1065).

    Everything about the transport succeeds here: the daemon accepts the exec
    and a shell really runs inside the container. The only thing that never
    happens is the agent - ``exec`` cannot replace the shell with a binary that
    is not there. Announcing before ``exec`` made this byte-identical to a real
    launch, so the exact case the marker exists to detect was the one it could
    not see, and the API would tell a user their session ran and lost its log.
    """
    docker = fake_docker(_RUNS_THE_CONTAINER_ARGV)
    missing = "/definitely/missing/claude"

    launches, lines = await _launches_and_lines(docker.adapter, [missing, "-p", "hello"])

    assert docker.client_ran, "the fake client must really run, or this test cannot fail"
    assert any(missing in line for line in lines), (
        f"the shell must really have tried and failed to exec {missing}; without its "
        f"diagnostic this would pass against a stream that never reached the wrapper: {lines}"
    )
    assert launches == 0


async def test_an_agent_binary_that_cannot_be_executed_is_not_evidence(
    fake_docker: Callable[[str], _FakeDocker],
    tmp_path: Path,
) -> None:
    """The same lie told by a file that exists, which resolution alone misses.

    A name that resolves is not a name that runs, and the shells disagree about
    which is which: dash hands back any path containing a slash unchecked, bash
    rejects it. A guard that only asked whether the name resolved would
    therefore pass this case or not depending on which /bin/sh the workspace
    image happens to ship, while ``exec`` fails 126 either way.
    """
    agent = tmp_path / "claude-without-the-bit"
    agent.write_text("#!/bin/sh\necho 'never reached'\n")
    agent.chmod(0o644)
    docker = fake_docker(_RUNS_THE_CONTAINER_ARGV)

    launches, lines = await _launches_and_lines(docker.adapter, [str(agent), "-p", "hello"])

    assert docker.client_ran, "the fake client must really run, or this test cannot fail"
    assert any(str(agent) in line for line in lines), (
        f"the shell must really have tried and failed to exec {agent}; without its "
        f"diagnostic this would pass against a stream that never reached the wrapper: {lines}"
    )
    assert launches == 0


async def test_an_agent_whose_interpreter_is_missing_is_not_evidence(
    fake_docker: Callable[[str], _FakeDocker],
    tmp_path: Path,
) -> None:
    """The case that defeats every check a wrapper could make before ``exec``.

    This file resolves, is a regular file, and carries the executable bit, so
    the three questions a shell can ask about it all answer yes. The kernel
    asks a fourth - can the interpreter on line one be loaded - and answers no,
    reporting ENOENT for a path that plainly exists. ``exec`` fails 127 with
    the marker already on the wire.

    An earlier fix guarded the announcement with exactly those three questions
    and was rejected on this counterexample, which is why it is pinned here:
    the point is not that these three checks were the wrong three, it is that
    predicting ``exec`` cannot be done from before it. The launch is settled
    from the status afterwards instead, and only that is proof against a
    counterexample nobody has thought of yet.
    """
    agent = tmp_path / "claude-with-a-missing-interpreter"
    agent.write_text("#!/definitely/missing/interpreter\nprint('never reached')\n")
    agent.chmod(0o755)
    docker = fake_docker(_RUNS_THE_CONTAINER_ARGV)

    launches, lines = await _launches_and_lines(docker.adapter, [str(agent), "-p", "hello"])

    assert agent.is_file() and os.access(agent, os.X_OK), (
        "the file must really resolve and really be executable, or this test is "
        "not the case that defeats a pre-exec guard"
    )
    assert docker.adapter.last_exit_code == 127, (
        "the real status must reach the observer; a cleanup path that reaped the "
        "child early would substitute 255 and this retraction would not fire"
    )
    assert any(str(agent) in line for line in lines), (
        f"the shell must really have tried and failed to exec {agent}; without its "
        f"diagnostic this would pass against a stream that never reached the wrapper: {lines}"
    )
    assert launches == 0


async def test_an_agent_that_spoke_and_then_exited_127_is_still_launched(
    fake_docker: Callable[[str], _FakeDocker],
) -> None:
    """The retraction's own residue, which reading the status alone got wrong (#1065).

    126 and 127 are not reserved. A process that really ran is free to exit
    with either - a shell script the agent invoked could not find a tool, a
    harness passes its child's status straight through - and this one has
    already put a line on the stream that no failed exec could have produced,
    because a failed exec means there was never an agent to produce it.

    Settling on the status alone recorded this session as never having started
    an agent, and the API then told its user the missing conversation log was
    not lost data. That is the same false statement as #1047, reached from the
    other direction.
    """
    docker = fake_docker(_RUNS_THE_CONTAINER_ARGV)

    launches, lines = await _launches_and_lines(
        docker.adapter,
        ["python3", "-c", 'print("{\\"type\\":\\"result\\"}"); raise SystemExit(127)'],
    )

    assert docker.adapter.last_exit_code == 127, (
        "the agent must really have chosen 127 itself, or this is not the case"
    )
    assert lines == ['{"type":"result"}'], (
        f"the agent must really have spoken before dying, or this cannot fail: {lines}"
    )
    assert launches == 1


async def test_an_agent_that_impersonates_the_wrapper_is_still_launched(
    fake_docker: Callable[[str], _FakeDocker],
) -> None:
    """Why the wrapper's name is minted rather than written down (#1065).

    Agent stdout and the wrapper's stderr are one stream by design (ADR-043),
    so whatever the wrapper is called, an agent can print a line that starts
    the same way. If that name were a constant in this repo - and it was, and
    it is quoted verbatim in the fixtures of this very test suite, which the
    agents working on it run - then an agent could print its own retraction and
    be reported as never having existed.

    So the readable part is not the evidence. This agent forges it exactly and
    exits 127, and the launch survives, because the name it could not see is
    the part that counts.
    """
    docker = fake_docker(_RUNS_THE_CONTAINER_ARGV)
    forged = "syn-launch: 1: exec: /usr/local/bin/claude: not found"

    launches, lines = await _launches_and_lines(
        docker.adapter, ["python3", "-c", f"print({forged!r}); raise SystemExit(127)"]
    )

    assert lines == [forged], "the agent must really have forged the line, or this cannot fail"
    assert docker.adapter.last_exit_code == 127
    assert launches == 1


async def test_an_agent_that_announces_a_wrapper_name_of_its_own_is_still_launched(
    fake_docker: Callable[[str], _FakeDocker],
) -> None:
    """The forgery a minted name alone does not stop (#1065).

    Randomness makes the wrapper's name unguessable; it does not make it
    unREPLACEABLE. An observer that learned which name to trust FROM the stream
    could be told a second time, so an agent never had to guess: announce a
    name of your own, sign a diagnostic with it, exit 127, and the observer
    retracts a launch that really happened - the false NOT_LAUNCHED this whole
    module exists to prevent, reachable from ordinary agent output.

    That is an ordering property ("exactly one announcement, before any agent
    output"), and no amount of entropy enforces an ordering. So the ordering is
    removed instead: the name is minted by the observer BEFORE this stream
    exists and handed to the transport, and a second announcement is just a
    line the agent typed.

    The whole chain is real - the production command builder, a real /bin/sh
    running the real wrapper, a real failed process status, the real observer -
    because the defect lived in exactly the hop between them.
    """
    docker = fake_docker(_RUNS_THE_CONTAINER_ARGV)
    forged_name = "syn-launch-deadbeefdeadbeef"
    forged_announcement = announce_as(forged_name)
    forged_diagnostic = f"{forged_name}: 1: exec: /usr/local/bin/claude: not found"

    launches, lines = await _launches_and_lines(
        docker.adapter,
        [
            "python3",
            "-c",
            f"print({forged_announcement!r}); print({forged_diagnostic!r}); raise SystemExit(127)",
        ],
    )

    assert lines == [forged_announcement, forged_diagnostic], (
        "the agent must really have announced a wrapper name of its own AND signed a "
        f"line with it, or this test cannot fail; a stream missing either is not the "
        f"uncovered shape (more than one announcement on one stream): {lines}"
    )
    assert docker.adapter.last_exit_code == 127, (
        "the retraction must really be armed, or the launch would survive for the wrong reason"
    )
    assert launches == 1, (
        "the agent genuinely launched - the real wrapper announced and exec'd it - so "
        "a name the agent chose must not be able to retract that"
    )


class _ContainerArgv(NamedTuple):
    """The three things the adapter hands a container, read back out of the argv.

    Taken positionally, from what a container would really be given, rather
    than by importing the constants a third time - an assertion that re-imports
    the value it is checking cannot see the two halves disagree.
    """

    script: str
    wrapper: str
    announcement: str

    @classmethod
    def of(cls, exec_argv: list[str]) -> _ContainerArgv:
        sh = exec_argv.index("sh")
        return cls(*exec_argv[sh + 2 : sh + 5])


async def _observed(lines_for: Callable[[str], list[str]]) -> tuple[bool, list[str]]:
    """Put lines through the real observer, settled as a clean exit would settle it.

    ``lines_for`` is handed the name the evidence minted, because that is the
    only way a stream can carry the announcement this evidence listens for.
    Taking a plain list instead would let a case pass while the transport
    announced under a name of its own - which is the whole failure being
    guarded against, so the fixture is not allowed to be able to express it.
    """
    launched = False

    async def observer() -> None:
        nonlocal launched
        launched = True

    evidence = AgentLaunchEvidence(observer)

    async def stream() -> AsyncIterator[str]:
        for line in lines_for(evidence.wrapper_name):
            yield line

    survived = [line async for line in evidence.observing(stream())]
    await evidence.settle(exit_code=0)
    return launched, survived


async def test_the_announcement_the_adapter_makes_is_the_one_the_domain_counts() -> None:
    """The hop between the two halves of the launch contract (#1065).

    ``_build_exec_command`` bakes the announcement into a container-side argv
    and reaches it through the orchestration context's public API;
    ``AgentLaunchEvidence`` decides what counts as evidence and defines it. Both
    ends are exercised above, but only against each other - so a public export
    that drifted from the line it re-exports would leave the adapter announcing
    a string the observer ignores, every session would report never-started,
    and every other test here would still pass.
    """
    built: list[_ContainerArgv] = []

    def as_the_adapter_would(wrapper_name: str) -> list[str]:
        built.append(
            _ContainerArgv.of(
                _build_exec_command(
                    _CONTAINER,
                    ["claude", "-p", "hello"],
                    None,
                    None,
                    wrapper_name=wrapper_name,
                )
            )
        )
        return [built[0].announcement, '{"type":"result"}']

    launched, survived = await _observed(as_the_adapter_would)

    argv = built[0]
    assert launched is True, (
        f"the observer does not count {argv.announcement!r}, the line the adapter really prints"
    )
    assert survived == ['{"type":"result"}'], "the announcement is consumed, not forwarded"
    assert argv.announcement == announce_as(argv.wrapper), (
        "the context owns this line's format; the adapter must announce exactly what "
        "it publishes, or the observer will not recognise the wrapper it then quotes"
    )
    assert argv.announcement.startswith(PUBLISHED_LAUNCH_MARKER), (
        "the context publishes this constant as the wire contract"
    )


async def test_each_exec_is_wrapped_under_a_name_the_last_one_did_not_use() -> None:
    """What stops the discriminator from being a string an agent can type (#1065).

    The retraction now turns on whether a line was signed by the wrapper, and
    agent stdout and the wrapper's stderr are the same stream by design
    (ADR-043). A wrapper named by a constant would therefore let an agent
    print its own retraction and be reported as never having existed - the
    exact false statement this module exists to prevent, reachable from
    ordinary output. Being unable to guess the name is the whole defence, so a
    name that repeats is the defect.
    """
    names = {
        _ContainerArgv.of(
            _build_exec_command(
                _CONTAINER,
                ["claude"],
                None,
                None,
                wrapper_name=AgentLaunchEvidence(None).wrapper_name,
            )
        ).wrapper
        for _ in range(50)
    }

    assert len(names) == 50, f"wrapper names repeat across execs: {sorted(names)[:5]}"
    assert all(len(name) >= 16 for name in names), f"too short to be unguessable: {names}"


@pytest.mark.parametrize("shell", ["dash", "bash"])
async def test_the_shell_signs_its_exec_diagnostic_with_the_name_we_gave_it(shell: str) -> None:
    """The property the retraction rests on, taken from a real shell (#1065).

    ``AgentLaunchEvidence`` tells the wrapper's voice from the agent's by the
    ``$0`` this repo sets, and NOT by the wording after it - because the
    wording is not ours. These two disagree about it completely:

        dash: ``NAME: 1: exec: /missing: not found``
        bash: ``NAME: line 1: /missing: No such file or directory``

    Which of them is /bin/sh is a property of the workspace image, so a rule
    that read the wording would pass here and fail in production the day that
    image changed. Both agree on the prefix, and this is what pins that.
    """
    if (shell_path := shutil.which(shell)) is None:
        pytest.skip(f"{shell} is not installed")
    argv = _ContainerArgv.of(
        _build_exec_command(
            _CONTAINER,
            ["/definitely/missing/claude"],
            None,
            None,
            wrapper_name=AgentLaunchEvidence(None).wrapper_name,
        )
    )

    missing = "/definitely/missing/claude"
    result = subprocess.run(
        [shell_path, "-c", argv.script, argv.wrapper, argv.announcement, missing],
        capture_output=True,
        text=True,
        check=False,
    )

    printed = (result.stdout + result.stderr).splitlines()
    assert argv.announcement in printed, f"{shell} did not make the announcement: {printed}"
    diagnostic = next(line for line in printed if line != argv.announcement)
    assert diagnostic.startswith(f"{argv.wrapper}:"), (
        f"{shell} does not sign its exec diagnostic with $0: {diagnostic!r}"
    )
    assert result.returncode == 127
