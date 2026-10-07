"""PC-83: a phase's `fallback_agent` is visible on the API and survives export.

Every hop between the YAML and the caller is exercised here, through the real
create service, the real projection and FastAPI over ASGI (as #1176 and #1376
established): a field dropped at `to_dict`, `from_dict`, `_map_phase` or
`_yaml_phase_lines` reports `null` here while the model still has it.
"""

from __future__ import annotations

import os

import pytest
import yaml

# In-memory adapters, as the other service-level workflow tests do.
os.environ.setdefault("APP_ENVIRONMENT", "test")

from syn_api.routes.workflows.commands import create_workflow_from_yaml
from syn_api.routes.workflows.phase_defs import _build_phase_defs
from syn_api.routes.workflows.queries import WorkflowResponse, _yaml_phase_lines
from syn_api.types import Ok
from syn_domain.contexts.orchestration._shared.workflow_definition import PhaseYamlDefinition
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    FallbackAgent,
)

pytestmark = pytest.mark.unit

_YAML = """
id: fallback-wf
name: Fallback Workflow
type: review
classification: simple

phases:
  - id: verify
    name: Verify
    order: 1
    prompt_template: "Verify it."
    agent:
      provider: codex
    fallback_agent:
      provider: claude
      model: opus

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


async def test_the_declared_fallback_reaches_the_caller_and_survives_export() -> None:
    assert isinstance(await create_workflow_from_yaml(_YAML), Ok)

    phases = {p.phase_id: p for p in (await _get_workflow("fallback-wf")).phases}

    verify = phases["verify"]
    assert verify.fallback_agent is not None
    assert (verify.fallback_agent.provider, verify.fallback_agent.model) == ("claude", "opus")
    # The negative half: a mapping that smeared one phase's fallback onto
    # every phase would pass the assertion above.
    assert phases["report"].fallback_agent is None

    emitted = yaml.safe_load("phases:\n" + "\n".join(_yaml_phase_lines(verify)))["phases"][0]
    emitted.pop("prompt_file", None)
    emitted["prompt_template"] = "body"
    reinstalled = PhaseYamlDefinition.model_validate(emitted).to_domain()
    assert reinstalled.fallback_agent == FallbackAgent(provider="claude", model="opus")


def test_the_json_create_path_holds_the_fallback_to_the_yaml_rules() -> None:
    [phase] = _build_phase_defs(
        [{"name": "Verify", "fallback_agent": {"provider": "claude", "model": "opus"}}]
    )
    assert phase.fallback_agent == FallbackAgent(provider="claude", model="opus")

    with pytest.raises(ValueError, match="max_cost_usd on provider 'codex'"):
        _build_phase_defs(
            [{"name": "Verify", "max_cost_usd": 5.0, "fallback_agent": {"provider": "codex"}}]
        )
    with pytest.raises(ValueError):
        _build_phase_defs([{"name": "Verify", "fallback_agent": {"model": "opus"}}])
