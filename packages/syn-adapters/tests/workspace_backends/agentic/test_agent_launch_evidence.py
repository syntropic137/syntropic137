"""What may count as proof that an agent process existed (#1047, #1065).

The fact these tests guard licenses one statement to a user: that a session
never started an agent, so its missing conversation log is not lost data. It
used to be taken from the stream advancing, which proves only that a `docker
exec` CLIENT started - and that client merges its own stderr into the agent's
stdout, so its failure diagnostics arrive looking exactly like agent output.

These drive the REAL adapter and the REAL observer through agentic-workspace's
REAL launcher: the stream runs on the provider operation contract, and the
provider here is AW's local one, whose launch marker is printed by a transient
``sh`` named by the marker's argv0 that the workload then replaces - the same
announce-then-exec shape the Docker provider runs inside the container. A real
``sh`` really fails a real ``exec``. Transport failures (no such container, a
refused exec) are now the provider's to report: ``start`` raises rather than
merging a client diagnostic into the stream, so there is no stream line left
for them to forge.

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
import sys
from typing import TYPE_CHECKING, NamedTuple

import pytest
from agentic_isolation import WorkspaceConfig, WorkspaceLocalProvider
from agentic_isolation.providers.operation_spool import OperationFailure

from syn_adapters.workspace_backends.agentic.credentials import WorkspaceCredentials
from syn_adapters.workspace_backends.agentic.stream_adapter import (
    AgenticEventStreamAdapter,
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

    from agentic_isolation.providers.base import Workspace

from syn_shared.settings.session_store import SessionStoreSettings

pytestmark = pytest.mark.unit


class _Launch(NamedTuple):
    """A stream adapter wired to AW's local operations provider."""

    adapter: AgenticEventStreamAdapter


class _LocalHost:
    def __init__(self, provider: WorkspaceLocalProvider, workspace: Workspace) -> None:
        self.operations = provider
        self.credentials = WorkspaceCredentials(SessionStoreSettings())
        self._workspace = workspace

    def workspace(self, isolation_id: str) -> Workspace | None:
        return self._workspace


@pytest.fixture
async def local_launch(tmp_path: Path) -> AsyncIterator[Callable[[], _Launch]]:
    """A real launcher on this host: the workload runs, unisolated, under ``sh``."""
    provider = WorkspaceLocalProvider(base_dir=tmp_path, allow_insecure=True)
    workspace = await provider.create(WorkspaceConfig(provider="local"))

    def _make() -> _Launch:
        return _Launch(AgenticEventStreamAdapter(_LocalHost(provider, workspace)))  # type: ignore[arg-type]

    yield _make
    await provider.destroy(workspace)


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


async def test_a_process_in_the_container_is_evidence_and_its_output_is_untouched(
    local_launch: Callable[[], _Launch],
) -> None:
    """The positive case, through the real wrapper.

    Drop the launch marker from the stream adapter's ``OperationSpec`` and this
    fails: nothing else in the stream can attest a launch. The marker must also
    stay out of the stream - a processor parsing JSONL would choke on it.

    The agent then exits 0, which is the ordinary end of every successful
    phase. Settling reads that status, so this is also where a retraction rule
    that keyed on the stream ENDING rather than on how it ended would show
    itself: the launch has to survive the process finishing.
    """
    docker = local_launch()

    launches, lines = await _launches_and_lines(
        docker.adapter, ["python3", "-c", 'print("{\\"type\\":\\"result\\"}")']
    )

    assert launches == 1, "recorded once, and not once per settle"
    assert docker.adapter.last_exit_code == 0, "the agent must really have exited normally"
    assert lines == ['{"type":"result"}']
    assert AGENT_LAUNCH_MARKER not in lines


@pytest.mark.parametrize("exit_code", [3, 126, 127])
async def test_an_agent_that_dies_before_printing_anything_still_counts(
    local_launch: Callable[[], _Launch],
    exit_code: int,
) -> None:
    """The mirror-image error, which counting agent output would commit.

    A process that exits before its first line is silent in the same way a
    refused exec is, and calling that never-started would be the same false
    statement pointing the other way. It has already announced itself by the
    time it dies.
    """
    docker = local_launch()

    launches, lines = await _launches_and_lines(
        docker.adapter, ["python3", "-c", f"raise SystemExit({exit_code})"]
    )

    assert launches == 1
    assert lines == []
    assert docker.adapter.last_exit_code == exit_code, (
        "an agent choosing its own non-zero status is not a shell reporting a failed exec"
    )


async def test_a_missing_agent_binary_is_not_evidence_that_an_agent_ran(
    local_launch: Callable[[], _Launch],
) -> None:
    """The failure the announcement itself used to manufacture (#1065).

    Everything about the transport succeeds here: the daemon accepts the exec
    and a shell really runs inside the container. The only thing that never
    happens is the agent - ``exec`` cannot replace the shell with a binary that
    is not there. Announcing before ``exec`` made this byte-identical to a real
    launch, so the exact case the marker exists to detect was the one it could
    not see, and the API would tell a user their session ran and lost its log.
    """
    docker = local_launch()
    missing = "/definitely/missing/claude"

    # AW's local provider refuses an argv0 it cannot exec before launching
    # anything, so no stream exists to carry a marker. The Docker provider
    # cannot see inside the container and lets the shell fail instead; that
    # shape is the missing-interpreter case below.
    with pytest.raises(OperationFailure, match="could not launch"):
        await _launches_and_lines(docker.adapter, [missing, "-p", "hello"])


