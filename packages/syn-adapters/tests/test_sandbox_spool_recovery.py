"""Remote spool recovery (#1916): route by the durable row, stop the writer, drain, then kill.

The provider is faked at the ``RecoverySandboxes`` boundary by ``ScriptedSandboxes``:
a remote account whose sandboxes outlive every worker. Each sandbox answers the
same commands the execute-based readers send (exporter spool index and bodies,
child journal export) and runs a simulated agent that writes one transcript
line on resume and on every command while it is alive. Everything above that
boundary is production code.
"""

from __future__ import annotations

import base64
import hashlib
import json
import shlex
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentic_isolation.child_journal import ChildChange
from agentic_isolation.providers.base import ExecuteResult
from event_sourcing.client.memory import MemoryEventStoreClient

from syn_adapters.session_inventory.recovery_worker import CaptureRecoveryWorker
from syn_adapters.session_inventory.sandbox_recovery import SandboxSpoolRecovery
from syn_adapters.session_inventory.spool_drain import LocalSpoolDrain, SpoolDrainProgress
from syn_domain.contexts.agent_sessions import CaptureSpool, CaptureSpoolLease, RunIdentity

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    import asyncpg

    from syn_adapters.session_inventory.database import Pool

SOURCE = "11111111-1111-4111-8111-111111111111"
EXECUTOR = "executor-dead"


def _spool(source: str = SOURCE, *, sandbox: str = "sbx-1") -> CaptureSpool:
    return CaptureSpool(
        run=RunIdentity(source_instance_id=source, execution_id="run-remote"),
        session_id="session-remote",
        phase_id="phase",
        profile="sandbox-spool/1",
        backend="e2b",
        executor_id=EXECUTOR,
        sandbox_id=sandbox,
    )


