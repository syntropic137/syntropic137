"""A run records the workflow version it launched from (Evals v2).

An eval run is one data point: which workflow, at which installed version. The
template is mutable, so its CURRENT version is wrong for every run that started
before an update; the version has to be written on the run's own start event.

Driven through the REAL `ExecuteWorkflowHandler` and processor over real
event-store repositories (the `_World` of the #967 tag test), across a real
template update, and read back from the store and the execution list
projection the eval runs route reads.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

import pytest
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration._shared.yaml_to_command import (
    build_command_from_definition,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
    WorkflowTemplateAggregate,
)
from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_summary import (
    WorkflowExecutionSummary,
)
from syn_domain.contexts.orchestration.slices.create_workflow_template.CreateWorkflowTemplateHandler import (
    _to_update_command,  # pyright: ignore[reportPrivateUsage]  # the install path's own translation
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_967_request_tags_reach_the_start_event import (
    _World,  # pyright: ignore[reportPrivateUsage]  # one harness for every start-event field
)
from syn_domain.contexts.orchestration.slices.list_executions.projection import (
    WorkflowExecutionListProjection,
)
from syn_domain.testing.stored_replay import replay, stored_envelopes

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


async def _install(world: _World, version: str | None, digest: str | None) -> None:
    command = build_command_from_definition(world.definition).model_copy(
        update={"version": version, "source_digest": digest, "force": True}
    )
    existing = await world.templates.get_by_id(world.definition.id)
    if existing is None:
        template = WorkflowTemplateAggregate()
        template.create_workflow(command)
        await world.templates.save_new(template)
        return
    existing.update_workflow(_to_update_command(command))
    await world.templates.save(existing)


async def _started_version(world: _World, execution_id: str) -> str | None:
    for envelope in await stored_envelopes(world.executions_store):
        payload = envelope.event.model_dump()
        if envelope.event.event_type == "WorkflowExecutionStarted" and (
            payload["execution_id"] == execution_id
        ):
            return payload.get("workflow_version")
    msg = f"no WorkflowExecutionStarted stored for {execution_id}"
    raise AssertionError(msg)


async def _listed_version(world: _World, execution_id: str) -> str | None:
    store = InMemoryProjectionStore()
    projection = WorkflowExecutionListProjection(store)
    await replay(world.executions_store, MemoryCheckpointStore(), projection)
    row = await store.get(projection.PROJECTION_NAME, execution_id)
    assert row is not None
    return WorkflowExecutionSummary.from_dict(row).workflow_version


async def test_runs_either_side_of_an_update_record_different_versions() -> None:
    world = _World(workflow_tags=[])
    await _install(world, "1.0.0", "a" * 40)
    await world.run("exec-v1", [])

    await _install(world, "2.0.0", "b" * 40)
    await world.run("exec-v2", [])

    assert await _started_version(world, "exec-v1") == "1.0.0"
    assert await _started_version(world, "exec-v2") == "2.0.0"
    assert await _listed_version(world, "exec-v1") == "1.0.0"
    assert await _listed_version(world, "exec-v2") == "2.0.0"


async def test_a_template_without_a_version_records_its_digest() -> None:
    world = _World(workflow_tags=[])
    await _install(world, None, "d" * 40)
    await world.run("exec-1", [])

    assert await _started_version(world, "exec-1") == "d" * 40


async def test_a_template_with_neither_writes_no_key() -> None:
    world = _World(workflow_tags=[])
    await _install(world, None, None)
    await world.run("exec-1", [])

    assert await _started_version(world, "exec-1") is None
    assert await _listed_version(world, "exec-1") is None
