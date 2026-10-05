"""PC-66: an empty or whitespace-only task is refused at admission.

`syn workflow run sdlc-implement-v3 -t ""` admitted exec-2dced6933763, which
would have run a full implement workflow on nothing. Two holes let it through:

- a sent ``task`` was only checked for presence, so ``""`` counted as a task;
- ``sdlc-implement-v3`` declared no ``task`` input at all, so there was no
  requirement for admission to enforce.

Every test goes through the real app and the real execute route; only
``execute()`` is replaced, so "admitted" means the route handed the request on.
The implement-v3 declarations are read from the workflow's own YAML and stored
through the real create path, so the test fails if the declaration is dropped
from the YAML, from the stored template, or from the admission check.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("APP_ENVIRONMENT", "test")

from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from syn_adapters.maintenance import InMemoryMaintenanceAdapter
from syn_domain.contexts._shared import AdmissionGate
from syn_domain.contexts.orchestration import WorkflowDefinition

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from syn_domain.contexts._shared import AdmissionTicket

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

_IMPLEMENT_V3 = Path(__file__).resolve().parents[3] / "workflows/sdlc/implement-v3/workflow.yaml"


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


class _CapturingExecute:
    """Stands in for `execute()`, keeping the inputs each admitted launch carried."""

    def __init__(self) -> None:
        self.launched: list[dict[str, str]] = []

    async def __call__(
        self,
        *,
        inputs: dict[str, str],
        admitted: AdmissionTicket | None = None,
        **_: object,
    ) -> None:
        self.launched.append(inputs)
        if admitted is not None:
            admitted.mark_visible()


@pytest.fixture
def execution(monkeypatch: pytest.MonkeyPatch) -> _CapturingExecute:
    import syn_api._wiring_admission as wiring
    from syn_api.routes.executions import commands

    captured = _CapturingExecute()
    monkeypatch.setattr(
        wiring,
        "_admission_gate_singleton",
        AdmissionGate(InMemoryMaintenanceAdapter()),
        raising=False,
    )
    monkeypatch.setattr(commands, "execute", captured)
    return captured


async def _create_workflow(*, declares_task: bool) -> str:
    from syn_api.routes.workflows import create_workflow
    from syn_api.types import Ok

    declarations = (
        [i.to_domain().model_dump() for i in WorkflowDefinition.from_file(_IMPLEMENT_V3).inputs]
        if declares_task
        else []
    )
    result = await create_workflow(
        name="PC-66 workflow",
        workflow_type="implementation",
        requires_repos=False,
        input_declarations=declarations,
    )
    assert isinstance(result, Ok)
    return result.value.workflow_id


_BLANK = [pytest.param("", id="empty"), pytest.param("  \t\n ", id="whitespace")]


class TestABlankTaskIsRefused:
    @pytest.mark.parametrize("task", _BLANK)
    async def test_a_blank_task_is_422_and_never_launched(
        self, client: AsyncClient, execution: _CapturingExecute, task: str
    ) -> None:
        workflow_id = await _create_workflow(declares_task=True)

        response = await client.post(f"/workflows/{workflow_id}/execute", json={"task": task})

        assert response.status_code == 422, response.text
        assert "task is empty" in response.text
        assert execution.launched == []

    @pytest.mark.parametrize("task", _BLANK)
    async def test_even_where_no_task_is_declared(
        self, client: AsyncClient, execution: _CapturingExecute, task: str
    ) -> None:
        """A sent task with no content is never an instruction; omit it instead."""
        workflow_id = await _create_workflow(declares_task=False)

        response = await client.post(f"/workflows/{workflow_id}/execute", json={"task": task})

        assert response.status_code == 422, response.text
        assert execution.launched == []


class TestImplementV3RequiresATask:
    """The declaration in implement-v3's YAML is what admission enforces."""

    async def test_no_task_at_all_is_422(
        self, client: AsyncClient, execution: _CapturingExecute
    ) -> None:
        workflow_id = await _create_workflow(declares_task=True)

        response = await client.post(f"/workflows/{workflow_id}/execute", json={})

        assert response.status_code == 422, response.text
        assert "Missing required inputs: task" in response.text
        assert execution.launched == []

    @pytest.mark.parametrize("task", _BLANK)
    async def test_a_blank_task_input_is_422(
        self, client: AsyncClient, execution: _CapturingExecute, task: str
    ) -> None:
        """`inputs.task` reaches the same prompt as `task`, so it is held to the same rule."""
        workflow_id = await _create_workflow(declares_task=True)

        response = await client.post(
            f"/workflows/{workflow_id}/execute", json={"inputs": {"task": task}}
        )

        assert response.status_code == 422, response.text
        assert "Missing required inputs: task" in response.text
        assert execution.launched == []

    async def test_a_real_task_is_launched(
        self, client: AsyncClient, execution: _CapturingExecute
    ) -> None:
        workflow_id = await _create_workflow(declares_task=True)

        response = await client.post(
            f"/workflows/{workflow_id}/execute", json={"task": "Fix PC-66."}
        )

        assert response.status_code == 200, response.text
        assert len(execution.launched) == 1


