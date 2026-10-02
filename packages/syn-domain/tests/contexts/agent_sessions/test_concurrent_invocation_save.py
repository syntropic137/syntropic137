"""A concurrent writer never erases an invocation command (#1398).

Runs against the ESP memory client, which enforces expected versions the same
way the event store does. The real-store race lives in syn-adapters'
test_session_inventory_live_worker.py.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from event_sourcing import ConcurrencyConflictError, RepositoryFactory, StreamAlreadyExistsError
from event_sourcing.client.memory import MemoryEventStoreClient

from syn_domain.contexts.agent_sessions import (
    AgentSessionAggregate,
    InvocationStatus,
    RecordSessionInvocationCommand,
    SessionInvocationState,
    save_reapplying,
)
from syn_domain.contexts.agent_sessions.domain.events.SessionInvocationBindingConflictedEvent import (
    SessionInvocationBindingConflictedEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SessionLifecycleManager import (
    SessionLifecycleManager,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from event_sourcing import EventStoreRepository

pytestmark = pytest.mark.unit
SESSION = "race-session"


class Sessions:
    """The domain repository surface over the SDK repository (as RepositoryAdapter)."""

    def __init__(self) -> None:
        self.client = MemoryEventStoreClient()
        self._sdk: EventStoreRepository[AgentSessionAggregate] = RepositoryFactory(
            self.client
        ).create_repository(AgentSessionAggregate, aggregate_type="AgentSession")  # type: ignore[arg-type]

    async def get_by_id(self, aggregate_id: str) -> AgentSessionAggregate | None:
        return await self._sdk.load(aggregate_id)

    async def save(self, aggregate: AgentSessionAggregate) -> None:
        await self._sdk.save(aggregate)

    async def save_new(self, aggregate: AgentSessionAggregate) -> None:
        await self._sdk.save_new(aggregate)

    async def exists(self, aggregate_id: str) -> bool:
        return await self._sdk.exists(aggregate_id)


@pytest.fixture
def repository(monkeypatch: pytest.MonkeyPatch) -> Sessions:
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    return Sessions()


def _manager(repository: Sessions) -> SessionLifecycleManager:
    return SessionLifecycleManager(
        repository=repository,
        session_id=SESSION,
        workflow_id="definition",
        execution_id="run",
        phase_id="phase",
        agent_provider="claude",
        agent_model=None,
    )


def _bind(intent: SessionInvocationState, native: str) -> Callable[[AgentSessionAggregate], None]:
    command = RecordSessionInvocationCommand(
        aggregate_id=SESSION,
        invocation=intent.model_copy(
            update={"status": InvocationStatus.LAUNCHED, "native_session_id": native}
        ),
    )
    return lambda aggregate: aggregate.record_invocation(command)


async def _conflicts(repository: Sessions) -> list[str]:
    events = await repository.client.read_events(f"AgentSession-{SESSION}")
    return [
        envelope.event.conflicting_native_session_id
        for envelope in events
        if isinstance(envelope.event, SessionInvocationBindingConflictedEvent)
    ]


async def test_racing_first_binds_keep_one_and_record_the_other(
    repository: Sessions,
) -> None:
    manager = _manager(repository)
    await manager.start()
    intent = await manager.prepare_invocation("claude")
    assert intent is not None
    # Both writers decide against the same unbound invocation.
    first, second = await repository.get_by_id(SESSION), await repository.get_by_id(SESSION)
    assert first is not None and second is not None
    claims = {"native-a": first, "native-b": second}

    async def write(native: str, aggregate: AgentSessionAggregate) -> None:
        command = _bind(intent, native)
        command(aggregate)
        await save_reapplying(repository, SESSION, aggregate, (command,))

    await asyncio.gather(*(write(native, aggregate) for native, aggregate in claims.items()))

    final = await repository.get_by_id(SESSION)
    assert final is not None
    (invocation,) = final.invocations
    assert invocation.native_session_id in claims
    loser = next(native for native in claims if native != invocation.native_session_id)
    assert await _conflicts(repository) == [loser]


async def test_manager_finish_after_a_concurrent_bind_records_the_conflict(
    repository: Sessions,
) -> None:
    manager = _manager(repository)
    await manager.start()
    intent = await manager.prepare_invocation("claude")
    assert intent is not None
    other = await repository.get_by_id(SESSION)
    assert other is not None
    _bind(intent, "native-other")(other)
    await repository.save(other)  # The manager's copy is now stale.

    await manager.finish_invocation(native_session_id="native-mine", status=InvocationStatus.FAILED)

    final = await repository.get_by_id(SESSION)
    assert final is not None
    (invocation,) = final.invocations
    assert invocation.native_session_id == "native-other"
    assert invocation.status is InvocationStatus.FAILED
    assert await _conflicts(repository) == ["native-mine"]
    # The manager now tracks the retained binding, so nothing is re-claimed.
    await manager.finish_invocation(native_session_id=None, status=InvocationStatus.FAILED)
    assert await _conflicts(repository) == ["native-mine"]


async def test_retries_are_bounded_and_new_streams_never_retry() -> None:
    class AlwaysBehind:
        loads = 0

        async def get_by_id(self, aggregate_id: str) -> object:
            del aggregate_id
            self.loads += 1
            return object()

        async def save(self, aggregate: object) -> None:
            del aggregate
            raise ConcurrencyConflictError(1, 2)

    store = AlwaysBehind()
    with pytest.raises(ConcurrencyConflictError):
        await save_reapplying(store, SESSION, object(), (), attempts=3)
    assert store.loads == 2

    class Exists(AlwaysBehind):
        async def save(self, aggregate: object) -> None:
            del aggregate
            raise StreamAlreadyExistsError(SESSION, 1)

    exists = Exists()
    with pytest.raises(StreamAlreadyExistsError):
        await save_reapplying(exists, SESSION, object(), ())
    assert exists.loads == 0
