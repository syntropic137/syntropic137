"""#1376: a phase's `max_cost_usd` is visible on the API and survives export.

The limit is stored on the phase definition and read back by the read model,
and both are tested in syn-domain. The two hops after that live here, and
deleting either left every test green:

- `GET /workflows/{id}` builds each phase in `_map_phase`. Drop the field
  there and the response reports `null`, so an operator asking "what limit
  does this phase run under" is told "none" while the phase is stopped at one.
- `_yaml_phase_lines` writes the phase out for export. Drop the field there
  and export -> reinstall produces a workflow with NO limit: the #1015
  laundering class, on the one bound that exists to cap spend.

The route test goes through FastAPI over ASGI, as #1176 established, because
that is the hop where a response can lose a field the model still has.
"""

from __future__ import annotations

import os

import pytest
import yaml

# In-memory adapters, as the other service-level workflow tests do.
os.environ.setdefault("APP_ENVIRONMENT", "test")

from syn_api.routes.workflows.commands import create_workflow_from_yaml
from syn_api.routes.workflows.queries import WorkflowResponse, _yaml_phase_lines
from syn_api.types import Ok, PhaseDefinitionResponse
from syn_domain.contexts.orchestration._shared.workflow_definition import PhaseYamlDefinition

pytestmark = pytest.mark.unit

_LIMIT_USD = 12.5

_YAML = f"""
id: cost-limited-wf
name: Cost Limited Workflow
type: research
classification: simple

phases:
  - id: experiment
    name: Experiment
    order: 1
    prompt_template: "Run the experiment."
    max_cost_usd: {_LIMIT_USD}

  - id: report
    name: Report
    order: 2
    prompt_template: "Write it up."
"""


@pytest.fixture(autouse=True)
def _reset_storage():
    from syn_adapters.projection_stores import get_projection_store
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    store = get_projection_store()
    if hasattr(store, "_data"):
        store._data.clear()
    if hasattr(store, "_state"):
        store._state.clear()
    yield
    reset_storage()
    reset_projection_manager()


async def _get_workflow(workflow_id: str) -> WorkflowResponse:
    """The workflow detail as a caller receives it, parsed from the JSON body."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from syn_api.routes.workflows.queries import router

    app = FastAPI()
    app.include_router(router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/workflows/{workflow_id}")

    assert response.status_code == 200, response.text
    return WorkflowResponse.model_validate_json(response.content)


class TestTheLimitIsOnTheWorkflowResponse:
    async def test_the_declared_limit_reaches_the_caller(self) -> None:
        assert isinstance(await create_workflow_from_yaml(_YAML), Ok)

        phases = {p.phase_id: p for p in (await _get_workflow("cost-limited-wf")).phases}

        assert phases["experiment"].max_cost_usd == _LIMIT_USD

    async def test_a_phase_that_declared_no_limit_reports_none(self) -> None:
        """The negative half: a mapping that smeared one phase's limit onto
        every phase would pass the test above."""
        assert isinstance(await create_workflow_from_yaml(_YAML), Ok)

        phases = {p.phase_id: p for p in (await _get_workflow("cost-limited-wf")).phases}

        assert phases["report"].max_cost_usd is None


def _exported(phase: PhaseDefinitionResponse) -> PhaseYamlDefinition:
    """Export one phase and reinstall it through the real loader.

    The loader wants the prompt inline; export writes it to a sibling file, so
    substitute exactly what the installer would have resolved.
    """
    emitted = yaml.safe_load("phases:\n" + "\n".join(_yaml_phase_lines(phase)))["phases"][0]
    emitted.pop("prompt_file", None)
    emitted["prompt_template"] = "body"
    return PhaseYamlDefinition.model_validate(emitted)


def _phase(max_cost_usd: float | None) -> PhaseDefinitionResponse:
    return PhaseDefinitionResponse(
        phase_id="experiment",
        name="Experiment",
        order=1,
        prompt_template="body",
        max_cost_usd=max_cost_usd,
    )


class TestTheLimitSurvivesExport:
    def test_an_exported_limit_reinstalls_as_the_same_limit(self) -> None:
        assert _exported(_phase(_LIMIT_USD)).max_cost_usd == _LIMIT_USD

    def test_no_limit_exports_as_no_limit(self) -> None:
        assert _exported(_phase(None)).max_cost_usd is None