@dataclass
class ScriptedSandbox:
    """One paused sandbox with a spool on its own disk and, maybe, a live agent."""

    owner: str
    writer_alive: bool = True
    stop_confirms: bool = True
    native: list[str] = field(default_factory=list)
    envelopes: list[bytes] = field(default_factory=list)
    children: list[ChildChange] = field(default_factory=list)
    paused: bool = True
    killed: bool = False
    log: list[str] = field(default_factory=list)

    def agent_writes(self, label: str) -> None:
        if self.writer_alive and not self.killed:
            self.native.append(json.dumps({"type": "user", "text": label}) + "\n")

    async def stop_writers(self) -> bool:
        self.log.append("stop")
        if self.stop_confirms:
            self.writer_alive = False
        return self.stop_confirms and not self.writer_alive

    async def execute(
        self,
        command: str,
        *,
        timeout: float | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> ExecuteResult:
        assert not self.paused and not self.killed, "commands need a resumed sandbox"
        self.agent_writes(f"during:{len(self.log)}")
        argv = shlex.split(command)
        self.log.append(" ".join(argv[:2]))
        if argv[0] == "cat" and argv[1].endswith(".origin-host"):
            return _ok("origin-sandbox\n")
        if argv[0] in {"cat", "sh"}:
            return _ok("")
        if argv[-1] == "--spool-only":
            self._snapshot()
            return _ok("")
        if argv[:2] == ["/usr/local/bin/apss-session-exporter", "--spool-list"]:
            return _ok(self._index(argv[2]))
        if argv[0] == "bash":
            sequence = int(shlex.split(argv[-1])[2])
            return _ok(base64.b64encode(self.envelopes[sequence - 1]).decode())
        if argv[:3] == ["python3", "-m", "agentic_session_store.child_export"]:
            return _ok(self._children_page(argv))
        raise AssertionError(f"unexpected sandbox command {argv}")

    def _snapshot(self) -> None:
        raw = "".join(self.native)
        if not raw or (self.envelopes and json.loads(self.envelopes[-1])["raw"] == raw):
            return
        self.envelopes.append(
            json.dumps(
                {
                    "scs_version": "1.0",
                    "origin": {"host": "origin-sandbox", "environment": "container"},
                    "agent": "codex",
                    "source_format": "codex-rollout-jsonl",
                    "session_id": "native",
                    "started_at": "2026-10-23T00:00:00Z",
                    "last_activity_at": "2026-10-23T00:00:01Z",
                    "raw": raw,
                }
            ).encode()
        )

    def _index(self, cursor: str) -> str:
        after, _, frozen = cursor.partition(":")
        watermark = int(frozen) if frozen else len(self.envelopes)
        entries = [
            {
                "sequence": sequence,
                "archive_sha256": hashlib.sha256(body).hexdigest(),
                "byte_count": len(body),
                "agent": "codex",
                "native_session_id": "native",
            }
            for sequence, body in enumerate(self.envelopes[:watermark], start=1)
            if sequence > int(after)
        ]
        return json.dumps({"schema_version": 1, "watermark": watermark, "entries": entries})

    def _children_page(self, argv: list[str]) -> str:
        after = int(argv[argv.index("--after") + 1])
        changes = [c.model_dump(mode="json") for c in self.children if c.sequence > after]
        return json.dumps(
            {
                "schema_version": 3,
                "page": {"watermark": len(self.children), "changes": changes, "next_after": None},
            }
        )

    def archived_lines(self) -> set[str]:
        return set(self.native)


def _ok(stdout: str) -> ExecuteResult:
    return ExecuteResult(exit_code=0, stdout=stdout, stderr="", duration_ms=0)


def _child(sequence: int) -> ChildChange:
    return ChildChange.model_validate(
        {
            "sequence": sequence,
            "intent": {
                "sequence": sequence,
                "child_invocation_id": f"child-{sequence}",
                "call": {
                    "invocation_id": "inv",
                    "attempt_id": "attempt",
                    "harness": "claude",
                    "parent_native_id": "native",
                    "tool_call_id": f"tool-{sequence}",
                    "target_harness": "codex",
                },
                "child_native_id": f"child-native-{sequence}",
                "status": "completed",
                "exit_code": 0,
            },
        }
    )


class ScriptedSandboxes:
    """The remote account: sandboxes survive every worker that touches them."""

    def __init__(self) -> None:
        self.sandboxes: dict[str, ScriptedSandbox] = {}
        self.order: list[str] = []

    @asynccontextmanager
    async def attach(self, sandbox_id: str, *, executor_id: str) -> AsyncIterator[ScriptedSandbox]:
        sandbox = self.sandboxes[sandbox_id]
        if sandbox.owner != executor_id:
            raise PermissionError("sandbox belongs to another executor")
        sandbox.paused = False
        self.order.append(f"resume:{sandbox_id}")
        # Resuming resumes the agent: it writes before anyone can stop it.
        sandbox.agent_writes("after-resume")
        try:
            yield sandbox
        finally:
            sandbox.paused = True
            self.order.append(f"pause:{sandbox_id}")

    async def kill(self, sandbox_id: str) -> bool:
        sandbox = self.sandboxes[sandbox_id]
        sandbox.agent_writes("at-kill")
        sandbox.killed = True
        self.order.append(f"kill:{sandbox_id}")
        return True


def _sandboxes(*, alive: bool = True) -> tuple[ScriptedSandboxes, ScriptedSandbox]:
    remote = ScriptedSandboxes()
    sandbox = ScriptedSandbox(owner=EXECUTOR, writer_alive=alive)
    sandbox.native.append(json.dumps({"type": "user", "text": "before-crash"}) + "\n")
    sandbox.children.append(_child(1))
    remote.sandboxes["sbx-1"] = sandbox
    return remote, sandbox


@pytest.mark.unit
def test_remote_spool_row_must_name_its_sandbox_and_executor() -> None:
    with pytest.raises(ValueError, match="sandbox and executor"):
        CaptureSpool.model_validate(
            {**_spool().model_dump(), "sandbox_id": None},
        )
    with pytest.raises(ValueError, match="profile"):
        CaptureSpool.model_validate({**_spool().model_dump(), "profile": "local-spool/1"})
    legacy = CaptureSpool.model_validate_json(
        json.dumps(
            {
                "run": {"source_instance_id": SOURCE, "execution_id": "r"},
                "session_id": "s",
                "phase_id": "p",
                "profile": "local-spool/1",
            }
        )
    )
    assert legacy.backend == "docker"
    assert legacy.sandbox_id is None


@pytest.mark.unit
async def test_open_stops_writer_before_reading_and_pauses_on_exit() -> None:
    remote, sandbox = _sandboxes()
    async with SandboxSpoolRecovery(remote).open(_spool()) as readers:
        assert readers.exclusive is True
        page = await readers.transcripts.page(0)
        bodies = [await readers.transcripts.read(entry) for entry in page.entries]
        children = await readers.children.page(0)
        assert not sandbox.paused
    assert sandbox.log[0] == "stop"
    assert sandbox.paused and not sandbox.killed
    # The line written between resume and stop reached the snapshot.
    assert "after-resume" in json.loads(bodies[-1])["raw"]
    assert [change.sequence for change in children.changes] == [1]


@pytest.mark.unit
@pytest.mark.parametrize("failure", ["unconfirmed", "raises"])
async def test_unconfirmed_stop_never_yields_exclusive(failure: str) -> None:
    remote, sandbox = _sandboxes()
    sandbox.stop_confirms = False
    if failure == "raises":
        sandbox.stop_writers = AsyncMock(side_effect=OSError("provider 503"))  # type: ignore[method-assign]
    async with SandboxSpoolRecovery(remote).open(_spool()) as readers:
        assert readers.exclusive is False


@pytest.mark.unit
async def test_worker_routes_remote_row_to_remote_port_and_claims_only_reachable_backends() -> None:
    remote, _ = _sandboxes()
    lease = CaptureSpoolLease(spool=_spool(), token=1, after=0)
    spools = AsyncMock()
    spools.claim.return_value = lease
    docker = AsyncMock()
    drain = AsyncMock()
    drain.page.return_value = SpoolDrainProgress(watermark=0, next_after=None, captured=0)
    worker = CaptureRecoveryWorker(
        spools,
        {"docker": docker, "e2b": SandboxSpoolRecovery(remote)},
        drain,
        lease_seconds=60,
        retry_seconds=5,
    )
    assert await worker.step()
    docker.open.assert_not_called()
    assert remote.order == ["resume:sbx-1", "pause:sbx-1"]
    assert set(spools.claim.await_args.kwargs["backends"]) == {"docker", "e2b"}

    docker_only = CaptureRecoveryWorker(
        spools, {"docker": docker}, drain, lease_seconds=60, retry_seconds=5
    )
    spools.claim.return_value = None
    assert not await docker_only.step()
    assert tuple(spools.claim.await_args.kwargs["backends"]) == ("docker",)


def _worker(remote: ScriptedSandboxes, capture: AsyncMock, order: list[str]):
    """The production worker and drain over the scripted sandbox; durable store mocked."""
    lease = CaptureSpoolLease(spool=_spool(), token=1, after=0)
    spools = AsyncMock()
    spools.claim.return_value = lease
    spools.mark_drained.side_effect = lambda _lease: order.append("mark_drained")
    recovery = SandboxSpoolRecovery(remote)

    class Release:
        async def after_drain(self, lease: CaptureSpoolLease, *, exclusive: bool) -> bool:
            order.append("release")
            return exclusive and await recovery.remove(lease.spool)

    worker = CaptureRecoveryWorker(
        spools,
        {"e2b": recovery},
        LocalSpoolDrain(capture),
        lease_seconds=60,
        retry_seconds=5,
        release={"e2b": Release()},
    )
    return worker, spools


@pytest.mark.unit
async def test_live_writer_is_stopped_drained_and_killed_only_after_mark_drained() -> None:
    remote, sandbox = _sandboxes(alive=True)
    capture = AsyncMock()
    order: list[str] = []
    worker, _ = _worker(remote, capture, order)
    assert await worker.step()
    archived = "".join(
        json.loads(call.args[0].content)["raw"] for call in capture.handle.await_args_list
    )
    # Every line the agent wrote, including the one between resume and stop,
    # is archived: nothing landed after the traversal.
    assert sandbox.native and all(line in archived for line in sandbox.native)
    assert '"after-resume"' in archived
    assert order == ["mark_drained", "release"]
    assert remote.order == ["resume:sbx-1", "pause:sbx-1", "kill:sbx-1"]


@pytest.mark.unit
async def test_failed_archive_keeps_sandbox_paused_and_spool_retryable() -> None:
    remote, sandbox = _sandboxes(alive=False)
    capture = AsyncMock()
    capture.handle.side_effect = OSError("archive unavailable")
    order: list[str] = []
    worker, spools = _worker(remote, capture, order)
    assert await worker.step()
    assert sandbox.paused and not sandbox.killed
    assert order == []
    spools.mark_drained.assert_not_awaited()
    spools.advance.assert_awaited_once()
    assert spools.advance.await_args.kwargs["retry_seconds"] == 5


# --- Real store, production wiring ------------------------------------------


async def _runtime(pool: asyncpg.Pool, archive: Path, remote: ScriptedSandboxes, source: str):
    """A fresh worker process: nothing survives but the database and the remote account."""
    from syn_adapters.session_inventory import runtime as runtime_module
    from syn_shared.settings.session_inventory import SessionInventorySettings

    settings = SessionInventorySettings(
        _env_file=None,
        archive_dir=archive,
        source_instance_id=source,
        retry_seconds=1,
    )
    return await runtime_module.create_inventory_runtime(
        cast("Pool", pool),
        MemoryEventStoreClient(),
        settings,
        remote_recovery={"e2b": SandboxSpoolRecovery(remote)},
    )


async def _row(pool: asyncpg.Pool, source: str) -> asyncpg.Record:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT after_sequence,child_after_sequence,drained_at,release_reason,released_at
            FROM session_capture_spools WHERE source_instance_id=$1""",
            source,
        )
    assert row is not None
    return row


def _archived(archive: Path) -> str:
    return "".join(
        json.loads(path.read_bytes())["raw"]
        for path in archive.rglob("*")
        if path.is_file()
        and path.suffix != ".tmp"
        and path.stat().st_size
        and path.read_bytes()[:1] == b"{"
    )


@pytest.mark.integration
async def test_fresh_worker_drains_live_writer_under_fencing_and_kills_only_after_drain(
    db_pool: asyncpg.Pool, tmp_path: Path
) -> None:
    """Paused sandbox, live agent, dead executor: a fresh worker recovers from the row."""
    source = str(uuid4())
    remote, sandbox = _sandboxes(alive=True)
    first = await _runtime(db_pool, tmp_path / "archive", remote, source)
    await first.spools.project(_spool(source))
    await first.spools.settle(_spool(source).session_id)
    del first  # the executor and its memory are gone

    fresh = await _runtime(db_pool, tmp_path / "archive", remote, source)
    await fresh.processor.process_pending()  # recovery drains and marks drained
    await fresh.processor.process_pending()  # nothing left: release must already be done

    row = await _row(db_pool, source)
    assert row["drained_at"] is not None
    assert row["release_reason"] == "archived" and row["released_at"] is not None
    assert row["child_after_sequence"] == 1
    assert remote.order[-1] == "kill:sbx-1"
    archived = _archived(tmp_path / "archive")
    # Every line the agent ever wrote reached the archive, including the one
    # written after resume and before the stop; nothing was written after it.
    for line in sandbox.native:
        assert line in archived
    assert '"after-resume"' in archived


@pytest.mark.integration
async def test_failed_archive_upload_leaves_sandbox_paused_and_spool_retryable(
    db_pool: asyncpg.Pool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = str(uuid4())
    remote, sandbox = _sandboxes(alive=False)
    runtime = await _runtime(db_pool, tmp_path / "archive", remote, source)
    await runtime.spools.project(_spool(source))
    await runtime.spools.settle(_spool(source).session_id)
    monkeypatch.setattr(
        runtime.archive, "put", AsyncMock(side_effect=OSError("archive unavailable"))
    )
    await runtime.processor.process_pending()

    row = await _row(db_pool, source)
    assert row["drained_at"] is None and row["release_reason"] is None
    assert sandbox.paused and not sandbox.killed
    assert "kill:sbx-1" not in remote.order
    assert await runtime.spools.claim(lease_seconds=60, backends=("e2b",)) is not None


@pytest.mark.integration
async def test_worker_without_remote_access_never_claims_a_remote_spool(
    db_pool: asyncpg.Pool, tmp_path: Path
) -> None:
    source = str(uuid4())
    remote, _ = _sandboxes()
    runtime = await _runtime(db_pool, tmp_path / "archive", remote, source)
    await runtime.spools.project(_spool(source))
    assert await runtime.spools.claim(lease_seconds=60, backends=("docker",)) is None
    assert await runtime.spools.claim(lease_seconds=60, backends=("e2b",)) is not None
