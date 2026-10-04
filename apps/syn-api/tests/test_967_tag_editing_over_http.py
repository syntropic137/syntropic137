"""#967: tags are edited after creation over HTTP, and the edit is persisted.

Every test goes through the real app (`create_app()`, so the strict-query
guard and request validation run), the real route, the real handler, the real
aggregate and the real event-store repository; only the store is in memory.
What is asserted is what reached the STREAM, read back from the event store
client, not what the route said it did (#955): a route that answered with the
right tags and dropped the command, or built it with the wrong id, fails here.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from typing import TYPE_CHECKING

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from syn_domain.contexts.orchestration import TagSet, WorkflowExecutionAggregate
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    StartExecutionCommand,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

pytestmark = pytest.mark.unit

EXECUTION_ID = "exec-tag-edit-967-0001"
LAUNCH_TAGS = ["nightly", "smoke"]


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
async def client() -> AsyncIterator[AsyncClient]:
    from syn_api.main import create_app

    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        yield c


async def _launch_execution() -> None:
    """An execution launched with LAUNCH_TAGS, saved and projected like a real one."""
    from syn_api._wiring import (
        ensure_connected,
        get_workflow_execution_repository,
        sync_published_events_to_projections,
    )

    await ensure_connected()
    aggregate = WorkflowExecutionAggregate()
    aggregate._handle_command(  # pyright: ignore[reportPrivateUsage]
        StartExecutionCommand(
            execution_id=EXECUTION_ID,
            workflow_id="wf-tag-edit",
            workflow_name="Tagged",
            total_phases=1,
            inputs={},
            tags=TagSet(LAUNCH_TAGS),
        )
    )
    await get_workflow_execution_repository().save_new(aggregate)
    await sync_published_events_to_projections()


async def _create_workflow() -> str:
    from syn_api.routes.workflows import create_workflow
    from syn_api.types import Ok

    result = await create_workflow(name="Tag edit workflow", workflow_type="research")
    assert isinstance(result, Ok)
    return result.value.workflow_id


async def _stream(stream: str) -> list[tuple[str, list[str]]]:
    """The tag edits persisted on a stream, as (event type, tags), in order."""
    from syn_adapters.storage.event_store_client import get_event_store_client

    envelopes = await get_event_store_client().read_events(stream)
    return [
        (e.event.event_type, list(e.event.model_dump()["tags"]))
        for e in envelopes
        if e.event.event_type.endswith(("TagsAdded", "TagsRemoved"))
    ]


async def _add(client: AsyncClient, path: str, tags: list[str]) -> httpx.Response:
    return await client.post(f"{path}/tags", json={"tags": tags})


async def _remove(client: AsyncClient, path: str, tags: list[str]) -> httpx.Response:
    return await client.delete(f"{path}/tags", params={"tag": tags})


EXEC_PATH = f"/executions/{EXECUTION_ID}"
EXEC_STREAM = f"WorkflowExecution-{EXECUTION_ID}"


class TestExecutionTagsArePersisted:
    async def test_add_persists_only_the_new_tag(self, client: AsyncClient) -> None:
        await _launch_execution()

        response = await _add(client, EXEC_PATH, ["Eval:Planning-2026-08", "nightly"])

        assert response.status_code == 200, response.text
        assert response.json() == {
            "execution_id": EXECUTION_ID,
            "tags": ["eval:planning-2026-08", "nightly", "smoke"],
            "inherited_tags": LAUNCH_TAGS,
        }
        assert await _stream(EXEC_STREAM) == [("ExecutionTagsAdded", ["eval:planning-2026-08"])]

    async def test_remove_persists_the_removal(self, client: AsyncClient) -> None:
        await _launch_execution()

        response = await _remove(client, EXEC_PATH, ["smoke"])

        assert response.status_code == 200, response.text
        assert response.json()["tags"] == ["nightly"]
        assert await _stream(EXEC_STREAM) == [("ExecutionTagsRemoved", ["smoke"])]

    async def test_a_prefix_id_edits_the_full_one(self, client: AsyncClient) -> None:
        await _launch_execution()

        response = await _add(client, "/executions/exec-tag-edit-967", ["x"])

        assert response.status_code == 200, response.text
        assert response.json()["execution_id"] == EXECUTION_ID
        assert await _stream(EXEC_STREAM) == [("ExecutionTagsAdded", ["x"])]


class TestEditsAreIdempotentNeverReplaceAll:
    async def test_add_then_remove_twice_each_records_one_event_each(
        self, client: AsyncClient
    ) -> None:
        await _launch_execution()

        first_add = await _add(client, EXEC_PATH, ["baseline"])
        second_add = await _add(client, EXEC_PATH, ["baseline"])
        first_remove = await _remove(client, EXEC_PATH, ["baseline"])
        second_remove = await _remove(client, EXEC_PATH, ["baseline"])

        assert [r.status_code for r in (first_add, second_add, first_remove, second_remove)] == [
            200
        ] * 4
        assert first_add.json() == second_add.json()
        assert first_remove.json() == second_remove.json()
        assert second_remove.json()["tags"] == LAUNCH_TAGS
        assert await _stream(EXEC_STREAM) == [
            ("ExecutionTagsAdded", ["baseline"]),
            ("ExecutionTagsRemoved", ["baseline"]),
        ]

    async def test_adding_one_tag_keeps_the_others(self, client: AsyncClient) -> None:
        await _launch_execution()

        response = await _add(client, EXEC_PATH, ["only-this"])

        assert response.json()["tags"] == ["nightly", "only-this", "smoke"]


class TestInheritedTagsAreARecord:
    async def test_removing_a_launch_tag_leaves_inherited_tags_unchanged(
        self, client: AsyncClient
    ) -> None:
        from syn_api._wiring import get_workflow_execution_repository

        await _launch_execution()

        response = await _remove(client, EXEC_PATH, ["nightly"])

        assert response.status_code == 200, response.text
        assert response.json()["tags"] == ["smoke"]
        assert response.json()["inherited_tags"] == LAUNCH_TAGS
        replayed = await get_workflow_execution_repository().get_by_id(EXECUTION_ID)
        assert replayed is not None
        assert list(replayed.tags.inherited) == LAUNCH_TAGS
        assert list(replayed.tags.current) == ["smoke"]


class TestTheListFilterSeesTheEdit:
    async def _listed(self, client: AsyncClient, tag: str) -> list[str]:
        response = await client.get("/executions", params={"tag": tag})
        assert response.status_code == 200, response.text
        return [e["workflow_execution_id"] for e in response.json()["executions"]]

    async def test_an_added_tag_is_filterable_and_a_removed_one_is_not(
        self, client: AsyncClient
    ) -> None:
        await _launch_execution()
        assert await self._listed(client, "eval:x") == []

        await _add(client, EXEC_PATH, ["eval:x"])
        assert await self._listed(client, "eval:x") == [EXECUTION_ID]

        await _remove(client, EXEC_PATH, ["eval:x", "nightly"])
        assert await self._listed(client, "eval:x") == []
        assert await self._listed(client, "nightly") == []
        assert await self._listed(client, "smoke") == [EXECUTION_ID]


class TestTheResponseIsTheAggregates:
    async def test_the_response_does_not_wait_for_the_projection(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from syn_api.routes import tags

        await _launch_execution()

        async def _projection_never_catches_up() -> None:
            return None

        monkeypatch.setattr(
            tags, "sync_published_events_to_projections", _projection_never_catches_up
        )

        response = await _add(client, EXEC_PATH, ["fresh"])

        assert response.json()["tags"] == ["fresh", "nightly", "smoke"]
        detail = await client.get(EXEC_PATH)
        assert "fresh" not in detail.json()["tags"]


class TestRefusals:
    @pytest.mark.parametrize("path", [EXEC_PATH, "/workflows/no-such-workflow"])
    async def test_an_unknown_id_is_404(self, client: AsyncClient, path: str) -> None:
        unknown = path.replace(EXECUTION_ID, "no-such-execution")
        assert (await _add(client, unknown, ["x"])).status_code == 404
        assert (await _remove(client, unknown, ["x"])).status_code == 404

    async def test_an_invalid_tag_is_422_and_writes_nothing(self, client: AsyncClient) -> None:
        await _launch_execution()

        added = await _add(client, EXEC_PATH, ["has space"])
        removed = await _remove(client, EXEC_PATH, ["has space"])

        assert (added.status_code, removed.status_code) == (422, 422)
        assert "has space" in added.text
        assert "has space" in removed.text
        assert await _stream(EXEC_STREAM) == []

    async def test_an_empty_add_is_422_and_writes_nothing(self, client: AsyncClient) -> None:
        await _launch_execution()

        response = await _add(client, EXEC_PATH, [])

        assert response.status_code == 422
        assert "At least one tag is required" in response.text
        assert await _stream(EXEC_STREAM) == []

    async def test_a_remove_without_tags_is_422(self, client: AsyncClient) -> None:
        await _launch_execution()
        assert (await client.delete(f"{EXEC_PATH}/tags")).status_code == 422

    async def test_add_is_not_replace_all(self, client: AsyncClient) -> None:
        """A body naming another field (say a `replace` flag) is refused, not ignored."""
        await _launch_execution()
        response = await client.post(f"{EXEC_PATH}/tags", json={"tags": ["x"], "replace": True})
        assert response.status_code == 422


class TestWorkflowTags:
    async def test_add_and_remove_persist_and_reach_the_read_model(
        self, client: AsyncClient
    ) -> None:
        workflow_id = await _create_workflow()
        path = f"/workflows/{workflow_id}"
        stream = f"WorkflowTemplate-{workflow_id}"

        added = await _add(client, path, ["Team:Evals", "nightly"])
        again = await _add(client, path, ["nightly"])
        removed = await _remove(client, path, ["nightly"])

        assert added.status_code == 200, added.text
        assert added.json() == {"workflow_id": workflow_id, "tags": ["nightly", "team:evals"]}
        assert again.json() == added.json()
        assert removed.json() == {"workflow_id": workflow_id, "tags": ["team:evals"]}
        assert await _stream(stream) == [
            ("WorkflowTagsAdded", ["nightly", "team:evals"]),
            ("WorkflowTagsRemoved", ["nightly"]),
        ]
        detail = await client.get(path)
        assert detail.json()["tags"] == ["team:evals"]

    async def test_an_invalid_workflow_tag_is_422(self, client: AsyncClient) -> None:
        workflow_id = await _create_workflow()
        response = await _add(client, f"/workflows/{workflow_id}", ["bad tag!"])
        assert response.status_code == 422
        assert await _stream(f"WorkflowTemplate-{workflow_id}") == []
