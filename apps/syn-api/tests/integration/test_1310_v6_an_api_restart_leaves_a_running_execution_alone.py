"""V6 on real processes: an API restart does not disturb a running execution (#1310, ADR-072 D1, D5, D10).

Run Queue on. The API is ``uvicorn syn_api.main:app`` with
SYN_EXECUTION_PROCESS_ROLE=api, unmodified, over real Postgres, event store,
Redis and MinIO. The executor is a second OS process, the same app with the
role ``executor`` (``_1310_v6_executor_process.py`` says exactly what it
replaces: the workspace image and the unlabelled reap). It holds two claimed
runs, each with an agent asleep in its own labelled container.

The API is SIGKILLed and a new API process boots through production startup, so
``resolve_previous_world`` runs twice with the flag on. Then:

* the survivor is untouched: same execution id, same executor, same lease
  token, same container, and once its agent is released it reaches
  ``WorkflowCompleted``, with no ``OrphanedByRestart`` on either stream;
* the second run is cancelled through the NEW API process, and stops on the
  executor: the cancel crosses the process boundary through the Redis signal
  queue (``get_controller`` in both processes), the real ``CancelSignalPoller``
  in the executor sees it, ends the agent and the run ends
  ``ExecutionCancelled``, with its container gone.

The API never reaches a real daemon. Its DOCKER_HOST is ``_DockerTrap``, a local
listener that answers like a daemon holding one workspace and records every
call. An unreachable host would not do: production's reap tolerates Docker
failures, so a reap that failed quietly would leave this test green. With the
trap a reap succeeds, against nothing, and the test fails on the record, and no
regression can remove anyone's ``agentic-ws-`` containers from a developer's
machine. A canary proves on every run that the API's environment reaches it.

Admission is the sibling tests' in-process ``processor.run``, not HTTP:
``test_1310_every_entrance_admits_into_postgres`` owns that hop. Only the
execution's stream and queue row are shared with what is under test here.

Run: ``uv run pytest -m integration apps/syn-api/tests/integration/test_1310_v6_an_api_restart_leaves_a_running_execution_alone.py``
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shutil
import socket
import sys
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import asyncpg
import httpx
import pytest
from pydantic import BaseModel, ConfigDict

from syn_adapters.execution_runs import PostgresExecutionRunQueue
from syn_api.routes.executions.control import ControlResponse
from syn_api.routes.executions.models import ExecutionDetailResponse, ExecutionListResponse
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
)
from syn_domain.testing.fake_agent_handler import A_DELIVERABLE, FakeAgentExecutionHandler

from ._1310_v6_executor_process import RELEASE_FILE, container_name
from .test_1310_a_claimed_three_phase_run_succeeds_on_real_stores import (
    infra,  # noqa: F401  # fixture
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_tests.fixtures.infrastructure import TestInfrastructure

    from .test_1310_a_claimed_three_phase_run_succeeds_on_real_stores import _Infra

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("docker") is None, reason="requires Docker"),
    pytest.mark.may_skip(reason="real containers and processes need Docker", issue="#1310"),
]

_CHILD = Path(__file__).with_name("_1310_v6_executor_process.py")
#: The image docker-compose.yaml pins: artifact storage has no other production backend.
_MINIO_IMAGE = (
    "ghcr.io/syntropic137/minio:RELEASE.2025-04-22T22-12-26Z"
    "@sha256:bbac678936882e4033b6068efd0a19d103b219002d979087f7c5bd330172e00d"
)
_MINIO_USER, _MINIO_SECRET = "v6-minio-user", "v6-minio-invented-secret"
#: Far above a ~15s boot or the 2s cancel poll; only a run that never gets there reaches it.
_WAIT_S = 120
#: Printed by `resolve_previous_world`, and only on its Run Queue branch.
_LEFT_TO_LEASE_EXPIRY = "Run Queue on: session reconcile is left to Lease expiry"
_TERMINAL = {"WorkflowCompleted", "WorkflowFailed", "WorkflowInterrupted", "ExecutionCancelled"}
#: What a daemon says first, so the client negotiates a version it can speak.
_TRAP_API_VERSION = "1.47"
_TRAPPED_ID = "feedface" * 8
#: One workspace, so a reap goes on to stop and remove it and those calls are recorded too.
_TRAP_LISTING = json.dumps(
    [{"Id": _TRAPPED_ID, "Names": ["/agentic-ws-v6-trap"], "Labels": {}, "State": "running"}]
)
_RUN_ROW = "SELECT state, executor_id, lease_token FROM execution_runs WHERE execution_id=$1"


class _Report(BaseModel):
    """One JSON line the executor process wrote."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event: str
    execution_id: str
    pid: int


