"""An E2B run writes exactly one capture spool row, and a Docker run is unchanged (#2161).

The phase is started through the production ``PhaseWorkspace.start_phase`` on a
real ``WorkspaceService``: the E2B one drives agentic-workspace's
``E2BWorkspaceProvider`` over the ``SandboxDouble`` E2B account, the Docker
stand-in is the memory backend (same kit default, ``spool_backend="docker"``).
Only provisioning's prompt and checkout work is skipped. The session stream it
saves is then replayed, twice, through the production
``HostSessionEvidenceProjector`` into a spool port with the Postgres adapter's
identity rule (first write wins, a different row for the same session raises).

Negative control: delete the ``record_sandbox_spool`` call in ``start_phase``
and ``test_an_e2b_run_writes_one_sandbox_spool_row`` finds no row.
"""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from syn_adapters.session_inventory.workspace_location import workspace_capture_location
from syn_adapters.workspace_backends.backend_kit import BackendKit
from syn_adapters.workspace_backends.e2b.test_e2b_backend import (
    _KEY,
    _TEMPLATE,
    SandboxDouble,
    _Command,
    _settings,
)
from syn_adapters.workspace_backends.host_labels import executor_host_id
from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService
from syn_domain.contexts.agent_sessions import (
    CaptureSpool,
    HostSessionEvidenceProjector,
    RunIdentity,
    SandboxSpoolRecordedEvent,
    SessionStartedEvent,
)
from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationConfig,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
    ProvisionResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_workspace import (
    PhaseWorkspace,
)
from syn_domain.testing.fake_session_repository import FakeSessionRepository

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

    from event_sourcing import DomainEvent, EventEnvelope

    from syn_domain.contexts.agent_sessions import CaptureSpoolLease, SpoolBackend

pytestmark = pytest.mark.unit

_SOURCE = "installation-2161"
_EXECUTION = "exec-2161"
_PHASE = "implement"


class _Spools:
    """The spool port's projection half, with ``PostgresCaptureSpools.project``'s rule."""

    def __init__(self) -> None:
        self.rows: dict[str, CaptureSpool] = {}

    async def project(self, spool: CaptureSpool) -> None:
        kept = self.rows.setdefault(spool.session_id, spool)
        if kept != spool:
            raise ValueError("Capture spool identity was rebound to a different session scope")

    async def settle(self, session_id: str) -> None:
        del session_id

    async def settle_run(self, run: RunIdentity) -> None:
        del run

    async def claim(
        self, *, lease_seconds: int, backends: Collection[SpoolBackend]
    ) -> CaptureSpoolLease | None:
        raise AssertionError("projection never claims")

    async def renew(self, lease: CaptureSpoolLease, *, lease_seconds: int) -> None:
        raise AssertionError("projection never renews")

    async def advance(
        self,
        lease: CaptureSpoolLease,
        *,
        after: int,
        watermark: int | None,
        retry_seconds: int,
        staged_bytes: int = 0,
    ) -> None:
        raise AssertionError("projection never advances")

    async def mark_drained(self, lease: CaptureSpoolLease) -> None:
        raise AssertionError("projection never drains")

    async def advance_children(
        self, lease: CaptureSpoolLease, *, after: int, watermark: int | None
    ) -> None:
        raise AssertionError("projection never advances")


class _RecordingSandbox(SandboxDouble):
    """The E2B double, keeping the environment every sandbox command ran with."""

    def __init__(self) -> None:
        super().__init__()
        self.environments: list[dict[str, str]] = []
        self.labels: list[dict[str, str]] = []

    async def create(
        self, *, template: str, metadata: Mapping[str, str], lifetime_seconds: int
    ) -> str:
        self.labels.append(dict(metadata))
        return await super().create(
            template=template, metadata=metadata, lifetime_seconds=lifetime_seconds
        )

    async def start(  # type: ignore[override]
        self,
        sandbox_id: str,
        command: str,
        *,
        cwd: str | None,
        env: Mapping[str, str],
        timeout: float | None,
        user: str,
        stdin: bytes | None = None,
    ) -> _Command:
        self.environments.append(dict(env or {}))
        return await super().start(
            sandbox_id, command, cwd=cwd, env=env, timeout=timeout, user=user, stdin=stdin
        )


