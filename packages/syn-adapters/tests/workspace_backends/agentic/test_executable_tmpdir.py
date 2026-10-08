"""`just` must be able to execute a shebang recipe in the workspace (#1042).

`/tmp` is mounted `noexec` by the isolation layer, deliberately. `just` writes a
shebang recipe to a temp file and runs it, so every shebang recipe - including
`qa-ci`, the gate the verify phase is told to run - failed with
`Permission denied (os error 13)`. A phase could spend an hour of model time and
then be unable to certify its own work.

Verified in a live workspace before writing this:

    $ just shebang-recipe                        -> Permission denied (os error 13)
    $ TMPDIR=/workspace/.tmp just shebang-recipe -> SHEBANG_RAN_OK
"""

from __future__ import annotations

import asyncio
import shlex
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from agentic_isolation.providers.base import ExecuteResult

from syn_adapters.workspace_backends.agentic.adapter import (
    _EXECUTABLE_TMPDIR,
    _WORKSPACE_CACHE_ENV,
    AgenticIsolationAdapter,
    _with_executable_tmpdir,
)
from syn_adapters.workspace_backends.errors import WorkspaceProvisionError
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationConfig,
)

if TYPE_CHECKING:
    from agentic_isolation import WorkspaceConfig

pytestmark = pytest.mark.unit


class TestTmpdirIsSet:
    def test_an_empty_environment_gets_a_tmpdir(self) -> None:
        assert _with_executable_tmpdir({})["TMPDIR"] == _EXECUTABLE_TMPDIR

    def test_it_does_not_point_at_tmp(self) -> None:
        """The whole point: /tmp is noexec, so TMPDIR must not resolve there."""
        tmpdir = _with_executable_tmpdir({})["TMPDIR"]
        assert not tmpdir.startswith("/tmp"), f"{tmpdir} is under the noexec mount"

    def test_other_variables_survive(self) -> None:
        out = _with_executable_tmpdir({"FOO": "bar", "BAZ": "qux"})
        assert out["FOO"] == "bar"
        assert out["BAZ"] == "qux"
        assert out["TMPDIR"] == _EXECUTABLE_TMPDIR


class TestCallerWins:
    """A default, not a policy - a phase that sets TMPDIR keeps it."""

    def test_a_caller_supplied_tmpdir_is_not_overwritten(self) -> None:
        assert _with_executable_tmpdir({"TMPDIR": "/workspace/mine"})["TMPDIR"] == "/workspace/mine"

    @pytest.mark.parametrize("empty", ["", None])
    def test_an_empty_tmpdir_is_replaced(self, empty: str | None) -> None:
        """An empty value is not a choice; it would leave `just` broken."""
        env: dict[str, str] = {} if empty is None else {"TMPDIR": empty}
        assert _with_executable_tmpdir(env)["TMPDIR"] == _EXECUTABLE_TMPDIR


class TestNoSideEffects:
    def test_the_input_dict_is_not_mutated(self) -> None:
        """Callers pass a config's own dict; mutating it would leak across phases."""
        original = {"FOO": "bar"}
        _with_executable_tmpdir(original)
        assert "TMPDIR" not in original


