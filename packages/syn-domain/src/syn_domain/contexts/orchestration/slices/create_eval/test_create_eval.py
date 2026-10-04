"""CreateEval through a real (in-memory) event store (evals plan, #967)."""

from __future__ import annotations

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
from syn_domain.testing.fake_revision_resolver import FakeRevisionResolver

pytestmark = pytest.mark.unit

_ID = EvalId("eval-1")
_SHA_A = "a" * 40
_SHA_B = "b" * 40


def _repository(client: MemoryEventStoreClient) -> RepositoryAdapter[EvalAggregate]:
    return RepositoryAdapter(
        EventStoreRepository(
            client,
            EvalAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
            "Eval",
        )
    )


def _resolver() -> FakeRevisionResolver:
    return FakeRevisionResolver(shas={("acme/api", "main"): _SHA_A, ("acme/web", "v2"): _SHA_B})


def _ask(slug: str, ref: str) -> BaselineRequest:
    return BaselineRequest(repository=RepositoryRef.from_slug(slug), requested_ref=ref)


from event_sourcing import StreamAlreadyExistsError  # noqa: E402

from syn_domain.contexts.orchestration.domain.commands.CreateEvalCommand import (  # noqa: E402
    CreateEvalCommand,
)
from syn_domain.contexts.orchestration.slices.create_eval import CreateEvalHandler  # noqa: E402
from syn_domain.testing.stored_replay import stored_envelopes  # noqa: E402


async def _create(handler: CreateEvalHandler, name: str = "Quality") -> bool:
    result = await handler.handle(
        eval_id=_ID,
        name=name,
        goal=Goal("Keep tests green"),
        baseline=[_ask("acme/web", "v2"), _ask("acme/api", "main")],
        tags=["nightly"],
    )
    assert result.success or result.error
    return result.success


async def test_pins_every_requested_ref_to_its_commit() -> None:
    repository = _repository(MemoryEventStoreClient())
    assert await _create(CreateEvalHandler(repository, _resolver()))
    stored = await repository.get_by_id(str(_ID))
    assert stored is not None
    assert [(b.repository.slug, b.requested_ref, b.commit_sha) for b in stored.baseline_repos] == [
        ("acme/api", "main", _SHA_A),
        ("acme/web", "v2", _SHA_B),
    ]


async def test_an_unresolved_ref_refuses_the_create_and_records_nothing() -> None:
    client = MemoryEventStoreClient()
    resolver = _resolver()
    resolver.unavailable.add("acme/web")
    result = await CreateEvalHandler(_repository(client), resolver).handle(
        eval_id=_ID,
        name="Quality",
        goal=Goal("Keep tests green"),
        baseline=[_ask("acme/api", "missing"), _ask("acme/web", "v2")],
    )
    assert not result.success
    assert "acme/api@missing (not_found)" in result.error
    assert "acme/web@v2 (unavailable" in result.error
    assert await stored_envelopes(client) == []


async def test_replay_reconstructs_the_aggregate_exactly() -> None:
    client = MemoryEventStoreClient()
    repository = _repository(client)
    assert await _create(CreateEvalHandler(repository, _resolver()))
    live = await repository.get_by_id(str(_ID))
    assert live is not None

    replayed = EvalAggregate()
    replayed.rehydrate(await stored_envelopes(client))  # pyright: ignore[reportArgumentType]

    assert vars(replayed) == vars(live)


async def test_a_retried_create_is_an_idempotent_success() -> None:
    client = MemoryEventStoreClient()
    handler = CreateEvalHandler(_repository(client), _resolver())
    assert await _create(handler)
    assert await _create(handler)
    assert len(await stored_envelopes(client)) == 1


async def test_a_different_create_for_a_taken_id_fails() -> None:
    client = MemoryEventStoreClient()
    handler = CreateEvalHandler(_repository(client), _resolver())
    assert await _create(handler)
    assert not await _create(handler, name="Someone else's eval")
    assert len(await stored_envelopes(client)) == 1


class _LosesTheRace(RepositoryAdapter[EvalAggregate]):
    """Sees no eval on the fast path, then finds one was written meanwhile."""

    def __init__(self, inner: RepositoryAdapter[EvalAggregate]) -> None:
        super().__init__(inner.sdk_repository)
        self.first_read = True

    async def get_by_id(self, aggregate_id: str) -> EvalAggregate | None:
        if self.first_read:
            self.first_read = False
            return None
        return await super().get_by_id(aggregate_id)


async def test_a_create_that_loses_a_race_answers_against_the_winner() -> None:
    client = MemoryEventStoreClient()
    assert await _create(CreateEvalHandler(_repository(client), _resolver()))

    racing = _LosesTheRace(_repository(client))
    assert await _create(CreateEvalHandler(racing, _resolver()))
    racing.first_read = True
    assert not await _create(CreateEvalHandler(racing, _resolver()), name="Different")
    assert len(await stored_envelopes(client)) == 1


async def test_save_new_is_create_only() -> None:
    client = MemoryEventStoreClient()
    repository = _repository(client)
    assert await _create(CreateEvalHandler(repository, _resolver()))
    fresh = EvalAggregate()
    fresh.create(CreateEvalCommand(eval_id=_ID, name="x", goal=Goal("y")))
    with pytest.raises(StreamAlreadyExistsError):
        await repository.save_new(fresh)