async def test_an_agent_binary_that_cannot_be_executed_is_not_evidence(
    local_launch: Callable[[], _Launch],
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
    docker = local_launch()

    # AW's local provider refuses an argv0 it cannot exec before launching
    # anything, so no stream exists to carry a marker. The Docker provider
    # cannot see inside the container and lets the shell fail instead; that
    # shape is the missing-interpreter case below.
    with pytest.raises(OperationFailure, match="could not launch"):
        await _launches_and_lines(docker.adapter, [str(agent), "-p", "hello"])


# The one case here whose expected status is decided by the host rather than by
# this repo. Every other exit code in this file is either chosen by the test's
# own fake agent or is the POSIX "command not found" convention that all shells
# share; this one comes from the kernel refusing a shebang, and the shells
# disagree about how to report it: Linux /bin/sh (dash) exits 127, macOS
# /bin/sh exits 1 (#1170). 127 is the true answer for the Linux workspace
# image, which is the only place this code runs, so asserting it on a host that
# answers differently tests the host. Skipped there rather than relaxed to
# "non-zero": settle() keys on _COULD_NOT_EXEC = {126, 127}, so 1 and 127 mean
# opposite things to the retraction and a loosened assertion would re-admit the
# over-retraction #1065 closed.
@pytest.mark.skipif(
    sys.platform != "linux",
    reason=(
        "exec of a missing shebang interpreter exits 127 under Linux /bin/sh (dash) "
        "and 1 under macOS /bin/sh; 127 is the workspace image's answer (#1170)"
    ),
)
async def test_an_agent_whose_interpreter_is_missing_is_not_evidence(
    local_launch: Callable[[], _Launch],
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
    docker = local_launch()

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


def test_the_missing_interpreter_case_still_runs_where_it_is_true() -> None:
    """That the guard above narrows this file's coverage and does not delete it.

    A platform skip is the one kind of fix that cannot fail loudly when it is
    wrong: widen it by a character - invert the comparison, name the wrong
    platform, drop the condition for a bare ``skip`` while chasing a red suite -
    and the case that #1065 was rejected on stops being checked ANYWHERE, on
    every host including CI, while the file still reports all green. Nothing
    else here would notice, because every other test in it passes with this one
    skipped.

    So the guard is asserted from outside rather than trusted: Linux is where
    the 127 is true, and Linux is therefore where this case must really run.
    """
    # getattr, not attribute access: a function carrying no marks at all has no
    # ``pytestmark``, and that is exactly the "someone deleted the guard" case
    # this test exists to report - it must arrive as the message below, not as
    # an AttributeError the reader has to decode.
    marks = getattr(test_an_agent_whose_interpreter_is_missing_is_not_evidence, "pytestmark", [])
    guards = [mark for mark in marks if mark.name == "skipif"]

    assert guards, (
        "the missing-interpreter case has lost its platform guard; on macOS it "
        "fails with the host's exit code rather than skipping (#1170)"
    )
    assert not (sys.platform == "linux" and any(mark.args[0] for mark in guards)), (
        "the platform guard skips the missing-interpreter case on Linux, which is "
        "the one host whose /bin/sh really does exit 127 - so the counterexample "
        "that #1065's pre-exec guard was rejected on is now checked nowhere"
    )


async def test_an_agent_that_spoke_and_then_exited_127_is_still_launched(
    local_launch: Callable[[], _Launch],
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
    docker = local_launch()

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
    local_launch: Callable[[], _Launch],
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
    docker = local_launch()
    forged = "syn-launch: 1: exec: /usr/local/bin/claude: not found"

    launches, lines = await _launches_and_lines(
        docker.adapter, ["python3", "-c", f"print({forged!r}); raise SystemExit(127)"]
    )

    assert lines == [forged], "the agent must really have forged the line, or this cannot fail"
    assert docker.adapter.last_exit_code == 127
    assert launches == 1


async def test_an_agent_that_announces_a_wrapper_name_of_its_own_is_still_launched(
    local_launch: Callable[[], _Launch],
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
    docker = local_launch()
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

    assert docker.adapter.last_exit_code == 127, (
        "the retraction must really be armed, or the launch would survive for the wrong reason"
    )
    assert launches == 1, (
        "the agent genuinely launched - the real wrapper announced and exec'd it - so "
        "a name the agent chose must not be able to retract that"
    )
    assert lines == [forged_announcement, forged_diagnostic], (
        "and both forged lines must reach the stream untouched, or this test is not the "
        "uncovered shape (MORE THAN ONE announcement-shaped line on one stream). An "
        "observer that consumed either had recognised a name it did not mint, which is "
        f"the defect itself: {lines}"
    )


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