class TestToolCachesAreOffTheTmpfs:
    """`$HOME` is a 128 MB tmpfs, and it is where every tool caches (#1133).

    A real verify phase died there, mid-gate, having already redirected TMPDIR:

        the workspace's 128 MiB /home/agent tmpfs ran out of space
        error: recipe `lint` failed on line 932 with exit code 1

    A prompt-level `export` is not enough: it lasts one shell, and the command
    that fills the disk is usually a dependency install run before the command
    carrying the export. So it belongs in the environment the workspace is
    given, next to TMPDIR.
    """

    @pytest.mark.parametrize("key", sorted(_WORKSPACE_CACHE_ENV))
    def test_every_cache_variable_is_set(self, key: str) -> None:
        assert _with_executable_tmpdir({})[key] == _WORKSPACE_CACHE_ENV[key]

    @pytest.mark.parametrize("key", sorted(_WORKSPACE_CACHE_ENV))
    def test_no_cache_lands_under_home_or_tmp(self, key: str) -> None:
        """The two small tmpfs mounts are exactly what these exist to avoid."""
        value = _with_executable_tmpdir({})[key]
        assert not value.startswith("/home"), f"{key}={value} is on the 128 MB tmpfs"
        assert not value.startswith("/tmp"), f"{key}={value} is on the 256 MB tmpfs"

    @pytest.mark.parametrize("key", sorted(_WORKSPACE_CACHE_ENV))
    def test_a_caller_supplied_value_wins(self, key: str) -> None:
        """A default, not a policy - the same contract TMPDIR already has."""
        assert _with_executable_tmpdir({key: "/somewhere/else"})[key] == "/somewhere/else"

    def test_an_empty_string_is_not_a_choice(self) -> None:
        """`FOO=` is how a variable gets unset by accident, not how it gets chosen."""
        assert (
            _with_executable_tmpdir({"UV_CACHE_DIR": ""})["UV_CACHE_DIR"]
            == (_WORKSPACE_CACHE_ENV["UV_CACHE_DIR"])
        )


@dataclass
class _WorkspaceFilesystem:
    """A provider double that models the one thing under test: which dirs exist.

    A fresh workspace has `/workspace` and nothing under it, which is exactly
    the state codex's sandbox probe met in PC-120. `mkdir -p` is the only
    command it understands; any other command fails loudly.
    """

    mkdir_exit_code: int = 0
    dirs: set[str] = field(default_factory=lambda: {"/workspace"})
    commands: list[list[str]] = field(default_factory=list)
    destroyed: list[object] = field(default_factory=list)
    environment: dict[str, str] = field(default_factory=dict)

    async def create(self, config: WorkspaceConfig) -> MagicMock:
        self.environment = dict(config.environment)
        workspace = MagicMock()
        workspace.id = "ws-1"
        workspace.metadata = {"workspace_dir": "/tmp/ws-1"}
        return workspace

    async def execute(self, workspace: object, command: str, **_: object) -> ExecuteResult:
        argv = shlex.split(command)
        self.commands.append(argv)
        assert argv[:2] == ["mkdir", "-p"], f"unexpected command at create: {argv}"
        if self.mkdir_exit_code == 0:
            self.dirs.update(argv[2:])
            return ExecuteResult(exit_code=0, stdout="", stderr="", duration_ms=1)
        return ExecuteResult(
            exit_code=self.mkdir_exit_code,
            stdout="",
            stderr="mkdir: cannot create directory: Read-only file system",
            duration_ms=1,
        )

    async def destroy(self, workspace: object) -> None:
        self.destroyed.append(workspace)


async def _create(
    provider: _WorkspaceFilesystem, environment: dict[str, str] | None = None
) -> AgenticIsolationAdapter:
    adapter = AgenticIsolationAdapter()

    async def _passthrough(image_ref: str) -> str:
        return image_ref

    with (
        patch.object(adapter, "_provider", provider),
        patch(
            "syn_adapters.workspace_backends.agentic.adapter.verify_image_async",
            side_effect=_passthrough,
        ),
    ):
        await adapter.create(
            IsolationConfig(
                execution_id="exec-1", workspace_id="ws-1", environment=environment or {}
            )
        )
    return adapter


