"""UpdateEval through a real (in-memory) event store (evals plan, #967)."""

from __future__ import annotations

import os

# WHY: the in-memory event store asserts a non-production environment.
os.environ.setdefault("APP_ENVIRONMENT", "test")

import pytest
from event_sourcing import ConcurrencyConflictError, EventStoreRepository
from event_sourcing.client.memory import MemoryEventStoreClient

from syn_adapters.storage.repositories import RepositoryAdapter
from syn_domain.contexts._shared.repository_ref import RepositoryRef
from syn_domain.contexts.orchestration._shared.repository_baseline import BaselineRequest
from syn_domain.contexts.orchestration.domain.aggregate_eval import EvalAggregate, EvalId, Goal
from syn_domain.contexts.orchestration.domain.commands.FreezeEvalCommand import (
    FreezeEvalCommand,
)
from syn_domain.contexts.orchestration.slices.archive_eval import ArchiveEvalHandler
from syn_domain.contexts.orchestration.slices.create_eval import CreateEvalHandler
from syn_domain.contexts.orchestration.slices.freeze_eval import FreezeEvalHandler
from syn_domain.contexts.orchestration.slices.update_eval import UpdateEvalHandler
from syn_domain.testing.fake_revision_resolver import FakeRevisionResolver
from syn_domain.testing.stored_replay import stored_envelopes

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
    return FakeRevisionResolver(shas={("acme/api", "main"): _SHA_A, ("acme/api", "dev"): _SHA_B})


def _ask(ref: str) -> BaselineRequest:
    return BaselineRequest(repository=RepositoryRef.from_slug("acme/api"), requested_ref=ref)


async def _store_with_eval() -> tuple[MemoryEventStoreClient, RepositoryAdapter[EvalAggregate]]:
    client = MemoryEventStoreClient()
    repository = _repository(client)
    result = await CreateEvalHandler(repository, _resolver()).handle(
        eval_id=_ID, name="Quality", goal=Goal("Keep tests green"), baseline=[_ask("main")]
    )
    assert result.success, result.error
    return client, repository


async def _stored(repository: RepositoryAdapter[EvalAggregate]) -> EvalAggregate:
    aggregate = await repository.get_by_id(str(_ID))
    assert aggregate is not None
    return aggregate


async def test_an_unknown_eval_is_none() -> None:
    _client, repository = await _store_with_eval()
    handler = UpdateEvalHandler(repository, _resolver())
    assert await handler.handle(eval_id=EvalId("eval-missing"), name="x") is None


async def test_re_pins_the_baseline_before_freezing() -> None:
    _client, repository = await _store_with_eval()
    result = await UpdateEvalHandler(repository, _resolver()).handle(
        eval_id=_ID, baseline=[_ask("dev")]
    )
    assert result is not None and result.success, result
    assert [b.commit_sha for b in (await _stored(repository)).baseline_repos] == [_SHA_B]


async def test_an_unresolved_ref_refuses_the_update() -> None:
    client, repository = await _store_with_eval()
    result = await UpdateEvalHandler(repository, _resolver()).handle(
        eval_id=_ID, name="Renamed", baseline=[_ask("gone")]
    )
    assert result is not None and not result.success
    assert "acme/api@gone (not_found)" in result.error
    assert len(await stored_envelopes(client)) == 1


async def test_a_frozen_eval_keeps_its_goal_and_baseline_but_not_its_name() -> None:
    client, repository = await _store_with_eval()
    update = UpdateEvalHandler(repository, _resolver())
    frozen = await FreezeEvalHandler(repository).handle(eval_id=_ID)
    assert frozen is not None and frozen.success

    refused = await update.handle(eval_id=_ID, goal=Goal("Different experiment"))
    assert refused is not None and not refused.success
    assert "frozen" in refused.error
    refused = await update.handle(eval_id=_ID, baseline=[_ask("dev")])
    assert refused is not None and not refused.success

    renamed = await update.handle(eval_id=_ID, name="Renamed", add_tags=["weekly"])
    assert renamed is not None and renamed.success
    stored = await _stored(repository)
    assert (stored.name, list(stored.tags), str(stored.goal)) == (
        "Renamed",
        ["weekly"],
        "Keep tests green",
    )
    assert [e.event.event_type for e in await stored_envelopes(client)] == [
        "EvalCreated",
        "EvalFrozen",
        "EvalUpdated",
    ]


async def test_an_archived_eval_refuses_update_and_freeze() -> None:
    _client, repository = await _store_with_eval()
    archived = await ArchiveEvalHandler(repository).handle(eval_id=_ID, archived_by="ops")
    assert archived is not None and archived.success

    update = await UpdateEvalHandler(repository, _resolver()).handle(eval_id=_ID, name="x")
    freeze = await FreezeEvalHandler(repository).handle(eval_id=_ID)
    assert update is not None and "archived" in update.error
    assert freeze is not None and "archived" in freeze.error


async def test_duplicate_freeze_and_archive_write_once() -> None:
    client, repository = await _store_with_eval()
    for _ in range(2):
        result = await FreezeEvalHandler(repository).handle(eval_id=_ID)
        assert result is not None and result.success
    for _ in range(2):
        result = await ArchiveEvalHandler(repository).handle(eval_id=_ID)
        assert result is not None and result.success
    assert [e.event.event_type for e in await stored_envelopes(client)] == [
        "EvalCreated",
        "EvalFrozen",
        "EvalArchived",
    ]


class _FrozenBehindYourBack(RepositoryAdapter[EvalAggregate]):
    """Hands out the eval, then lets a concurrent FreezeEval land first."""

    async def get_by_id(self, aggregate_id: str) -> EvalAggregate | None:
        seen = await super().get_by_id(aggregate_id)
        rival = await super().get_by_id(aggregate_id)
        assert rival is not None
        rival.freeze(FreezeEvalCommand(eval_id=EvalId(aggregate_id)))
        await super().save(rival)
        return seen


async def test_an_update_racing_a_freeze_loses_on_the_stream_version() -> None:
    """The baseline edit was decided against an unfrozen eval; it must not land."""
    client, repository = await _store_with_eval()
    racing = _FrozenBehindYourBack(repository.sdk_repository)

    with pytest.raises(ConcurrencyConflictError):
        await UpdateEvalHandler(racing, _resolver()).handle(eval_id=_ID, baseline=[_ask("dev")])

    stored = await _stored(repository)
    assert stored.is_frozen
    assert [b.commit_sha for b in stored.baseline_repos] == [_SHA_A]
    assert [e.event.event_type for e in await stored_envelopes(client)] == [
        "EvalCreated",
        "EvalFrozen",
    ]
