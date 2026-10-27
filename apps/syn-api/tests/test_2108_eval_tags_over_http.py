"""#2108 S3: `POST /evals/{id}/tags` writes an eval-set roster onto an existing eval.

The harness registers a roster by tagging each case's eval with
``suite-version:<n>``, ``split:<s>`` and ``polarity:<p>``. Evals made before
the roster existed must gain those tags, so tags are added after create.
Through the real app, route, handler, aggregate and event-store repository;
what is asserted is what reached the stream and the tag filter the roster is read through.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from syn_api.types import CreateEvalRequest, EvalBaselineRepoRequest
from syn_domain.contexts.orchestration.slices.create_eval.test_1920_concurrent_keyed_creates_make_one_eval import (
    SHA,
    RendezvousResolver,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

ROSTER = ["suite-version:7", "split:holdout", "polarity:defect"]


@pytest.fixture(autouse=True)
def _reset_storage() -> Iterator[None]:
    from syn_adapters.projection_stores import get_projection_store
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    store = get_projection_store()
    if hasattr(store, "_data"):
        store._data.clear()  # pyright: ignore[reportAttributeAccessIssue]  # in-memory store only
    if hasattr(store, "_state"):
        store._state.clear()  # pyright: ignore[reportAttributeAccessIssue]  # in-memory store only
    yield
    reset_storage()
    reset_projection_manager()


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    from syn_api.main import create_app

    monkeypatch.setattr(
        "syn_api.routes.evals.get_revision_resolver", lambda: RendezvousResolver(parties=1)
    )
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        yield c


async def _create(client: AsyncClient) -> str:
    body = CreateEvalRequest(
        stable_key="suite:verifier-seed\ncase:roster-tags",
        name="verifier-seed: roster-tags",
        goal="The verifier blocks what it should",
        baseline_repos=[EvalBaselineRepoRequest(repository="acme/app", requested_ref=SHA)],
        tags=["suite:verifier-seed", "case:roster-tags"],
    )
    response = await client.post("/evals", json=body.model_dump())
    assert response.status_code == 201, response.text
    return str(response.json()["eval_id"])


async def _catch_up() -> None:
    """Replay the store into the eval read model, as the coordinator would."""
    from event_sourcing.client.memory import MemoryEventStoreClient
    from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

    from syn_adapters.projections.manager import get_projection_manager
    from syn_adapters.storage.event_store_client import get_event_store_client
    from syn_domain.testing.stored_replay import replay

    store_client = get_event_store_client()
    assert isinstance(store_client, MemoryEventStoreClient)
    await replay(store_client, MemoryCheckpointStore(), get_projection_manager().eval_list)


async def _event_types(eval_id: str) -> list[str]:
    from syn_adapters.storage.event_store_client import get_event_store_client

    stored = await get_event_store_client().read_events(f"Eval-{eval_id}")
    return [e.event.event_type for e in stored]


async def test_added_tags_reach_the_stream_and_the_tag_filter(client: AsyncClient) -> None:
    eval_id = await _create(client)

    response = await client.post(f"/evals/{eval_id}/tags", json={"tags": ROSTER})

    assert response.status_code == 200, response.text
    assert set(response.json()["tags"]) == {"suite:verifier-seed", "case:roster-tags", *ROSTER}
    assert await _event_types(eval_id) == ["EvalCreated", "EvalUpdated"]
    await _catch_up()
    found = await client.get(
        "/evals", params=[("tag", "suite-version:7"), ("tag", "split:holdout")]
    )
    assert [e["eval_id"] for e in found.json()["evals"]] == [eval_id]


async def test_re_adding_present_tags_writes_nothing(client: AsyncClient) -> None:
    eval_id = await _create(client)
    await client.post(f"/evals/{eval_id}/tags", json={"tags": ROSTER})

    again = await client.post(f"/evals/{eval_id}/tags", json={"tags": ROSTER})

    assert again.status_code == 200, again.text
    assert await _event_types(eval_id) == ["EvalCreated", "EvalUpdated"]


async def test_an_unknown_eval_is_404(client: AsyncClient) -> None:
    response = await client.post("/evals/eval-nobody/tags", json={"tags": ROSTER})

    assert response.status_code == 404, response.text


async def test_an_invalid_tag_is_422_and_writes_nothing(client: AsyncClient) -> None:
    eval_id = await _create(client)

    response = await client.post(f"/evals/{eval_id}/tags", json={"tags": ["models:a+b"]})

    assert response.status_code == 422, response.text
    assert await _event_types(eval_id) == ["EvalCreated"]
