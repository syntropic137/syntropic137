"""#967 step 6: evals are created, listed, shown, archived and their runs read over HTTP.

Through the real app, routes, handlers, aggregates and event-store repositories;
only the store and the revision resolver are doubles. Writes are asserted on
the STREAM, reads on what the eval and execution read models serve.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from syn_domain.contexts.orchestration import TagSet, WorkflowExecutionAggregate
from syn_domain.contexts.orchestration._shared.eval_choice import EvalSelection, LaunchEval
from syn_domain.contexts.orchestration.domain.aggregate_eval import EvalId
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    StartExecutionCommand,
)
from syn_domain.testing.fake_revision_resolver import FakeRevisionResolver

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

SHA = "a" * 40


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
def resolver(monkeypatch: pytest.MonkeyPatch) -> FakeRevisionResolver:
    fake = FakeRevisionResolver(shas={("acme/app", "main"): SHA})
    monkeypatch.setattr("syn_api.routes.evals.get_revision_resolver", lambda: fake)
    return fake


@pytest.fixture
async def client(resolver: FakeRevisionResolver) -> AsyncIterator[AsyncClient]:
    from syn_api.main import create_app

    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        yield c


async def _stream_event_types(eval_id: str) -> list[str]:
    from syn_adapters.storage.event_store_client import get_event_store_client

    envelopes = await get_event_store_client().read_events(f"Eval-{eval_id}")
    return [e.event.event_type for e in envelopes]


async def _catch_up() -> None:
    """The coordinator catching the eval read model up: replay the store into it.

    The in-process sync path does not deliver Eval events (they are typed
    handlers, and the legacy event map passes dicts), so this is the lag a
    client sees until the coordinator runs. Replay is idempotent.
    """
    from event_sourcing.client.memory import MemoryEventStoreClient
    from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

    from syn_adapters.projections.manager import get_projection_manager
    from syn_adapters.storage.event_store_client import get_event_store_client
    from syn_domain.testing.stored_replay import replay

    store_client = get_event_store_client()
    assert isinstance(store_client, MemoryEventStoreClient)
    await replay(store_client, MemoryCheckpointStore(), get_projection_manager().eval_list)


async def _create(client: AsyncClient) -> str:
    response = await client.post(
        "/evals",
        json={
            "name": "Refactor baseline",
            "goal": "Does the refactor workflow keep tests green?",
            "baseline_repos": [{"repository": "acme/app", "requested_ref": "main"}],
            "tags": ["Refactor"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["eval_id"]


async def _launch_into(eval_id: str, execution_id: str) -> None:
    from syn_api._wiring import (
        ensure_connected,
        get_workflow_execution_repository,
        sync_published_events_to_projections,
    )

    await ensure_connected()
    aggregate = WorkflowExecutionAggregate()
    aggregate._handle_command(  # pyright: ignore[reportPrivateUsage]
        StartExecutionCommand(
            execution_id=execution_id,
            workflow_id="wf-eval-967",
            workflow_name="Evaluated",
            total_phases=1,
            inputs={},
            tags=TagSet(),
            launch_eval=LaunchEval(EvalId(eval_id), EvalSelection.EXPLICIT),
        )
    )
    await get_workflow_execution_repository().save_new(aggregate)
    await sync_published_events_to_projections()


class TestCreateEval:
    async def test_the_receipt_carries_the_pinned_baseline_from_the_aggregate(
        self, client: AsyncClient, resolver: FakeRevisionResolver
    ) -> None:
        response = await client.post(
            "/evals",
            json={
                "name": "Refactor baseline",
                "goal": "Does the refactor workflow keep tests green?",
                "baseline_repos": [{"repository": "acme/app", "requested_ref": "main"}],
                "tags": ["Refactor"],
            },
        )

        assert response.status_code == 201, response.text
        receipt = response.json()
        assert receipt["eval_id"].startswith("eval-")
        assert receipt["baseline_repos"] == [
            {"repository": "acme/app", "requested_ref": "main", "commit_sha": SHA}
        ]
        assert receipt["tags"] == ["refactor"]
        assert resolver.asked == [("acme/app", "main")]
        assert await _stream_event_types(receipt["eval_id"]) == ["EvalCreated"]

    async def test_a_caller_cannot_choose_the_id(self, client: AsyncClient) -> None:
        """A chosen id could equal an execution's, and streams are keyed by id alone (#1557)."""
        response = await client.post(
            "/evals",
            json={"eval_id": "exec-0001", "name": "n", "goal": "g"},
        )

        assert response.status_code == 422
        assert await _stream_event_types("exec-0001") == []

    async def test_two_creates_mint_two_streams(self, client: AsyncClient) -> None:
        first = await _create(client)
        second = await _create(client)

        assert first != second
        assert await _stream_event_types(first) == ["EvalCreated"]
        assert await _stream_event_types(second) == ["EvalCreated"]

    async def test_an_unresolvable_ref_is_422_and_records_nothing(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            "/evals",
            json={
                "name": "n",
                "goal": "g",
                "baseline_repos": [{"repository": "acme/app", "requested_ref": "gone"}],
            },
        )

        assert response.status_code == 422
        assert "acme/app@gone" in response.json()["detail"]

    async def test_a_malformed_repository_is_422(self, client: AsyncClient) -> None:
        response = await client.post(
            "/evals",
            json={
                "name": "n",
                "goal": "g",
                "baseline_repos": [{"repository": "not-a-slug", "requested_ref": "main"}],
            },
        )

        assert response.status_code == 422


