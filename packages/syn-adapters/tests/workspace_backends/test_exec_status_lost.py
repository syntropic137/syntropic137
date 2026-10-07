"""A docker exec that comes back with no status and no output (selfhost, 2026-10-06/07).

THE INCIDENT. Four verify/reverify phases failed with "Secret-injection setup
for phase '...' failed without reporting an exit status (-1) and printed
nothing", and exec-ff7e0c990b00 failed closed with "unable to remove staged
codex credential ... attempts=4 [#1 exit=-1 (no exit status), ...]". Neither
record said why.

THE CAUSE, from the API log. The API event loop froze for 60-190s at a time,
always between "copy_from: Checking path" and "copy_from: Collected file": a
DEBUG listing of the whole workspace (130-170k entries) ran on the loop even
though no handler printed it. exec-27fed66a653d's setup started 06:21:54, the
loop froze 06:21:56-06:24:15, and the setup came back at 06:24:15 as exit -1
with nothing on stderr - 141s against its 120s timeout.

THE MECHANISM, pinned by the first test below against the real provider: a
deadline that expires while the loop is blocked lands on a process that has
already exited, ``proc.kill()`` raises an empty ``ProcessLookupError``, and the
provider's catch-all reports that as exit -1 with ``stderr=""``.

The remaining tests drive the PRODUCTION path - ``run_setup_phase`` through a
real ``ManagedWorkspace`` and a real ``AgenticIsolationAdapter`` - with only the
provider underneath replaced, so the shape enters exactly where docker hands
it over.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from agentic_isolation import ExecuteResult, WorkspaceDockerProvider

from syn_adapters.workspace_backends import exec_status_lost
from syn_adapters.workspace_backends.agentic import adapter_copy
from syn_adapters.workspace_backends.agentic.adapter import AgenticIsolationAdapter
from syn_adapters.workspace_backends.service import setup_phase
from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
from syn_adapters.workspace_backends.service.setup_phase import run_setup_phase
from syn_adapters.workspace_backends.service.setup_phase_secrets import SetupPhaseSecrets
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationHandle,
)
from syn_shared.process_exit import describe_process_failure

pytestmark = [pytest.mark.unit]

_ISOLATION_ID = "ws-f98153c5"
_CONTAINER = "agentic-ws-f98153c5"
_STATE = "running oom_killed=false restarts=0 exit_code=0"


def _lost(duration_ms: float = 141_000.0) -> ExecuteResult:
    """Exactly what the provider returned for exec-27fed66a653d's setup."""
    return ExecuteResult(exit_code=-1, stdout="", stderr="", duration_ms=duration_ms)


def _ok(stdout: str = "") -> ExecuteResult:
    return ExecuteResult(exit_code=0, stdout=stdout, stderr="", duration_ms=5.0)


@dataclass
class _Docker:
    """The provider, minus docker. Scripted per command; never invents an answer."""

    setup: list[ExecuteResult]
    removal: list[ExecuteResult] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    written: list[str] = field(default_factory=list)

    async def execute(self, _workspace: object, command: str, **_kw: object) -> ExecuteResult:
        self.commands.append(command)
        if "setup.sh" in command:
            return self.setup.pop(0)
        if command.startswith("rm -f -- /workspace/.setup/codex-auth.json"):
            return self.removal.pop(0) if self.removal else _ok()
        if "STAGED_CREDENTIAL" in command:
            return _ok("STAGED_CREDENTIAL_ABSENT\n")
        return _ok()  # clear_secrets' cleanup script and its own removal

    async def write_file(self, _workspace: object, path: str, _content: bytes) -> None:
        self.written.append(path)

    def setup_runs(self) -> int:
        return sum("setup.sh" in c for c in self.commands)


class _Service:
    def __init__(self, isolation: AgenticIsolationAdapter) -> None:
        self._isolation = isolation


def _workspace(docker: _Docker) -> ManagedWorkspace:
    adapter = object.__new__(AgenticIsolationAdapter)
    adapter._provider = docker  # type: ignore[attr-defined]  # the one double
    adapter._workspaces = {_ISOLATION_ID: object()}  # type: ignore[attr-defined]
    return ManagedWorkspace(
        workspace_id="307ff22a",
        execution_id="exec-27fed66a653d",
        aggregate=MagicMock(),
        isolation_handle=IsolationHandle(isolation_id=_ISOLATION_ID, isolation_type="docker"),
        sidecar_handle=None,
        _service=_Service(adapter),  # type: ignore[arg-type]
    )


