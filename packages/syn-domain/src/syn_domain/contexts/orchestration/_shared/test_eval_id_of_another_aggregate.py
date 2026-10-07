"""An eval id that names another aggregate's stream is not an eval (#967, #1557).

The ESP server keys a stream by aggregate id alone, so loading ``Eval-<id>``
where ``<id>`` is an execution's id returns the EXECUTION's events. The SDK
rehydrates an ``EvalAggregate`` from them (unknown events are skipped, the id
comes from the envelope), so ``aggregate.id`` is set although no eval was ever
created. Every eval command must treat that as "no such eval" and write
nothing; otherwise ``POST /evals/<execution-id>/archive`` or
``syn workflow run --eval <execution-id>`` appends Eval events to the
execution's stream.

``MemoryEventStoreClient`` keys a stream by aggregate id alone, as the server
does, since ESP v0.17.0 (event-sourcing-platform#345); before that it keyed by
the whole stream name and hid this.
"""

from __future__ import annotations

import os

# WHY: the in-memory event store asserts a non-production environment.
os.environ.setdefault("APP_ENVIRONMENT", "test")

import pytest
from event_sourcing import EventStoreRepository
from event_sourcing.client.memory import MemoryEventStoreClient

from syn_adapters.storage.repositories import RepositoryAdapter
from syn_domain.contexts.orchestration import TagSet, WorkflowExecutionAggregate
from syn_domain.contexts.orchestration._shared.eval_admission import (
    EvalUnavailableError,
    admit_launch,
    open_eval,
)
from syn_domain.contexts.orchestration.domain.aggregate_eval import EvalAggregate, EvalId
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    StartExecutionCommand,
)
from syn_domain.contexts.orchestration.slices.archive_eval import ArchiveEvalHandler
from syn_domain.contexts.orchestration.slices.update_eval.UpdateEvalHandler import (
    UpdateEvalHandler,
)
from syn_domain.testing.fake_revision_resolver import FakeRevisionResolver

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

EXECUTION_ID = "exec-967-foreign"


async def _world() -> tuple[MemoryEventStoreClient, RepositoryAdapter[EvalAggregate]]:
    client = MemoryEventStoreClient()
    executions = RepositoryAdapter(
        EventStoreRepository(
            client,
            WorkflowExecutionAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
            "WorkflowExecution",
        )
    )
    execution = WorkflowExecutionAggregate()
    execution._handle_command(  # pyright: ignore[reportPrivateUsage]
        StartExecutionCommand(
            execution_id=EXECUTION_ID,
            workflow_id="wf-967",
            workflow_name="Foreign",
            total_phases=1,
            inputs={},
            tags=TagSet(),
        )
    )
    await executions.save_new(execution)
    evals = RepositoryAdapter(
        EventStoreRepository(
            client,
            EvalAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
            "Eval",
        )
    )
    return client, evals


async def _stream(client: MemoryEventStoreClient) -> list[str]:
    return [e.event.event_type for e in await client.read_events(f"Eval-{EXECUTION_ID}")]


async def test_the_shared_stream_is_real() -> None:
    """The hazard: the eval repository does load the execution's stream."""
    _, evals = await _world()
    loaded = await evals.get_by_id(EXECUTION_ID)
    assert loaded is not None and loaded.id is not None
    assert not loaded.exists


async def test_archive_is_not_found_and_writes_nothing() -> None:
    client, evals = await _world()
    before = await _stream(client)
    assert await ArchiveEvalHandler(evals).handle(eval_id=EvalId(EXECUTION_ID)) is None
    assert await _stream(client) == before


async def test_update_is_not_found_and_writes_nothing() -> None:
    client, evals = await _world()
    before = await _stream(client)
    result = await UpdateEvalHandler(evals, FakeRevisionResolver()).handle(
        eval_id=EvalId(EXECUTION_ID), name="x"
    )
    assert result is None
    assert await _stream(client) == before


async def test_a_launch_or_attach_refuses_it_as_missing() -> None:
    client, evals = await _world()
    before = await _stream(client)
    with pytest.raises(EvalUnavailableError) as refused:
        await open_eval(evals, EXECUTION_ID)
    assert refused.value.missing
    with pytest.raises(EvalUnavailableError):
        await admit_launch(evals, EXECUTION_ID)
    assert await _stream(client) == before