class TestTmpdirExistsBeforeAnythingRuns:
    """A TMPDIR that does not exist makes codex's sandbox panic (PC-120).

    Codex's linux-sandbox canonicalizes TMPDIR, and a missing one is fatal:

        thread 'main' panicked at linux-sandbox/src/linux_run_main.rs:1353:17:
        failed to resolve synthetic mount registry temp directory
        /workspace/.tmp: No such file or directory (os error 2)

    Reproduced in the omni-agent image: `codex sandbox -c
    'sandbox_mode="workspace-write"' -- true` with TMPDIR=/workspace/.tmp
    panics exactly so, and gets past it once the directory exists. Only
    `skills add` ever created it, so the eval verifier - the one codex phase
    with no skills - was refused at provision on 5 of 6 runs.
    """

    @pytest.mark.asyncio
    async def test_the_default_tmpdir_exists_once_the_workspace_is_created(self) -> None:
        provider = _WorkspaceFilesystem()
        await _create(provider)

        assert provider.environment["TMPDIR"] == _EXECUTABLE_TMPDIR
        assert _EXECUTABLE_TMPDIR in provider.dirs

    @pytest.mark.asyncio
    async def test_a_caller_supplied_tmpdir_is_created_too(self) -> None:
        provider = _WorkspaceFilesystem()
        await _create(provider, {"TMPDIR": "/workspace/mine"})

        assert "/workspace/mine" in provider.dirs

    @pytest.mark.asyncio
    async def test_a_tmpdir_that_cannot_be_made_fails_provisioning_and_reaps(self) -> None:
        provider = _WorkspaceFilesystem(mkdir_exit_code=1)

        with pytest.raises(WorkspaceProvisionError, match=r"could not create TMPDIR"):
            await _create(provider)

        assert len(provider.destroyed) == 1, "the container must not leak"


@dataclass
class _MkdirHangs(_WorkspaceFilesystem):
    """A provider whose mkdir never returns, so the provision can be cancelled in it."""

    mkdir_started: asyncio.Event = field(default_factory=asyncio.Event)

    async def execute(self, workspace: object, command: str, **_: object) -> ExecuteResult:
        self.commands.append(shlex.split(command))
        self.mkdir_started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


@dataclass
class _MkdirHangsAndReapIsSlow(_MkdirHangs):
    """The reap yields first, so a second cancellation lands while it runs."""

    async def destroy(self, workspace: object) -> None:
        await asyncio.sleep(0.05)
        self.destroyed.append(workspace)


class _MkdirHangsAndReapFails(_MkdirHangs):
    """The reap yields, then fails: a second cancellation has already returned the caller."""

    async def destroy(self, workspace: object) -> None:
        await asyncio.sleep(0.05)
        raise RuntimeError("docker rm failed")


class TestCancelledProvisionDoesNotLeak:
    """Cancelled during the mkdir, the container exists but no handle does (#1706 review).

    Nothing else can reap it: `create` has not returned, so the caller has no
    handle, and the adapter has not registered it. So `create` must.
    """

    @pytest.mark.asyncio
    async def test_cancelling_during_mkdir_destroys_the_container_and_propagates(self) -> None:
        provider = _MkdirHangs()
        task = asyncio.ensure_future(_create(provider))
        await provider.mkdir_started.wait()

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert len(provider.destroyed) == 1, "the cancelled provision leaked its container"

    @pytest.mark.asyncio
    async def test_a_second_cancellation_cannot_interrupt_the_reap(self) -> None:
        provider = _MkdirHangsAndReapIsSlow()
        task = asyncio.ensure_future(_create(provider))
        await provider.mkdir_started.wait()

        task.cancel()
        await asyncio.sleep(0)  # the reap has started and is sleeping
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0.1)  # let the shielded reap finish

        assert len(provider.destroyed) == 1, "the second cancellation stopped the reap"

    @pytest.mark.asyncio
    async def test_a_reap_that_fails_after_a_second_cancellation_is_still_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        provider = _MkdirHangsAndReapFails()
        task = asyncio.ensure_future(_create(provider))
        await provider.mkdir_started.wait()

        task.cancel()
        await asyncio.sleep(0)  # the reap has started and is sleeping
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with caplog.at_level("ERROR"):
            await asyncio.sleep(0.1)  # let the shielded reap fail

        assert "Could not destroy workspace" in caplog.text, (
            "a reap that failed after the caller left went unlogged"
        )
