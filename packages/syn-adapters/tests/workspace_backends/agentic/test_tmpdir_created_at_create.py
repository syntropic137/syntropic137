"""A workspace is handed out with its TMPDIR already there.

Codex's linux-sandbox canonicalizes TMPDIR and panics when it is missing, and
the codex sandbox probe then refuses the workspace. The eval verifier hit it on
5 of 6 runs:

    probe exit 101: thread 'main' panicked at linux-sandbox/src/linux_run_main.rs:1353:17:
    failed to resolve synthetic mount registry temp directory /workspace/.tmp:
    No such file or directory (os error 2)

So `create()` makes the directory itself, and a workspace where it cannot is
destroyed rather than returned.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from types import MappingProxyType
from unittest.mock import patch

import pytest

from syn_adapters.workspace_backends.agentic.adapter import (
    _EXECUTABLE_TMPDIR,
    AgenticIsolationAdapter,
)
from syn_adapters.workspace_backends.errors import WorkspaceProvisionError
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationConfig,
)

pytestmark = pytest.mark.unit


@dataclass
class _Result:
    exit_code: int
    success: bool
    stderr: str = ""


@dataclass
class _Workspace:
    id: str = "ws-1"
    metadata: MappingProxyType[str, str] = field(
        default_factory=lambda: MappingProxyType({"workspace_dir": "/tmp/ws-1"})
    )


@dataclass
class _Provider:
    """A fresh workspace holds only `/workspace`; it understands `mkdir -p`."""

    mkdir_fails: bool = False
    execute_raises: bool = False
    dirs: set[str] = field(default_factory=lambda: {"/workspace"})
    commands: list[str] = field(default_factory=list)
    destroyed: list[_Workspace] = field(default_factory=list)

    async def create(self, _config: object) -> _Workspace:
        return _Workspace()

    async def execute(self, _workspace: _Workspace, command: str, **_kw: object) -> _Result:
        self.commands.append(command)
        if self.execute_raises:
            raise RuntimeError("container went away")
        argv = shlex.split(command)
        assert argv[:2] == ["mkdir", "-p"], f"unexpected command at create: {command}"
        if self.mkdir_fails:
            return _Result(exit_code=1, success=False, stderr="mkdir: Read-only file system")
        self.dirs.update(argv[2:])
        return _Result(exit_code=0, success=True)

    async def destroy(self, workspace: _Workspace) -> None:
        self.destroyed.append(workspace)


def _config(environment: dict[str, str] | None = None) -> IsolationConfig:
    return IsolationConfig(
        execution_id="exec-1", workspace_id="ws-1", environment=environment or {}
    )


async def _create(provider: _Provider, config: IsolationConfig | None = None) -> object:
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
        return await adapter.create(config or _config())


@pytest.mark.asyncio
async def test_the_default_tmpdir_exists_when_create_returns() -> None:
    provider = _Provider()
    await _create(provider)

    assert _EXECUTABLE_TMPDIR in provider.dirs
    assert provider.destroyed == []


@pytest.mark.asyncio
async def test_a_caller_supplied_tmpdir_is_the_one_created() -> None:
    provider = _Provider()
    await _create(provider, _config({"TMPDIR": "/workspace/my tmp"}))

    assert "/workspace/my tmp" in provider.dirs


@pytest.mark.asyncio
async def test_a_failed_mkdir_destroys_the_workspace_and_raises() -> None:
    provider = _Provider(mkdir_fails=True)

    with pytest.raises(WorkspaceProvisionError, match=r"/workspace/\.tmp"):
        await _create(provider)

    assert len(provider.destroyed) == 1


@pytest.mark.asyncio
async def test_an_execute_that_raises_destroys_the_workspace_and_raises() -> None:
    provider = _Provider(execute_raises=True)

    with pytest.raises(WorkspaceProvisionError, match="container went away"):
        await _create(provider)

    assert len(provider.destroyed) == 1
