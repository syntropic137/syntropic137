"""Real gRPC event store + PostgreSQL + local archive, driven only by live signals.

The image is built from the pinned submodule. No vendor API calls, no shared dev
ports, and no direct calls to process_pending: the production coordinator owns
replay/live dispatch. Docker is required for this integration test.
"""

from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock

import asyncpg
import pytest
from event_sourcing import (
    EventEnvelope,
    EventMetadata,
    GrpcEventStoreClient,
    PostgresCheckpointStore,
    RepositoryFactory,
)
from event_sourcing.core.errors import StreamAlreadyExistsError
from fastapi import FastAPI
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network
from testcontainers.core.wait_strategies import PortWaitStrategy
from testcontainers.postgres import PostgresContainer

from syn_adapters.session_inventory.runtime import InventoryRuntime, create_inventory_runtime
from syn_adapters.storage.repositories import RepositoryAdapter
from syn_adapters.subscriptions.coordinator_service import CoordinatorSubscriptionService
from syn_domain.contexts.agent_sessions import (
    AgentSessionAggregate,
    EvidenceBatch,
    InventorySnapshot,
    InvocationStatus,
    RecordSessionInvocationCommand,
    RunIdentity,
    SessionInvocationState,
)
from syn_domain.contexts.agent_sessions._shared.inventory_reconciliation import ReconciliationStage
from syn_domain.contexts.agent_sessions.domain.events.SessionStartedEvent import SessionStartedEvent
from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
    NodeEvidence,
    SessionEvidence,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    EvidenceReference,
    IdentityBinding,
    InventoryGap,
    InventoryNodeRef,
    Membership,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowCompletedEvent import (
    WorkflowCompletedEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SessionLifecycleManager import (
    SessionLifecycleManager,
)
from syn_shared.settings.session_inventory import SessionInventorySettings
from syn_shared.testing import (
    DEFAULT_DB_NAME,
    DEFAULT_DB_PASSWORD,
    DEFAULT_DB_USER,
    DEV_STACK_PORTS,
    get_test_timescaledb_url,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from syn_adapters.session_inventory.database import Pool

pytestmark = pytest.mark.integration
_IMAGE = "syn-inventory-integration-event-store:local"

# Evidence watermarks count appended batches, so each target is derived from the
# events the test emits rather than hard-coded. HostSessionEvidenceProjector writes
# one batch per SessionStarted and per registered invocation, and two per launched
# or terminal invocation (identity plus the separate lifecycle stream, #1398).
_STARTED_BATCHES = 1
_REGISTERED_BATCHES = 1
_LIFECYCLE_BATCHES = 2
_LIVE_INVOCATION_BATCHES = (
    _STARTED_BATCHES  # start()
    + _REGISTERED_BATCHES  # prepare_invocation()
    + _LIFECYCLE_BATCHES  # mark_launched()
    + _LIFECYCLE_BATCHES  # finish_invocation(COMPLETED)
)
_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class InventoryStack:
    database_url: str
    event_store_address: str


@pytest.fixture(scope="module")
def inventory_stack() -> Iterator[InventoryStack]:
    source = _ROOT / "lib/event-sourcing-platform"
    subprocess.run(
        [
            "docker",
            "build",
            "-f",
            str(source / "event-store/Dockerfile"),
            "-t",
            _IMAGE,
            str(source),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    postgres_port = DEV_STACK_PORTS["timescaledb"]
    event_port = DEV_STACK_PORTS["eventstore"]
    with Network() as network:
        database = PostgresContainer(
            "postgres:16-alpine",
            username=DEFAULT_DB_USER,
            password=DEFAULT_DB_PASSWORD,
            dbname=DEFAULT_DB_NAME,
        )
        database.with_network(network).with_network_aliases("inventory-db")
        with database:
            server = DockerContainer(_IMAGE).with_network(network).with_exposed_ports(event_port)
            server.with_env("BACKEND", "postgres").with_env(
                "DATABASE_URL",
                get_test_timescaledb_url(
                    host="inventory-db",
                    port=postgres_port,
                ),
            ).with_env("BIND_ADDR", f"0.0.0.0:{event_port}")
            server.waiting_for(PortWaitStrategy(event_port))
            with server:
                yield InventoryStack(
                    database_url=database.get_connection_url().replace(
                        "postgresql+psycopg2://", "postgresql://"
                    ),
                    event_store_address=f"{server.get_container_host_ip()}:{server.get_exposed_port(event_port)}",
                )


async def _wait_current(runtime: InventoryRuntime, run: RunIdentity, watermark: int) -> None:
    head = job = None
    try:
        async with asyncio.timeout(20):
            while True:
                head = await runtime.inventory.head(run)
                job = await runtime.jobs.latest(run)
                if (
                    head is not None
                    and head.evidence_watermark == watermark
                    and job is not None
                    and job.state.stage is ReconciliationStage.COMPLETED
                ):
                    return
                await asyncio.sleep(0.05)
    except TimeoutError:
        watermark_seen = None if head is None else head.evidence_watermark
        raise AssertionError(
            f"inventory never reached watermark {watermark}: head={watermark_seen} job={job!r}"
        ) from None


def _batch(run: RunIdentity, identity: str) -> EvidenceBatch:
    return EvidenceBatch(
        batch_id=identity,
        producer_id="test",
        evidence=SessionEvidence(
            run=run,
            nodes=(
                NodeEvidence(
                    node=InventoryNodeRef(
                        kind="transcript",
                        source_instance_id=run.source_instance_id,
                        harness="fake",
                        local_id=identity,
                    ),
                    evidence=EvidenceReference(
                        evidence_id=identity,
                        producer_id="test",
                        source_revision="1",
                        locator=identity,
                        extractor_version="test/1",
                    ),
                ),
            ),
        ),
    )


async def _register_live_invocation(client: GrpcEventStoreClient, run: RunIdentity) -> None:
    repository = RepositoryAdapter(
        RepositoryFactory(client).create_repository(
            AgentSessionAggregate,
            aggregate_type="AgentSession",  # type: ignore[arg-type]
        )
    )
    manager = SessionLifecycleManager(
        repository=repository,
        session_id="controlled-session",
        workflow_id="definition",
        execution_id=run.execution_id,
        phase_id="phase-two",
        agent_provider="claude",
        agent_model=None,
    )
    await manager.start()
    await manager.prepare_invocation("claude")
    await manager.mark_launched()
    await manager.finish_invocation(
        native_session_id="native-live", status=InvocationStatus.COMPLETED
    )
    restored = await repository.get_by_id("controlled-session")
    assert restored is not None
    assert restored.invocations[0].native_session_id == "native-live"
    assert restored.invocations[0].status == InvocationStatus.COMPLETED


async def test_live_clock_recovers_pending_inventory_after_full_runtime_restart(
    inventory_stack: InventoryStack,
    tmp_path: Path,
) -> None:
    pool = await asyncpg.create_pool(inventory_stack.database_url, min_size=1, max_size=5)
    assert pool is not None
    client = GrpcEventStoreClient(inventory_stack.event_store_address)
    await client.connect()
    settings = SessionInventorySettings(
        _env_file=None,
        archive_dir=tmp_path,
        sweep_interval_seconds=1,
        retry_seconds=1,
    )
    runtime = await create_inventory_runtime(cast("Pool", pool), client, settings)
    checkpoints = PostgresCheckpointStore(pool)  # type: ignore[arg-type]  # asyncpg dynamic connection proxy
    coordinator = CoordinatorSubscriptionService(
        event_store=client, projections=[runtime.processor], checkpoint_store=checkpoints
    )
    run = RunIdentity(source_instance_id=runtime.source_instance_id, execution_id="live-run")
    try:
        # An old platform event is acquired during catch-up, without a direct
        # inventory write and without inventing an invocation/native identity.
        await client.append_events(
            "AgentSession-before-restart",
            [
                EventEnvelope(
                    event=SessionStartedEvent(
                        session_id="before-restart",
                        workflow_id="definition",
                        execution_id=run.execution_id,
                        phase_id="phase-one",
                        agent_provider="fake",
                        started_at=datetime.now(UTC),
                    ),
                    metadata=EventMetadata(
                        aggregate_id="before-restart",
                        aggregate_type="AgentSession",
                        aggregate_nonce=1,
                        event_type=SessionStartedEvent.event_type,
                    ),
                )
            ],
            expected_version=0,
        )
        await coordinator.start()
        await runtime.clock.start()
        after_catch_up = _STARTED_BATCHES
        await _wait_current(runtime, run, after_catch_up)
        first = await runtime.inventory.head(run)
        assert first is not None
        memberships = await runtime.inventory.page(run, first.snapshot_id, "membership")
        assert len(memberships.items) == 1
        assert isinstance(memberships.items[0], Membership)
        assert memberships.items[0].phase_id == "phase-one"
        assert first.counts.node == 1
        assert first.coverage.state == "unknown"
        await _register_live_invocation(client, run)
        after_live = after_catch_up + _LIVE_INVOCATION_BATCHES
        await _wait_current(runtime, run, after_live)
        controlled = await runtime.inventory.head(run)
        assert controlled is not None
        assert controlled.counts.node == 4
        assert controlled.counts.binding == 1
        assert controlled.coverage.state == "open"
        # The pre-restart platform session is a known node of this run (WP-A
        # seal): it must settle too, so the contract expects it alongside the
        # registered invocation.
        assert controlled.coverage.expected_count == 2
        await runtime.clock.stop()
        await coordinator.stop()
        await runtime.evidence.append(_batch(run, "arrived-while-stopped"))
        await pool.expire_connections()
        # Recreate every inventory/coordinator object. Only durable stores remain.
        runtime = await create_inventory_runtime(cast("Pool", pool), client, settings)
        coordinator = CoordinatorSubscriptionService(
            event_store=client,
            projections=[runtime.processor],
            checkpoint_store=PostgresCheckpointStore(pool),
        )  # type: ignore[arg-type]
        await coordinator.start()
        await runtime.clock.start()
        await _wait_current(runtime, run, after_live + 1)
        latest = await runtime.inventory.head(run)
        assert latest is not None
        assert latest.counts.node == 5
        assert latest.revision != first.revision
        assert len((await runtime.inventory.page(run, first.snapshot_id, "node")).items) == 1
    finally:
        await runtime.clock.stop()
        await coordinator.stop()
        await client.disconnect()
        await pool.close()


# ---------------------------------------------------------------------------
# Acceptance row 4 (#1398): invocation intent across a crash before binding.
# ---------------------------------------------------------------------------


@dataclass
class _Live:
    pool: asyncpg.Pool
    client: GrpcEventStoreClient
    settings: SessionInventorySettings
    runtime: InventoryRuntime
    coordinator: CoordinatorSubscriptionService

    @classmethod
    async def start(cls, stack: InventoryStack, tmp_path: Path) -> _Live:
        pool = await asyncpg.create_pool(stack.database_url, min_size=1, max_size=5)
        assert pool is not None
        client = GrpcEventStoreClient(stack.event_store_address)
        await client.connect()
        settings = SessionInventorySettings(
            _env_file=None,
            archive_dir=tmp_path,
            sweep_interval_seconds=1,
            retry_seconds=1,
            settlement_grace_seconds=0,
        )
        live = cls(pool, client, settings, None, None)  # type: ignore[arg-type]
        await live._boot()
        return live

    async def _boot(self) -> None:
        self.runtime = await create_inventory_runtime(
            cast("Pool", self.pool), self.client, self.settings
        )
        self.coordinator = CoordinatorSubscriptionService(
            event_store=self.client,
            projections=[self.runtime.processor],
            checkpoint_store=PostgresCheckpointStore(self.pool),  # type: ignore[arg-type]
        )
        await self.coordinator.start()
        await self.runtime.clock.start()

    async def stop(self) -> None:
        await self.runtime.clock.stop()
        await self.coordinator.stop()

    async def restart(self) -> None:
        """Drop every in-memory inventory/coordinator object; only durable stores remain."""
        await self.stop()
        await self.pool.expire_connections()
        await self._boot()

    async def close(self) -> None:
        await self.stop()
        await self.client.disconnect()
        await self.pool.close()

    def sessions(self) -> RepositoryAdapter[AgentSessionAggregate]:
        return RepositoryAdapter(
            RepositoryFactory(self.client).create_repository(
                AgentSessionAggregate,
                aggregate_type="AgentSession",  # type: ignore[arg-type]
            )
        )

    def manager(self, run: RunIdentity, session_id: str, harness: str) -> SessionLifecycleManager:
        return SessionLifecycleManager(
            repository=self.sessions(),
            session_id=session_id,
            workflow_id="definition",
            execution_id=run.execution_id,
            phase_id="phase",
            agent_provider=harness,
            agent_model=None,
        )

    async def wait_for(
        self, run: RunIdentity, ready: Callable[[InventorySnapshot], bool]
    ) -> InventorySnapshot:
        head = None
        try:
            async with asyncio.timeout(30):
                while True:
                    head = await self.runtime.inventory.head(run)
                    job = await self.runtime.jobs.latest(run)
                    current = await self.runtime.evidence.watermark(run)
                    if (
                        head is not None
                        and head.evidence_watermark == current
                        and job is not None
                        and job.state.stage is ReconciliationStage.COMPLETED
                        and ready(head)
                    ):
                        return head
                    await asyncio.sleep(0.05)
        except TimeoutError:
            raise AssertionError(f"inventory never became ready: head={head!r}") from None

    async def items(self, run: RunIdentity, head: InventorySnapshot, kind: str) -> list[object]:
        page = await self.runtime.inventory.page(run, head.snapshot_id, kind, limit=500)  # type: ignore[arg-type]
        return list(page.items)


def _invocation_key(run: RunIdentity, invocation_id: str) -> str:
    return InventoryNodeRef(
        kind="invocation", source_instance_id=run.source_instance_id, local_id=invocation_id
    ).key


async def _record(
    repository: RepositoryAdapter[AgentSessionAggregate],
    session_id: str,
    *states: SessionInvocationState,
) -> int:
    """Apply states on the aggregate reloaded from the event store; return events saved."""
    aggregate = await repository.get_by_id(session_id)
    assert aggregate is not None
    for state in states:
        aggregate.record_invocation(
            RecordSessionInvocationCommand(aggregate_id=session_id, invocation=state)
        )
    saved = len(aggregate.get_uncommitted_events())
    if saved:
        await repository.save(aggregate)
    return saved


async def test_intent_survives_crash_before_bind_then_late_bind_duplicates_and_conflict(
    inventory_stack: InventoryStack,
    tmp_path: Path,
) -> None:
    live = await _Live.start(inventory_stack, tmp_path)
    run = RunIdentity(source_instance_id=live.runtime.source_instance_id, execution_id="crash-run")
    try:
        # Intent is durable before launch; the host process then dies before any
        # launch, bind or finish is recorded.
        crashed = live.manager(run, "crashed-session", "codex")
        await crashed.start()
        intent = await crashed.prepare_invocation("codex")
        assert intent is not None
        del crashed
        await live.restart()

        key = _invocation_key(run, intent.invocation_id)
        head = await live.wait_for(run, lambda h: h.counts.node >= 1)
        gaps = cast("list[InventoryGap]", await live.items(run, head, "gap"))
        assert head.coverage.state == "open"
        assert key in head.coverage.missing_keys
        assert any(g.reason == "expected_body_unavailable" and key in g.node_keys for g in gaps)
        assert head.counts.binding == 0, "no native ID is fabricated for an unbound intent"
        members = cast("list[Membership]", await live.items(run, head, "membership"))
        assert any(
            m.node.key == key and m.attempt_id == intent.attempt_id and m.confidence == "registered"
            for m in members
        )
        repository = live.sessions()
        restored = await repository.get_by_id("crashed-session")
        assert restored is not None
        assert restored.invocations == (intent,)
        # A redelivered registration after the restart is a no-op.
        assert await _record(repository, "crashed-session", intent) == 0

        # The bind arrives late, after the restart, and resolves to that intent.
        launched = intent.model_copy(update={"status": InvocationStatus.LAUNCHED})
        finished = launched.model_copy(
            update={"status": InvocationStatus.COMPLETED, "native_session_id": "late-native"}
        )
        assert await _record(repository, "crashed-session", launched, finished) == 2
        head = await live.wait_for(run, lambda h: h.counts.binding == 1)
        (binding,) = cast("list[IdentityBinding]", await live.items(run, head, "binding"))
        assert (binding.owner.key, binding.transcript.local_id) == (key, "late-native")
        assert binding.confidence == "registered"
        bound_revision = head.revision

        # Duplicate start is refused by the event store; nothing new is appended.
        with pytest.raises(StreamAlreadyExistsError):
            await live.manager(run, "crashed-session", "codex").start()
        # A redelivered bind+finish (same terminal state) is a no-op.
        assert await _record(repository, "crashed-session", finished, finished) == 0
        watermark = await live.runtime.evidence.watermark(run)
        await asyncio.sleep(2)  # Two live clock sweeps: nothing new to reconcile.
        assert await live.runtime.evidence.watermark(run) == watermark
        assert (await live.wait_for(run, lambda _: True)).revision == bound_revision

        # A contradicting bind is recorded, never applied: coverage turns conflicting.
        other = finished.model_copy(update={"native_session_id": "other-native"})
        assert await _record(repository, "crashed-session", other) == 1
        assert await _record(repository, "crashed-session", other) == 0
        head = await live.wait_for(run, lambda h: h.coverage.state == "conflicting")
        gaps = cast("list[InventoryGap]", await live.items(run, head, "gap"))
        assert any(g.reason == "conflicting_native_binding" and key in g.node_keys for g in gaps)
        natives = {
            b.transcript.local_id
            for b in cast("list[IdentityBinding]", await live.items(run, head, "binding"))
        }
        assert natives == {"late-native", "other-native"}
        final = await repository.get_by_id("crashed-session")
        assert final is not None
        assert final.invocations[0].native_session_id == "late-native"
    finally:
        await live.close()


async def test_failed_launch_stays_distinct_from_launched_but_uncaptured_in_api(
    inventory_stack: InventoryStack,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from httpx import ASGITransport, AsyncClient

    from syn_api.routes.executions import inventory as inventory_routes

    live = await _Live.start(inventory_stack, tmp_path)
    run = RunIdentity(
        source_instance_id=live.runtime.source_instance_id, execution_id="outcome-run"
    )
    try:
        never = live.manager(run, "never-launched", "claude")
        await never.start()
        failed_launch = await never.prepare_invocation("claude")
        await never.finish_invocation(native_session_id=None, status=InvocationStatus.LAUNCH_FAILED)
        lost = live.manager(run, "launched-uncaptured", "codex")
        await lost.start()
        uncaptured = await lost.prepare_invocation("codex")
        await lost.mark_launched()
        await lost.finish_invocation(native_session_id=None, status=InvocationStatus.FAILED)
        assert failed_launch is not None and uncaptured is not None
        await live.client.append_events(
            "WorkflowExecution-outcome-run",
            [
                EventEnvelope(
                    event=WorkflowCompletedEvent(
                        workflow_id="definition",
                        execution_id=run.execution_id,
                        completed_at=datetime.now(UTC),
                        total_phases=1,
                        completed_phases=0,
                        total_input_tokens=0,
                        total_output_tokens=0,
                        total_tokens=0,
                        total_duration_seconds=1.0,
                        artifact_ids=[],
                    ),
                    metadata=EventMetadata(
                        aggregate_id="outcome-run",
                        aggregate_type="WorkflowExecution",
                        aggregate_nonce=1,
                        event_type=WorkflowCompletedEvent.event_type,
                    ),
                )
            ],
            expected_version=0,
        )
        # Zero grace: the live clock releases the deadline on its next sweep.
        await live.wait_for(run, lambda h: h.coverage.state == "missing")

        monkeypatch.setattr(inventory_routes, "get_inventory_runtime", lambda: live.runtime)
        monkeypatch.setattr(inventory_routes, "_visible_run", AsyncMock(return_value=run))
        app = FastAPI()
        app.include_router(inventory_routes.router)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
            body = (await http.get("/executions/outcome-run/session-inventory")).json()
            assert body["reconstruction_status"] == "current"
            snapshot = body["snapshot"]
            assert snapshot["coverage"]["state"] == "missing"
            page = await http.get(
                f"/executions/outcome-run/session-inventory/{snapshot['snapshot_id']}/gap"
            )
            assert page.status_code == 200
        by_reason: dict[str, set[str]] = {}
        for gap in page.json()["items"]:
            by_reason.setdefault(gap["reason"], set()).update(gap["node_keys"])
        never_key = _invocation_key(run, failed_launch.invocation_id)
        lost_key = _invocation_key(run, uncaptured.invocation_id)
        assert by_reason["invocation_launch_failed"] == {never_key}
        assert by_reason["invocation_failed"] == {lost_key}
        # Only the process that ran owes a transcript it never delivered.
        assert by_reason["capture_unsettled_at_seal"] == {lost_key}
        assert never_key not in by_reason.get("invocation_unsettled_at_seal", set())
        assert lost_key not in by_reason["invocation_launch_failed"]
    finally:
        await live.close()