class TestReadEvals:
    async def test_list_and_show_serve_the_read_model_with_the_run_tally(
        self, client: AsyncClient
    ) -> None:
        eval_id = await _create(client)
        await _launch_into(eval_id, "exec-eval-967-a")
        assert (await client.get(f"/evals/{eval_id}")).status_code == 404  # lagging
        await _catch_up()

        listed = (await client.get("/evals")).json()
        shown = await client.get(f"/evals/{eval_id}")

        assert listed["total"] == 1
        row = listed["evals"][0]
        assert row["eval_id"] == eval_id
        assert row["run_count"] == 1
        assert row["baseline_repos"][0]["commit_sha"] == SHA
        assert shown.status_code == 200
        assert shown.json()["run_count"] == 1
        assert shown.json()["goal"] == "Does the refactor workflow keep tests green?"

    async def test_an_unknown_eval_is_404(self, client: AsyncClient) -> None:
        assert (await client.get("/evals/eval-missing")).status_code == 404

    async def test_runs_are_the_execution_list_filtered_by_eval(self, client: AsyncClient) -> None:
        eval_id = await _create(client)
        other = await _create(client)
        await _launch_into(eval_id, "exec-eval-967-in")
        await _launch_into(other, "exec-eval-967-out")
        # The eval id resolves against the eval read model, as on show (#508).
        assert (await client.get(f"/evals/{eval_id}/runs")).status_code == 404  # lagging
        await _catch_up()

        runs = (await client.get(f"/evals/{eval_id}/runs")).json()
        executions = (await client.get("/executions", params={"eval_id": eval_id})).json()

        ids = [row["execution_id"] for row in runs["items"]]
        assert ids == ["exec-eval-967-in"]
        assert runs["total"] == 1
        assert [row["workflow_execution_id"] for row in executions["executions"]] == ids


class TestArchiveEval:
    async def test_archive_persists_and_shows_as_archived(self, client: AsyncClient) -> None:
        eval_id = await _create(client)

        response = await client.post(f"/evals/{eval_id}/archive")
        again = await client.post(f"/evals/{eval_id}/archive")

        assert response.status_code == 200
        assert response.json() == {"eval_id": eval_id, "archived": True}
        assert again.status_code == 200
        assert await _stream_event_types(eval_id) == ["EvalCreated", "EvalArchived"]
        await _catch_up()
        listed = (await client.get("/evals", params={"status": "archived"})).json()
        assert [row["eval_id"] for row in listed["evals"]] == [eval_id]

    async def test_an_unknown_eval_is_404(self, client: AsyncClient) -> None:
        assert (await client.post("/evals/eval-missing/archive")).status_code == 404