class TestAWorkflowThatTakesNoTask:
    async def test_runs_without_one(
        self, client: AsyncClient, execution: _CapturingExecute
    ) -> None:
        workflow_id = await _create_workflow(declares_task=False)

        response = await client.post(f"/workflows/{workflow_id}/execute", json={})

        assert response.status_code == 200, response.text
        assert len(execution.launched) == 1


async def _store_predeclaration_workflow(
    prompts: list[str], *, declarations: list[dict[str, object]] | None = None
) -> str:
    """Store a definition as installs before PC-66 left it: phases, no ``task`` declaration.

    The stream is written once and never re-read from YAML, so this is what an
    existing installation holds until someone reinstalls it.
    """
    from syn_api.routes.workflows import create_workflow
    from syn_api.types import Ok

    result = await create_workflow(
        name="Installed before PC-66",
        workflow_type="implementation",
        requires_repos=False,
        phases=[{"name": f"phase {i}", "prompt_template": p} for i, p in enumerate(prompts)],
        input_declarations=declarations or [],
    )
    assert isinstance(result, Ok)
    return result.value.workflow_id


def _implement_v3_prompts() -> list[str]:
    phases = WorkflowDefinition.from_file(_IMPLEMENT_V3).get_domain_phases()
    return [p.prompt_template or "" for p in phases]


class TestAStoredDefinitionWithoutTheDeclaration:
    """The review finding: existing installs never see the YAML's new ``inputs:``."""

    async def test_implement_v3_as_installed_before_still_needs_a_task(
        self, client: AsyncClient, execution: _CapturingExecute
    ) -> None:
        prompts = _implement_v3_prompts()
        assert any("$ARGUMENTS" in p for p in prompts)
        workflow_id = await _store_predeclaration_workflow(prompts)

        response = await client.post(f"/workflows/{workflow_id}/execute", json={})

        assert response.status_code == 422, response.text
        assert "Missing required inputs: task" in response.text
        assert execution.launched == []

    @pytest.mark.parametrize("prompt", ["Do this: $ARGUMENTS", "Task: {{task}}"])
    @pytest.mark.parametrize("task", _BLANK)
    async def test_a_prompt_that_takes_the_task_refuses_a_blank_one(
        self, client: AsyncClient, execution: _CapturingExecute, prompt: str, task: str
    ) -> None:
        workflow_id = await _store_predeclaration_workflow(["Read the repo.", prompt])

        response = await client.post(
            f"/workflows/{workflow_id}/execute", json={"inputs": {"task": task}}
        )

        assert response.status_code == 422, response.text
        assert "Missing required inputs: task" in response.text
        assert execution.launched == []

    async def test_with_a_task_it_is_launched(
        self, client: AsyncClient, execution: _CapturingExecute
    ) -> None:
        workflow_id = await _store_predeclaration_workflow(_implement_v3_prompts())

        response = await client.post(
            f"/workflows/{workflow_id}/execute", json={"task": "Fix PC-66."}
        )

        assert response.status_code == 200, response.text
        assert len(execution.launched) == 1

    async def test_prompts_that_never_take_a_task_run_without_one(
        self, client: AsyncClient, execution: _CapturingExecute
    ) -> None:
        workflow_id = await _store_predeclaration_workflow(
            ["Summarise the repository.", "Report {{execution_id}}."]
        )

        response = await client.post(f"/workflows/{workflow_id}/execute", json={})

        assert response.status_code == 200, response.text
        assert len(execution.launched) == 1

    async def test_an_explicit_declaration_outranks_the_prompt(
        self, client: AsyncClient, execution: _CapturingExecute
    ) -> None:
        """A workflow that declares ``task`` optional means it, $ARGUMENTS or not."""
        workflow_id = await _store_predeclaration_workflow(
            ["Optional focus: $ARGUMENTS"],
            declarations=[{"name": "task", "required": False}],
        )

        response = await client.post(f"/workflows/{workflow_id}/execute", json={})

        assert response.status_code == 200, response.text
        assert len(execution.launched) == 1
