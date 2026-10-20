"""Concurrent creates of one stable key make one eval on the REAL event store (#1920).

The unit test (``slices/create_eval/test_1920_concurrent_keyed_creates_make_one_eval.py``)
runs this race over ``MemoryEventStoreClient``. This runs it over the ESP gRPC
server, so the no-stream refusal that decides the race is the production
store's, not a double's (#1574). Keys are unique per run, so this never meets
another stream in a shared test store.

    uv run pytest -m integration \\
        packages/syn-domain/tests/integration/test_1920_keyed_eval_create_real_store.py
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syn_adapters.storage.repositories import RepositoryAdapter
from syn_domain.contexts._shared.repository_ref import RepositoryRef
from syn_domain.contexts.orchestration._shared.repository_baseline import BaselineRequest
from syn_domain.contexts.orchestration.domain.aggregate_eval import EvalAggregate, EvalId, Goal
from syn_domain.contexts.orchestration.slices.create_eval import CreateEvalHandler
from syn_domain.contexts.orchestration.slices.create_eval.test_1920_concurrent_keyed_creates_make_one_eval import (
    SHA,
    RendezvousResolver,
)

if TYPE_CHECKING:
    from event_sourcing import RepositoryFactory

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

CASES = ("teardown-lock-waiter-race", "binary-artifact-minio-key")


def eval_repository(factory: RepositoryFactory) -> RepositoryAdapter[EvalAggregate]:
    return RepositoryAdapter(
        factory.create_repository(EvalAggregate, "Eval")  # type: ignore[arg-type]  # ESP SDK TEvent invariance
    )


async def launch(
    factory: RepositoryFactory, suite_tag: str, meet: dict[str, RendezvousResolver]
) -> list[EvalId]:
    """One suite launch: every case's eval, each id derived from suite and case.

    ``meet`` holds one rendezvous per case, shared by both launches, so each
    case's two creates have both seen "no eval" before either writes.
    """
    ids: list[EvalId] = []
    for case in CASES:
        eval_id = EvalId.for_key(f"{suite_tag}\ncase:{case}")
        result = await CreateEvalHandler(eval_repository(factory), meet[case]).handle(
            eval_id=eval_id,
            name=f"verifier-seed: {case}",
            goal=Goal("The verifier blocks what it should"),
            baseline=[
                BaselineRequest(repository=RepositoryRef.from_slug("acme/api"), requested_ref=SHA)
            ],
            tags=[suite_tag, f"case:{case}"],
        )
        assert result.success, result.error
        ids.append(eval_id)
    return ids


async def test_two_concurrent_launches_store_one_eval_per_case(
    repository_factory: RepositoryFactory,
) -> None:
    suite_tag = f"suite:it-1920-{uuid4().hex[:8]}"
    meet = {case: RendezvousResolver(parties=2) for case in CASES}

    first, second = await asyncio.gather(
        launch(repository_factory, suite_tag, meet),
        launch(repository_factory, suite_tag, meet),
    )

    assert first == second
    assert len(set(first)) == len(CASES)
    for eval_id in first:
        stored = await eval_repository(repository_factory).get_by_id(str(eval_id))
        assert stored is not None
        # One EvalCreated: the losing create wrote nothing.
        assert stored.version == 1
