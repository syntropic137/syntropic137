"""A production executor with a sleeping agent, for the V6 test.

Not a test module. Usage (only the V6 test runs it)::

    python _1310_v6_executor_process.py PORT OUT

This is ``syn_api.main:app`` under uvicorn, as ``docker-compose.selfhost.yaml``
runs it, with SYN_EXECUTION_PROCESS_ROLE=executor in the environment: real
lifecycle, real ``start_execution_host``, real ``get_execution_processor``,
real ``get_controller``, real ``AgentExecutionHandler`` and stream processor.
Exactly two things are replaced:

* ``build_workspace_service``: the workspace image is not available here, so a
  workspace is one ``alpine`` container, labelled by production's label
  producer, and the "agent" is a shell loop inside it that sleeps until the
  file ``RELEASE_FILE`` appears and then prints one result line. Anything else
  the memory backend does stays what it does.
* ``_unlabelled_ids``: production startup reaps every unlabelled ``agentic-ws-``
  container on the daemon when it is the only live executor, which on a
  developer's machine is other people's work. The sibling startup test stubs
  the same call for the same reason.

Each report is one JSON line in OUT.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import uvicorn

from syn_adapters.workspace_backends.agentic.adapter import _container_labels
from syn_adapters.workspace_backends.memory import (
    MemoryEventStreamAdapter,
    MemoryIsolationAdapter,
)
from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService
from syn_api import _wiring
from syn_api.services import unlabelled_containers
from syn_shared.settings import reset_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterable

    from syn_adapters.workspace_backends.service.workspace_service import WorkspaceServiceConfig
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationConfig,
        IsolationHandle,
    )

RELEASE_FILE = "/tmp/release-the-agent"
_PID_FILE = "/tmp/agent.pid"
_RESULT_LINE = json.dumps(
    {"type": "result", "subtype": "success", "is_error": False, "result": "The phase's findings."}
)
#: `$$` is this shell, so killing it ends the `docker exec` the stream is reading.
_SLEEPING_AGENT = (
    f'echo $$ > {_PID_FILE}; until [ -e {RELEASE_FILE} ]; do sleep 0.2; done; printf "%s\\n" "$0"'
)
_DELIVERABLE = ("artifacts/output/deliverable.md", b"# Deliverable\n\nThe phase's findings.")


def _report(out: Path, **line: object) -> None:
    with out.open("a") as f:
        f.write(json.dumps(line) + "\n")


async def _docker(*args: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "docker", *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    if await proc.wait() != 0:
        raise RuntimeError(f"`docker {args[0]}` exited {proc.returncode}")


def container_name(execution_id: str) -> str:
    return f"agentic-ws-v6-{execution_id}"


class _ContainerIsolation(MemoryIsolationAdapter):
    """The memory backend, plus one real labelled container per workspace."""

    def __init__(self) -> None:
        super().__init__()
        self.execution_ids: dict[str, str] = {}

    async def create(self, config: IsolationConfig) -> IsolationHandle:
        handle = await super().create(config)
        assert config.execution_id is not None
        self.execution_ids[handle.isolation_id] = config.execution_id
        await _docker(
            "run", "-d", "--name", container_name(config.execution_id),
            *(f"--label={key}={value}" for key, value in _container_labels(config).items()),
            "alpine:3", "sleep", "3600",
        )  # fmt: skip
        return handle

    async def destroy(self, handle: IsolationHandle) -> None:
        await _docker("rm", "-f", container_name(self.execution_ids[handle.isolation_id]))
        await super().destroy(handle)


class _SleepingAgent(MemoryEventStreamAdapter):
    """Streams the shell loop inside the workspace's container, so a CANCEL has a process to end."""

    def __init__(self, isolation: _ContainerIsolation, out: Path) -> None:
        super().__init__()
        self._isolation, self._out = isolation, out

    async def stream(
        self,
        handle: IsolationHandle,
        command: list[str],
        *,
        timeout_seconds: int | None = None,
        working_directory: str | None = None,
        environment: dict[str, str] | None = None,
        wrapper_name: str | None = None,
        withheld: Callable[[], Iterable[str]] | None = None,
    ) -> AsyncIterator[str]:
        del command, timeout_seconds, working_directory, environment, wrapper_name, withheld
        execution_id = self._isolation.execution_ids[handle.isolation_id]
        await self._isolation.copy_to(handle, [_DELIVERABLE])
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", container_name(execution_id),
            "sh", "-c", _SLEEPING_AGENT, _RESULT_LINE,
            stdout=asyncio.subprocess.PIPE,
        )  # fmt: skip
        assert proc.stdout is not None
        _report(self._out, event="agent_started", execution_id=execution_id, pid=os.getpid())
        async for raw in proc.stdout:
            yield raw.decode().rstrip("\n")
        self._exit_codes[handle.isolation_id] = await proc.wait()

    async def cancel_running(self, handle: IsolationHandle) -> bool:
        execution_id = self._isolation.execution_ids[handle.isolation_id]
        name = container_name(execution_id)
        await _docker("exec", name, "sh", "-c", f'kill -9 "$(cat {_PID_FILE})"')
        _report(self._out, event="agent_killed", execution_id=execution_id, pid=os.getpid())
        return True


def _workspaces(out: Path) -> Callable[[WorkspaceServiceConfig, str | None], WorkspaceService]:
    """Build the doubles now: their ADR-060 guard is checked once, at construction."""
    production = os.environ["APP_ENVIRONMENT"]
    os.environ["APP_ENVIRONMENT"] = "test"
    reset_settings()
    isolation = _ContainerIsolation()
    agent = _SleepingAgent(isolation, out)
    service = WorkspaceService.create(backend=WorkspaceBackend.MEMORY)
    os.environ["APP_ENVIRONMENT"] = production
    reset_settings()
    service._isolation, service._event_stream = isolation, agent

    def build(_config: WorkspaceServiceConfig, _capture_source: str | None) -> WorkspaceService:
        return service

    return build


async def _no_unlabelled() -> list[str]:
    return []


def main(port: str, out: str) -> None:
    _wiring.build_workspace_service = _workspaces(Path(out))
    unlabelled_containers._unlabelled_ids = _no_unlabelled
    uvicorn.run("syn_api.main:app", host="127.0.0.1", port=int(port))


if __name__ == "__main__":
    main(*sys.argv[1:3])