async def _start_phase(
    service: WorkspaceService, monkeypatch: pytest.MonkeyPatch
) -> tuple[list[EventEnvelope[DomainEvent]], str]:
    """Start one phase through ``PhaseWorkspace`` and return its session stream."""
    repository = FakeSessionRepository()
    runtime = MagicMock()
    runtime.record_starting_point = AsyncMock()
    runtime.rehearse_quarantine_credential = AsyncMock()
    workspaces = PhaseWorkspace(
        session_repository=repository,
        workspace_service=service,
        artifact_repository=MagicMock(),
        artifact_content_storage=None,
        artifact_query=None,
        observability_writer=None,
        prompt_builder=AsyncMock(),
        command_builder=MagicMock(),
        claude_plugin_materializer=None,
        skill_materializer=None,
        runtime=runtime,
        journal=AsyncMock(),
        inputs={},
    )
    sandbox_ids: list[str] = []
    async with AsyncExitStack() as stack:

        async def provision(*, todo: TodoItem, session_id: str, **_: object) -> ProvisionResult:
            # What WorkspaceProvisionHandler asks the service for, minus prompts.
            cm = service.create_workspace(
                todo.execution_id,
                "wf-2161",
                todo.phase_id,
                with_sidecar=False,
                capture_session_id=session_id,
            )
            workspace = await stack.enter_async_context(cm)
            sandbox_ids.append(workspace.isolation_handle.isolation_id)
            return ProvisionResult(
                workspace=workspace,
                workspace_cm=cm,
                agent_env={},
                claude_cmd=[],
                command=MagicMock(),
            )

        monkeypatch.setattr(workspaces, "provision", provision)
        phase = MagicMock()
        phase.name, phase.order, phase.delivers_repo_changes = "Implement", 1, False
        phase.agent_config.provider, phase.agent_config.model = "claude", "claude-opus-5-5"
        aggregate = MagicMock()
        aggregate.workflow_id = "wf-2161"
        await workspaces.start_phase(
            TodoItem(
                execution_id=_EXECUTION, action=TodoAction.PROVISION_WORKSPACE, phase_id=_PHASE
            ),
            phase,
            aggregate,
            repos=None,
            completed_phase_ids=[],
            phase_outputs=MagicMock(),
        )
    ((session_id, stream),) = repository.streams.items()
    del session_id
    return stream, sandbox_ids[0]


async def _replay(stream: list[EventEnvelope[DomainEvent]]) -> _Spools:
    """Catch-up twice over the same stream: projection must converge, not duplicate."""
    spools = _Spools()
    projector = HostSessionEvidenceProjector(AsyncMock(), _SOURCE, spools)
    subscribed = projector.get_subscribed_event_types()
    for _ in range(2):
        for position, envelope in enumerate(stream, start=1):
            # The metadata the event store stamps on append; uncommitted has none.
            stored = envelope.model_copy(
                update={
                    "metadata": envelope.metadata.model_copy(
                        update={"event_type": envelope.event.event_type, "global_nonce": position}
                    )
                }
            )
            if stored.metadata.event_type in subscribed:
                await projector.handle(stored)
    return spools


def _assert_no_reattach_token(*texts: str) -> None:
    for text in texts:
        assert "reattach" not in text.lower()


