"""CreateEval through a real (in-memory) event store (evals plan, #967)."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable  # noqa: TC003
from dataclasses import dataclass, replace
from datetime import datetime  # noqa: TC003

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
_SHA_C = "c" * 40


def _repository(client: MemoryEventStoreClient) -> RepositoryAdapter[EvalAggregate]:
    return RepositoryAdapter(
        EventStoreRepository(
            client,
            EvalAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
            "Eval",
        )
    )


def _resolver() -> FakeRevisionResolver:
    return FakeRevisionResolver(
        shas={
            ("acme/api", "main"): _SHA_A,
            ("acme/web", "v2"): _SHA_B,
            ("acme/api", "dev"): _SHA_C,
        }
    )


def _ask(slug: str, ref: str) -> BaselineRequest:
    return BaselineRequest(repository=RepositoryRef.from_slug(slug), requested_ref=ref)


from event_sourcing import StreamAlreadyExistsError  # noqa: E402

from syn_domain.contexts.orchestration.domain.commands.CreateEvalCommand import (  # noqa: E402
    CreateEvalCommand,
)
from syn_domain.contexts.orchestration.slices.archive_eval import ArchiveEvalHandler  # noqa: E402
from syn_domain.contexts.orchestration.slices.create_eval import CreateEvalHandler  # noqa: E402
from syn_domain.contexts.orchestration.slices.freeze_eval import FreezeEvalHandler  # noqa: E402
from syn_domain.contexts.orchestration.slices.update_eval import UpdateEvalHandler  # noqa: E402
from syn_domain.testing.stored_replay import stored_envelopes  # noqa: E402


async def _create(
    handler: CreateEvalHandler,
    name: str = "Quality",
    baseline: tuple[BaselineRequest, ...] = (_ask("acme/web", "v2"), _ask("acme/api", "main")),
) -> bool:
    result = await handler.handle(
        eval_id=_ID,
        name=name,
        goal=Goal("Keep tests green"),
        baseline=baseline,
        tags=["nightly"],
        starting_workflow_id="wf-1",
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


@dataclass(frozen=True)
class _State:
    """Every field an Eval exposes, in plain values a test can write down."""

    name: str | None
    goal: str | None
    starting_workflow_id: str | None
    baseline: tuple[tuple[str, str, str], ...]
    tags: tuple[str, ...]
    is_frozen: bool
    is_archived: bool
    created_at: datetime | None
    updated_at: datetime | None
    frozen_at: datetime | None
    archived_at: datetime | None


def _state(aggregate: EvalAggregate | None) -> _State:
    assert aggregate is not None
    return _State(
        name=aggregate.name,
        goal=None if aggregate.goal is None else str(aggregate.goal),
        starting_workflow_id=aggregate.starting_workflow_id,
        baseline=tuple(
            (b.repository.slug, b.requested_ref, b.commit_sha) for b in aggregate.baseline_repos
        ),
        tags=aggregate.tags.values,
        is_frozen=aggregate.is_frozen,
        is_archived=aggregate.is_archived,
        created_at=aggregate.created_at,
        updated_at=aggregate.updated_at,
        frozen_at=aggregate.frozen_at,
        archived_at=aggregate.archived_at,
    )


async def test_replay_reconstructs_what_every_command_decided() -> None:
    """Expected state is written down from the requests, not read off a replay.

    Each step reloads through the repository (a replay) and compares with the
    values the commands asked for; timestamps come from the event that step
    wrote. A replay handler that drops or bends a field fails at its step.
    """
    client = MemoryEventStoreClient()
    repository = _repository(client)

    assert await _create(CreateEvalHandler(repository, _resolver()))
    created = (await stored_envelopes(client))[-1].event
    expected = _State(
        name="Quality",
        goal="Keep tests green",
        starting_workflow_id="wf-1",
        baseline=(("acme/api", "main", _SHA_A), ("acme/web", "v2", _SHA_B)),
        tags=("nightly",),
        is_frozen=False,
        is_archived=False,
        created_at=created.created_at,  # pyright: ignore[reportAttributeAccessIssue]
        updated_at=created.created_at,  # pyright: ignore[reportAttributeAccessIssue]
        frozen_at=None,
        archived_at=None,
    )
    assert _state(await repository.get_by_id(str(_ID))) == expected

    updated = await UpdateEvalHandler(repository, _resolver()).handle(
        eval_id=_ID,
        name="Quality v2",
        goal=Goal("Ship faster"),
        baseline=[_ask("acme/api", "dev")],
        add_tags=["weekly"],
        remove_tags=["nightly"],
    )
    assert updated is not None and updated.success, updated
    stamp = (await stored_envelopes(client))[-1].event.updated_at  # pyright: ignore[reportAttributeAccessIssue]
    expected = replace(
        expected,
        name="Quality v2",
        goal="Ship faster",
        baseline=(("acme/api", "dev", _SHA_C),),
        tags=("weekly",),
        updated_at=stamp,
    )
    assert _state(await repository.get_by_id(str(_ID))) == expected

    frozen = await FreezeEvalHandler(repository).handle(eval_id=_ID)
    assert frozen is not None and frozen.success
    stamp = (await stored_envelopes(client))[-1].event.frozen_at  # pyright: ignore[reportAttributeAccessIssue]
    expected = replace(expected, is_frozen=True, frozen_at=stamp)
    assert _state(await repository.get_by_id(str(_ID))) == expected

    archived = await ArchiveEvalHandler(repository).handle(eval_id=_ID, archived_by="ops")
    assert archived is not None and archived.success
    stored = await stored_envelopes(client)
    stamp = stored[-1].event.archived_at  # pyright: ignore[reportAttributeAccessIssue]
    expected = replace(expected, is_archived=True, archived_at=stamp)
    assert _state(await repository.get_by_id(str(_ID))) == expected

    assert [e.event.event_type for e in stored] == [
        "EvalCreated",
        "EvalUpdated",
        "EvalFrozen",
        "EvalArchived",
    ]
    assert None not in (expected.created_at, expected.updated_at, expected.frozen_at)
    replayed = EvalAggregate()
    replayed.rehydrate(stored)  # pyright: ignore[reportArgumentType]
    assert _state(replayed) == expected


async def test_a_retried_create_is_an_idempotent_success() -> None:
    client = MemoryEventStoreClient()
    handler = CreateEvalHandler(_repository(client), _resolver())
    assert await _create(handler)
    assert await _create(handler)
    assert len(await stored_envelopes(client)) == 1


async def test_a_retry_resolves_nothing_so_an_unreachable_forge_cannot_fail_it() -> None:
    client = MemoryEventStoreClient()
    resolver = _resolver()
    handler = CreateEvalHandler(_repository(client), resolver)
    assert await _create(handler)

    resolver.unavailable.update({"acme/api", "acme/web"})
    resolver.asked.clear()
    assert await _create(handler)
    assert resolver.asked == []
    assert len(await stored_envelopes(client)) == 1


async def _rename(repository: RepositoryAdapter[EvalAggregate]) -> None:
    result = await UpdateEvalHandler(repository, _resolver()).handle(eval_id=_ID, name="Renamed")
    assert result is not None and result.success


async def _retag(repository: RepositoryAdapter[EvalAggregate]) -> None:
    result = await UpdateEvalHandler(repository, _resolver()).handle(
        eval_id=_ID, add_tags=["weekly"], remove_tags=["nightly"]
    )
    assert result is not None and result.success


async def _regoal(repository: RepositoryAdapter[EvalAggregate]) -> None:
    result = await UpdateEvalHandler(repository, _resolver()).handle(
        eval_id=_ID, goal=Goal("Ship faster")
    )
    assert result is not None and result.success


async def _rebaseline(repository: RepositoryAdapter[EvalAggregate]) -> None:
    result = await UpdateEvalHandler(repository, _resolver()).handle(
        eval_id=_ID, baseline=[_ask("acme/api", "dev")]
    )
    assert result is not None and result.success


@pytest.mark.parametrize("edit", [_rename, _retag, _regoal, _rebaseline])
async def test_the_original_create_is_still_a_retry_after_an_edit(
    edit: Callable[[RepositoryAdapter[EvalAggregate]], Awaitable[None]],
) -> None:
    client = MemoryEventStoreClient()
    repository = _repository(client)
    handler = CreateEvalHandler(repository, _resolver())
    assert await _create(handler)
    await edit(repository)

    assert await _create(handler)
    assert len(await stored_envelopes(client)) == 2


async def test_a_retry_listing_a_repository_twice_is_refused_like_a_fresh_create() -> None:
    client = MemoryEventStoreClient()
    resolver = _resolver()
    handler = CreateEvalHandler(_repository(client), resolver)
    assert await _create(handler)

    resolver.asked.clear()
    twice = (_ask("acme/web", "v2"), _ask("acme/api", "main"), _ask("acme/api", "main"))
    result = await handler.handle(
        eval_id=_ID,
        name="Quality",
        goal=Goal("Keep tests green"),
        baseline=twice,
        tags=["nightly"],
        starting_workflow_id="wf-1",
    )
    assert not result.success
    assert "repeated: acme/api" in result.error
    assert resolver.asked == []
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
