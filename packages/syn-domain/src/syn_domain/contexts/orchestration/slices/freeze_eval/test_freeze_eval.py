"""FreezeEval slice (evals plan, #967). The rules are pinned in the aggregate
tests and the cross-slice behaviour in ``update_eval``; this pins the handler."""

from __future__ import annotations

import os

# WHY: the in-memory event store asserts a non-production environment.
os.environ.setdefault("APP_ENVIRONMENT", "test")

import pytest
from event_sourcing import EventStoreRepository
from event_sourcing.client.memory import MemoryEventStoreClient

from syn_adapters.storage.repositories import RepositoryAdapter
from syn_domain.contexts.orchestration.domain.aggregate_eval import EvalAggregate, EvalId, Goal
from syn_domain.contexts.orchestration.slices.create_eval import CreateEvalHandler
from syn_domain.contexts.orchestration.slices.freeze_eval import FreezeEvalHandler
from syn_domain.testing.fake_revision_resolver import FakeRevisionResolver

pytestmark = pytest.mark.unit


async def test_freezes_an_existing_eval_and_ignores_an_unknown_one() -> None:
    repository = RepositoryAdapter(
        EventStoreRepository(
            MemoryEventStoreClient(),
            EvalAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
            "Eval",
        )
    )
    created = await CreateEvalHandler(repository, FakeRevisionResolver()).handle(
        eval_id=EvalId("eval-1"), name="Quality", goal=Goal("Keep tests green")
    )
    assert created.success

    handler = FreezeEvalHandler(repository)
    assert await handler.handle(eval_id=EvalId("eval-unknown")) is None
    result = await handler.handle(eval_id=EvalId("eval-1"))
    assert result is not None and result.success
    stored = await repository.get_by_id("eval-1")
    assert stored is not None and stored.is_frozen and stored.frozen_at is not None