class _Health(BaseModel):
    """The two facts of /health this test reads; the rest is not its business."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    status: str
    degraded_reasons: list[str] = []


class _Service(NamedTuple):
    """A private container this test started, and the host port it answers on."""

    name: str
    port: int


class _Stack(NamedTuple):
    """What both processes are configured with."""

    redis: _Service
    minio: _Service
    database_url: str
    api_port: int
    executor_port: int
    docker_trap_port: int
    logs: Path


class _DockerCall(NamedTuple):
    method: str
    path: str


class _DockerTrap:
    """Stands in for the Docker daemon behind the API's DOCKER_HOST, recording every call."""

    def __init__(self) -> None:
        self.calls: list[_DockerCall] = []

    @property
    def container_calls(self) -> list[_DockerCall]:
        """Every touch of a container: list, inspect, stop, kill, remove. The API owes none."""
        return [call for call in self.calls if call.path.startswith("/containers")]

    async def answer(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            method, target = head.decode().split(" ", 2)[:2]
            call = _DockerCall(method, re.sub(r"^/v[0-9.]+", "", target.split("?")[0]))
            self.calls.append(call)
            writer.write(_trap_reply(call))
            await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass  # a client that hung up has already been recorded, or asked nothing
        finally:
            writer.close()


def _trap_reply(call: _DockerCall) -> bytes:
    if call.path == "/_ping":
        status, body = "200 OK", "OK"
    elif call.path == "/containers/json":
        status, body = "200 OK", _TRAP_LISTING
    elif call.method in {"POST", "DELETE"}:
        status, body = "204 No Content", ""
    else:
        status, body = "404 Not Found", '{"message": "no such object"}'
    return (
        f"HTTP/1.1 {status}\r\nApi-Version: {_TRAP_API_VERSION}\r\nOstype: linux\r\n"
        f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n"
        f"Connection: close\r\n\r\n{body}"
    ).encode()


class _RunRow(NamedTuple):
    state: str
    executor_id: str | None
    lease_token: int


def _lines(out: Path) -> list[_Report]:
    if not out.exists():
        return []
    return [_Report.model_validate_json(line) for line in out.read_text().splitlines()]


async def _until_reported(out: Path, event: str, execution_id: str) -> _Report:
    async with asyncio.timeout(_WAIT_S):
        while True:
            for line in _lines(out):
                if (line.event, line.execution_id) == (event, execution_id):
                    return line
            await asyncio.sleep(0.1)


async def _docker(*args: str, check: bool = True, env: dict[str, str] | None = None) -> str:
    """Run one docker command; with ``check``, a failure raises rather than reading as empty.

    A command that outlives its wait is killed and reaped before the timeout
    propagates: left running, a `docker run` could create a container after
    teardown had already removed everything it knew of.
    """
    proc = await asyncio.create_subprocess_exec(
        "docker", *args, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    try:
        async with asyncio.timeout(_WAIT_S * 2):  # a first run pulls the image
            out, _ = await proc.communicate()
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
    assert not check or proc.returncode == 0, f"docker {args[0]} exited {proc.returncode}"
    return out.decode().strip()


async def _remove(name: str) -> None:
    """Best effort, so one stuck removal never spares the containers after it."""
    with contextlib.suppress(TimeoutError):
        await _docker("rm", "-f", name, check=False)


async def _service(started: list[str], prefix: str, port: int, *run: str) -> _Service:
    """Start a container, named in ``started`` BEFORE it exists, so any failure removes it."""
    name = f"syn-v6-{prefix}-{uuid4().hex[:8]}"
    started.append(name)
    await _docker("run", "-d", "--name", name, "-p", f"127.0.0.1::{port}", *run)
    mapped = await _docker("port", name, f"{port}/tcp")
    return _Service(name, int(mapped.splitlines()[0].rsplit(":", 1)[1]))


async def _minio_live(port: int) -> None:
    async with asyncio.timeout(_WAIT_S), httpx.AsyncClient() as client:
        while True:
            with contextlib.suppress(httpx.TransportError):
                if (await client.get(f"http://127.0.0.1:{port}/minio/health/live")).is_success:
                    return
            await asyncio.sleep(0.2)


async def _redis_live(name: str) -> None:
    async with asyncio.timeout(_WAIT_S):
        while await _docker("exec", name, "redis-cli", "ping", check=False) != "PONG":
            await asyncio.sleep(0.2)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _in_database(url: str, name: str) -> str:
    return urlunsplit(urlsplit(url)._replace(path=f"/{name}"))


@pytest.fixture
async def database(test_infrastructure: TestInfrastructure) -> AsyncIterator[str]:
    """A database of its own: production's pool takes no schema, and it owns every table here."""
    name = f"run_queue_v6_{uuid4().hex}"
    admin = await asyncpg.connect(test_infrastructure.timescaledb_url)
    await admin.execute(f"CREATE DATABASE {name}")
    try:
        yield _in_database(test_infrastructure.timescaledb_url, name)
    finally:
        await admin.execute(f"DROP DATABASE {name} WITH (FORCE)")
        await admin.close()


@pytest.fixture
async def pool(database: str) -> AsyncIterator[asyncpg.Pool]:
    """The fixture ``infra`` reads, over the database the two processes share."""
    created = await asyncpg.create_pool(database)
    assert created is not None
    try:
        await PostgresExecutionRunQueue(created).ensure_ready()
        yield created
    finally:
        await created.close()


@pytest.fixture
async def docker_trap() -> AsyncIterator[tuple[_DockerTrap, int]]:
    trap = _DockerTrap()
    server = await asyncio.start_server(trap.answer, "127.0.0.1", 0)
    try:
        yield trap, server.sockets[0].getsockname()[1]
    finally:
        server.close()


@pytest.fixture
async def stack(
    database: str, tmp_path: Path, docker_trap: tuple[_DockerTrap, int]
) -> AsyncIterator[_Stack]:
    """Redis and MinIO of its own: CI's integration job has neither, and both are load-bearing."""
    started: list[str] = []
    try:
        redis = await _service(started, "redis", 6379, "redis:7-alpine")
        minio = await _service(
            started, "minio", 9000,
            "-e", f"MINIO_ROOT_USER={_MINIO_USER}",
            "-e", f"MINIO_ROOT_PASSWORD={_MINIO_SECRET}",
            _MINIO_IMAGE, "server", "/data",
        )  # fmt: skip
        await _redis_live(redis.name)
        await _minio_live(minio.port)
        yield _Stack(redis, minio, database, _free_port(), _free_port(), docker_trap[1], tmp_path)
    finally:
        for name in started:
            await _remove(name)


def _environment(world: _Infra, stack: _Stack, role: str) -> dict[str, str]:
    """Production's settings for ``role``; nothing of the test process's SYN_ or test env leaks."""
    inherited = {k: v for k, v in os.environ.items() if not k.startswith(("SYN_", "TEST_"))}
    host, port = world.address.rsplit(":", 1)
    return {
        **inherited,
        "APP_ENVIRONMENT": "development",
        "SYN_EXECUTION_RUN_QUEUE_ENABLED": "true",
        "SYN_EXECUTION_PROCESS_ROLE": role,
        "SYN_OBSERVABILITY_DB_URL": stack.database_url,
        "EVENT_STORE_HOST": host,
        "EVENT_STORE_PORT": port,
        "EVENT_STORE_TENANT_ID": world.tenant,
        "REDIS_URL": f"redis://127.0.0.1:{stack.redis.port}/0",
        "SYN_STORAGE_PROVIDER": "minio",
        "SYN_STORAGE_MINIO_ENDPOINT": f"127.0.0.1:{stack.minio.port}",
        "SYN_STORAGE_MINIO_ACCESS_KEY": _MINIO_USER,
        "SYN_STORAGE_MINIO_SECRET_KEY": _MINIO_SECRET,
        "SYN_STORAGE_MINIO_SECURE": "false",
        "SYN_WORKSPACE_CONTAINER_DIR": str(stack.logs),
        "SYN_WORKSPACE_HOST_DIR": str(stack.logs),
        "ANTHROPIC_API_KEY": "sk-ant-v6-invented-not-a-key",
        "LOG_LEVEL": "INFO",  # the guard's line is what proves it ran
        "PYTHONUNBUFFERED": "1",
    }


def _api_environment(world: _Infra, stack: _Stack) -> dict[str, str]:
    """The API's settings, with the trap as its only Docker daemon (see the module docstring)."""
    env = _environment(world, stack, "api")
    for selects_a_daemon in (
        "DOCKER_CONTEXT",
        "DOCKER_TLS",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
    ):
        env.pop(selects_a_daemon, None)
    env["DOCKER_HOST"] = f"tcp://127.0.0.1:{stack.docker_trap_port}"
    return env


async def _spawn_api(world: _Infra, stack: _Stack, log: Path) -> asyncio.subprocess.Process:
    env = _api_environment(world, stack)
    with log.open("w") as sink:
        return await asyncio.create_subprocess_exec(
            sys.executable, "-m", "uvicorn", "syn_api.main:app",
            "--host", "127.0.0.1", "--port", str(stack.api_port),
            cwd=stack.logs, env=env, stdout=sink, stderr=sink,
        )  # fmt: skip


async def _spawn_executor(
    world: _Infra, stack: _Stack, out: Path, log: Path
) -> asyncio.subprocess.Process:
    with log.open("w") as sink:
        return await asyncio.create_subprocess_exec(
            sys.executable, str(_CHILD), str(stack.executor_port), str(out),
            cwd=stack.logs, env=_environment(world, stack, "executor"), stdout=sink, stderr=sink,
        )  # fmt: skip


async def _api_serving(client: httpx.AsyncClient, port: int) -> None:
    """Wait for a finished startup: /health says ``starting`` until the gate opens."""
    async with asyncio.timeout(_WAIT_S):
        while True:
            with contextlib.suppress(httpx.TransportError):
                reply = await client.get(f"http://127.0.0.1:{port}/health")
                if reply.status_code == 200:
                    health = _Health.model_validate_json(reply.text)
                    if health.status == "healthy":
                        assert "subscription_coordinator" not in health.degraded_reasons, health
                        return
            await asyncio.sleep(0.2)


async def _in_the_read_models(client: httpx.AsyncClient, port: int, execution_id: str) -> None:
    """Wait until the API reads the run as running: what a global reconcile would act on."""
    base = f"http://127.0.0.1:{port}"
    async with asyncio.timeout(_WAIT_S):
        while True:
            detail = await client.get(f"{base}/executions/{execution_id}")
            listing = await client.get(f"{base}/executions", params={"status": "running"})
            if detail.status_code == 200 and listing.status_code == 200:
                running = ExecutionDetailResponse.model_validate_json(detail.text).status
                rows = ExecutionListResponse.model_validate_json(listing.text).executions
                if running == "running" and execution_id in {
                    row.workflow_execution_id for row in rows
                }:
                    return
            await asyncio.sleep(0.2)


async def _admit(world: _Infra) -> str:
    admitting, _ = await world.processor(
        FakeAgentExecutionHandler.success(produces=A_DELIVERABLE), queued=True
    )
    execution_id = f"exec-{uuid4().hex[:12]}"
    result = await admitting.run(
        workflow_id="wf-1310-v6",
        workflow_name="One sleeping phase",
        phases=[
            ExecutablePhase(
                phase_id="phase-1",
                name="Phase 1",
                order=1,
                description="sleeps until released",
                agent_config=AgentConfiguration(),
                prompt_template="do the thing",
                output_artifact_types=(),
                timeout_seconds=1800,
            )
        ],
        inputs={"task": "fix it"},
        execution_id=execution_id,
    )
    assert result.status == "admitted"
    return execution_id


async def _run_row(runs: asyncpg.Pool, execution_id: str) -> _RunRow:
    async with runs.acquire() as conn:
        row = await conn.fetchrow(_RUN_ROW, execution_id)
    assert row is not None
    return _RunRow(row["state"], row["executor_id"], row["lease_token"])


async def _ends_with(world: _Infra, execution_id: str, terminal: str) -> list[str]:
    async with asyncio.timeout(_WAIT_S):
        while (types := await world.event_types(execution_id))[-1] not in _TERMINAL:
            await asyncio.sleep(0.2)
    assert types[-1] == terminal, types
    return types


async def _container_id(execution_id: str) -> str:
    return await _docker("inspect", "-f", "{{.Id}}", container_name(execution_id))


async def _assert_no_orphaning(world: _Infra, execution_id: str) -> None:
    events = await world.events(execution_id)
    assert not [e for e in events if getattr(e, "error_type", None) == "OrphanedByRestart"]
    types = [e.event_type for e in events]
    assert types.count("WorkflowExecutionStarted") == 1, types
    assert types.count("WorkspaceProvisionedForPhase") == 1, types  # one workspace, never a second
    assert not {"WorkflowFailed", "WorkflowInterrupted"} & set(types), types


async def _stop(child: asyncio.subprocess.Process) -> None:
    with contextlib.suppress(ProcessLookupError):
        child.kill()
    await child.wait()


async def test_v6_an_api_restart_leaves_a_running_run_alone_and_a_later_cancel_stops_on_the_executor(
    infra: _Infra,  # noqa: F811
    pool: asyncpg.Pool,
    stack: _Stack,
    docker_trap: tuple[_DockerTrap, int],
) -> None:
    trap, _ = docker_trap
    # The canary: a docker client in the API's environment reaches the trap and only the trap.
    listed = await _docker("ps", "-q", env=_api_environment(infra, stack))
    assert listed == _TRAPPED_ID[:12], listed
    assert trap.container_calls == [_DockerCall("GET", "/containers/json")]
    trap.calls.clear()

    out = stack.logs / "executor.jsonl"
    first_log, second_log = stack.logs / "api-1.log", stack.logs / "api-2.log"
    children: list[asyncio.subprocess.Process] = []
    survivor = cancelled = ""
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            first_api = await _spawn_api(infra, stack, first_log)
            children.append(first_api)
            await _api_serving(client, stack.api_port)

            survivor, cancelled = await _admit(infra), await _admit(infra)
            executor = await _spawn_executor(infra, stack, out, stack.logs / "executor.log")
            children.append(executor)
            for execution_id in (survivor, cancelled):
                started = await _until_reported(out, "agent_started", execution_id)
                assert started.pid == executor.pid  # never the API
                await _in_the_read_models(client, stack.api_port, execution_id)
            held = await _run_row(pool, survivor)
            assert held.state == "claimed", held
            container = await _container_id(survivor)
            host_label = await _docker(
                "inspect", "-f", '{{index .Config.Labels "syn.host_id"}}', container
            )
            assert host_label == held.executor_id

            # The API dies and is replaced, through production startup.
            first_api.kill()
            await first_api.wait()
            second_api = await _spawn_api(infra, stack, second_log)
            children.append(second_api)
            await _api_serving(client, stack.api_port)
            assert trap.container_calls == []  # neither startup reaped, or even looked
            assert _LEFT_TO_LEASE_EXPIRY in first_log.read_text()
            assert _LEFT_TO_LEASE_EXPIRY in second_log.read_text()
            assert executor.returncode is None, "the executor died with the API"
            await _assert_no_orphaning(infra, survivor)
            await _assert_no_orphaning(infra, cancelled)
            assert await _run_row(pool, survivor) == held

            # A cancel the new API takes must stop the run on the executor.
            reply = await client.post(
                f"http://127.0.0.1:{stack.api_port}/executions/{cancelled}/cancel",
                json={"reason": "V6: after the API restart"},
            )
            assert reply.status_code == 200, reply.text
            assert ControlResponse.model_validate_json(reply.text).success, reply.text
            killed = await _until_reported(out, "agent_killed", cancelled)
            assert killed.pid == executor.pid
            await _ends_with(infra, cancelled, "ExecutionCancelled")
            await _assert_no_orphaning(infra, cancelled)
            async with asyncio.timeout(_WAIT_S):
                while await _docker("ps", "-aq", "--filter", f"name={container_name(cancelled)}"):
                    await asyncio.sleep(0.2)

            # The cancel touched only its own run; the survivor sleeps on.
            assert await _run_row(pool, survivor) == held
            assert not _TERMINAL & set(await infra.event_types(survivor))
            assert await _container_id(survivor) == container

            await _docker("exec", container_name(survivor), "touch", RELEASE_FILE)
            await _ends_with(infra, survivor, "WorkflowCompleted")
            await _assert_no_orphaning(infra, survivor)
            assert [line.event for line in _lines(out)].count("agent_started") == 2
            assert not [line for line in _lines(out) if line.execution_id == survivor][1:]
            assert executor.returncode is None
            assert trap.container_calls == []
        finally:
            for child in children:
                await _stop(child)
            for execution_id in (survivor, cancelled):
                if execution_id:
                    await _remove(container_name(execution_id))


async def test_a_docker_command_that_outlives_its_wait_is_killed_before_the_timeout_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid_file = tmp_path / "pid"
    shim = tmp_path / "docker"
    shim.write_text(f"#!/bin/sh\necho $$ > {pid_file}\nexec sleep 600\n")
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path), prepend=os.pathsep)
    monkeypatch.setattr(sys.modules[__name__], "_WAIT_S", 0.25)

    with pytest.raises(TimeoutError):
        await _docker("run", "anything")

    with pytest.raises(ProcessLookupError):  # reaped, so its pid is gone
        os.kill(int(pid_file.read_text()), 0)


async def test_a_service_whose_setup_fails_after_creation_is_still_named_for_removal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_docker = _docker

    async def port_refused(*args: str, check: bool = True) -> str:
        if args[0] == "port":
            raise AssertionError("docker port exited 1")
        return await real_docker(*args, check=check)

    monkeypatch.setattr(sys.modules[__name__], "_docker", port_refused)
    started: list[str] = []
    try:
        with pytest.raises(AssertionError, match="docker port"):
            await _service(started, "half-made", 6379, "alpine:3", "sleep", "600")
        (name,) = started
        assert await real_docker("ps", "-aq", "--filter", f"name={name}")  # it does exist
    finally:
        for leftover in started:
            await _remove(leftover)
    assert not await real_docker("ps", "-aq", "--filter", f"name={name}")
