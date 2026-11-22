"""The engine launches an agent on E2B, and knows whether it launched (#1912).

``AgentExecutionHandler`` - the handler ``WorkflowExecutionProcessor`` builds
for every RUN_AGENT todo - drives the production ``ManagedWorkspace``,
``AgenticEventStreamAdapter``, ``E2BWorkspaceProvider`` and agentic-workspace's
own ``E2BOperations``. Only the E2B SDK port is a double. It plays the
sandbox-side launcher: it reads the wrapper name and marker the production
launch put on stdin, prints them as the real wrapper does (hex-framed, split
across SDK chunks), and then speaks, stays silent, or fails its exec.

The marker is checked against ``announce_as`` independently of the spec, so a
launch that announces the wrong line, or none, is caught here.
"""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from syn_adapters.workspace_backends.e2b.test_e2b_backend import (
    _KEY,
    _TEMPLATE,
    SandboxDouble,
    _Command,
    _settings,
)
from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService
from syn_domain.contexts.orchestration import announce_as
from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
    AgentExecutionHandler,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.unit

_AGENT = ["claude", "-p", "hello", "--output-format", "stream-json"]
#: Not a value any default produces: only the sandbox's outcome can put it there.
_EXIT = 7
_EXEC_FAILED = 127


class _FramedCommand(_Command):
    """The launcher's output as the SDK delivers it: hex, in chunks that ignore lines."""

    def __init__(self, payload: bytes, code: int) -> None:
        super().__init__(4321, payload.hex() + "\n", code)

    async def output(self) -> AsyncIterator[str]:
        for begin in range(0, len(self._text), 13):
            yield self._text[begin : begin + 13]


class _LaunchingSandbox(SandboxDouble):
    """An E2B account whose operation launcher behaves as ``shape`` says."""

    def __init__(self, shape: str) -> None:
        super().__init__()
        self.shape = shape
        self.launches: list[tuple[str, dict[str, str], tuple[str, str]]] = []

    async def start(  # type: ignore[override]
        self,
        sandbox_id: str,
        command: str,
        *,
        cwd: str | None,
        env: dict[str, str] | None,
        timeout: float | None,
        user: str | None,
        stdin: bytes | None = None,
    ) -> _Command:
        if stdin is None or "aw-operation" not in command:
            return await super().start(  # type: ignore[return-value]
                sandbox_id, command, cwd=cwd, env=env, timeout=timeout, user=user, stdin=stdin
            )
        wrapper, marker = stdin.decode().splitlines()
        self.launches.append((command, dict(env or {}), (wrapper, marker)))
        payload = f"4321\n{marker}\n"
        if self.shape == "exec-failed":
            payload += f"{wrapper}: 1: exec: claude: not found\n"
        elif self.shape == "speaks":
            payload += '{"type":"system","subtype":"init"}\n'
        code = _EXEC_FAILED if self.shape == "exec-failed" else _EXIT
        return _FramedCommand(payload.encode(), code)


@pytest.mark.parametrize("shape", ["speaks", "silent", "exec-failed"])
async def test_the_engine_launches_an_agent_on_e2b(
    monkeypatch: pytest.MonkeyPatch, shape: str
) -> None:
    e2b = _settings(monkeypatch, ENABLED="true", API_KEY=_KEY, TEMPLATE=_TEMPLATE, MEMORY_MB="4096")
    sandbox = _LaunchingSandbox(shape)
    service = WorkspaceService.create(backend=WorkspaceBackend.E2B, e2b=e2b, e2b_client=sandbox)
    async with service.create_workspace("exec-1912", with_sidecar=False) as workspace:
        assert workspace.isolation_handle.isolation_type == "e2b"
        # Twice, with different credentials: each launch carries its own.
        for token in ("first-launch-credential", "second-launch-credential"):
            launched = AsyncMock()
            result = await AgentExecutionHandler(controller=None).handle(
                todo=TodoItem(
                    execution_id="exec-1912",
                    action=TodoAction.RUN_AGENT,
                    phase_id="p1",
                    session_id="s1",
                ),
                workspace=workspace,
                agent_env={"SYN_API_TOKEN": token},
                claude_cmd=_AGENT,
                session_id="s1",
                agent_model="claude-haiku",
                timeout_seconds=30,
                on_launch=launched,
            )

            command, env, (wrapper, marker) = sandbox.launches[-1]
            # The sandbox argv, unprefixed: no docker exec on a remote launch.
            assert command.endswith(shlex.join(_AGENT)), command
            assert "docker" not in command
            # The credential travels as SDK environment, never argv or stdin.
            assert env["SYN_API_TOKEN"] == token
            assert token not in command
            assert token not in wrapper + marker
            # The marker is the engine's own announcement for that wrapper.
            assert marker == announce_as(wrapper)

            failed = shape == "exec-failed"
            assert result.exit_code == (_EXEC_FAILED if failed else _EXIT)
            assert workspace.last_stream_exit_code == result.exit_code
            assert result.launch_failed is failed
            # Silence is still a launch; a failed exec is none, whatever it printed.
            assert launched.await_count == (0 if failed else 1)
        assert len(sandbox.launches) == 2
