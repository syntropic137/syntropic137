"""#1920: concurrent `POST /evals` with one `stable_key` answer with one eval.

Through the real app, route, handler, aggregate and SDK repository over
``MemoryEventStoreClient``, which refuses a second "no stream yet" append as
the gRPC store does. The two requests meet inside the revision resolver, so
both have seen "no eval" before either writes.
"""

from __future__ import annotations

import asyncio
import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from syn_api.types import CreateEvalRequest, EvalBaselineRepoRequest
from syn_domain.contexts.orchestration.domain.aggregate_eval import EvalId
from syn_domain.contexts.orchestration.slices.create_eval.test_1920_concurrent_keyed_creates_make_one_eval import (
    SHA,
    RendezvousResolver,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

KEY = "suite:verifier-seed\ncase:teardown-lock-waiter-race"


@pytest.fixture(autouse=True)
def _reset_storage() -> Iterator[None]:
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    yield
    reset_storage()
    reset_projection_manager()


def _body(stable_key: str | None) -> CreateEvalRequest:
    return CreateEvalRequest(
        stable_key=stable_key,
        name="verifier-seed: teardown-lock-waiter-race",
        goal="The verifier blocks what it should",
        baseline_repos=[EvalBaselineRepoRequest(repository="acme/app", requested_ref=SHA)],
        tags=["suite:verifier-seed", "case:teardown-lock-waiter-race"],
    )


async def test_two_creates_with_one_stable_key_answer_with_one_eval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from syn_adapters.storage.event_store_client import get_event_store_client
    from syn_api.main import create_app

    resolver = RendezvousResolver(parties=2)
    monkeypatch.setattr("syn_api.routes.evals.get_revision_resolver", lambda: resolver)
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        first, second = await asyncio.gather(
            c.post("/evals", json=_body(KEY).model_dump()),
            c.post("/evals", json=_body(KEY).model_dump()),
        )

    assert (first.status_code, second.status_code) == (201, 201), (first.text, second.text)
    eval_id = str(EvalId.for_key(KEY))
    assert first.json()["eval_id"] == second.json()["eval_id"] == eval_id
    stored = await get_event_store_client().read_events(f"Eval-{eval_id}")
    assert [e.event.event_type for e in stored] == ["EvalCreated"]


async def test_a_create_without_a_stable_key_still_gets_a_fresh_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from syn_api.main import create_app

    resolver = RendezvousResolver(parties=1)
    monkeypatch.setattr("syn_api.routes.evals.get_revision_resolver", lambda: resolver)
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        response = await c.post("/evals", json=_body(None).model_dump())

    assert response.status_code == 201, response.text
    assert response.json()["eval_id"] != str(EvalId.for_key(KEY))
