"""#821 / #444: an eval written over HTTP reads back over HTTP in test mode.

The test-mode EVENT_HANDLERS map had no Eval* routes, so the in-process sync
every eval route calls after a save delivered nothing: a created eval never
appeared in `GET /evals` until something replayed the store into the read
model. No replay here; the only path from write to read is the route's own
`sync_published_events_to_projections()`.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from syn_domain.testing.fake_revision_resolver import FakeRevisionResolver

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

SHA = "b" * 40


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

    fake = FakeRevisionResolver(shas={("acme/app", "main"): SHA})
    monkeypatch.setattr("syn_api.routes.evals.get_revision_resolver", lambda: fake)
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        yield c


async def test_a_created_eval_is_listed_and_an_archived_one_is_listed_as_archived(
    client: AsyncClient,
) -> None:
    created = await client.post(
        "/evals",
        json={
            "name": "Read-your-writes baseline",
            "goal": "Does test-mode dispatch reach the eval read model?",
            "baseline_repos": [{"repository": "acme/app", "requested_ref": "main"}],
        },
    )
    assert created.status_code == 201, created.text
    eval_id = created.json()["eval_id"]

    listed = (await client.get("/evals")).json()
    assert [(e["eval_id"], e["name"]) for e in listed["evals"]] == [
        (eval_id, "Read-your-writes baseline")
    ]

    archived = await client.post(f"/evals/{eval_id}/archive")
    assert archived.status_code == 200, archived.text

    by_status = (await client.get("/evals", params={"status": "archived"})).json()
    assert [e["eval_id"] for e in by_status["evals"]] == [eval_id]
