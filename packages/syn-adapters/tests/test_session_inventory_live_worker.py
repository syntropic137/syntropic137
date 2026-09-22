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

import asyncpg
import pytest
from event_sourcing import (
    EventEnvelope,
    EventMetadata,
    GrpcEventStoreClient,
    PostgresCheckpointStore,
    RepositoryFactory,
)
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
    InvocationStatus,
    RunIdentity,
)
from syn_domain.contexts.agent_sessions._shared.inventory_reconciliation import ReconciliationStage
from syn_domain.contexts.agent_sessions.domain.events.SessionStartedEvent import SessionStartedEvent
from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
    NodeEvidence,
    SessionEvidence,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    EvidenceReference,
    InventoryNodeRef,
    Membership,
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
    from collections.abc import Iterator

    from syn_adapters.session_inventory.database import Pool

pytestmark = pytest.mark.integration
_IMAGE = "syn-inventory-integration-event-store:local"
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
        await _wait_current(runtime, run, 1)
        first = await runtime.inventory.head(run)
        assert first is not None
        memberships = await runtime.inventory.page(run, first.snapshot_id, "membership")
        assert len(memberships.items) == 1
        assert isinstance(memberships.items[0], Membership)
        assert memberships.items[0].phase_id == "phase-one"
        assert first.counts.node == 1
        assert first.coverage.state == "unknown"
        await _register_live_invocation(client, run)
        await _wait_current(runtime, run, 5)
        controlled = await runtime.inventory.head(run)
        assert controlled is not None
        assert controlled.counts.node == 4
        assert controlled.counts.binding == 1
        assert controlled.coverage.state == "open"
        assert controlled.coverage.expected_count == 1
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
        await _wait_current(runtime, run, 6)
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