async def test_an_e2b_run_writes_one_sandbox_spool_row(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    e2b = _settings(monkeypatch, ENABLED="true", API_KEY=_KEY, TEMPLATE=_TEMPLATE, MEMORY_MB="4096")
    sandbox = _RecordingSandbox()
    service = WorkspaceService.create(
        backend=WorkspaceBackend.E2B,
        e2b=e2b,
        e2b_client=sandbox,
        capture_source_instance_id=_SOURCE,
    )

    stream, sandbox_id = await _start_phase(service, monkeypatch)
    spools = await _replay(stream)

    events = [envelope.event for envelope in stream]
    assert [type(e).__name__ for e in events] == [
        "SessionStartedEvent",
        "SandboxSpoolRecordedEvent",
    ]
    started, recorded = events
    assert isinstance(started, SessionStartedEvent)
    assert isinstance(recorded, SandboxSpoolRecordedEvent)
    assert started.capture_profile == "sandbox-spool/1"
    assert (recorded.backend, recorded.sandbox_id) == ("e2b", sandbox_id)

    (row,) = spools.rows.values()
    assert row == CaptureSpool(
        run=RunIdentity(source_instance_id=_SOURCE, execution_id=_EXECUTION),
        session_id=started.session_id,
        phase_id=_PHASE,
        profile="sandbox-spool/1",
        backend="e2b",
        executor_id=executor_host_id(),
        sandbox_id=sandbox_id,
    )
    # The sandbox's own label is the executor the row names: recovery's
    # ownership check compares the two.
    (labels,) = sandbox.labels
    assert labels["syn.host_id"] == row.executor_id

    # Mountless capture: the sandbox's commands ran with the capture env, aimed
    # at /spool and the partition recovery derives from the row.
    partition = workspace_capture_location(row.run, row.session_id).partition
    assert any(
        env.get("AGENTIC_SESSION_STORE_SPOOL") == "/spool"
        and env.get("AGENTIC_SESSION_STORE_PARTITION") == partition
        for env in sandbox.environments
    )

    _assert_no_reattach_token(
        *(event.model_dump_json() for event in events), row.model_dump_json(), caplog.text
    )


async def test_a_docker_run_is_unchanged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    service = WorkspaceService.create(backend=WorkspaceBackend.MEMORY)
    assert service.spool_backend == "docker"

    stream, _ = await _start_phase(service, monkeypatch)
    spools = await _replay(stream)

    events = [envelope.event for envelope in stream]
    (started,) = events
    assert isinstance(started, SessionStartedEvent)
    assert started.capture_profile == "local-spool/1"
    (row,) = spools.rows.values()
    # The historical Docker row, byte for byte: no backend, sandbox or executor set.
    assert row == CaptureSpool(
        run=RunIdentity(source_instance_id=_SOURCE, execution_id=_EXECUTION),
        session_id=started.session_id,
        phase_id=_PHASE,
    )
    _assert_no_reattach_token(started.model_dump_json(), row.model_dump_json(), caplog.text)


async def test_a_sandbox_spool_start_alone_writes_no_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the recorded sandbox makes a row: a start cannot name a sandbox yet."""
    e2b = _settings(monkeypatch, ENABLED="true", API_KEY=_KEY, TEMPLATE=_TEMPLATE, MEMORY_MB="4096")
    service = WorkspaceService.create(
        backend=WorkspaceBackend.E2B,
        e2b=e2b,
        e2b_client=_RecordingSandbox(),
        capture_source_instance_id=_SOURCE,
    )
    stream, _ = await _start_phase(service, monkeypatch)
    spools = await _replay(stream[:1])
    assert spools.rows == {}


def test_the_spool_event_and_row_have_no_place_for_a_reattach_token() -> None:
    """A credential (#1919) cannot ride either: no field, and extra fields are refused."""
    assert set(SandboxSpoolRecordedEvent.model_fields) == {
        "session_id",
        "execution_id",
        "phase_id",
        "backend",
        "executor_id",
        "sandbox_id",
        "recorded_at",
    }
    with pytest.raises(ValidationError):
        CaptureSpool(
            run=RunIdentity(source_instance_id=_SOURCE, execution_id=_EXECUTION),
            session_id="s",
            phase_id=_PHASE,
            profile="sandbox-spool/1",
            backend="e2b",
            executor_id="host",
            sandbox_id="sbx",
            reattach_token="not-a-real-token",  # type: ignore[call-arg]
        )


def _isolation_config() -> IsolationConfig:
    return IsolationConfig(
        execution_id=_EXECUTION, workspace_id="ws-2161", capture_session_id="s-2161"
    )


def test_the_e2b_kit_captures_without_a_mount() -> None:
    kit = BackendKit.e2b(_TEMPLATE, cpu_count=2, memory_mb=4096, capture_source_instance_id=_SOURCE)
    environment: dict[str, str] = {}
    assert kit.capture_mounts(_isolation_config(), environment) == []
    assert kit.spool_backend == "e2b"
    assert environment["AGENTIC_SESSION_STORE_SPOOL"] == "/spool"
    assert environment["AGENTIC_SESSION_STORE_PROVIDER"] == "local"
    assert "session-store" in environment["AGENTIC_CAPABILITIES"].split()


def test_the_e2b_kit_without_a_capture_source_captures_nothing() -> None:
    kit = BackendKit.e2b(_TEMPLATE, cpu_count=2, memory_mb=4096)
    environment: dict[str, str] = {}
    assert kit.capture_mounts(_isolation_config(), environment) == []
    assert environment == {}


def test_the_docker_kit_still_mounts_its_volume() -> None:
    kit = BackendKit(capture_source_instance_id=_SOURCE)
    environment: dict[str, str] = {}
    (mount,) = kit.capture_mounts(_isolation_config(), environment)
    location = workspace_capture_location(
        RunIdentity(source_instance_id=_SOURCE, execution_id=_EXECUTION), "s-2161"
    )
    assert (mount.host_path, mount.container_path, mount.kind) == (
        location.volume_name,
        "/spool",
        "volume",
    )
    assert environment["AGENTIC_SESSION_STORE_PARTITION"] == location.partition
