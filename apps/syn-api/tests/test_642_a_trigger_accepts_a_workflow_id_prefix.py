"""A trigger names its workflow by the prefix `syn workflow list` prints (#642).

`syn workflow list` shows 8-character workflow IDs. `syn triggers register
--workflow <prefix>` and `syn triggers enable <preset> --workflow <prefix>`
refused them as "does not exist", because the routes looked the raw string up
by exact ID. The trigger fires its workflow later, by the ID it stored, so a
prefix that is accepted must also be stored as the full ID.

These drive the HTTP routes the CLI calls, then read the stored trigger back:
the full ID is only worth anything if it is what the trigger keeps.
"""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient, Response

from syn_api.types import Ok, TriggerError, TriggerErrorResponse

pytestmark = pytest.mark.unit

os.environ.setdefault("APP_ENVIRONMENT", "test")

_REPO = "acme/widgets"
# An explicit installation keeps GitHub out of these tests (#1864 covers it).
_INSTALLATION = "inst-642"

_UNIQUE = "f00dcafe-6420-4642-8642-000000000642"
# Two workflows sharing their first eight characters: that prefix means both.
_TWIN_A = "a1b2c3d4-0000-4642-8642-000000000001"
_TWIN_B = "a1b2c3d4-1111-4642-8642-000000000002"


async def _seed_workflow(workflow_id: str) -> None:
    from syn_adapters.storage.repositories import get_workflow_repository
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
        PhaseDefinition,
        WorkflowClassification,
        WorkflowType,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
        WorkflowTemplateAggregate,
    )
    from syn_domain.contexts.orchestration.domain.commands.CreateWorkflowTemplateCommand import (
        CreateWorkflowTemplateCommand,
    )

    aggregate = WorkflowTemplateAggregate()
    aggregate._handle_command(
        CreateWorkflowTemplateCommand(
            aggregate_id=workflow_id,
            name=f"workflow-{workflow_id[:8]}",
            workflow_type=WorkflowType.CUSTOM,
            classification=WorkflowClassification.SIMPLE,
            repository_url="https://github.com/acme/widgets",
            repository_ref="main",
            phases=[PhaseDefinition(phase_id="phase-1", name="phase1", order=1)],
        )
    )
    await get_workflow_repository().save(aggregate)


@pytest.fixture(autouse=True)
async def _fresh_stores_with_workflows():
    import syn_api._wiring
    from syn_adapters.storage import reset_storage
    from syn_api._wiring import ensure_connected, sync_published_events_to_projections
    from syn_domain.contexts.github.slices.register_trigger.trigger_store import (
        reset_trigger_store,
    )

    reset_storage()
    reset_trigger_store()
    syn_api._wiring._test_trigger_repo = None
    await ensure_connected()
    for workflow_id in (_UNIQUE, _TWIN_A, _TWIN_B):
        await _seed_workflow(workflow_id)
    # The prefix resolves through the `workflow_details` read model, exactly
    # as `syn workflow show <prefix>` does, so it has to be caught up.
    await sync_published_events_to_projections()
    yield
    reset_trigger_store()
    syn_api._wiring._test_trigger_repo = None


async def _post(path: str, body: dict[str, str]) -> Response:
    from fastapi import FastAPI

    from syn_api.routes.triggers import router

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(path, json=body)


async def _register(workflow_id: str) -> Response:
    return await _post(
        "/triggers",
        {
            "name": "on-push",
            "event": "push",
            "repository": _REPO,
            "workflow_id": workflow_id,
            "installation_id": _INSTALLATION,
        },
    )


async def _enable_preset(workflow_id: str) -> Response:
    return await _post(
        "/triggers/presets/self-healing",
        {"repository": _REPO, "workflow_id": workflow_id, "installation_id": _INSTALLATION},
    )


async def _stored_workflow_ids() -> list[str]:
    from syn_api.routes.triggers import list_triggers

    listed = await list_triggers()
    assert isinstance(listed, Ok)
    return [t.workflow_id for t in listed.value]


_CREATE = pytest.mark.parametrize("create", [_register, _enable_preset], ids=["register", "preset"])


@_CREATE
async def test_a_unique_prefix_is_stored_as_the_full_workflow_id(create) -> None:
    response = await create(_UNIQUE[:8])

    assert response.status_code == 200, response.text
    assert await _stored_workflow_ids() == [_UNIQUE]


@_CREATE
async def test_the_full_workflow_id_still_works(create) -> None:
    response = await create(_UNIQUE)

    assert response.status_code == 200, response.text
    assert await _stored_workflow_ids() == [_UNIQUE]


@_CREATE
async def test_a_full_id_whose_read_model_lags_is_still_accepted(create) -> None:
    """The event store, not the projection, decides a workflow exists (#1570)."""
    from syn_api._wiring import get_projection_mgr

    await get_projection_mgr().store.delete("workflow_details", _UNIQUE)

    response = await create(_UNIQUE)

    assert response.status_code == 200, response.text
    assert await _stored_workflow_ids() == [_UNIQUE]


@_CREATE
async def test_an_ambiguous_prefix_is_refused_and_nothing_is_stored(create) -> None:
    response = await create("a1b2c3d4")

    assert response.status_code == 409, response.text
    refusal = TriggerErrorResponse.model_validate_json(response.content)
    assert refusal.code == TriggerError.WORKFLOW_AMBIGUOUS
    assert "Ambiguous workflow ID 'a1b2c3d4' matches 2 entries" in refusal.detail
    assert await _stored_workflow_ids() == []


@_CREATE
async def test_an_unknown_id_keeps_the_not_found_refusal(create) -> None:
    response = await create("deadbeef")

    assert response.status_code == 400, response.text
    refusal = TriggerErrorResponse.model_validate_json(response.content)
    assert refusal.code == TriggerError.WORKFLOW_NOT_FOUND
    assert refusal.detail == (
        "Workflow 'deadbeef' does not exist. Seed workflows before creating triggers."
    )
    assert await _stored_workflow_ids() == []


@_CREATE
async def test_an_unreadable_read_model_is_not_reported_as_not_found(
    create, monkeypatch: pytest.MonkeyPatch
) -> None:
    from syn_api._wiring import get_projection_mgr

    store = get_projection_mgr().store

    async def _down(*_args: object, **_kwargs: object) -> None:
        raise ConnectionError("projection store unreachable")

    monkeypatch.setattr(store, "get", _down)

    response = await create(_UNIQUE[:8])

    assert response.status_code == 400, response.text
    refusal = TriggerErrorResponse.model_validate_json(response.content)
    assert refusal.code == TriggerError.STORE_UNAVAILABLE
    assert "not a statement that the workflow is missing" in refusal.detail
    assert await _stored_workflow_ids() == []
