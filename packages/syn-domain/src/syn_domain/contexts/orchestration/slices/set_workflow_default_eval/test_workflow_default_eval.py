"""A workflow's default eval, from YAML to the detail read model (evals plan, #967).

Driven through the REAL install handler and `SetWorkflowDefaultEvalHandler`
over real event-store repositories; the detail projection is fed from what the
store holds. Launch behaviour is pinned in
``execute_workflow/test_967_eval_membership.py``.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from event_sourcing import EventStoreRepository
from event_sourcing.client.memory import MemoryEventStoreClient
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore
from pydantic import ValidationError

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.storage.repositories import RepositoryAdapter
from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration._shared.yaml_to_command import (
    build_command_from_definition,
)
from syn_domain.contexts.orchestration.domain.aggregate_eval import EvalAggregate, EvalId, Goal
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
    WorkflowTemplateAggregate,
)
from syn_domain.contexts.orchestration.domain.commands.SetWorkflowDefaultEvalCommand import (
    SetWorkflowDefaultEvalCommand,
)
from syn_domain.contexts.orchestration.slices.create_eval import CreateEvalHandler
from syn_domain.contexts.orchestration.slices.create_workflow_template.CreateWorkflowTemplateHandler import (
    CreateWorkflowTemplateHandler,
)
from syn_domain.contexts.orchestration.slices.get_workflow_detail.projection import (
    WorkflowDetailProjection,
)
from syn_domain.contexts.orchestration.slices.set_workflow_default_eval import (
    SetWorkflowDefaultEvalHandler,
)
from syn_domain.testing.fake_revision_resolver import FakeRevisionResolver
from syn_domain.testing.stored_replay import replay, stored_envelopes
from syn_shared.agents import PhaseModelDefaults

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.read_models.workflow_detail import (
        WorkflowDetail,
    )

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

_PACKAGE = Path(__file__).resolve().parents[8] / "workflows" / "sdlc" / "quickfix"


def _definition(tmp_path: Path, extra: str) -> WorkflowDefinition:
    """The quickfix package with ``extra`` appended to its workflow.yaml."""
    source = (_PACKAGE / "workflow.yaml").read_text(encoding="utf-8")
    path = tmp_path / "workflow.yaml"
    path.write_text(f"{source}\n{extra}\n", encoding="utf-8")
    return WorkflowDefinition.from_file(path, base_dir=_PACKAGE)


class _World:
    def __init__(self) -> None:
        self.templates_store = MemoryEventStoreClient()
        self.templates = RepositoryAdapter(
            EventStoreRepository(
                self.templates_store,
                WorkflowTemplateAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
                "WorkflowTemplate",
            )
        )
        self.evals = RepositoryAdapter(
            EventStoreRepository(
                MemoryEventStoreClient(),
                EvalAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
                "Eval",
            )
        )
        self.install = CreateWorkflowTemplateHandler(
            self.templates, AsyncMock(), model_defaults=PhaseModelDefaults()
        )
        self.set_default = SetWorkflowDefaultEvalHandler(self.templates, self.evals)

    async def create_eval(self, eval_id: str) -> None:
        created = await CreateEvalHandler(self.evals, FakeRevisionResolver()).handle(
            eval_id=EvalId(eval_id), name=eval_id, goal=Goal("Keep tests green")
        )
        assert created.success

    async def default_eval_id(self, workflow_id: str) -> str | None:
        workflow = await self.templates.get_by_id(workflow_id)
        assert workflow is not None
        return workflow.default_eval_id

    async def detail(self, workflow_id: str) -> WorkflowDetail:
        projection = WorkflowDetailProjection(store=InMemoryProjectionStore())
        await replay(self.templates_store, MemoryCheckpointStore(), projection)
        detail = await projection.get_by_id(workflow_id)
        assert detail is not None
        return detail


async def test_default_eval_id_installs_from_yaml_and_reaches_the_detail(
    tmp_path: Path,
) -> None:
    world = _World()
    definition = _definition(tmp_path, "default_eval_id: eval-planning")

    await world.install.handle(build_command_from_definition(definition))

    assert await world.default_eval_id(definition.id) == "eval-planning"
    assert (await world.detail(definition.id)).default_eval_id == "eval-planning"


async def test_a_reinstall_replaces_the_default_with_the_packages(tmp_path: Path) -> None:
    world = _World()
    first = _definition(tmp_path, "default_eval_id: eval-a")
    await world.install.handle(build_command_from_definition(first))

    second = _definition(tmp_path, "default_eval_id: eval-b")
    await world.install.handle(build_command_from_definition(second))

    assert await world.default_eval_id(first.id) == "eval-b"
    assert (await world.detail(first.id)).default_eval_id == "eval-b"


def test_an_unknown_key_is_still_refused(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="default_eval"):
        _definition(tmp_path, "default_eval: eval-a")


def test_an_invalid_eval_id_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="eval id"):
        _definition(tmp_path, "default_eval_id: 'has spaces'")


async def test_set_and_clear_the_default_records_one_event_each(tmp_path: Path) -> None:
    world = _World()
    definition = _definition(tmp_path, "")
    await world.install.handle(build_command_from_definition(definition))
    await world.create_eval("eval-1")
    set_it = SetWorkflowDefaultEvalCommand(aggregate_id=definition.id, eval_id=EvalId("eval-1"))

    first = await world.set_default.handle(set_it)
    again = await world.set_default.handle(set_it)
    assert (await world.detail(definition.id)).default_eval_id == "eval-1"
    cleared = await world.set_default.handle(
        SetWorkflowDefaultEvalCommand(aggregate_id=definition.id, eval_id=None)
    )

    assert first is not None and first.success
    assert again is not None and again.success
    assert cleared is not None and cleared.success
    recorded = [
        envelope.event.model_dump()["eval_id"]
        for envelope in await stored_envelopes(world.templates_store)
        if envelope.event.event_type == "WorkflowDefaultEvalSet"
    ]
    assert recorded == ["eval-1", None]
    assert await world.default_eval_id(definition.id) is None
    assert (await world.detail(definition.id)).default_eval_id is None


async def test_an_unknown_workflow_is_not_a_result() -> None:
    world = _World()

    result = await world.set_default.handle(
        SetWorkflowDefaultEvalCommand(aggregate_id="wf-nope", eval_id=None)
    )

    assert result is None
