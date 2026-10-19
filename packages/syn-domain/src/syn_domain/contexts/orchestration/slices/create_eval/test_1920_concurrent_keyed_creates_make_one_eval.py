"""Concurrent creates of one stable key make one eval (#1920).

Two ``eval_suite launch`` runs that both miss the case's eval each create it.
Each derives the id from the same key, so both write the same stream: the
store's no-stream guard admits one, and the other answers with the winner.

The store here is the SDK repository over ``MemoryEventStoreClient``, which
refuses an append to an existing stream at "no stream yet" exactly as the
gRPC store does; never a hand-rolled double that skips the check (#1574).
The same race against the real store is
``packages/syn-domain/tests/integration/test_1920_keyed_eval_create_real_store.py``.
"""

from __future__ import annotations

import asyncio
import os

# WHY: the in-memory event store asserts a non-production environment.
os.environ.setdefault("APP_ENVIRONMENT", "test")

import pytest
from event_sourcing import EventStoreRepository
from event_sourcing.client.memory import MemoryEventStoreClient

from syn_adapters.storage.repositories import RepositoryAdapter
from syn_domain.contexts._shared.repository_ref import RepositoryRef
from syn_domain.contexts.orchestration._shared.repository_baseline import BaselineRequest
from syn_domain.contexts.orchestration.domain.aggregate_eval import EvalAggregate, EvalId, Goal
from syn_domain.contexts.orchestration.ports.RevisionResolverPort import (
    ResolvedRevision,
    RevisionResolution,
)
from syn_domain.contexts.orchestration.slices.create_eval import CreateEvalHandler
from syn_domain.testing.stored_replay import stored_envelopes

pytestmark = pytest.mark.unit

KEY = "suite:verifier-seed\ncase:teardown-lock-waiter-race"
SHA = "d" * 40


class RendezvousResolver:
    """Holds every resolve until ``parties`` creators are inside it.

    Resolving happens after the handler's existence check and before its
    write, so releasing them together means every creator has already seen
    "no eval" and all of them reach the write: the race, made certain.
    """

    def __init__(self, parties: int) -> None:
        self._parties = parties
        self._arrived = 0
        self._all_in = asyncio.Event()

    async def resolve(self, repository: RepositoryRef, requested_ref: str, /) -> RevisionResolution:
        self._arrived += 1
        if self._arrived >= self._parties:
            self._all_in.set()
        await asyncio.wait_for(self._all_in.wait(), timeout=5)
        return ResolvedRevision(SHA)


def eval_repository(client: MemoryEventStoreClient) -> RepositoryAdapter[EvalAggregate]:
    return RepositoryAdapter(
        EventStoreRepository(
            client,
            EvalAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
            "Eval",
        )
    )


async def create_for_key(
    repository: RepositoryAdapter[EvalAggregate], resolver: RendezvousResolver
) -> tuple[EvalId, bool, str | None]:
    """One launch's create: it derives the id itself, as each launch does."""
    eval_id = EvalId.for_key(KEY)
    result = await CreateEvalHandler(repository, resolver).handle(
        eval_id=eval_id,
        name="verifier-seed: teardown-lock-waiter-race",
        goal=Goal("The verifier blocks what it should"),
        baseline=[
            BaselineRequest(repository=RepositoryRef.from_slug("acme/api"), requested_ref=SHA)
        ],
        tags=["suite:verifier-seed", "case:teardown-lock-waiter-race"],
    )
    return eval_id, result.success, result.error


async def test_two_concurrent_creates_of_one_key_store_one_eval_and_both_get_it() -> None:
    client = MemoryEventStoreClient()
    resolver = RendezvousResolver(parties=2)

    first, second = await asyncio.gather(
        create_for_key(eval_repository(client), resolver),
        create_for_key(eval_repository(client), resolver),
    )

    assert (first[1], first[2]) == (True, "")
    assert (second[1], second[2]) == (True, "")
    assert first[0] == second[0]
    stored = await stored_envelopes(client)
    assert {e.metadata.aggregate_id for e in stored} == {str(first[0])}
    assert [type(e.event).__name__ for e in stored] == ["EvalCreatedEvent"]


def test_a_key_names_one_id_and_another_key_another() -> None:
    assert EvalId.for_key(KEY) == EvalId.for_key(KEY)
    assert EvalId.for_key(KEY) != EvalId.for_key(KEY + "x")
    assert str(EvalId.for_key(KEY)).startswith("eval-")


def test_an_empty_key_names_nothing() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        EvalId.for_key("")