@pytest.fixture(autouse=True)
def _no_real_docker(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """`docker inspect` answers as the container did: running, never restarted."""
    asked: list[str] = []

    async def _inspect(name: str) -> str:
        asked.append(name)
        return _STATE

    monkeypatch.setattr(exec_status_lost, "container_state", _inspect)
    monkeypatch.setattr(setup_phase, "_SETUP_RETRY_BACKOFF_SECONDS", 0.0)
    monkeypatch.setattr(setup_phase, "_RETRY_BACKOFF_SECONDS", (0.0, 0.0, 0.0))
    return asked


def _codex_secrets() -> SetupPhaseSecrets:
    return SetupPhaseSecrets.for_testing(codex_auth_json='{"invented":"not-a-credential"}')


class TestTheMechanism:
    async def test_a_deadline_that_lapses_while_the_loop_is_blocked_loses_the_status(
        self,
    ) -> None:
        """The real provider, a real process that SUCCEEDS, and a blocked loop.

        `sleep 0.1` exits 0 a moment after the loop is blocked, and the loop is
        held for longer than the exec's timeout, as the workspace walk held it
        in production. The
        exit status the process reported is never read: the result is the
        lost-status shape (or, if the kill lands first, a timeout) - never 0.
        """
        provider = object.__new__(WorkspaceDockerProvider)
        loop = asyncio.get_running_loop()
        loop.call_later(0.05, time.sleep, 1.0)  # the blocked loop

        result = await provider._run_exec(["sh", "-c", "sleep 0.1"], timeout=0.3)

        assert result.exit_code != 0, "the process exited 0 and that is what was lost"
        assert exec_status_lost.status_was_lost(result) or result.timed_out, result


class TestTheSetupPhase:
    async def test_a_lost_status_is_run_again_and_the_phase_proceeds(self) -> None:
        docker = _Docker(setup=[_lost(), _ok()])

        result = await run_setup_phase(_workspace(docker), _codex_secrets())

        assert result.exit_code == 0, result
        assert docker.setup_runs() == 2
        # Restaged for the second run: the first may have consumed it.
        assert docker.written.count(".setup/codex-auth.json") == 2

    async def test_a_reported_failure_is_never_retried(self) -> None:
        """Only a LOST status is retried. A status is an answer."""
        docker = _Docker(setup=[ExecuteResult(exit_code=1, stdout="", stderr="clone failed")])

        result = await run_setup_phase(_workspace(docker), _codex_secrets())

        assert result.exit_code == 1
        assert docker.setup_runs() == 1

    async def test_a_status_lost_twice_says_why(self, _no_real_docker: list[str]) -> None:
        docker = _Docker(setup=[_lost(), _lost()])

        result = await run_setup_phase(_workspace(docker), _codex_secrets())
        operator_reads = describe_process_failure(
            "Secret-injection setup for phase 'Verify the change independently'",
            exit_code=result.exit_code,
            output=result.stderr,
            timed_out=result.timed_out,
        )

        assert docker.setup_runs() == 2, "bounded: one retry, not a loop"
        assert "printed nothing" not in operator_reads
        assert "no exit status" in operator_reads
        assert f"container {_CONTAINER}: {_STATE}" in operator_reads
        assert "141.0s against a 120s timeout" in operator_reads
        assert "event loop is blocked" in operator_reads
        assert _no_real_docker == [_CONTAINER, _CONTAINER]


class TestTheCredentialGuard:
    async def test_it_still_fails_closed_and_now_says_why(self) -> None:
        """exec-ff7e0c990b00: every removal attempt lost its status."""
        docker = _Docker(setup=[_ok()], removal=[_lost(7_200.0)] * 4)

        with pytest.raises(RuntimeError) as raised:
            await run_setup_phase(_workspace(docker), _codex_secrets())

        message = str(raised.value)
        assert message.startswith("SECURITY: unable to remove staged codex credential")
        assert "attempts=4" in message
        assert message.count(f"container {_CONTAINER}: {_STATE}") == 4
        assert "7.2s against a 5s timeout" in message


class TestTheCause:
    async def test_collecting_artifacts_does_not_block_the_event_loop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The loop keeps running while a slow filesystem is being read."""

        def _slow(path: Path, patterns: list[str]) -> list[tuple[str, bytes]]:
            time.sleep(0.5)
            return []

        monkeypatch.setattr(adapter_copy, "collect_matching_files", _slow)
        ticks = 0

        async def _tick() -> None:
            nonlocal ticks
            while True:
                ticks += 1
                await asyncio.sleep(0.01)

        ticker = asyncio.create_task(_tick())
        handle = IsolationHandle(
            isolation_id=_ISOLATION_ID, isolation_type="docker", host_workspace_path=str(tmp_path)
        )
        await adapter_copy.copy_from_workspace(handle, ["artifacts/output/**/*"])
        ticker.cancel()

        assert ticks >= 10, f"the event loop ran {ticks} times in 0.5s: it was blocked"

    async def test_collecting_artifacts_never_walks_the_whole_workspace(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DEBUG is enabled on every logger, so "only at DEBUG" meant always."""
        (tmp_path / "artifacts" / "output").mkdir(parents=True)
        (tmp_path / "artifacts" / "output" / "verify.md").write_text("ok")
        walked: list[object] = []

        def _record_walk(*args: object, **_kw: object) -> list[Path]:
            walked.append(args)
            return []

        monkeypatch.setattr(Path, "rglob", _record_walk)
        handle = IsolationHandle(
            isolation_id=_ISOLATION_ID, isolation_type="docker", host_workspace_path=str(tmp_path)
        )
        previous = adapter_copy.logger.level
        adapter_copy.logger.setLevel(logging.DEBUG)  # as agentic_logging leaves it
        try:
            files = await adapter_copy.copy_from_workspace(handle, ["artifacts/output/**/*"])
        finally:
            adapter_copy.logger.setLevel(previous)

        assert walked == [], "walked the entire workspace"
        assert files == [("artifacts/output/verify.md", b"ok")]
